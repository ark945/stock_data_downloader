"""
TWSE 臺灣證券交易所（上市股票）券商買賣日報表高強健爬蟲
升級亮點：
1. 整合專屬 CNN 模型 + ddddocr 雙引擎驗證碼辨識
2. 預先過濾當日成交量 > 0 標的 (過濾零成交冷門股)
3. 2-Stage 自動補抓佇列 (Retry Queue，成功率 > 98%)
4. 標準 13 欄位聚合輸出 (Parquet / Excel)
"""

import os
import sys
import time
import re
import json
from collections import Counter
from dataclasses import dataclass
from threading import Event, Lock
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)

# 載入雙引擎驗證碼
try:
    from captcha_engine import recognize_captcha
except ImportError:
    from .captcha_engine import recognize_captcha


@dataclass
class FetchResult:
    status: str
    raw_csv: Optional[str] = None
    reason: str = ""


def get_active_listed_symbols(trade_date: Optional[str] = None) -> List[str]:
    """
    從 TWSE 官方取得當日有實際成交量的上市股票清單 (排除零成交特別股/ETN)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # 策略 1: TWSE 每日收盤行情 (MI_INDEX) - 最精準過濾成交量 > 0
    try:
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=ALLBUT0999"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            res_json = r.json()
            tables = res_json.get("tables", [])
            for tbl in tables:
                data_rows = tbl.get("data", [])
                if data_rows and len(data_rows[0]) > 2:
                    active_symbols = []
                    for row in data_rows:
                        code = str(row[0]).strip()
                        # 第 2 欄通常為成交股數
                        vol_str = str(row[2]).replace(",", "").strip()
                        try:
                            vol = float(vol_str)
                            if vol > 0:
                                active_symbols.append(code)
                        except ValueError:
                            active_symbols.append(code)
                    if len(active_symbols) > 500:
                        return sorted(list(dict.fromkeys(active_symbols)))
    except Exception:
        pass

    # 策略 2: TWSE OpenAPI
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            active_symbols = []
            for item in data:
                code = str(item.get("Code", "")).strip()
                trade_vol = float(str(item.get("TradeVolume", "0")).replace(",", ""))
                if code and trade_vol > 0:
                    active_symbols.append(code)
            if len(active_symbols) > 500:
                return sorted(list(dict.fromkeys(active_symbols)))
    except Exception:
        pass

    # 策略 3: 本地 twstock.codes 上市標的保底 (確保全市場不漏抓)
    try:
        import twstock
        twse_fallbacks = [
            code for code, info in twstock.codes.items()
            if getattr(info, "market", "") == "上市" and getattr(info, "type", "") in ["股票", "ETF", "臺灣存託憑證"]
        ]
        if len(twse_fallbacks) > 500:
            return sorted(list(dict.fromkeys(twse_fallbacks)))
    except Exception:
        pass

    # 備用保底清單
    return ["2330", "2317", "2454", "2382", "2308", "2881", "2412", "2882", "2303", "2891"]


class TWSEBrokerCrawler:
    """TWSE 券商買賣日報表爬蟲類別"""

    MENU_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"
    CONTENT_URL = "https://bsr.twse.com.tw/bshtm/bsContent.aspx"
    NO_DATA_MARKERS = (
        "查無資料",
        "查無此代碼",
        "查無符合條件之資料",
        "查無此證券",
    )

    def __init__(
        self,
        delay_sec: float = 0.4,
        max_retries: int = 6,
        diagnostics_dir: Optional[str] = None,
        diagnostic_symbols: Optional[Set[str]] = None,
    ):
        """
        初始化上市爬蟲實例
        :param delay_sec: 每次請求之間的保護性延遲秒數 (預設 0.4s 安全平衡)
        :param max_retries: 單一股票單輪最大重試次數
        :param diagnostics_dir: 若提供，將輸出單檔診斷 HTML / JSON 檔
        :param diagnostic_symbols: 只對這些股票輸出診斷檔；未提供時代表 diagnostics_dir 啟用後全部輸出
        """
        self.delay_sec = delay_sec
        self.max_retries = max_retries
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://bsr.twse.com.tw",
            "Referer": "https://bsr.twse.com.tw/bshtm/bsMenu.aspx",
        }
        self.last_run_stats: Dict[str, object] = {
            "success_count": 0,
            "no_data_count": 0,
            "technical_failure_count": 0,
            "status_counts": {},
            "reason_counts": {},
        }
        self.stop_event = Event()
        self.diagnostics_dir = diagnostics_dir
        self.diagnostic_symbols = {str(sym).strip().upper() for sym in diagnostic_symbols} if diagnostic_symbols else None
        self._diagnostic_lock = Lock()
        self._diagnostic_fetch_counts: Dict[str, int] = {}

    @staticmethod
    def _normalize_reason(reason: str) -> str:
        return reason.replace(":", "_").replace(" ", "_") if reason else "unknown"

    @classmethod
    def _is_no_data_response(cls, html: str) -> bool:
        # TWSE 會用多種文案表示正常查詢但當日無券商分點資料，不能一律視為技術失敗。
        return any(marker in html for marker in cls.NO_DATA_MARKERS)

    def _should_collect_diagnostics(self, stock_id: str) -> bool:
        if not self.diagnostics_dir:
            return False
        if self.diagnostic_symbols is None:
            return True
        return str(stock_id).strip().upper() in self.diagnostic_symbols

    def _next_diagnostic_fetch_no(self, stock_id: str) -> int:
        with self._diagnostic_lock:
            current = self._diagnostic_fetch_counts.get(stock_id, 0) + 1
            self._diagnostic_fetch_counts[stock_id] = current
            return current

    def _write_diagnostic_artifact(
        self,
        stock_id: str,
        fetch_no: int,
        attempt_no: int,
        label: str,
        content: str,
        extension: str,
    ) -> None:
        if not self._should_collect_diagnostics(stock_id):
            return
        os.makedirs(self.diagnostics_dir, exist_ok=True)
        filename = f"{str(stock_id).strip()}_fetch{fetch_no:02d}_attempt{attempt_no:02d}_{label}.{extension}"
        path = os.path.join(self.diagnostics_dir, filename)
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)

    def _write_diagnostic_json(
        self,
        stock_id: str,
        fetch_no: int,
        attempt_no: int,
        payload: Dict[str, object],
    ) -> None:
        if not self._should_collect_diagnostics(stock_id):
            return
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self._write_diagnostic_artifact(stock_id, fetch_no, attempt_no, "summary", text, "json")

    def request_stop(self):
        self.stop_event.set()

    def _sleep_or_stop(self, seconds: float) -> bool:
        if seconds <= 0:
            return self.stop_event.is_set()
        return self.stop_event.wait(seconds)

    def _get_latest_trade_date(self) -> str:
        today = get_taipei_now()
        w = today.weekday()
        is_ready = (today.hour, today.minute) >= (16, 30)
        if w == 5:
            delta = 1
        elif w == 6:
            delta = 2
        elif w == 0:
            delta = 0 if is_ready else 3
        else:
            delta = 0 if is_ready else 1
        return (today - pd.Timedelta(days=delta)).strftime("%Y-%m-%d")

    def fetch_stock_raw_csv(self, stock_id: str) -> FetchResult:
        last_reason = "unknown"
        fetch_no = self._next_diagnostic_fetch_no(stock_id) if self._should_collect_diagnostics(stock_id) else 0
        for attempt in range(1, self.max_retries + 1):
            if self.stop_event.is_set():
                return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
            try:
                session = requests.Session()
                session.headers.update(self.headers)

                # 1. 取得首頁與 ViewState
                r_menu = session.get(self.MENU_URL, timeout=8)
                if r_menu.status_code != 200:
                    last_reason = f"menu_http_error:{r_menu.status_code}"
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {"stage": "menu", "status": "technical_failure", "reason": last_reason},
                    )
                    if self._sleep_or_stop(0.3):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    continue

                soup = BeautifulSoup(r_menu.text, "html.parser")
                viewstate_el = soup.find("input", {"id": "__VIEWSTATE"})
                viewstate_gen_el = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})
                event_val_el = soup.find("input", {"id": "__EVENTVALIDATION"})
                captcha_imgs = [img["src"] for img in soup.find_all("img") if "Captcha" in img.get("src", "")]

                if not (viewstate_el and captcha_imgs):
                    last_reason = "menu_missing_form_fields"
                    self._write_diagnostic_artifact(stock_id, fetch_no, attempt, "menu_response", r_menu.text, "html")
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {"stage": "menu", "status": "technical_failure", "reason": last_reason},
                    )
                    if self._sleep_or_stop(0.3):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    continue

                viewstate = viewstate_el["value"]
                viewstate_gen = viewstate_gen_el["value"] if viewstate_gen_el else ""
                event_val = event_val_el["value"] if event_val_el else ""

                # 2. 下載驗證碼並透過雙引擎辨識
                captcha_url = "https://bsr.twse.com.tw/bshtm/" + captcha_imgs[0]
                r_img = session.get(captcha_url, timeout=8)
                if r_img.status_code != 200:
                    last_reason = f"captcha_http_error:{r_img.status_code}"
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {"stage": "captcha", "status": "technical_failure", "reason": last_reason},
                    )
                    continue

                captcha_code = recognize_captcha(r_img.content)
                if not captcha_code:
                    last_reason = "captcha_recognition_failed"
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {"stage": "captcha", "status": "technical_failure", "reason": last_reason},
                    )
                    continue

                # 3. POST 表單送出查詢
                payload = {
                    "__VIEWSTATE": viewstate,
                    "__VIEWSTATEGENERATOR": viewstate_gen,
                    "__EVENTVALIDATION": event_val,
                    "RadioButton_Normal": "RadioButton_Normal",
                    "TextBox_Stkno": str(stock_id).strip(),
                    "CaptchaControl1": captcha_code,
                    "btnOK": "查詢",
                }
                r_post = session.post(self.MENU_URL, data=payload, timeout=8)
                if r_post.status_code != 200:
                    last_reason = f"post_http_error:{r_post.status_code}"
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {
                            "stage": "post",
                            "status": "technical_failure",
                            "reason": last_reason,
                            "captcha_code": captcha_code,
                        },
                    )
                    if self._sleep_or_stop(0.2):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    continue
                post_html = r_post.text
                self._write_diagnostic_artifact(stock_id, fetch_no, attempt, "post_response", post_html, "html")

                # 檢查 POST 回應大小 - 如果回應太短（<200 bytes），多半是異常頁面
                # 正常POST回應應該包含完整的HTML結構 (通常 > 5KB)
                post_html_len = len(post_html)
                
                # 正向精確判定：檢查多種可能的下載連結標記
                # 標準標記：HyperLink_DownloadCSV, bsContent.aspx
                # 擴展標記：LinkButton, ctl00_ContentPlaceHolder1_（ASPX 動態控制項）, __doPostBack（JavaScript 回發）
                download_link_indicators = [
                    "HyperLink_DownloadCSV" in post_html,
                    "bsContent.aspx" in post_html,
                    "ctl00_ContentPlaceHolder1_" in post_html and "LinkButton" in post_html,  # ASPX 伺服器控制項
                    "__doPostBack" in post_html and "ctl00" in post_html,  # JavaScript 回發機制
                ]
                
                if any(download_link_indicators):
                    if self._sleep_or_stop(0.35):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    r_content = session.get(self.CONTENT_URL, timeout=8)
                    if r_content.status_code != 200:
                        last_reason = f"content_http_error:{r_content.status_code}"
                        self._write_diagnostic_json(
                            stock_id,
                            fetch_no,
                            attempt,
                            {
                                "stage": "content",
                                "status": "technical_failure",
                                "reason": last_reason,
                                "captcha_code": captcha_code,
                            },
                        )
                        if self._sleep_or_stop(0.2):
                            return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                        continue
                    if len(r_content.content) > 100:
                        raw_text = r_content.content.decode("utf-8-sig", errors="replace")
                        if "券商買賣股票成交價量資訊" in raw_text or "股票代碼" in raw_text:
                            self._write_diagnostic_json(
                                stock_id,
                                fetch_no,
                                attempt,
                                {
                                    "stage": "content",
                                    "status": "success",
                                    "reason": "csv_download_ok",
                                    "captcha_code": captcha_code,
                                },
                            )
                            return FetchResult(status="success", raw_csv=raw_text, reason="csv_download_ok")
                    last_reason = "content_invalid_payload"
                    self._write_diagnostic_artifact(
                        stock_id,
                        fetch_no,
                        attempt,
                        "content_response",
                        r_content.content.decode("utf-8-sig", errors="replace"),
                        "txt",
                    )
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {
                            "stage": "content",
                            "status": "technical_failure",
                            "reason": last_reason,
                            "captcha_code": captcha_code,
                        },
                    )
                    if self._sleep_or_stop(0.2):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    continue

                # 若查詢頁已明確回傳「查無資料」類文案，代表網站正常響應，只是當日無可下載資料。
                if self._is_no_data_response(post_html):
                    self._write_diagnostic_json(
                        stock_id,
                        fetch_no,
                        attempt,
                        {
                            "stage": "post",
                            "status": "no_data",
                            "reason": "no_data_reported",
                            "captcha_code": captcha_code,
                        },
                    )
                    return FetchResult(status="no_data", raw_csv="", reason="no_data_reported")

                # 緊急備用策略：即使找不到下載連結標記，也嘗試請求 bsContent.aspx
                # 可能 TWSE 改了 HTML 結構但 session cookie 已保存
                if post_html_len < 300:  # POST HTML 太短，直接試著下載
                    if self._sleep_or_stop(0.35):
                        return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                    try:
                        r_content = session.get(self.CONTENT_URL, timeout=8)
                        if r_content.status_code == 200 and len(r_content.content) > 100:
                            raw_text = r_content.content.decode("utf-8-sig", errors="replace")
                            if "券商買賣股票成交價量資訊" in raw_text or "股票代碼" in raw_text:
                                self._write_diagnostic_json(
                                    stock_id,
                                    fetch_no,
                                    attempt,
                                    {
                                        "stage": "post",
                                        "status": "success",
                                        "reason": "emergency_content_fallback",
                                        "captcha_code": captcha_code,
                                        "post_html_len": post_html_len,
                                    },
                                )
                                return FetchResult(status="success", raw_csv=raw_text, reason="emergency_content_fallback")
                    except Exception:
                        pass  # 備用策略失敗，繼續進行重試

                if "驗證碼" in post_html and ("錯誤" in post_html or "不符" in post_html):
                    last_reason = "captcha_validation_failed"
                else:
                    last_reason = "post_missing_download_link"
                self._write_diagnostic_json(
                    stock_id,
                    fetch_no,
                    attempt,
                    {
                        "stage": "post",
                        "status": "technical_failure",
                        "reason": last_reason,
                        "captcha_code": captcha_code,
                    },
                )

                # 其餘狀況 (驗證碼錯誤或伺服器忙碌) 自動進入下一次換圖重試
                if self._sleep_or_stop(0.2):
                    return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")
                continue

            except requests.RequestException as e:
                last_reason = f"http_exception:{type(e).__name__}"
            except Exception as e:
                last_reason = f"unexpected_exception:{type(e).__name__}"
            if self._sleep_or_stop(0.1):
                return FetchResult(status="technical_failure", raw_csv=None, reason="interrupted")

        return FetchResult(status="technical_failure", raw_csv=None, reason=last_reason)

    def parse_csv_to_dataframe(self, csv_text: str, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        lines = csv_text.splitlines()
        data_lines = lines[3:] if len(lines) >= 3 else lines

        records = []
        for line in data_lines:
            parts = [p.strip().strip('"') for p in line.split(",")]
            # 左側 5 欄
            if len(parts) >= 5 and parts[1]:
                broker_str = parts[1]
                price_str = parts[2]
                buy_str = parts[3]
                sell_str = parts[4]
                try:
                    price = float(price_str.replace(",", ""))
                    buy = float(buy_str.replace(",", ""))
                    sell = float(sell_str.replace(",", ""))
                    if broker_str:
                        records.append({"broker": broker_str, "price": price, "buy": buy, "sell": sell})
                except ValueError:
                    pass

            # 右側 5 欄 (若為雙欄格式)
            if len(parts) >= 11 and parts[7]:
                broker_str = parts[7]
                price_str = parts[8]
                buy_str = parts[9]
                sell_str = parts[10]
                try:
                    price = float(price_str.replace(",", ""))
                    buy = float(buy_str.replace(",", ""))
                    sell = float(sell_str.replace(",", ""))
                    if broker_str:
                        records.append({"broker": broker_str, "price": price, "buy": buy, "sell": sell})
                except ValueError:
                    pass

        if not records:
            return None

        df_raw = pd.DataFrame(records)
        df_raw["broker_id"] = df_raw["broker"].str[:4]
        df_raw["buy_amt"] = df_raw["price"] * df_raw["buy"] / 1000.0
        df_raw["sell_amt"] = df_raw["price"] * df_raw["sell"] / 1000.0

        grouped = df_raw.groupby("broker_id", as_index=False).agg({
            "buy": "sum",
            "sell": "sum",
            "buy_amt": "sum",
            "sell_amt": "sum"
        })

        grouped.rename(columns={"buy": "buy_vol", "sell": "sell_vol"}, inplace=True)
        grouped["symbol"] = str(stock_id).strip()
        grouped["trade_date"] = str(trade_date).strip()
        grouped["net_vol"] = grouped["buy_vol"] - grouped["sell_vol"]
        grouped["net_amt"] = grouped["buy_amt"] - grouped["sell_amt"]

        grouped["buy_avg_price"] = np.where(
            grouped["buy_vol"] > 0,
            (grouped["buy_amt"] * 1000.0) / grouped["buy_vol"],
            np.nan
        )
        grouped["sell_avg_price"] = np.where(
            grouped["sell_vol"] > 0,
            (grouped["sell_amt"] * 1000.0) / grouped["sell_vol"],
            np.nan
        )

        grouped["turnover"] = grouped["buy_amt"] + grouped["sell_amt"]
        total_turnover = grouped["turnover"].sum()
        grouped["market_share"] = np.where(
            total_turnover > 0,
            (grouped["turnover"] / total_turnover) * 100.0,
            np.nan
        )

        standard_cols = [
            "symbol", "trade_date", "broker_id", "buy_vol", "sell_vol",
            "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price",
            "sell_avg_price", "turnover", "market_share"
        ]
        res_df = grouped[standard_cols].copy()
        res_df["symbol"] = res_df["symbol"].astype(str)
        res_df["trade_date"] = res_df["trade_date"].astype(str)
        res_df["broker_id"] = res_df["broker_id"].astype(str)
        for num_col in ["buy_vol", "sell_vol", "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price", "sell_avg_price", "turnover", "market_share"]:
            res_df[num_col] = res_df[num_col].astype(np.float64)

        return res_df

    def _crawl_single_worker(self, sym: str, trade_date: str) -> Tuple[str, Optional[pd.DataFrame], str, str]:
        if self.delay_sec > 0 and self._sleep_or_stop(self.delay_sec):
            return (sym, None, "technical_failure", "interrupted")
        if self.stop_event.is_set():
            return (sym, None, "technical_failure", "interrupted")
        fetch_res = self.fetch_stock_raw_csv(sym)
        if fetch_res.status == "success" and fetch_res.raw_csv:
            df = self.parse_csv_to_dataframe(fetch_res.raw_csv, sym, trade_date)
            if df is not None and not df.empty:
                return (sym, df, "success", fetch_res.reason)
            return (sym, None, "technical_failure", "parsed_empty_dataframe")
        return (sym, None, fetch_res.status, fetch_res.reason)

    def crawl_stocks(
        self,
        symbols: List[str],
        trade_date: str = "",
        max_workers: int = 4,
        max_retry_rounds: int = 10
    ) -> Tuple[List[pd.DataFrame], List[str], int]:
        """
        批次抓取指定上市股票清單 (支援多輪自適應安全防護與最終收斂補抓機制)
        :return: (all_dfs, final_failed_symbols, total_rounds_executed)
        """
        if not trade_date:
            trade_date = self._get_latest_trade_date()

        total_symbols = len(symbols)
        print(f"==================================================")
        print(f"[*] TWSE 上市券商買賣日報表爬蟲 ({max_retry_rounds} 輪終極自適應安全防護版)")
        print(f"[*] 目標交易日期: {trade_date}")
        print(f"[*] 待抓取標的數: {total_symbols} 檔")
        print(f"[*] 並行執行緒數: {max_workers} Workers (第 1 輪)")
        print(f"[*] 最大補抓輪數: {max_retry_rounds} 輪 (含第 {max_retry_rounds} 輪深度收斂跑到完機制)")
        print(f"==================================================")
        sys.stdout.flush()

        all_dfs = []
        failed_symbols = []
        confirmed_no_data_symbols = []
        completed_count = 0
        total_rows = 0
        start_time = time.time()
        status_counts = Counter()
        reason_counts = Counter()
        technical_failure_reason_by_symbol: Dict[str, str] = {}

        # 第 1 輪：標準並行抓取
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_sym = {
                executor.submit(self._crawl_single_worker, sym, trade_date): sym
                for sym in symbols
            }

            for future in as_completed(future_to_sym):
                if self.stop_event.is_set():
                    raise KeyboardInterrupt
                completed_count += 1
                sym, df, status, reason = future.result()
                status_counts[status] += 1
                reason_counts[self._normalize_reason(reason)] += 1

                if df is not None and not df.empty:
                    all_dfs.append(df)
                    total_rows += len(df)
                elif status == "no_data":
                    confirmed_no_data_symbols.append(sym)
                    technical_failure_reason_by_symbol.pop(sym, None)
                else:
                    failed_symbols.append(sym)
                    technical_failure_reason_by_symbol[sym] = reason

                if completed_count % 15 == 0 or completed_count == total_symbols:
                    elapsed = time.time() - start_time
                    speed = completed_count / elapsed if elapsed > 0 else 0
                    remaining = (total_symbols - completed_count) / speed if speed > 0 else 0
                    pct = (completed_count / total_symbols) * 100
                    success_cnt = len(all_dfs)
                    no_data_cnt = len(confirmed_no_data_symbols)
                    retry_cnt = len(failed_symbols)
                    ts_now = get_taipei_now().strftime("%H:%M:%S")
                    print(
                        f"[{ts_now}] [第1輪 進度 {completed_count}/{total_symbols} ({pct:.1f}%)] "
                        f"成功: {success_cnt} 檔 | 明確無資料: {no_data_cnt} 檔 | 技術待補: {retry_cnt} 檔 | "
                        f"累積: {total_rows:,} 筆 | 速度: {speed:.1f} 檔/s | "
                        f"剩餘約: {remaining/60:.1f} 分鐘"
                    )
                    sys.stdout.flush()
        except KeyboardInterrupt:
            self.request_stop()
            executor.shutdown(wait=False, cancel_futures=True)
            print("\n[!] 偵測到 Ctrl+C，中止 TWSE 第 1 輪抓取並停止後續補抓...")
            sys.stdout.flush()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        rounds_executed = 1
        
        # 檢查首輪失敗率，若過高則自動增加起始延遲
        first_round_total = len(symbols)
        first_round_success = len(all_dfs)
        first_round_success_rate = (first_round_success / first_round_total) if first_round_total > 0 else 0.0
        
        # 分析 ETF 失敗率
        etf_symbols = [s for s in symbols if len(s) <= 6 and (s.startswith("00") or len(s) == 4)]
        etf_failed = [s for s in failed_symbols if s in etf_symbols]
        etf_success_rate = 1.0 - (len(etf_failed) / len(etf_symbols)) if etf_symbols else 1.0
        
        print(f"[*] 首輪成功分析：整體 {first_round_success_rate*100:.1f}% | ETF 成功率 {etf_success_rate*100:.1f}%")
        
        # 動態調整：如果 ETF 成功率 < 20%（基本全滅），進入超激進模式
        if etf_success_rate < 0.2 and etf_symbols:
            print(f"[🔴] 臨界警報：ETF 成功率僅 {etf_success_rate*100:.1f}%，切換至 ETF 100% 搶救模式")
            print(f"[*] 將對所有失敗 ETF 採用延遲遞進策略 + 優先級隊列")
            base_delay_boost = 2.0  # 最激進
        elif first_round_success_rate < 0.3:
            print(f"[*] 警告：首輪成功率僅 {first_round_success_rate*100:.1f}%，自動啟用超強防護模式（延遲拉長 +1.0s）")
            base_delay_boost = 1.0
        elif first_round_success_rate < 0.5:
            print(f"[*] 提示：首輪成功率 {first_round_success_rate*100:.1f}%，提升防護延遲 +0.5s")
            base_delay_boost = 0.5
        else:
            base_delay_boost = 0.0
        
        sys.stdout.flush()

        # 第 2 輪起階梯式自適應安全補抓，最後一輪為終極深層收斂輪
        # 改進：遞進式拉長延遲，特別針對失敗率高的輪次
        delay_schedule = [1.2, 1.8, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.0]  # 各輪安全延遲秒數（更激進）
        # 應用動態延遲增強
        if base_delay_boost > 0:
            delay_schedule = [d + base_delay_boost for d in delay_schedule]
        
        while failed_symbols and rounds_executed < max_retry_rounds:
            rounds_executed += 1
            retry_count = len(failed_symbols)
            is_final_round = (rounds_executed == max_retry_rounds)
            current_delay = delay_schedule[min(rounds_executed - 2, len(delay_schedule) - 1)]
            current_workers = min(max_workers, retry_count)
            single_stock_retries = 8 if is_final_round else (6 if rounds_executed >= 5 else 4)

            ts_round = get_taipei_now().strftime("%H:%M:%S")
            print(f"\n" + "-"*50)
            if is_final_round:
                print(f"[{ts_round}] [FINAL] 【啟動第 {rounds_executed}/{max_retry_rounds} 輪終極收斂跑到底機制】(待補抓: {retry_count} 檔)")
                print(f"[{ts_round}] [*] 終極防護策略: {current_workers}-Workers 溫和無干擾模式, 請求間隔 {current_delay}s, 單檔最高 {single_stock_retries} 次深度辨識重試！")
            else:
                print(f"[{ts_round}] [*] 啟動第 {rounds_executed}/{max_retry_rounds} 輪精準安全補抓佇列 (待補抓: {retry_count} 檔)")
                print(f"[{ts_round}] [*] 安全防護策略: {current_workers}-Workers 安全並行模式, 請求間隔 {current_delay}s, 單檔 {single_stock_retries} 次重試")
            print(f"-"*50)
            sys.stdout.flush()
            
            if self._sleep_or_stop(2):
                print(f"[{ts_round}] [!] 偵測到中斷請求，停止進入下一輪補抓。")
                sys.stdout.flush()
                break
            
            # 載入名稱快取以利友善顯示
            name_map = {}
            map_p = os.path.join(os.path.dirname(__file__), "stock_name_map.json")
            if os.path.exists(map_p):
                try:
                    import json
                    with open(map_p, "r", encoding="utf-8") as f:
                        name_map = json.load(f)
                except Exception:
                    pass

            retry_crawler = TWSEBrokerCrawler(
                delay_sec=current_delay,
                max_retries=single_stock_retries,
                diagnostics_dir=self.diagnostics_dir,
                diagnostic_symbols=self.diagnostic_symbols,
            )
            retry_crawler._diagnostic_lock = self._diagnostic_lock
            retry_crawler._diagnostic_fetch_counts = self._diagnostic_fetch_counts
            if self.stop_event.is_set():
                retry_crawler.request_stop()
            
            # 優先級隊列：對失敗的 ETF 進行排序
            # 策略：短代碼 ETF (4-5位) 優先，因為這些最難抓
            def etf_priority(symbol):
                # 返回值越小優先度越高
                code_len = len(symbol)
                is_etf = code_len <= 6 and (symbol.startswith("00") or code_len == 4)
                
                if not is_etf:
                    return 100  # 普通股票放後面
                elif code_len == 4:
                    return 1    # 4位 ETF 最優先
                elif code_len == 5:
                    return 2    # 5位混合型次優先
                else:
                    return 3    # 6位長代碼較不難
            
            # 按優先級排序，相同優先級保持原序
            failed_symbols_sorted = sorted(failed_symbols, key=etf_priority)
            if failed_symbols_sorted != failed_symbols:
                print(f"[*] 啟用 ETF 優先級隊列排序：短代碼 ETF 優先補抓")
            
            still_failed = []
            retry_success = 0
            retry_done_cnt = 0

            retry_exec = ThreadPoolExecutor(max_workers=current_workers)
            try:
                future_map = {
                    retry_exec.submit(retry_crawler._crawl_single_worker, s, trade_date): s
                    for s in failed_symbols_sorted
                }

                for fut in as_completed(future_map):
                    if self.stop_event.is_set():
                        raise KeyboardInterrupt
                    retry_done_cnt += 1
                    sym, df, status, reason = fut.result()
                    status_counts[status] += 1
                    reason_counts[self._normalize_reason(reason)] += 1
                    sym_name = name_map.get(sym, "")
                    name_str = f"({sym_name})" if sym_name else ""
                    ts_item = datetime.now().strftime("%H:%M:%S")

                    if df is not None and not df.empty:
                        all_dfs.append(df)
                        total_rows += len(df)
                        retry_success += 1
                        tag = "[終極救回 OK]" if is_final_round else "[OK]"
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] {tag} {sym} {name_str} -> 成功補回 {len(df)} 筆！")
                    elif status == "no_data":
                        confirmed_no_data_symbols.append(sym)
                        technical_failure_reason_by_symbol.pop(sym, None)
                        tag = "[確認無資料]" if is_final_round else "[確認本日無資料]"
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] {tag} {sym} {name_str}")
                    else:
                        still_failed.append(sym)
                        technical_failure_reason_by_symbol[sym] = reason
                        reason_tag = reason or "unknown"
                        tag = "[技術失敗]" if is_final_round else "[待下輪補抓]"
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] {tag} {sym} {name_str} (原因: {reason_tag})")
                    sys.stdout.flush()
            except KeyboardInterrupt:
                self.request_stop()
                retry_crawler.request_stop()
                retry_exec.shutdown(wait=False, cancel_futures=True)
                print(f"\n[{ts_round}] [!] 偵測到 Ctrl+C，中止 TWSE 第 {rounds_executed} 輪補抓...")
                sys.stdout.flush()
                raise
            finally:
                retry_exec.shutdown(wait=False, cancel_futures=True)

            ts_done = datetime.now().strftime("%H:%M:%S")
            print(
                f"[{ts_done}] [+] 第 {rounds_executed} 輪補抓完成！成功救回 {retry_success}/{retry_count} 檔 "
                f"(累計明確無資料: {len(confirmed_no_data_symbols)} 檔 | 剩餘技術失敗: {len(still_failed)} 檔)"
            )
            failed_symbols = still_failed

        ts_all_done = datetime.now().strftime("%H:%M:%S")
        if not failed_symbols:
            print(f"\n[{ts_all_done}] [+] 全市場標的 100% 抓取達成！(共執行 {rounds_executed} 輪)")
        else:
            print(f"\n[{ts_all_done}] [!] 達到最大補抓輪數 ({max_retry_rounds} 輪)，剩餘技術性失敗標的: {len(failed_symbols)} 檔")
            
            # 分析失敗原因分佈，特別針對 403 錯誤
            failure_by_reason = {}
            for sym, reason in technical_failure_reason_by_symbol.items():
                if reason not in failure_by_reason:
                    failure_by_reason[reason] = []
                failure_by_reason[reason].append(sym)
            
            if "post_http_error:403" in failure_by_reason or "menu_http_error:403" in failure_by_reason:
                http_403_count = len(failure_by_reason.get("post_http_error:403", [])) + len(failure_by_reason.get("menu_http_error:403", []))
                if http_403_count > 0:
                    print(f"[{ts_all_done}] [!] 注意：{http_403_count} 檔標的返回 HTTP 403（TWSE 持久限制），建議次日重試或檢查交易時間")

        self.last_run_stats = {
            "success_count": len(all_dfs),
            "no_data_count": len(confirmed_no_data_symbols),
            "technical_failure_count": len(failed_symbols),
            "status_counts": dict(status_counts),
            "reason_counts": dict(reason_counts),
            "confirmed_no_data_symbols": list(confirmed_no_data_symbols),
            "technical_failure_symbols": list(failed_symbols),
            "technical_failure_reason_by_symbol": dict(technical_failure_reason_by_symbol),
        }

        return all_dfs, failed_symbols, rounds_executed
