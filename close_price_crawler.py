"""
台股每日收盤價爬蟲 (TWSE 上市 + TPEX 上櫃)
--------------------------------------------
獨立輕量級模組：僅依賴 requests + pandas，無需瀏覽器自動化 / CAPTCHA 辨識，
單次 JSON API 請求即可取得「當日全市場」收盤行情，未來可依 (symbol, trade_date)
與券商分點買賣日報表 (api_absr1_*.parquet) 進行 Join 分析。

資料來源：
- TWSE 上市：https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
  (支援 date=YYYYMMDD 查詢任意歷史交易日之「每日收盤行情」表)
- TPEX 上櫃：https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php
  (支援 d=民國年/MM/DD 查詢任意歷史交易日；備援採用僅提供當日資料的 OpenAPI
  https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes)

標準 14 欄位輸出 (api_close1_*.parquet)：
    symbol, name, trade_date, market, open, high, low, close, change,
    volume, transaction_count, turnover, last_bid_price, last_ask_price

產檔規格 (與分點 api_absr1_* 對齊，雲端存放於同一 Google Drive 根目錄)：
    api_close1_{YYYY-MM-DD}_{YYYY-MM-DD}.parquet        (全市場)
    api_close1_{YYYY-MM-DD}_{YYYY-MM-DD}_twse.parquet   (僅上市)
    api_close1_{YYYY-MM-DD}_{YYYY-MM-DD}_tpex.parquet   (僅上櫃)
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional
from trading_calendar import is_trading_day, get_latest_trading_date as tc_get_latest_trading_date, should_proceed_crawler
import requests
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

CLOSE_PRICE_COLUMNS = [
    "symbol", "name", "trade_date", "market",
    "open", "high", "low", "close", "change",
    "volume", "transaction_count", "turnover",
    "last_bid_price", "last_ask_price",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def get_latest_trading_date() -> str:
    """計算台股最新真實開盤交易日 (由 trading_calendar 智慧日曆驅動)"""
    return tc_get_latest_trading_date()


def log_msg(msg: str):
    """輸出帶有精準台灣時間時戳的日誌"""
    ts = get_taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    sys.stdout.flush()


def _to_float(value) -> Optional[float]:
    """將原始字串轉為 float，無法解析 (--、空白) 則回傳 None"""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in ("", "--", "---", "X"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_twse_close_price(trade_date: str) -> pd.DataFrame:
    """
    抓取 TWSE 上市當日（或指定歷史日）全市場收盤行情 (單次 JSON API 請求)
    :param trade_date: YYYY-MM-DD
    """
    date_compact = trade_date.replace("-", "")
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    params = {"response": "json", "date": date_compact, "type": "ALLBUT0999"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    res_json = r.json()

    target_table = None
    for tbl in res_json.get("tables", []):
        title = tbl.get("title", "")
        fields = tbl.get("fields", [])
        if "每日收盤行情" in title and "證券代號" in fields:
            target_table = tbl
            break
    if not target_table:
        return pd.DataFrame(columns=CLOSE_PRICE_COLUMNS)

    records = []
    for row in target_table.get("data", []):
        if len(row) < 15:
            continue
        sign_html = str(row[9])
        change_diff = _to_float(row[10])
        change = None
        if change_diff is not None:
            if "green" in sign_html:
                change = -change_diff
            elif "red" in sign_html:
                change = change_diff
            else:
                change = change_diff  # 持平或無比價時差值通常為 0

        records.append({
            "symbol": str(row[0]).strip(),
            "name": str(row[1]).strip(),
            "trade_date": trade_date,
            "market": "TWSE",
            "open": _to_float(row[5]),
            "high": _to_float(row[6]),
            "low": _to_float(row[7]),
            "close": _to_float(row[8]),
            "change": change,
            "volume": _to_float(row[2]),
            "transaction_count": _to_float(row[3]),
            "turnover": _to_float(row[4]),
            "last_bid_price": _to_float(row[11]),
            "last_ask_price": _to_float(row[13]),
        })

    return pd.DataFrame(records, columns=CLOSE_PRICE_COLUMNS)


def _parse_tpex_legacy_table(table: dict, trade_date: str) -> pd.DataFrame:
    records = []
    for row in table.get("data", []):
        if len(row) < 13:
            continue
        records.append({
            "symbol": str(row[0]).strip(),
            "name": str(row[1]).strip(),
            "trade_date": trade_date,
            "market": "TPEX",
            "open": _to_float(row[4]),
            "high": _to_float(row[5]),
            "low": _to_float(row[6]),
            "close": _to_float(row[2]),
            "change": _to_float(row[3]),
            "volume": _to_float(row[7]),
            "transaction_count": _to_float(row[9]),
            "turnover": _to_float(row[8]),
            "last_bid_price": _to_float(row[10]),
            "last_ask_price": _to_float(row[12]),
        })
    return pd.DataFrame(records, columns=CLOSE_PRICE_COLUMNS)


def _fetch_tpex_close_price_openapi(trade_date: str) -> pd.DataFrame:
    """備援：TPEX OpenAPI (僅提供「當日」資料，適用於排程當天執行的情境)"""
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    records = []
    for item in data:
        symbol = str(item.get("SecuritiesCompanyCode", "")).strip()
        # 篩選 4 碼個股 (如 6488)、特別股 (如 8349A) 或上櫃 ETF (如 00720B)，排除 6 碼權證
        if not re.match(r"^[0-9]{4}[A-Za-z]?$", symbol) and not re.match(r"^00[0-9]{3}[A-Za-z0-9]?$", symbol):
            continue
        records.append({
            "symbol": symbol,
            "name": str(item.get("CompanyName", "")).strip(),
            "trade_date": trade_date,
            "market": "TPEX",
            "open": _to_float(item.get("Open")),
            "high": _to_float(item.get("High")),
            "low": _to_float(item.get("Low")),
            "close": _to_float(item.get("Close")),
            "change": _to_float(item.get("Change")),
            "volume": _to_float(item.get("TradingShares")),
            "transaction_count": _to_float(item.get("TransactionNumber")),
            "turnover": _to_float(item.get("TransactionAmount")),
            "last_bid_price": _to_float(item.get("LatestBidPrice")),
            "last_ask_price": _to_float(item.get("LatesAskPrice")),
        })
    return pd.DataFrame(records, columns=CLOSE_PRICE_COLUMNS)


def fetch_tpex_close_price(trade_date: str, max_retries: int = 3) -> pd.DataFrame:
    """
    抓取 TPEX 上櫃當日（或指定歷史日）全市場收盤行情 (單次 JSON API 請求)
    :param trade_date: YYYY-MM-DD
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    roc_date = f"{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}"
    url = "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php"
    params = {"d": roc_date, "se": "EW", "o": "json"}

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
            res_json = r.json()
            tables = res_json.get("tables", [])
            if not tables:
                return pd.DataFrame(columns=CLOSE_PRICE_COLUMNS)
            table = tables[0]
            # 官方回傳 totalCount=0 (data 為空陣列) 代表當日非交易日 (假日)，屬正常情況，非錯誤
            if not table.get("data"):
                return pd.DataFrame(columns=CLOSE_PRICE_COLUMNS)
            return _parse_tpex_legacy_table(table, trade_date)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 * attempt)

    log_msg(f"[!] TPEX 歷史行情查詢連續 {max_retries} 次失敗: {last_error}")

    # OpenAPI 備援僅提供「當日」快照，僅在查詢目標為系統自動判斷之最新交易日時才適用，
    # 避免將當日資料誤標記為歷史日期而污染區間回補結果
    if trade_date == get_latest_trading_date():
        log_msg("[*] 切換至 TPEX OpenAPI 當日備援...")
        return _fetch_tpex_close_price_openapi(trade_date)

    log_msg(f"[!] {trade_date} 非當日查詢，略過 OpenAPI 備援 (避免資料錯誤標記)，判定本日抓取失敗")
    raise RuntimeError(f"TPEX {trade_date} 歷史行情查詢失敗: {last_error}")


