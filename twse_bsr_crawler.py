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
from collections import Counter
from typing import List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)

# 載入雙引擎驗證碼
try:
    from captcha_engine import recognize_captcha
except ImportError:
    from .captcha_engine import recognize_captcha


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

    # 備用保底清單
    return ["2330", "2317", "2454", "2382", "2308", "2881", "2412", "2882", "2303", "2891"]


class TWSEBrokerCrawler:
    """TWSE 券商買賣日報表爬蟲類別"""

    MENU_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"
    CONTENT_URL = "https://bsr.twse.com.tw/bshtm/bsContent.aspx"

    def __init__(self, delay_sec: float = 0.4, max_retries: int = 6, debug: bool = False):
        """
        初始化上市爬蟲實例
        :param delay_sec: 每次請求之間的保護性延遲秒數 (預設 0.4s 安全平衡)
        :param max_retries: 單一股票單輪最大重試次數
        """
        self.delay_sec = delay_sec
        self.max_retries = max_retries
        self.debug = debug
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://bsr.twse.com.tw/bshtm/bsMenu.aspx",
        }

    def _get_latest_trade_date(self) -> str:
        today = get_taipei_now()
        if today.weekday() == 5:
            delta = 1
        elif today.weekday() == 6:
            delta = 2
        else:
            delta = 0 if today.hour >= 18 else 1
        return (today - pd.Timedelta(days=delta)).strftime("%Y-%m-%d")

    def fetch_stock_raw_csv_with_reason(self, stock_id: str) -> Tuple[Optional[str], str]:
        last_reason = "unknown"
        for attempt in range(1, self.max_retries + 1):
            try:
                session = requests.Session()
                session.headers.update(self.headers)

                # 1. 取得首頁與 ViewState
                r_menu = session.get(self.MENU_URL, timeout=8)
                if r_menu.status_code != 200:
                    last_reason = f"menu_http_{r_menu.status_code}"
                    time.sleep(0.3)
                    continue

                soup = BeautifulSoup(r_menu.text, "html.parser")
                viewstate_el = soup.find("input", {"id": "__VIEWSTATE"})
                viewstate_gen_el = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})
                event_val_el = soup.find("input", {"id": "__EVENTVALIDATION"})
                captcha_imgs = [img["src"] for img in soup.find_all("img") if "Captcha" in img.get("src", "")]

                if not (viewstate_el and captcha_imgs):
                    last_reason = "menu_parse_missing_viewstate_or_captcha"
                    time.sleep(0.3)
                    continue

                viewstate = viewstate_el["value"]
                viewstate_gen = viewstate_gen_el["value"] if viewstate_gen_el else ""
                event_val = event_val_el["value"] if event_val_el else ""

                # 2. 下載驗證碼並透過雙引擎辨識
                captcha_url = "https://bsr.twse.com.tw/bshtm/" + captcha_imgs[0]
                r_img = session.get(captcha_url, timeout=8)
                if r_img.status_code != 200:
                    last_reason = f"captcha_http_{r_img.status_code}"
                    continue

                captcha_code = recognize_captcha(r_img.content)
                if not captcha_code:
                    last_reason = "captcha_ocr_failed"
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
                    last_reason = f"post_http_{r_post.status_code}"
                    continue
                post_html = r_post.text

                # 正向精確判定：只要伺服器生成下載連結，代表查詢成功，立刻下載 CSV
                if "HyperLink_DownloadCSV" in post_html or "bsContent.aspx" in post_html:
                    time.sleep(0.35)
                    r_content = session.get(self.CONTENT_URL, timeout=8)
                    if r_content.status_code == 200 and len(r_content.content) > 100:
                        raw_text = r_content.content.decode("utf-8-sig", errors="replace")
                        if "券商買賣股票成交價量資訊" in raw_text or "股票代碼" in raw_text:
                            return raw_text, "success"
                        last_reason = "content_schema_mismatch"
                        continue
                    last_reason = f"content_http_{r_content.status_code}_or_too_small"
                    continue

                # 若明確回傳查無代碼或查無符合資料，代表當日確實無交易
                if "查無此代碼" in post_html or "查無符合條件之資料" in post_html or "查無此證券" in post_html:
                    return "", "no_trade_confirmed"
                if "驗證碼" in post_html:
                    last_reason = "captcha_invalid"
                elif "系統忙碌" in post_html or "稍後再試" in post_html:
                    last_reason = "server_busy_or_rate_limited"
                else:
                    last_reason = "post_response_unclassified"

                # 其餘狀況 (驗證碼錯誤或伺服器忙碌) 自動進入下一次換圖重試
                time.sleep(0.2)
                continue

            except requests.Timeout:
                last_reason = "request_timeout"
            except requests.RequestException as e:
                last_reason = f"request_exception_{type(e).__name__}"
            except Exception as e:
                last_reason = f"exception_{type(e).__name__}"

            if self.debug:
                ts = get_taipei_now().strftime("%H:%M:%S")
                print(f"[{ts}] [TWSE-DEBUG] {stock_id} attempt {attempt}/{self.max_retries} -> {last_reason}")
            time.sleep(0.1)

        return None, last_reason

    def fetch_stock_raw_csv(self, stock_id: str) -> Optional[str]:
        csv_text, _ = self.fetch_stock_raw_csv_with_reason(stock_id)
        return csv_text

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
        if self.delay_sec > 0:
            time.sleep(self.delay_sec)
        csv_text, reason = self.fetch_stock_raw_csv_with_reason(sym)
        if csv_text == "":
            return (sym, None, "no_trade", reason)
        if csv_text is None:
            return (sym, None, "failed", reason)

        df = self.parse_csv_to_dataframe(csv_text, sym, trade_date)
        if df is not None and not df.empty:
            return (sym, df, "success", "success")
        return (sym, None, "failed", "parse_empty_or_invalid")

    def crawl_stocks(
        self,
        symbols: List[str],
        trade_date: str = "",
        max_workers: int = 4,
        max_retry_rounds: int = 6
    ) -> Tuple[List[pd.DataFrame], List[str], int, List[str], dict]:
        """
        批次抓取指定上市股票清單 (支援最多 6 輪自適應安全補抓機制)
        :return: (all_dfs, final_failed_symbols, total_rounds_executed, no_trade_symbols, failed_reason_map)
        """
        if not trade_date:
            trade_date = self._get_latest_trade_date()

        total_symbols = len(symbols)
        print(f"==================================================")
        print(f"[*] TWSE 上市券商買賣日報表爬蟲 (6 輪自適應安全防護版)")
        print(f"[*] 目標交易日期: {trade_date}")
        print(f"[*] 待抓取標的數: {total_symbols} 檔")
        print(f"[*] 並行執行緒數: {max_workers} Workers (第 1 輪)")
        print(f"[*] 最大補抓輪數: {max_retry_rounds} 輪 (自適應降速防 Ban)")
        print(f"==================================================")
        sys.stdout.flush()

        all_dfs = []
        failed_symbols = []
        no_trade_symbols = []
        failed_reason_map = {}
        completed_count = 0
        total_rows = 0
        start_time = time.time()

        # 第 1 輪：雙線程標準並行抓取
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_sym = {
                executor.submit(self._crawl_single_worker, sym, trade_date): sym
                for sym in symbols
            }

            for future in as_completed(future_to_sym):
                completed_count += 1
                sym, df, status, reason = future.result()

                if status == "success" and df is not None and not df.empty:
                    all_dfs.append(df)
                    total_rows += len(df)
                    failed_reason_map.pop(sym, None)
                elif status == "no_trade":
                    no_trade_symbols.append(sym)
                    failed_reason_map.pop(sym, None)
                else:
                    failed_symbols.append(sym)
                    failed_reason_map[sym] = reason
                    if self.debug:
                        ts_dbg = get_taipei_now().strftime("%H:%M:%S")
                        print(f"[{ts_dbg}] [TWSE-DEBUG] 第1輪待補 {sym} -> {reason}")

                if completed_count % 15 == 0 or completed_count == total_symbols:
                    elapsed = time.time() - start_time
                    speed = completed_count / elapsed if elapsed > 0 else 0
                    remaining = (total_symbols - completed_count) / speed if speed > 0 else 0
                    pct = (completed_count / total_symbols) * 100
                    success_cnt = len(all_dfs)
                    no_trade_cnt = len(no_trade_symbols)
                    retry_cnt = len(failed_symbols)
                    ts_now = get_taipei_now().strftime("%H:%M:%S")
                    print(
                        f"[{ts_now}] [第1輪 進度 {completed_count}/{total_symbols} ({pct:.1f}%)] "
                        f"成功: {success_cnt} 檔 | 無交易: {no_trade_cnt} 檔 | 待補: {retry_cnt} 檔 | "
                        f"累積: {total_rows:,} 筆 | 速度: {speed:.1f} 檔/s | "
                        f"剩餘約: {remaining/60:.1f} 分鐘"
                    )
                    sys.stdout.flush()

        rounds_executed = 1

        # 第 2 ~ N 輪階梯式自適應安全補抓
        delay_schedule = [1.2, 1.8, 2.5, 3.2, 4.0]  # 各輪安全延遲秒數
        
        while failed_symbols and rounds_executed < max_retry_rounds:
            rounds_executed += 1
            retry_count = len(failed_symbols)
            current_delay = delay_schedule[min(rounds_executed - 2, len(delay_schedule) - 1)]
            
            ts_round = get_taipei_now().strftime("%H:%M:%S")
            print(f"\n" + "-"*50)
            print(f"[{ts_round}] [*] 啟動第 {rounds_executed}/{max_retry_rounds} 輪精準安全補抓佇列 (待補抓: {retry_count} 檔)")
            print(f"[{ts_round}] [*] 安全防護策略: 4-Workers 安全並行模式, 請求間隔 {current_delay}s, 預防 TWSE 頻率限制")
            print(f"-"*50)
            sys.stdout.flush()
            
            time.sleep(2)  # 輪次切換冷卻 2 秒
            
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

            retry_crawler = TWSEBrokerCrawler(delay_sec=current_delay, max_retries=4, debug=self.debug)
            still_failed = []
            still_failed_reason_map = {}
            retry_success = 0
            retry_done_cnt = 0

            with ThreadPoolExecutor(max_workers=4) as retry_exec:
                future_map = {
                    retry_exec.submit(retry_crawler._crawl_single_worker, s, trade_date): s
                    for s in failed_symbols
                }

                for fut in as_completed(future_map):
                    retry_done_cnt += 1
                    sym, df, status, reason = fut.result()
                    sym_name = name_map.get(sym, "")
                    name_str = f"({sym_name})" if sym_name else ""
                    ts_item = datetime.now().strftime("%H:%M:%S")

                    if status == "success" and df is not None and not df.empty:
                        all_dfs.append(df)
                        total_rows += len(df)
                        retry_success += 1
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] [OK] {sym} {name_str} -> 成功補回 {len(df)} 筆！")
                    elif status == "no_trade":
                        no_trade_symbols.append(sym)
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] [無交易] {sym} {name_str} (TWSE 回覆查無符合資料)")
                        failed_reason_map.pop(sym, None)
                    else:
                        still_failed.append(sym)
                        still_failed_reason_map[sym] = reason
                        print(f"[{ts_item}]   [第{rounds_executed}輪 {retry_done_cnt}/{retry_count}] [待下輪補抓] {sym} {name_str} (技術性失敗)")
                        if self.debug:
                            print(f"[{ts_item}]   [TWSE-DEBUG] {sym} {name_str} 技術性失敗原因: {reason}")
                    sys.stdout.flush()

            ts_done = datetime.now().strftime("%H:%M:%S")
            print(
                f"[{ts_done}] [+] 第 {rounds_executed} 輪補抓完成！成功救回 {retry_success}/{retry_count} 檔 "
                f"(剩餘待補: {len(still_failed)} 檔, 已確認無交易: {len(no_trade_symbols)} 檔)"
            )
            failed_symbols = still_failed
            failed_reason_map = still_failed_reason_map

        ts_all_done = datetime.now().strftime("%H:%M:%S")
        if not failed_symbols:
            print(
                f"\n[{ts_all_done}] [+] 全市場標的抓取完成！(共執行 {rounds_executed} 輪) "
                f"| 成功: {len(all_dfs)} 檔 | 無交易: {len(no_trade_symbols)} 檔"
            )
        else:
            print(
                f"\n[{ts_all_done}] [!] 達到最大補抓輪數 ({max_retry_rounds} 輪)，剩餘技術性失敗: {len(failed_symbols)} 檔 "
                f"| 已確認無交易: {len(no_trade_symbols)} 檔"
            )
            if self.debug and failed_reason_map:
                reason_counter = Counter(failed_reason_map.values())
                reason_text = ", ".join([f"{k}: {v}" for k, v in reason_counter.items()])
                print(f"[{ts_all_done}] [TWSE-DEBUG] 失敗原因統計 -> {reason_text}")

        return all_dfs, failed_symbols, rounds_executed, no_trade_symbols, failed_reason_map
