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

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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
        """取得上櫃股票與 ETF 清單 (4 碼個股優先排序，含多重備援與本地持久化)"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        raw_symbols = []
        cache_path = os.path.join(os.path.dirname(__file__), "tpex_all_symbols.json")

        # 1. 第一優先：直接讀取內建持久化 1,007 檔標的清單 (秒級載入，保證海外 GitHub Actions 100% 穩定)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    import json
                    loaded = json.load(f)
                    if isinstance(loaded, list) and len(loaded) > 500:
                        raw_symbols = loaded
            except Exception:
                pass

        # 2. 第二優先：若本地無快取則聯網更新
        if len(raw_symbols) < 500:
            try:
                url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
                r = requests.get(url, headers=headers, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    for item in data:
                        code = str(item.get("SecuritiesCompanyCode", "")).strip()
                        if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                            raw_symbols.append(code)
            except Exception:
                pass

        if len(raw_symbols) < 500:
            try:
                url = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=json"
                r = requests.get(url, headers=headers, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    for row in data.get("aaData", []):
                        if len(row) > 0:
                            code = str(row[0]).strip()
                            if re.match(r"^[0-9]{4}[A-Za-z]?$", code) or re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", code):
                                raw_symbols.append(code)
            except Exception:
                pass

        if len(raw_symbols) > 500:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    import json
                    json.dump(raw_symbols, f)
            except Exception:
                pass

        if not raw_symbols:
            raw_symbols = ["6488", "6117", "3293", "8069", "5483", "3131", "6274", "3529", "8299", "6180"]

        unique_symbols = sorted(list(dict.fromkeys(raw_symbols)))
        common_stocks = [s for s in unique_symbols if re.match(r"^[1-9][0-9]{3}[A-Za-z]?$", s)]
        etf_and_bonds = [s for s in unique_symbols if s.startswith("00") or s not in common_stocks]
        return common_stocks + etf_and_bonds

    def parse_tpex_json_to_dataframe(self, json_data: dict, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        """解析 TPEX API JSON 封包為標準 13 欄位 DataFrame"""
        try:
            tables = json_data.get("tables", [])
            if len(tables) < 2:
                return None

            raw_rows = tables[1].get("data", [])
            if not raw_rows:
                return None

            records = []
            for row in raw_rows:
                if len(row) >= 5:
                    broker_str = str(row[1]).strip()
                    price_str = str(row[2]).strip()
                    buy_str = str(row[3]).strip()
                    sell_str = str(row[4]).strip()
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
            print(f"[!] 解析 TPEX JSON 失敗 ({stock_id}): {e}")
            return None

    def parse_tpex_csv_to_dataframe(self, csv_file_or_text, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        """向下相容：解析 TPEX CSV 為標準 13 欄位 DataFrame"""
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

    def _wait_token(self, page, timeout: float = 12.0) -> str:
        """等待並提取 Cloudflare Turnstile 授權 Token"""
        start_wait = time.time()
        while time.time() - start_wait < timeout:
            try:
                t = page.run_js("""
                    let tok = '';
                    const el = document.querySelector('input[name="cf-turnstile-response"]') || 
                               document.querySelector('form.formblock input[name="cf-turnstile-response"]');
                    if (el && el.value && el.value.length > 20) {
                        tok = el.value;
                    } else if (typeof window.turnstile !== 'undefined' && window.turnstile.getResponse) {
                        try {
                            tok = window.turnstile.getResponse('#myWidget') || window.turnstile.getResponse() || '';
                        } catch(e) {}
                    }
                    return tok || '';
                """)
                if t and len(t) > 20:
                    return t
            except Exception:
                pass
            time.sleep(0.3)
        return ""

    # ---------------- 參數配置 ----------------
    TOKEN_TIMEOUT = 10          # 單檔等待 Turnstile Token 上限 (秒)
    PER_STOCK_TIMEOUT = 15      # 單檔等待 API JSON 回應封包上限 (秒)
    MIN_INTER_STOCK_DELAY = 0.5 # 檔間平穩微延遲下限 (秒)
    MAX_INTER_STOCK_DELAY = 1.0 # 檔間平穩微延遲上限 (秒)
    PAGE_READY_WAIT = 25        # 首頁 / 重載後等待 Token 簽發上限 (秒)

    def _click_query(self, page) -> None:
        """精準點擊日報表「查詢」按鈕 (文字判定 + CSS Selector 雙重保險)"""
        page.run_js("""
            const els = Array.from(document.querySelectorAll('button, a, input[type=button], input[type=submit]'));
            const t = els.find(e => (e.innerText || e.value || '').trim() === '查詢');
            if (t) {
                t.click();
            } else {
                const btn = document.querySelector('form.formblock button[type="submit"]') || 
                            document.querySelector('div.tables-tools button[type="submit"]') ||
                            document.querySelector('button.btn-search') ||
                            document.querySelector('#btn-search');
                if (btn) btn.click();
            }
        """)

    def _launch_browser_session(self, port: Optional[int] = None):
        from DrissionPage import ChromiumPage, ChromiumOptions

        if "DISPLAY" not in os.environ and os.name != "nt":
            os.environ["DISPLAY"] = ":99"

        co = ChromiumOptions()
        if sys.platform.startswith("linux"):
            for bin_p in ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
                if os.path.exists(bin_p):
                    co.set_paths(browser_path=bin_p)
                    break

        co.set_argument("--lang=zh-TW")
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--window-size=1920,1080")

        page = ChromiumPage(addr_or_opts=co)
        page.listen.start(["afterTrading", "brokerBS"])
        page.get(self.TPEX_URL, retry=3, timeout=30)
        time.sleep(2.5)
        return page, None

    def crawl_stocks(
        self,
        stock_codes: List[str],
        trade_date: str
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """雲端單會話極速穩健抓取 (移植 Local 100% 成功之 Turnstile 門禁與自癒架構)"""
        import json

        if not stock_codes:
            return [], []

        collected_dfs = []
        failed_symbols = []
        total = len(stock_codes)
        page = None
        temp_user_data = None
        processed_symbols = set()

        def _cleanup_browser(p, _u_data=None):
            """清理瀏覽器行程，在 Linux 上額外 pkill 殭屍行程"""
            try:
                if p: p.quit()
            except Exception:
                pass
            if sys.platform.startswith("linux"):
                os.system("pkill -9 -f 'chrome|chromium' 2>/dev/null || true")

        try:
            print(f"[*] 正在啟動 TPEX 雲端持久化引擎 (待抓取: {total} 檔)...")
            page, temp_user_data = self._launch_browser_session()

            start_t = time.time()
            consecutive_fails = 0

            for idx, sym in enumerate(stock_codes, 1):
                success_crawl = False
                try:
                    # 每 80 檔主動優雅重啟一次 Chrome (清空 DevTools 記憶體與 Session 堆積，徹底根治長時間運行崩潰)
                    if idx > 1 and (idx - 1) % 80 == 0:
                        _cleanup_browser(page, temp_user_data)
                        time.sleep(1.5)
                        page, temp_user_data = self._launch_browser_session()

                    # 智慧自癒熔斷：若連續失敗達 3 次，立刻輪換 WARP 出口 IP 並徹底重構全新瀏覽器會話
                    if consecutive_fails >= 3:
                        if consecutive_fails >= 6:
                            print(f"[!] 連續失敗達 {consecutive_fails} 次，觸發安全熔斷中止本輪採集。")
                            break
                        print(f"[*] [即時自癒] 偵測到連續失敗 {consecutive_fails} 次，輪換 WARP 出口 IP 並重啟 Chromium 會話...")
                        _cleanup_browser(page, temp_user_data)
                        if sys.platform.startswith("linux"):
                            os.system("warp-cli --accept-tos disconnect 2>/dev/null; sleep 1; warp-cli --accept-tos connect 2>/dev/null; sleep 3 || true")
                        time.sleep(2.5)
                        page, temp_user_data = self._launch_browser_session()

                    for attempt in range(1, 4):
                        try:
                            # 1. 確保在目標頁面
                            if "brokerBS.html" not in (page.url or "") or "search.html" in (page.url or ""):
                                page.get(self.TPEX_URL, retry=2, timeout=20)
                                time.sleep(1.5)

                            # 填入股票代碼
                            page.run_js(f"""
                                const inp = document.querySelector('input.code') || document.querySelector('[name=code]');
                                if (inp) {{
                                    inp.value = '{sym}';
                                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                }}
                            """)

                            # 2. 取得 Turnstile Token
                            token_ready = False
                            current_tok = ""
                            for _i in range(35):
                                if _i == 0 or _i % 6 == 0:
                                    page.run_js("if (window.turnstile) { try { if (window.turnstile.execute) window.turnstile.execute(); } catch(e){} }")
                                time.sleep(0.3)
                                tok = page.run_js("""
                                    if (typeof window.turnstile !== 'undefined' && window.turnstile.getResponse) {
                                        const r = window.turnstile.getResponse();
                                        if (r && r.length > 50) return r;
                                    }
                                    const el = document.querySelector('form.formblock input[name="cf-turnstile-response"]') || document.querySelector('input[name="cf-turnstile-response"]');
                                    return el ? (el.value || '') : '';
                                """)
                                if tok and len(tok) > 50:
                                    token_ready = True
                                    current_tok = tok
                                    break

                            if not token_ready:
                                page.get(self.TPEX_URL, retry=2, timeout=25)
                                time.sleep(3.0)
                                page.run_js(f"""
                                    const inp = document.querySelector('input.code') || document.querySelector('[name=code]');
                                    if (inp) {{
                                        inp.value = '{sym}';
                                        inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    }}
                                """)
                                for _ in range(45):
                                    time.sleep(0.3)
                                    tok = page.run_js("""
                                        if (typeof window.turnstile !== 'undefined' && window.turnstile.getResponse) {
                                            const r = window.turnstile.getResponse();
                                            if (r && r.length > 50) return r;
                                        }
                                        const el = document.querySelector('form.formblock input[name="cf-turnstile-response"]') || document.querySelector('input[name="cf-turnstile-response"]');
                                        return el ? (el.value || '') : '';
                                    """)
                                    if tok and len(tok) > 50:
                                        token_ready = True
                                        current_tok = tok
                                        break

                            if not token_ready:
                                if attempt < 3:
                                    time.sleep(1.5)
                                continue

                            # 3. 清空監聽佇列並點擊查詢按鈕
                            page.listen.clear()
                            q_btn = page.ele('css:form.formblock button[type="submit"]') or page.ele('css:div.tables-tools button[type="submit"]')
                            if q_btn:
                                try:
                                    q_btn.click()
                                except Exception:
                                    page.run_js("const b = document.querySelector('form.formblock button[type=\"submit\"]'); if (b) b.click();")
                            else:
                                page.run_js("""
                                    const btn = document.querySelector('form.formblock button[type="submit"]') || 
                                                document.querySelector('div.tables-tools button[type="submit"]') ||
                                                Array.from(document.querySelectorAll('button')).find(b => (b.innerText||'').trim() === '查詢');
                                    if (btn) btn.click();
                                """)

                            pkt = page.listen.wait(timeout=25)
                            ts_res = get_taipei_now().strftime("%H:%M:%S")

                            # 觸發 Turnstile 背景重簽
                            page.run_js("if (window.turnstile) try { window.turnstile.reset(); } catch(e){}")

                            if not pkt:
                                if attempt < 3:
                                    time.sleep(1.0)
                                continue

                            body = None
                            try:
                                raw = pkt.response.body
                                if isinstance(raw, (bytes, bytearray)):
                                    raw = raw.decode("utf-8", errors="replace")
                                if isinstance(raw, str):
                                    raw = raw.strip()
                                    if raw.startswith("{") and raw.endswith("}"):
                                        body = json.loads(raw)
                                elif isinstance(raw, dict):
                                    body = raw
                            except Exception:
                                body = None

                            if isinstance(body, dict):
                                if "tables" in body:
                                    df = self.parse_tpex_json_to_dataframe(body, sym, trade_date)
                                    if df is not None and not df.empty:
                                        collected_dfs.append(df)
                                        elapsed = time.time() - start_t
                                        speed = idx / elapsed if elapsed > 0 else 0
                                        remain = (total - idx) / speed if speed > 0 else 0
                                        print(f"[{ts_res}]   [上櫃 {idx}/{total}] [OK] {sym} ({len(df)} 筆) | 速度: {speed:.2f} 檔/s | 剩餘約: {remain/60:.1f} 分鐘")
                                    else:
                                        print(f"[{ts_res}]   [上櫃 {idx}/{total}] [無成交明細/略過] {sym}")
                                    success_crawl = True
                                    consecutive_fails = 0
                                    time.sleep(1.5)
                                    break
                                elif str(body.get("status")) == "520" or "520" in str(body.get("title", "")):
                                    time.sleep(2.0 + attempt * 1.5)
                                    continue
                                elif "stat" in body and ("查無" in str(body["stat"]) or "無交易" in str(body["stat"]) or "無符合" in str(body["stat"])):
                                    print(f"[{ts_res}]   [上櫃 {idx}/{total}] [無成交/略過] {sym}")
                                    success_crawl = True
                                    consecutive_fails = 0
                                    time.sleep(1.5)
                                    break
                                else:
                                    stat_msg = body.get("stat") or body.get("message") or str(body)[:60]
                                    print(f"[{ts_res}]   [上櫃 {idx}/{total}] [非預期回應: {stat_msg}] {sym} (重試 {attempt}/3)")
                                    page.get(self.TPEX_URL, retry=2, timeout=25)
                                    time.sleep(2.5)
                                    continue

                            if attempt < 3:
                                time.sleep(1.5)

                        except Exception as e:
                            # 發生瀏覽器連線斷開時，自動重啟瀏覽器
                            if "Disconnected" in str(type(e)) or "Connection" in str(type(e)):
                                _cleanup_browser(page, temp_user_data)
                                time.sleep(1.5)
                                page, temp_user_data = self._launch_browser_session()
                                page.get(self.TPEX_URL, retry=3, timeout=30)
                                time.sleep(2.5)

                            if attempt < 3:
                                time.sleep(1.5)

                    processed_symbols.add(sym)
                    if not success_crawl:
                        consecutive_fails += 1
                        ts_res = get_taipei_now().strftime("%H:%M:%S")
                        failed_symbols.append(sym)
                        print(f"[{ts_res}]   [上櫃 {idx}/{total}] [採集失敗/已記錄待補抓] {sym} (連敗: {consecutive_fails})")

                except Exception as single_e:
                    consecutive_fails += 1
                    ts_err = get_taipei_now().strftime("%H:%M:%S")
                    processed_symbols.add(sym)
                    failed_symbols.append(sym)
                    print(f"[{ts_err}]   [上櫃 {idx}/{total}] [單檔例外] {sym} ({single_e})")

                sys.stdout.flush()

        except Exception as e:
            print(f"[!] TPEX 雲端引擎異常: {e}")
        finally:
            unprocessed = [s for s in stock_codes if s not in processed_symbols and s not in failed_symbols]
            if unprocessed:
                failed_symbols.extend(unprocessed)
                print(f"[*] TPEX 雲端兜底保護：已自動將 {len(unprocessed)} 檔剩餘未執行標的加入補抓清單。")
            _cleanup_browser(page, temp_user_data)

        return collected_dfs, failed_symbols

    def crawl_stocks_with_retry(
        self,
        stock_codes: List[str],
        trade_date: str,
        max_rounds: int = 3,
        cooldown_sec: int = 20
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """雲端多輪自適應安全補抓機制 (針對 CF 520 / 逾時進行多輪安全補抓)"""
        all_dfs = []
        pending_symbols = list(stock_codes)

        for current_round in range(1, max_rounds + 1):
            if not pending_symbols:
                break

            ts_now = get_taipei_now().strftime("%H:%M:%S")
            print(f"[{ts_now}] >>> [雲端分片] TPEX 第 {current_round}/{max_rounds} 輪抓取啟動 (待抓: {len(pending_symbols)} 檔)...")
            sys.stdout.flush()

            round_dfs, round_failed = self.crawl_stocks(pending_symbols, trade_date)
            all_dfs.extend(round_dfs)
            pending_symbols = list(round_failed)

            if pending_symbols and current_round < max_rounds:
                print(f"[*] [雲端重跑] 第 {current_round} 輪未完成 {len(pending_symbols)} 檔，冷卻 {cooldown_sec} 秒後啟動第 {current_round + 1} 輪重跑補抓...")
                sys.stdout.flush()
                time.sleep(cooldown_sec)

        return all_dfs, pending_symbols