def _fetch_combined(trade_date: str, markets: str) -> pd.DataFrame:
    """抓取單一交易日之 TWSE/TPEX 收盤行情並合併為一份 DataFrame"""
    dfs = []
    if markets in ["all", "twse"]:
        log_msg(f"[*] {trade_date} 抓取 TWSE 上市收盤行情...")
        twse_df = fetch_twse_close_price(trade_date)
        log_msg(f"[✓] {trade_date} TWSE 上市：{len(twse_df):,} 檔")
        dfs.append(twse_df)
    if markets in ["all", "tpex"]:
        log_msg(f"[*] {trade_date} 抓取 TPEX 上櫃收盤行情...")
        tpex_df = fetch_tpex_close_price(trade_date)
        log_msg(f"[✓] {trade_date} TPEX 上櫃：{len(tpex_df):,} 檔")
        dfs.append(tpex_df)

    full_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame(columns=CLOSE_PRICE_COLUMNS)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "market"], inplace=True)
    full_df.sort_values(by=["market", "symbol"], inplace=True)
    return full_df


def run_close_price_crawler(
    trade_date: Optional[str] = None,
    markets: str = "all",
    output_dir: Optional[str] = None,
    upload_gdrive: bool = True,
) -> str:
    """
    執行收盤價全流程：抓取 -> 聚合 -> 輸出 Parquet -> 同步 Google Drive (與分點資料同一根目錄)
    :return: 產出的本地 Parquet 檔案路徑
    """
    if not trade_date:
        trade_date = get_latest_trading_date()
    markets = (markets or "all").lower().strip()

    output_dir = output_dir or os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    market_suffix = f"_{markets}" if markets in ["twse", "tpex"] else ""
    filename = f"api_close1_{trade_date}_{trade_date}{market_suffix}.parquet"
    filepath = os.path.join(output_dir, filename)

    print("==================================================")
    log_msg("[*] 台股每日收盤價爬蟲啟動")
    log_msg(f"[*] 交易日期: {trade_date}")
    log_msg(f"[*] 目標市場範疇: {markets.upper()} (產檔規格: {filename})")
    print("==================================================")

    full_df = _fetch_combined(trade_date, markets)

    full_df.to_parquet(filepath, compression="zstd", index=False)
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    log_msg(f"[✓] Parquet 已儲存: {filepath} ({size_mb:.2f} MB, 共 {len(full_df):,} 筆)")

    if upload_gdrive:
        try:
            from gdrive_sync import upload_file_to_gdrive
            log_msg("[*] 正在同步上傳至 Google Drive (與分點資料相同根目錄)...")
            res = upload_file_to_gdrive(filepath)
            if res:
                log_msg(f"[✓] 已上傳至 Google Drive (ID: {res.get('file_id')})")
        except Exception as e:
            log_msg(f"[!] Google Drive 同步異常: {e}")
    else:
        log_msg("[*] 已略過 Google Drive 上傳 (--no-gdrive)")

    return filepath


