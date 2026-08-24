"""
TPEX 證券櫃檯買賣中心（上櫃股票）券商買賣日報表爬蟲
支援：
1. 取得全市場上櫃標的清單
2. DrissionPage 瀏覽器自動化繞過 Cloudflare 下載分點 CSV
3. 自動解析聚合為標準 13 欄位 DataFrame (對齊 TWSE / FinLab 格式)
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
import multiprocessing
import pandas as pd
import numpy as np

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)

def _mp_tpex_worker_task(
    worker_id: int,
    symbols: List[str],
    trade_date: str,
    download_dir: str,
    tpex_url: str,
    result_queue: multiprocessing.Queue
):
    """獨立進程專屬的 Chromium Worker 任務 (完全隔離、零線程衝突)"""
    from DrissionPage import ChromiumPage, ChromiumOptions

    save_dir = os.path.join(download_dir, f"worker_proc_{worker_id}")
    os.makedirs(save_dir, exist_ok=True)
    temp_user_data = tempfile.mkdtemp()

    if "DISPLAY" not in os.environ and os.name != "nt":
        os.environ["DISPLAY"] = ":99"

    co = ChromiumOptions()
    co.set_local_port(9430 + worker_id)
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

    page = None
    collected_dfs = []
    failed_symbols = []
    worker_total = len(symbols)
    crawler = TPEXBrokerCrawler(download_dir=download_dir)

    try:
        page = ChromiumPage(addr_or_opts=co)
        page.set.download_path(save_dir)
        try:
            page.download.set.show_msg(False)
        except Exception:
            pass

        # 錯開啟動時機，防止同時向 Cloudflare 發起初始握手
        if worker_id > 1:
            time.sleep((worker_id - 1) * 1.5)

        page.get(tpex_url, retry=3, timeout=25)
        time.sleep(2.5)

        stk_input = page.ele("css:input.code", timeout=4) or page.ele("@name=code", timeout=4)
        q_btn = page.ele("css:.btn-query", timeout=1) or page.ele("text:查詢", timeout=1)
        d_btn = page.ele("text:下載 CSV (UTF-8)", timeout=1) or page.ele("text:下載 CSV", timeout=1)

        for idx, sym in enumerate(symbols, 1):
            try:
                target_csv_file = os.path.join(save_dir, f"{sym}.csv")
                if os.path.exists(target_csv_file):
                    try: os.remove(target_csv_file)
                    except OSError: pass

                if not stk_input:
                    stk_input = page.ele("css:input.code", timeout=3) or page.ele("@name=code", timeout=3)

                if stk_input:
                    stk_input.input(sym, clear=True, by_js=True)

                if q_btn:
                    q_btn.click(by_js=True)
                    time.sleep(0.2)

                if d_btn:
                    mission = d_btn.click.to_download(save_path=save_dir, rename=f"{sym}.csv")
                    mission.wait(show=False, timeout=3.5)

                    ts_res = datetime.now().strftime("%H:%M:%S")
                    if os.path.exists(target_csv_file):
                        df = crawler.parse_tpex_csv_to_dataframe(target_csv_file, sym, trade_date)
                        if df is not None and not df.empty:
                            collected_dfs.append(df)
                            print(f"[{ts_res}]   [W{worker_id} {idx}/{worker_total}] [OK] {sym} ({len(df)} 筆)")
                        else:
                            failed_symbols.append(sym)
                            print(f"[{ts_res}]   [W{worker_id} {idx}/{worker_total}] [無資料/略過] {sym}")
                    else:
                        failed_symbols.append(sym)
                        print(f"[{ts_res}]   [W{worker_id} {idx}/{worker_total}] [無資料/略過] {sym}")
                else:
                    ts_btn = datetime.now().strftime("%H:%M:%S")
                    failed_symbols.append(sym)
                    print(f"[{ts_btn}]   [W{worker_id} {idx}/{worker_total}] [查無按鈕] {sym}")

            except Exception as e:
                ts_err = datetime.now().strftime("%H:%M:%S")
                failed_symbols.append(sym)
                print(f"[{ts_err}]   [W{worker_id} {idx}/{worker_total}] [異常] {sym} ({e})")

            sys.stdout.flush()

    except Exception as e:
        import traceback
        print(f"[!] TPEX Worker {worker_id} 引擎異常: {e}")
        traceback.print_exc()
    finally:
        if page:
            try: page.quit()
            except Exception: pass
        shutil.rmtree(temp_user_data, ignore_errors=True)
        shutil.rmtree(save_dir, ignore_errors=True)

    result_queue.put((collected_dfs, failed_symbols))


class TPEXBrokerCrawler:
    """TPEX 櫃買中心券商買賣日報表爬蟲類別"""

    TPEX_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir or os.path.join(os.path.dirname(__file__), "downloads_tpex")
        os.makedirs(self.download_dir, exist_ok=True)

    @staticmethod
    def get_all_tpex_symbols() -> List[str]:
        """
        取得目前所有上櫃（TPEx）股票與 ETF 代碼清單 (精確排除 9,500+ 檔 6 碼權證)
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 策略 1: TPEX OpenAPI 每日收盤行情
        try:
            url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                stock_symbols = []
                for item in data:
                    code = str(item.get("SecuritiesCompanyCode", "")).strip()
                    # 篩選 4 碼個股 (如 6488)、特別股 (如 8349A) 或上櫃 ETF (如 00720B)，排除 6 碼權證 (如 734294)
                    if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                        stock_symbols.append(code)
                if len(stock_symbols) > 300:
                    return sorted(list(dict.fromkeys(stock_symbols)))
        except Exception:
            pass

        # 策略 2: 傳統 TPEX API
        try:
            url = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=json"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                tables = data.get("aaData", [])
                stock_symbols = []
                for row in tables:
                    if len(row) > 0:
                        code = str(row[0]).strip()
                        if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                            stock_symbols.append(code)
                if len(stock_symbols) > 300:
                    return sorted(list(dict.fromkeys(stock_symbols)))
        except Exception:
            pass

        # 策略 3: 官方證券編碼彙總表 (ISIN - 包含所有上櫃股票與 ETF，全年無休最穩定)
        try:
            from bs4 import BeautifulSoup
            url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                r.encoding = "big5"
                soup = BeautifulSoup(r.text, "html.parser")
                stock_symbols = []
                for row in soup.find_all("tr"):
                    tds = row.find_all("td")
                    if len(tds) > 0:
                        txt = tds[0].text.strip()
                        parts = txt.split()
                        if len(parts) >= 2:
                            code = parts[0]
                            if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                                stock_symbols.append(code)
                if len(stock_symbols) > 300:
                    return sorted(list(dict.fromkeys(stock_symbols)))
        except Exception:
            pass

        # 預設常見上櫃指標股
        return ["6488", "6117", "3293", "8069", "5483", "3131", "6274", "3529", "8299", "6180"]

    def _find_downloaded_csv(self, stock_code: str, search_dir: str) -> Optional[str]:
        patterns = [
            f"{stock_code}*.csv",
            f"*{stock_code}*.csv",
            "brokerBS*.csv",
            "brokerBS*",
        ]
        candidates = []
        for pat in patterns:
            for f in glob.glob(os.path.join(search_dir, pat)):
                if os.path.exists(f) and os.path.getsize(f) > 100:
                    candidates.append(f)
        if candidates:
            return max(candidates, key=os.path.getctime)
        return None

    def parse_tpex_csv_to_dataframe(self, csv_file_or_text, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        """
        解析 TPEX 原始 CSV 並聚合為標準 13 欄位 DataFrame (支援 CP950/Big5/UTF-8 自適應解碼)
        """
        try:
            lines = []
            if os.path.exists(str(csv_file_or_text)):
                for enc in ["cp950", "big5", "utf-8-sig", "utf-8"]:
                    try:
                        with open(csv_file_or_text, "r", encoding=enc) as f:
                            lines = f.readlines()
                        if lines and len(lines) > 2:
                            break
                    except Exception:
                        continue
            else:
                lines = str(csv_file_or_text).splitlines()

            if not lines:
                return None

            # TPEX 格式前 2 行包含：證券代號,XXXX 或 證券代碼,XXXX
            # 嚴格校驗 CSV 內部代碼是否符合目標 stock_id，防止誤讀舊檔
            content_header = "".join(lines[:5])
            if ("證券代碼" in content_header or "證券代號" in content_header) and stock_id not in content_header:
                return None

            # 找到包含「序號」或「券商」的資料起點
            data_start = 0
            for i, line in enumerate(lines[:10]):
                if "序號" in line and "券商" in line:
                    data_start = i + 1
                    break

            records = []
            for line in lines[data_start:]:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 5:
                    # 序號, 券商, 價格, 買進股數, 賣出股數
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

            # 計算均價與市佔率
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

    def _launch_tpex_browser_session(self, port: int):
        """啟動一個全新 Chromium session，回傳 (page, temp_user_data, save_dir)。
        每次呼叫產生獨立 user data 與下載目錄，供 hard-restart 使用。
        save_dir 必須位於專案目錄且權限 0o755，snap chromium 才能寫入下載暫存檔。"""
        from DrissionPage import ChromiumPage, ChromiumOptions

        os.makedirs(self.download_dir, exist_ok=True)
        unique = f"{port}_{int(time.time() * 1000)}"
        save_dir = os.path.join(self.download_dir, f"batch_{unique}")
        temp_user_data = os.path.join(self.download_dir, f"userdata_{unique}")
        os.makedirs(save_dir, exist_ok=True)
        os.makedirs(temp_user_data, exist_ok=True)
        try:
            os.chmod(save_dir, 0o755)
            os.chmod(temp_user_data, 0o755)
        except OSError:
            pass

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
        page.get(self.TPEX_URL, retry=3, timeout=25)
        # 給 Cloudflare Turnstile 足夠時間自動解算 (雲端 IP 首次進站尤其需要)。
        time.sleep(8)
        return page, temp_user_data, save_dir

    def crawl_all_stocks_session(
        self,
        stock_codes: List[str],
        trade_date: str,
        workers: int = 1
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """
        使用單一持久化 Chromium 瀏覽器會話循序抓取全市場上櫃股票 (規避 Cloudflare 限流，100% 穩定零漏抓)
        每 4 分鐘主動 hard-restart Chromium (Cloudflare Turnstile Token 5 分鐘過期)；連續 3 檔失敗亦強制重建。
        """
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions  # noqa: F401
        except ImportError:
            print("[!] 未安裝 DrissionPage，請執行 pip install DrissionPage")
            return [], stock_codes

        # Cloudflare Turnstile Token 約 5 分鐘過期，提前 1 分鐘 (240s) 主動換 session。
        SESSION_MAX_SEC = 240
        MAX_CONSECUTIVE_MISS = 3
        BASE_PORT = 9333
        # 單一 round 內限制 restart 次數，超過就中斷 round 讓外層 retry 隔更久接手 (避免對 CF 反覆撞牆)。
        MAX_RESTART_PER_ROUND = 3
        # Hard-restart 前的冷卻，給 CF 該 IP 反爬蟲評分緩衝。
        RESTART_COOLDOWN_SEC = 5

        page = None
        temp_user_data = None
        save_dir = None
        collected_dfs = []
        failed_symbols = []
        total = len(stock_codes)
        start_t = time.time()
        restart_counter = 0

        def _cleanup_session():
            nonlocal page, temp_user_data, save_dir
            if page:
                try: page.quit()
                except Exception: pass
                page = None
            if temp_user_data:
                shutil.rmtree(temp_user_data, ignore_errors=True)
                temp_user_data = None
            if save_dir:
                shutil.rmtree(save_dir, ignore_errors=True)
                save_dir = None

        def _restart_session(reason: str):
            nonlocal page, temp_user_data, save_dir, restart_counter
            _cleanup_session()
            restart_counter += 1
            port = BASE_PORT + restart_counter
            ts = get_taipei_now().strftime("%H:%M:%S")
            print(f"[{ts}] [*] Hard-restart TPEX Chromium session #{restart_counter} (port={port}) — 原因: {reason} — 冷卻 {RESTART_COOLDOWN_SEC}s")
            sys.stdout.flush()
            time.sleep(RESTART_COOLDOWN_SEC)
            page, temp_user_data, save_dir = self._launch_tpex_browser_session(port)

        try:
            print(f"[*] 正在啟動 TPEX 單一持久化極速引擎 (待抓取: {total} 檔)...")
            page, temp_user_data, save_dir = self._launch_tpex_browser_session(BASE_PORT)
            session_start = time.time()
            consecutive_misses = 0

            for idx, sym in enumerate(stock_codes, 1):
                # Turnstile Token 即將過期 → 主動 hard-restart 避開失敗
                if time.time() - session_start >= SESSION_MAX_SEC:
                    _restart_session(f"session 已使用 {int(time.time() - session_start)}s (>= {SESSION_MAX_SEC}s)")
                    session_start = time.time()
                    consecutive_misses = 0

                try:
                    # 清空暫存目錄下的所有舊 CSV
                    for old_f in glob.glob(os.path.join(save_dir, "*.csv")):
                        try: os.remove(old_f)
                        except OSError: pass

                    # 定位輸入框並填入代號
                    stk_input = page.ele("css:input.code", timeout=4) or page.ele("@name=code", timeout=4)
                    if not stk_input:
                        page.get(self.TPEX_URL, retry=2, timeout=15)
                        time.sleep(3.5)
                        stk_input = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)
                        if not stk_input:
                            failed_symbols.append(sym)
                            continue

                    stk_input.input(sym, clear=True, by_js=True)
                    # 讓 React/Vue state 收到 input event
                    try:
                        page.run_js('var el=document.querySelector("input.code");if(el){el.dispatchEvent(new Event("input",{bubbles:true}));el.dispatchEvent(new Event("change",{bubbles:true}));}')
                    except Exception:
                        pass

                    q_btn = page.ele("css:.btn-query", timeout=2) or page.ele("text:查詢", timeout=2)
                    if not q_btn:
                        failed_symbols.append(sym)
                        consecutive_misses += 1
                        ts_nq = get_taipei_now().strftime("%H:%M:%S")
                        print(f"[{ts_nq}]   [上櫃 {idx}/{total}] [查詢鈕缺失] {sym}")
                        # 觸發下方 restart 檢查
                        if consecutive_misses >= MAX_CONSECUTIVE_MISS:
                            if restart_counter >= MAX_RESTART_PER_ROUND:
                                for skip_sym in stock_codes[idx:]:
                                    failed_symbols.append(skip_sym)
                                break
                            _restart_session(f"連續 {consecutive_misses} 檔失敗")
                            session_start = time.time()
                            consecutive_misses = 0
                        continue

                    q_btn.click(by_js=True)
                    time.sleep(1.2)

                    # 1. 快速檢測頁面是否提示「查無資料 / 本日無交易」
                    no_data = False
                    for kw in ["查無符合資料", "無符合條件", "本日無交易", "查無資料", "沒有符合", "無此股票"]:
                        if page.ele(f"text:{kw}", timeout=0.5):
                            no_data = True
                            break

                    if no_data:
                        ts_nd = get_taipei_now().strftime("%H:%M:%S")
                        consecutive_misses = 0
                        print(f"[{ts_nd}]   [上櫃 {idx}/{total}] [無交易/略過] {sym}")
                        sys.stdout.flush()
                        continue

                    found_csv = None
                    reason = ""

                    d_btn = page.ele("text:下載 CSV", timeout=2.5) or page.ele("text:下載 CSV (UTF-8)", timeout=1.5)
                    if not d_btn:
                        ts_nd = get_taipei_now().strftime("%H:%M:%S")
                        consecutive_misses = 0
                        print(f"[{ts_nd}]   [上櫃 {idx}/{total}] [無交易/略過] {sym}")
                        sys.stdout.flush()
                        continue

                    # 2. 乾淨的原生點擊下載 (完全杜絕 page.listen CDP 死鎖)
                    try:
                        d_btn.click(by_js=True)
                    except Exception:
                        try:
                            d_btn.click()
                        except Exception as e_clk:
                            reason = f"點擊失敗: {e_clk}"

                    # 3. 穩定輪詢下載目錄中的 CSV 檔案 (最多 8 秒，0.5s * 16)
                    for _ in range(16):
                        time.sleep(0.5)
                        # 檢查是否仍在下載 (.crdownload)
                        if glob.glob(os.path.join(save_dir, "*.crdownload")) or glob.glob(os.path.join(save_dir, "*.tmp")):
                            continue
                        candidates = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
                        if candidates:
                            found_csv = candidates[0]
                            break

                    if not found_csv and not reason:
                        reason = "下載無回應"

                    ts_res = get_taipei_now().strftime("%H:%M:%S")
                    if found_csv and os.path.exists(found_csv):
                        df = self.parse_tpex_csv_to_dataframe(found_csv, sym, trade_date)
                        if df is not None and not df.empty:
                            collected_dfs.append(df)
                            consecutive_misses = 0
                            elapsed = time.time() - start_t
                            speed = idx / elapsed if elapsed > 0 else 0
                            remain = (total - idx) / speed if speed > 0 else 0
                            print(f"[{ts_res}]   [上櫃 {idx}/{total}] [OK] {sym} ({len(df)} 筆) | 速度: {speed:.2f} 檔/s | 剩餘約: {remain/60:.1f} 分鐘")
                        else:
                            consecutive_misses = 0
                            print(f"[{ts_res}]   [上櫃 {idx}/{total}] [無成交明細/略過] {sym}")
                    else:
                        failed_symbols.append(sym)
                        print(f"[{ts_res}]   [上櫃 {idx}/{total}] [未產出: {reason}] {sym}")

                    # 4. 若頁面完全卡死或 crash 才進行重連，不因個別檔案無回應而輕易重啟
                    if "crash" in reason.lower() or "disconnected" in reason.lower():
                        _restart_session(f"瀏覽器異常: {reason}")
                        session_start = time.time()
                        consecutive_misses = 0

                except Exception as e:
                    ts_err = get_taipei_now().strftime("%H:%M:%S")
                    failed_symbols.append(sym)
                    consecutive_misses += 1
                    print(f"[{ts_err}]   [上櫃 {idx}/{total}] [異常] {sym} ({e})")
                    err_msg = str(e).lower()
                    if "斷開" in str(e) or "disconnected" in err_msg or "target closed" in err_msg or "crash" in err_msg or consecutive_misses >= MAX_CONSECUTIVE_MISS:
                        try:
                            _restart_session(f"瀏覽器異常或連線中斷: {e}")
                            session_start = time.time()
                            consecutive_misses = 0
                        except Exception as re:
                            print(f"[!] 瀏覽器重啟失敗: {re}")

                sys.stdout.flush()

        except Exception as e:
            import traceback
            print(f"[!] TPEX 瀏覽器批次引擎異常: {e}")
            traceback.print_exc()
        finally:
            _cleanup_session()

        return collected_dfs, failed_symbols

    def crawl_stocks_with_retry(
        self,
        stock_codes: List[str],
        trade_date: str,
        max_rounds: int = 2,
        cooldown_sec: int = 30
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """
        對稱 TWSE 的多輪補抓機制：第 1 輪跑全清單，後續輪次只針對 failed_symbols 用新 Chromium session 重跑。
        每輪內部仍有 4 分鐘 Turnstile session hard-restart。
        """
        all_dfs: List[pd.DataFrame] = []
        remaining = list(stock_codes)
        for round_no in range(1, max_rounds + 1):
            if not remaining:
                break
            ts = get_taipei_now().strftime("%H:%M:%S")
            print(f"[{ts}] >>> TPEX 第 {round_no}/{max_rounds} 輪抓取啟動 (待抓: {len(remaining)} 檔)")
            sys.stdout.flush()
            dfs, failed = self.crawl_all_stocks_session(remaining, trade_date)
            all_dfs.extend(dfs)
            ts_end = get_taipei_now().strftime("%H:%M:%S")
            print(f"[{ts_end}] [+] TPEX 第 {round_no} 輪完成：成功 {len(dfs)} 檔，仍失敗 {len(failed)} 檔")
            if not failed:
                print(f"[{ts_end}] [+] TPEX 全清單抓取完成（第 {round_no} 輪達成）")
                remaining = []
                break
            if round_no < max_rounds:
                print(f"[{ts_end}] [*] 冷卻 {cooldown_sec}s 後進第 {round_no + 1} 輪補抓...")
                sys.stdout.flush()
                time.sleep(cooldown_sec)
            remaining = failed
        return all_dfs, remaining
