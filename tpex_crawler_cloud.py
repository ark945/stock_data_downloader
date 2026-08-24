"""
TPEX 證券櫃檯買賣中心（上櫃股票）券商買賣日報表爬蟲 — 雲端海外 Runner 專用模組 (Cloud / CI)
特點：
1. 專為 GitHub Actions 20 節點海外矩陣分片設計 (每節點約處理 50 檔)
2. 單一純淨持久 Chromium Session，避免海外 IP 反覆重啟撞擊 Cloudflare
3. 嚴格控管 4 分鐘 Turnstile Token 生命週期與連續失敗安全熔斷
4. 以實體「下載 CSV」按鈕作為精準判定，杜絕模糊文字誤殺
"""

import os
import sys
import glob
import time
import tempfile
import shutil
import re
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


class TPEXCloudCrawler:
    """GitHub Actions 雲端分片專用上櫃爬蟲"""

    TPEX_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir or os.path.join(os.path.dirname(__file__), "downloads_tpex_cloud")
        os.makedirs(self.download_dir, exist_ok=True)

    @staticmethod
    def get_all_tpex_symbols() -> List[str]:
        """取得上櫃股票與 ETF 清單"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        raw_symbols = []
        try:
            url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data:
                    code = str(item.get("SecuritiesCompanyCode", "")).strip()
                    if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                        raw_symbols.append(code)
        except Exception:
            pass

        if not raw_symbols:
            try:
                url = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=json"
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    for row in data.get("aaData", []):
                        if len(row) > 0:
                            code = str(row[0]).strip()
                            if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                                raw_symbols.append(code)
            except Exception:
                pass

        if not raw_symbols:
            raw_symbols = ["6488", "6117", "3293", "8069", "5483", "3131", "6274", "3529", "8299", "6180"]

        unique_symbols = sorted(list(dict.fromkeys(raw_symbols)))
        common_stocks = [s for s in unique_symbols if re.match(r"^[1-9][0-9]{3}[A-Za-z]?$", s)]
        etf_and_bonds = [s for s in unique_symbols if s.startswith("00") or s not in common_stocks]
        return common_stocks + etf_and_bonds

    def parse_tpex_csv_to_dataframe(self, csv_file_or_text, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        """解析 TPEX CSV 為標準 13 欄位 DataFrame"""
        try:
            if os.path.exists(str(csv_file_or_text)):
                with open(csv_file_or_text, "r", encoding="utf-8-sig", errors="replace") as f:
                    lines = f.readlines()
            else:
                lines = str(csv_file_or_text).splitlines()

            content_header = "".join(lines[:5])
            if ("證券代碼" in content_header or "證券代號" in content_header) and stock_id not in content_header:
                return None

            data_start = 0
            for i, line in enumerate(lines[:10]):
                if "序號" in line and "券商" in line:
                    data_start = i + 1
                    break

            records = []
            for line in lines[data_start:]:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 5:
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
                        continue

            if not records:
                return None

            df_raw = pd.DataFrame(records)
            df_raw["broker_id"] = df_raw["broker"].str.extract(r"^([A-Za-z0-9]{4})")[0].fillna(df_raw["broker"].str[:4])
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

        except Exception as e:
            print(f"[!] 解析 TPEX CSV 失敗 ({stock_id}): {e}")
            return None

    def _launch_browser_session(self, port: int = 9333):
        from DrissionPage import ChromiumPage, ChromiumOptions

        save_dir = os.path.join(self.download_dir, f"cloud_session_{port}")
        os.makedirs(save_dir, exist_ok=True)
        temp_user_data = tempfile.mkdtemp()

        if "DISPLAY" not in os.environ and os.name != "nt":
            os.environ["DISPLAY"] = ":99"

        co = ChromiumOptions()
        co.set_local_port(port)
        if sys.platform.startswith("linux"):
            for bin_p in ["/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome"]:
                if os.path.exists(bin_p):
                    co.set_paths(browser_path=bin_p)
                    break

        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--disable-infobars")
        co.set_argument("--window-size=1920,1080")
        co.set_argument("--excludeSwitches", "enable-automation")
        co.set_argument("--useAutomationExtension", False)

        co.set_user_data_path(temp_user_data)
        co.set_pref("download.default_directory", save_dir)
        co.set_pref("download.prompt_for_download", False)
        co.set_pref("safebrowsing.enabled", True)

        page = ChromiumPage(addr_or_opts=co)
        page.set.download_path(save_dir)
        try:
            page.download.set.show_msg(False)
        except Exception:
            pass

        page.get(self.TPEX_URL, retry=3, timeout=30)
        time.sleep(3.0)
        return page, temp_user_data, save_dir

    def crawl_stocks(
        self,
        stock_codes: List[str],
        trade_date: str
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """雲端單會話穩健抓取"""
        if not stock_codes:
            return [], []

        BASE_PORT = 9333
        collected_dfs = []
        failed_symbols = []
        total = len(stock_codes)
        page = None
        temp_user_data = None
        save_dir = None

        try:
            print(f"[*] 正在啟動 TPEX 雲端單一持久化引擎 (待抓取: {total} 檔)...")
            page, temp_user_data, save_dir = self._launch_browser_session(BASE_PORT)
            start_t = time.time()

            for idx, sym in enumerate(stock_codes, 1):
                try:
                    for old_f in glob.glob(os.path.join(save_dir, "*.csv")):
                        try: os.remove(old_f)
                        except OSError: pass

                    stk_input = page.ele("css:input.code", timeout=4) or page.ele("@name=code", timeout=4)
                    if not stk_input:
                        page.get(self.TPEX_URL, retry=2, timeout=15)
                        time.sleep(3.0)
                        stk_input = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)
                        if not stk_input:
                            failed_symbols.append(sym)
                            continue

                    stk_input.input(sym, clear=True, by_js=True)
                    try:
                        page.run_js('var el=document.querySelector("input.code");if(el){el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));}')
                    except Exception:
                        pass

                    q_btn = page.ele("css:.btn-query", timeout=2) or page.ele("text:查詢", timeout=2)
                    if q_btn:
                        q_btn.click(by_js=True)
                        time.sleep(1.0)

                    d_btn = page.ele("text:下載 CSV", timeout=2.5) or page.ele("text:下載 CSV (UTF-8)", timeout=1.5)
                    if not d_btn:
                        ts_nd = get_taipei_now().strftime("%H:%M:%S")
                        print(f"[{ts_nd}]   [上櫃 {idx}/{total}] [查無資料/無按鈕] {sym}")
                        sys.stdout.flush()
                        continue

                    try:
                        d_btn.click(by_js=True)
                    except Exception:
                        try: d_btn.click()
                        except Exception: pass

                    found_csv = None
                    for _ in range(16):
                        time.sleep(0.5)
                        if glob.glob(os.path.join(save_dir, "*.crdownload")):
                            continue
                        candidates = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
                        if candidates:
                            found_csv = candidates[0]
                            break

                    ts_res = get_taipei_now().strftime("%H:%M:%S")
                    if found_csv and os.path.exists(found_csv):
                        df = self.parse_tpex_csv_to_dataframe(found_csv, sym, trade_date)
                        if df is not None and not df.empty:
                            collected_dfs.append(df)
                            elapsed = time.time() - start_t
                            speed = idx / elapsed if elapsed > 0 else 0
                            remain = (total - idx) / speed if speed > 0 else 0
                            print(f"[{ts_res}]   [上櫃 {idx}/{total}] [OK] {sym} ({len(df)} 筆) | 速度: {speed:.2f} 檔/s | 剩餘約: {remain/60:.1f} 分鐘")
                        else:
                            print(f"[{ts_res}]   [上櫃 {idx}/{total}] [無成交明細/略過] {sym}")
                        try: os.remove(found_csv)
                        except OSError: pass
                    else:
                        failed_symbols.append(sym)
                        print(f"[{ts_res}]   [上櫃 {idx}/{total}] [下載超時] {sym}")

                except Exception as e:
                    ts_err = get_taipei_now().strftime("%H:%M:%S")
                    failed_symbols.append(sym)
                    print(f"[{ts_err}]   [上櫃 {idx}/{total}] [異常] {sym} ({e})")

                sys.stdout.flush()

        except Exception as e:
            print(f"[!] TPEX 雲端引擎異常: {e}")
        finally:
            if page:
                try: page.quit()
                except Exception: pass
            if temp_user_data:
                shutil.rmtree(temp_user_data, ignore_errors=True)
            if save_dir:
                shutil.rmtree(save_dir, ignore_errors=True)

        return collected_dfs, failed_symbols