def run_close_price_range(
    start_date: str,
    end_date: str,
    markets: str = "all",
    output_dir: Optional[str] = None,
    upload_gdrive: bool = False,
    save_daily: bool = True,
    request_delay_sec: float = 0.5,
) -> str:
    """
    批次回補指定日期區間 (含首尾) 之收盤價：逐日抓取 -> 可選輸出每日 Parquet -> 合併輸出整段區間 Parquet
    非交易日 (週末/假日) 會自動偵測並略過 (若當日 TWSE 與 TPEX 均無資料則視為非交易日)。
    :return: 合併後的整段區間 Parquet 檔案路徑
    """
    markets = (markets or "all").lower().strip()
    output_dir = output_dir or os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
        start_date, end_date = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")

    market_suffix = f"_{markets}" if markets in ["twse", "tpex"] else ""

    print("==================================================")
    log_msg("[*] 台股收盤價區間回補啟動")
    log_msg(f"[*] 區間範圍: {start_date} ~ {end_date}")
    log_msg(f"[*] 目標市場範疇: {markets.upper()}")
    print("==================================================")

    all_dfs = []
    skipped_dates = []
    failed_dates = []
    cur = start_dt
    while cur <= end_dt:
        date_str = cur.strftime("%Y-%m-%d")
        if cur.weekday() >= 5:
            cur += timedelta(days=1)
            continue

        try:
            day_df = _fetch_combined(date_str, markets)
        except Exception as e:
            log_msg(f"[!] {date_str} 抓取失敗: {e}")
            failed_dates.append(date_str)
            cur += timedelta(days=1)
            time.sleep(request_delay_sec)
            continue

        if day_df.empty:
            log_msg(f"[*] {date_str}：無資料 (可能為假日或非交易日)，略過")
            skipped_dates.append(date_str)
            cur += timedelta(days=1)
            time.sleep(request_delay_sec)
            continue

        all_dfs.append(day_df)
        if save_daily:
            daily_filename = f"api_close1_{date_str}_{date_str}{market_suffix}.parquet"
            daily_path = os.path.join(output_dir, daily_filename)
            day_df.to_parquet(daily_path, compression="zstd", index=False)
            log_msg(f"[✓] {date_str}：共 {len(day_df):,} 檔，已儲存 {daily_path}")

        cur += timedelta(days=1)
        time.sleep(request_delay_sec)

    if not all_dfs:
        log_msg("[!] 區間內查無任何交易日資料！")
        return ""

    combined_df = pd.concat(all_dfs, ignore_index=True)
    combined_df.drop_duplicates(subset=["symbol", "trade_date", "market"], inplace=True)
    combined_df.sort_values(by=["trade_date", "market", "symbol"], inplace=True)

    combined_filename = f"api_close1_{start_date}_{end_date}{market_suffix}.parquet"
    combined_path = os.path.join(output_dir, combined_filename)
    combined_df.to_parquet(combined_path, compression="zstd", index=False)
    size_mb = os.path.getsize(combined_path) / (1024 * 1024)

    print("==================================================")
    log_msg(f"[✓] 區間合併 Parquet 已儲存: {combined_path} ({size_mb:.2f} MB, 共 {len(combined_df):,} 筆)")
    log_msg(f"[+] 實際交易日數: {len(all_dfs)} 天 | 略過非交易日: {len(skipped_dates)} 天 | 抓取失敗: {len(failed_dates)} 天")
    if failed_dates:
        log_msg(f"[!] 失敗日期: {', '.join(failed_dates)}")
    print("==================================================")

    if upload_gdrive:
        try:
            from gdrive_sync import upload_file_to_gdrive
            log_msg("[*] 正在同步上傳合併檔至 Google Drive (與分點資料相同根目錄)...")
            res = upload_file_to_gdrive(combined_path)
            if res:
                log_msg(f"[✓] 已上傳至 Google Drive (ID: {res.get('file_id')})")
        except Exception as e:
            log_msg(f"[!] Google Drive 同步異常: {e}")

    return combined_path


