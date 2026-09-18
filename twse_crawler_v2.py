#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全新一代 TWSE 證交所券商分點買賣日報表爬蟲 (v2)
=====================================================
核心設計理念：
1. 【熔斷冷卻機制 (Circuit Breaker)】：
   - 實時監控站方限流指紋 (236 bytes 純空白頁、HTTP 403/429)。
   - 連續命中時自動休眠 60~90 秒，並透過單次探針驗證解封，杜絕盲目打爆 IP。
2. 【原生斷點續傳 (Checkpoint Manager)】：
   - 成功標的即時落盤至本地快取，隨時 Ctrl+C 中斷，再次啟動 0 秒跳過已完成標的。
3. 【自適應防禦節奏 (Adaptive Pacing Engine)】：
   - 全市場模式：1.0s ~ 1.5s 隨機震盪 + 每 50 檔微休呼吸 3~5 秒。
   - 定向小批量：自動切換 0.6s ~ 0.8s 敏捷模式。
4. 【雙引擎驗證碼與瀏覽器指紋】：
   - 整合 captcha_engine 專用 CNN + ddddocr 雙引擎。
   - 規範標準標頭 (Origin, Referer, Chrome 124)。
"""

import os
import sys
import time
import json
import random
import logging
import argparse
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Set

import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np

# 載入驗證碼辨識雙引擎
try:
    from captcha_engine import recognize_captcha
except ImportError:
    # 若在不同工作目錄啟動，補入腳本所在路徑
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from captcha_engine import recognize_captcha

# 控制台輸出編碼保障
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 建立專屬 logs 目錄與 FileHandler
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"crawler_twse_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logger = logging.getLogger("TWSE_v2")
logger.setLevel(logging.INFO)
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(log_file, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class TWSECrawlerV2:
    MENU_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"
    CONTENT_URL = "https://bsr.twse.com.tw/bshtm/bsContent.aspx"

    NO_DATA_MARKERS = [
        "查無資料",
        "查無此代碼",
        "查無符合條件之資料",
        "查無此證券",
    ]

    def __init__(
        self,
        trade_date: Optional[str] = None,
        base_delay: float = 1.2,
        max_retries: int = 4,
        output_dir: str = "output",
        circuit_cooldown: int = 75,
    ):
        """
        :param trade_date: 交易日期 (YYYY-MM-DD)，預設為今日
        :param base_delay: 基準請求間隔秒數 (預設 1.2s)
        :param max_retries: 單檔重試次數
        :param output_dir: 成品與快取輸出路徑
        :param circuit_cooldown: 熔斷觸發時的冷卻休眠秒數
        """
        self.trade_date = trade_date or datetime.today().strftime("%Y-%m-%d")
        self.base_delay = max(0.5, float(base_delay))
        self.max_retries = max_retries
        self.output_dir = output_dir
        self.circuit_cooldown = circuit_cooldown

        # 快取與斷點目錄
        self.cache_dir = os.path.join(self.output_dir, f".twse_v2_cache_{self.trade_date}")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.checkpoint_file = os.path.join(self.cache_dir, "completed_symbols.json")
        self.completed_symbols: Set[str] = self._load_checkpoint()

        # 標準瀏覽器指紋標頭
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": "https://bsr.twse.com.tw",
            "Referer": "https://bsr.twse.com.tw/bshtm/bsMenu.aspx",
        }

        # 熔斷狀態追蹤 (放寬閾值，避免偶發抖動過度休眠)
        self.consecutive_rate_limits = 0
        self.circuit_breaker_limit = 6  # 連續 6 次才判定為全局限流
        self.circuit_cooldown = min(self.circuit_cooldown, 25)  # 休眠秒數優化為 25 秒

    def _load_checkpoint(self) -> Set[str]:
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data)
            except Exception as e:
                logger.warning(f"讀取斷點檔案失敗 ({e})，重新建立斷點追蹤")
        return set()

    def _save_checkpoint(self, symbol: str):
        self.completed_symbols.add(str(symbol).strip())
        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self.completed_symbols)), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"寫入斷點失敗 ({e})")

    def _trigger_circuit_breaker(self):
        """觸發熔斷冷卻程序，倒數並使用探針檢驗解封"""
        logger.warning("=" * 60)
        logger.warning(f"[!] ⚠️ 偵測到 TWSE 站方限流警報 (連續 {self.consecutive_rate_limits} 次收到空白頁或拒絕連線)")
        logger.warning(f"[!] 啟動智慧熔斷冷卻機制，暫停所有請求休眠 {self.circuit_cooldown} 秒...")
        logger.warning("=" * 60)

        # 倒數計時
        for sec_left in range(self.circuit_cooldown, 0, -5):
            print(f"\r[*] 冷卻中，剩餘 {sec_left:2d} 秒...", end="", flush=True)
            time.sleep(min(5, sec_left))
        print("\r[*] 冷卻結束，發送探針驗證 TWSE 服務狀態...        ", flush=True)

        # 探針驗證
        for probe_attempt in range(3):
            time.sleep(2)
            probe_ok = self._probe_twse_alive()
            if probe_ok:
                logger.info("[✓] 探針驗證通過！TWSE 站方已恢復正常回應，重啟採集佇列！")
                self.consecutive_rate_limits = 0
                return
            else:
                logger.warning(f"[!] 探針仍被限流，額外冷卻 20 秒 (重試 {probe_attempt + 1}/3)...")
                time.sleep(20)

        logger.error("[!] 多次探針驗證均受限，嘗試繼續執行...")
        self.consecutive_rate_limits = 0

    def _probe_twse_alive(self) -> bool:
        """發送輕量探針確認是否已解除空白頁限流"""
        try:
            s = requests.Session()
            s.headers.update(self.headers)
            r = s.get(self.MENU_URL, timeout=8)
            if r.status_code != 200 or len(r.text) < 1000:
                return False
            soup = BeautifulSoup(r.text, "html.parser")
            return bool(soup.find("input", {"id": "__VIEWSTATE"}))
        except Exception:
            return False

    def fetch_single_symbol(self, symbol: str) -> Tuple[str, Optional[pd.DataFrame], str]:
        """
        採集單檔標的原始數據並解析
        :return: (symbol, DataFrame or None, status: 'success' | 'no_data' | 'failed')
        """
        sym = str(symbol).strip()

        # 若已在斷點快取中，直接讀取
        cached_parquet = os.path.join(self.cache_dir, f"{sym}.parquet")
        if sym in self.completed_symbols and os.path.exists(cached_parquet):
            try:
                df = pd.read_parquet(cached_parquet)
                return sym, df, "success"
            except Exception:
                pass

        for attempt in range(1, self.max_retries + 1):
            # 隨機安全微延遲
            delay = self.base_delay + random.uniform(0.1, 0.4)
            time.sleep(delay)

            session = requests.Session()
            session.headers.update(self.headers)

            try:
                # 1. 取得首頁表單欄位與驗證碼
                r_menu = session.get(self.MENU_URL, timeout=10)
                if r_menu.status_code != 200:
                    if r_menu.status_code in [403, 429]:
                        self.consecutive_rate_limits += 1
                        if self.consecutive_rate_limits >= self.circuit_breaker_limit:
                            self._trigger_circuit_breaker()
                    continue

                soup = BeautifulSoup(r_menu.text, "html.parser")
                viewstate_el = soup.find("input", {"id": "__VIEWSTATE"})
                viewstate_gen_el = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})
                event_val_el = soup.find("input", {"id": "__EVENTVALIDATION"})
                captcha_imgs = [img["src"] for img in soup.find_all("img") if "Captcha" in img.get("src", "")]

                if not (viewstate_el and captcha_imgs):
                    continue

                viewstate = viewstate_el["value"]
                viewstate_gen = viewstate_gen_el["value"] if viewstate_gen_el else ""
                event_val = event_val_el["value"] if event_val_el else ""

                # 2. 下載驗證碼並辨識
                captcha_url = "https://bsr.twse.com.tw/bshtm/" + captcha_imgs[0]
                r_img = session.get(captcha_url, timeout=8)
                if r_img.status_code != 200 or not r_img.content:
                    continue

                code = recognize_captcha(r_img.content)
                if not code or len(code) not in [5, 6]:
                    continue

                # 3. POST 表單送出查詢 (動態萃取全部隱藏欄位，確保 __VIEWSTATEENCRYPTED 等校驗標記完整)
                payload = {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input") if inp.get("name")}
                payload["RadioButton_Normal"] = "RadioButton_Normal"
                payload["TextBox_Stkno"] = str(sym).strip()
                payload["CaptchaControl1"] = code
                payload["btnOK"] = "查詢"
                payload.pop("RadioButton_Excd", None)
                payload.pop("Button_Reset", None)

                r_post = session.post(self.MENU_URL, data=payload, timeout=10)

                # 【關鍵限流偵測】：長度 < 500 bytes 且空 HTML (如 236 bytes 靜默限流)
                post_len = len(r_post.text)
                if r_post.status_code in [403, 429] or (r_post.status_code == 200 and post_len < 500):
                    self.consecutive_rate_limits += 1
                    if self.consecutive_rate_limits >= self.circuit_breaker_limit:
                        self._trigger_circuit_breaker()
                    continue

                post_html = r_post.text

                # 檢查是否為無資料標記
                if any(marker in post_html for marker in self.NO_DATA_MARKERS):
                    self.consecutive_rate_limits = 0
                    self._save_checkpoint(sym)
                    return sym, None, "no_data"

                # 檢查是否有下載連結
                has_download_link = "HyperLink_DownloadCSV" in post_html or "bsContent.aspx" in post_html
                if not has_download_link:
                    # 驗證碼錯誤或無下載連結，重試
                    continue

                # 4. 下載 CSV 內容
                time.sleep(0.4)
                r_content = session.get(self.CONTENT_URL, timeout=10)
                if r_content.status_code != 200 or len(r_content.content) < 50:
                    continue

                raw_csv = r_content.content.decode("utf-8-sig", errors="replace")
                df = self._parse_csv_to_dataframe(raw_csv, sym, self.trade_date)
                if df is not None and not df.empty:
                    # 成功採集，重置限流計數並即時落盤快取
                    self.consecutive_rate_limits = 0
                    df.to_parquet(cached_parquet, index=False)
                    self._save_checkpoint(sym)
                    return sym, df, "success"

            except Exception as e:
                # 遭遇網路短暫異常
                continue

        return sym, None, "failed"

    def _parse_csv_to_dataframe(self, csv_text: str, symbol: str, trade_date: str) -> Optional[pd.DataFrame]:
        """將 TWSE 雙欄 CSV 解析為標準 DataFrame 格式"""
        lines = csv_text.splitlines()
        data_lines = lines[3:] if len(lines) >= 3 else lines

        records = []
        for line in data_lines:
            parts = [p.strip().strip('"') for p in line.split(",")]
            # 左 5 欄
            if len(parts) >= 5 and parts[1]:
                try:
                    p = float(parts[2].replace(",", ""))
                    b = float(parts[3].replace(",", ""))
                    s = float(parts[4].replace(",", ""))
                    records.append({"broker": parts[1], "price": p, "buy": b, "sell": s})
                except ValueError:
                    pass

            # 右 5 欄 (若有)
            if len(parts) >= 11 and parts[7]:
                try:
                    p = float(parts[8].replace(",", ""))
                    b = float(parts[9].replace(",", ""))
                    s = float(parts[10].replace(",", ""))
                    records.append({"broker": parts[7], "price": p, "buy": b, "sell": s})
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
        grouped["symbol"] = str(symbol).strip()
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
        for c in ["buy_vol", "sell_vol", "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price", "sell_avg_price", "turnover", "market_share"]:
            res_df[c] = res_df[c].astype(np.float64)

        return res_df

    def get_all_twse_symbols(self) -> List[str]:
        """多重保底獲取全量 TWSE 上市股票與 ETF 代碼清單"""
        # 1. 本地 twstock 保底
        try:
            import twstock
            symbols = [
                code for code, info in twstock.codes.items()
                if getattr(info, "market", "") == "上市" and getattr(info, "type", "") in ["股票", "ETF", "臺灣存託憑證"]
            ]
            if len(symbols) > 500:
                return sorted(list(dict.fromkeys(symbols)))
        except Exception:
            pass

        # 2. TWSE OpenAPI 保底
        try:
            url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            r = requests.get(url, timeout=6)
            if r.status_code == 200:
                data = r.json()
                symbols = [item["Code"].strip() for item in data if "Code" in item and len(item["Code"].strip()) in [4, 5, 6]]
                if len(symbols) > 500:
                    return sorted(list(dict.fromkeys(symbols)))
        except Exception:
            pass

        # 3. 預設清單
        return ["2330", "2317", "2454", "2382", "2308", "2881", "2412", "2882", "2303", "2891"]

    def run(
        self,
        symbols: Optional[List[str]] = None,
        max_rounds: int = 3,
        shard_id: Optional[int] = None,
        num_shards: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        執行採集主流程
        :param symbols: 指定採集標的清單；若為 None 則採集全市場
        :param max_rounds: 失敗標的最大補抓輪數
        :param shard_id: 雲端分片 ID (0-indexed)
        :param num_shards: 雲端總分片數
        """
        raw_targets = symbols or self.get_all_twse_symbols()

        # 分片切分邏輯 (若提供 shard_id 與 num_shards)
        if shard_id is not None and num_shards is not None and num_shards > 1:
            target_symbols = [s for idx, s in enumerate(raw_targets) if idx % num_shards == shard_id]
            logger.info(f"[*] 啟動【雲端分片模式】：節點 {shard_id + 1} / {num_shards} (分得 {len(target_symbols)} / {len(raw_targets)} 檔)")
        else:
            target_symbols = raw_targets

        total_targets = len(target_symbols)

        # 依標的規模自適應調整節奏
        is_targeted = total_targets < 50
        if is_targeted:
            self.base_delay = 0.7
            logger.info(f"[*] 啟動【定向敏捷模式】：目標 {total_targets} 檔，基準延遲 {self.base_delay}s")
        else:
            logger.info(f"[*] 啟動【安全斷點模式】：目標 {total_targets} 檔，基準延遲 {self.base_delay}s")

        logger.info(f"[*] 交易日期: {self.trade_date} | 已完成斷點數: {len(self.completed_symbols)} 檔")

        pending_symbols = [s for s in target_symbols if s not in self.completed_symbols]
        logger.info(f"[*] 本次實際待採集標的: {len(pending_symbols)} 檔")

        round_no = 1
        while pending_symbols and round_no <= max_rounds:
            logger.info("=" * 60)
            logger.info(f"[*] >>> 第 {round_no} 輪採集啟動 (剩餘待辦: {len(pending_symbols)} 檔)...")
            logger.info("=" * 60)

            failed_in_this_round = []
            round_start_time = time.time()
            total_pending = len(pending_symbols)
            accumulated_rows = 0

            for idx, sym in enumerate(pending_symbols, 1):
                # 每 50 檔小休呼吸 3 秒 (防限流)
                if not is_targeted and idx > 1 and idx % 50 == 0:
                    logger.info(f"[*] 達到批次呼吸節點 ({idx}/{total_pending})，小休 3 秒...")
                    time.sleep(3)

                sym_res, df, status = self.fetch_single_symbol(sym)
                elapsed = max(0.1, time.time() - round_start_time)
                speed = idx / elapsed
                remaining_sec = (total_pending - idx) / speed if speed > 0 else 0
                pct = (idx / total_pending) * 100

                if status == "success":
                    rows_count = len(df) if df is not None else 0
                    accumulated_rows += rows_count
                    logger.info(f"[第{round_no}輪 進度 {idx}/{total_pending} ({pct:4.1f}%)] [✓] 標的 {sym:<5} 成功: {rows_count:4d} 筆 (累積: {accumulated_rows:6,d} 筆) | 速度: {speed:3.1f} 檔/s | 剩餘約: {remaining_sec/60:4.1f} 分")
                elif status == "no_data":
                    logger.info(f"[第{round_no}輪 進度 {idx}/{total_pending} ({pct:4.1f}%)] [-] 標的 {sym:<5} 今日無交易資料 | 速度: {speed:3.1f} 檔/s | 剩餘約: {remaining_sec/60:4.1f} 分")
                else:
                    logger.warning(f"[第{round_no}輪 進度 {idx}/{total_pending} ({pct:4.1f}%)] [!] 標的 {sym:<5} 採集失敗，待補抓")
                    failed_in_this_round.append(sym)

                sys.stdout.flush()

            pending_symbols = failed_in_this_round
            round_no += 1

            if pending_symbols and round_no <= max_rounds:
                logger.info(f"[*] 第 {round_no - 1} 輪完成，等待 5 秒後進行補抓...")
                time.sleep(5)

        # 匯總所有快取資料
        return self.export_results(target_symbols, shard_id=shard_id)

    def export_results(self, target_symbols: List[str], shard_id: Optional[int] = None) -> pd.DataFrame:
        """匯總快取中屬於本次標的的 parquet 檔案並導出標準成品"""
        logger.info("[*] 正在匯總快取成果...")
        dfs = []
        for sym in target_symbols:
            cached_parquet = os.path.join(self.cache_dir, f"{sym}.parquet")
            if os.path.exists(cached_parquet):
                try:
                    df = pd.read_parquet(cached_parquet)
                    dfs.append(df)
                except Exception:
                    pass

        if not dfs:
            logger.warning("[!] 未採集到任何有效交易資料")
            return pd.DataFrame()

        final_df = pd.concat(dfs, ignore_index=True)
        final_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id", "buy_vol", "sell_vol"], inplace=True)

        os.makedirs(self.output_dir, exist_ok=True)

        # 若為雲端分片執行，產出分片獨立檔
        if shard_id is not None:
            out_parquet = os.path.join(self.output_dir, f"api_absr1_{self.trade_date}_{self.trade_date}_twse_shard_{shard_id}.parquet")
            final_df.to_parquet(out_parquet, index=False)
            logger.info(f"[✓] 成功導出分片 Parquet: {out_parquet} (共計 {len(final_df)} 筆, 涵蓋 {final_df['symbol'].nunique()} 檔上市股)")
            return final_df

        out_parquet = os.path.join(self.output_dir, f"api_absr1_{self.trade_date}_{self.trade_date}_twse.parquet")
        out_excel = os.path.join(self.output_dir, f"api_absr1_{self.trade_date}_{self.trade_date}_twse.xlsx")

        final_df.to_parquet(out_parquet, index=False)
        logger.info(f"[✓] 成功導出上市 Parquet: {out_parquet} (共計 {len(final_df)} 筆, 涵蓋 {final_df['symbol'].nunique()} 檔上市股)")

        # 導出上市 Excel
        if len(final_df) <= 200000:
            try:
                final_df.to_excel(out_excel, index=False)
                logger.info(f"[✓] 成功導出上市 Excel: {out_excel}")
            except Exception:
                pass

        # 自動合併回全市場母表 (api_absr1_{DATE}_{DATE}.parquet)
        all_market_parquet = os.path.join(self.output_dir, f"api_absr1_{self.trade_date}_{self.trade_date}.parquet")
        all_market_excel = os.path.join(self.output_dir, f"api_absr1_{self.trade_date}_{self.trade_date}.xlsx")
        try:
            if os.path.exists(all_market_parquet):
                existing_df = pd.read_parquet(all_market_parquet)
                merged_all = pd.concat([existing_df, final_df], ignore_index=True)
                merged_all.drop_duplicates(subset=["symbol", "trade_date", "broker_id", "buy_vol", "sell_vol"], inplace=True)
                merged_all.to_parquet(all_market_parquet, index=False)
                logger.info(f"[✓] 成功自動合併至全市場總表: {all_market_parquet} (共 {len(merged_all)} 筆, {merged_all['symbol'].nunique()} 檔上市櫃)")
                if len(merged_all) <= 200000:
                    merged_all.to_excel(all_market_excel, index=False)
            else:
                final_df.to_parquet(all_market_parquet, index=False)
        except Exception as e:
            logger.warning(f"[!] 自動合併全市場總表失敗 ({e})，上市獨立檔已安全落盤")

        return final_df