def main():
    parser = argparse.ArgumentParser(description="台股每日收盤價爬蟲 (TWSE 上市 + TPEX 上櫃)")
    parser.add_argument("--date", type=str, default=None, help="目標交易日期 (單日，格式 YYYY-MM-DD，留空則自動判斷最新交易日)")
    parser.add_argument("--start-date", type=str, default=None, help="區間回補起始日期 (需搭配 --end-date 使用)")
    parser.add_argument("--end-date", type=str, default=None, help="區間回補結束日期 (需搭配 --start-date 使用)")
    parser.add_argument("--market", type=str, choices=["all", "twse", "tpex"], default="all", help="執行市場 (all, twse, tpex)")
    parser.add_argument("--output-dir", type=str, default=None, help="指定輸出目錄")
    parser.add_argument("--no-gdrive", action="store_true", help="略過 Google Drive 上傳 (測試用)")
    parser.add_argument("--no-daily-files", action="store_true", help="區間模式下略過每日單独檔案，僅輸出合併檔")
    parser.add_argument("--force", action="store_true", help="強制抓取，忽略營業日/開盤日休市檢查")
    parser.add_argument("--no-check-trading-day", action="store_true", help="停用營業日檢查")
    args = parser.parse_args()

    if args.start_date or args.end_date:
        if not (args.start_date and args.end_date):
            parser.error("--start-date 與 --end-date 必須同時提供")
        run_close_price_range(
            start_date=args.start_date,
            end_date=args.end_date,
            markets=args.market,
            output_dir=args.output_dir,
            upload_gdrive=not args.no_gdrive,
            save_daily=not args.no_daily_files,
        )
    else:
        target_date = args.date or get_latest_trading_date()
        if not args.no_check_trading_day:
            if not should_proceed_crawler(target_date, force=args.force):
                log_msg(f"今日 ({target_date}) 為休市日，爬蟲已按設定優雅跳過。")
                return
        run_close_price_crawler(
            trade_date=target_date,
            markets=args.market,
            output_dir=args.output_dir,
            upload_gdrive=not args.no_gdrive,
        )


if __name__ == "__main__":
    main()