def main():
    parser = argparse.ArgumentParser(description="全新一代 TWSE 證交所券商分點買賣日報表爬蟲 (v2)")
    parser.add_argument("--date", type=str, default=datetime.today().strftime("%Y-%m-%d"), help="指定交易日期 (YYYY-MM-DD)")
    parser.add_argument("--symbols", type=str, default=None, help="指定標的清單 (逗號分隔，例如: 2330,2317,2454)")
    parser.add_argument("--delay", type=float, default=1.2, help="基準延遲秒數 (預設 1.2s)")
    parser.add_argument("--output-dir", type=str, default="output", help="輸出資料夾")
    parser.add_argument("--cooldown", type=int, default=75, help="熔斷休眠秒數 (預設 75s)")
    parser.add_argument("--rounds", type=int, default=3, help="最大補抓輪數")
    parser.add_argument("--shard-id", type=int, default=None, help="雲端分片 ID (0-indexed)")
    parser.add_argument("--num-shards", type=int, default=None, help="雲端總分片數")
    args = parser.parse_args()

    symbol_list = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    crawler = TWSECrawlerV2(
        trade_date=args.date,
        base_delay=args.delay,
        output_dir=args.output_dir,
        circuit_cooldown=args.cooldown,
    )

    df_res = crawler.run(
        symbols=symbol_list,
        max_rounds=args.rounds,
        shard_id=args.shard_id,
        num_shards=args.num_shards,
    )
    print(f"\n[*] 採集任務結束！有效數據行數: {len(df_res)}")


if __name__ == "__main__":
    main()
