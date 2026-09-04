# -*- coding: utf-8 -*-
"""
台股每日融資融券與券資比爬蟲 (TWSE 上市 + TPEx 上櫃)
=====================================================
功能特點：
1. 原生輕量級 API 請求：直接調用證交所 (TWSE) 與櫃買中心 (TPEx) 官方開放 JSON 端點。
2. 跨市場自動整合：全市場 2,200+ 檔上市櫃股票一次性完整收錄。
3. 關鍵量化衍生欄位：自動計算「融資今日增減」、「融券今日增減」與「券資比 (%)」。
4. 歷史批次回補：支援 `--start-date` 與 `--end-date` 補跑自 2026-06-01 至今任一交易日。
5. 支援斷點續跑：已存在之 Parquet 自動略過，避免重複請求。
6. 產出規範：api_margin_{YYYY-MM-DD}_{YYYY-MM-DD}.parquet (與分點/收盤價規範統一)。
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import requests
import pandas as pd
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

MARGIN_COLUMNS = [
    "symbol", "name", "trade_date", "market",
    "margin_buy", "margin_sell", "margin_cash_repay",
    "margin_prev_balance", "margin_balance", "margin_limit", "margin_utilization_pct",
    "short_buy", "short_sell", "short_cash_repay",
    "short_prev_balance", "short_balance", "short_limit", "short_utilization_pct",
    "offset_share", "margin_net", "short_net", "short_margin_ratio_pct", "note"
]


def clean_number(val: Any) -> float:
    """清理數值字串 (處理逗號、負號、空白與無效值)"""
    if val is None or pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "").replace("+", "")
    if not s or s in ("-", "--", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_twse_margin(trade_date: str) -> pd.DataFrame:
    """
    抓取 TWSE 上市股票融資融券彙總 (全部)
    API: https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={YYYYMMDD}&selectType=ALL&response=json
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    date_str = dt.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date_str}&selectType=ALL&response=json"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[!] TWSE 回應狀態碼異常: {resp.status_code}")
            return pd.DataFrame()

        data = resp.json()
        if data.get("stat") != "OK":
            print(f"[!] TWSE 無資料 ({trade_date}): {data.get('stat')}")
            return pd.DataFrame()

        tables = data.get("tables", [])
        if len(tables) < 2:
            return pd.DataFrame()

        # 第二張表通常為「融資融券彙總 (全部)」
        target_table = None
        for t in tables:
            if "融資融券彙總" in t.get("title", ""):
                target_table = t
                break
        if not target_table and len(tables) >= 2:
            target_table = tables[1]

        raw_rows = target_table.get("data", [])
        records = []
        for r in raw_rows:
            if len(r) < 15:
                continue
            symbol = str(r[0]).strip()
            name = str(r[1]).strip()
            if not symbol or symbol == "合計":
                continue

            # 融資欄位 (張)
            m_buy = clean_number(r[2])
            m_sell = clean_number(r[3])
            m_cash_repay = clean_number(r[4])
            m_prev_bal = clean_number(r[5])
            m_bal = clean_number(r[6])
            m_limit = clean_number(r[7])

            # 融券欄位 (張)
            s_buy = clean_number(r[8])
            s_sell = clean_number(r[9])
            s_cash_repay = clean_number(r[10])
            s_prev_bal = clean_number(r[11])
            s_bal = clean_number(r[12])
            s_limit = clean_number(r[13])

            offset = clean_number(r[14])
            note = str(r[15]).strip() if len(r) > 15 else ""

            m_net = m_bal - m_prev_bal
            s_net = s_bal - s_prev_bal
            m_util = round((m_bal / m_limit * 100.0), 2) if m_limit > 0 else 0.0
            s_util = round((s_bal / s_limit * 100.0), 2) if s_limit > 0 else 0.0
            sm_ratio = round((s_bal / m_bal * 100.0), 2) if m_bal > 0 else 0.0

            records.append({
                "symbol": symbol,
                "name": name,
                "trade_date": trade_date,
                "market": "上市",
                "margin_buy": m_buy,
                "margin_sell": m_sell,
                "margin_cash_repay": m_cash_repay,
                "margin_prev_balance": m_prev_bal,
                "margin_balance": m_bal,
                "margin_limit": m_limit,
                "margin_utilization_pct": m_util,
                "short_buy": s_buy,
                "short_sell": s_sell,
                "short_cash_repay": s_cash_repay,
                "short_prev_balance": s_prev_bal,
                "short_balance": s_bal,
                "short_limit": s_limit,
                "short_utilization_pct": s_util,
                "offset_share": offset,
                "margin_net": m_net,
                "short_net": s_net,
                "short_margin_ratio_pct": sm_ratio,
                "note": note
            })

        df = pd.DataFrame(records)
        return df
    except Exception as e:
        print(f"[!] 抓取 TWSE 融資融券失敗 ({trade_date}): {e}")
        return pd.DataFrame()


def fetch_tpex_margin(trade_date: str) -> pd.DataFrame:
    """
    抓取 TPEx 上櫃股票融資融券餘額
    API: https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={民國年/MM/DD}
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    roc_year = dt.year - 1911
    roc_date_str = f"{roc_year}/{dt.month:02d}/{dt.day:02d}"
    url = f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={roc_date_str}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[!] TPEx 回應狀態碼異常: {resp.status_code}")
            return pd.DataFrame()

        data = resp.json()
        tables = data.get("tables", [])
        if not tables:
            return pd.DataFrame()

        raw_rows = tables[0].get("data", [])
        records = []
        for r in raw_rows:
            if len(r) < 19:
                continue
            symbol = str(r[0]).strip()
            name = str(r[1]).strip()
            if not symbol or symbol in ("合計", "總計"):
                continue

            # TPEx 格式:
            # 0:代號, 1:名稱, 2:前資餘額, 3:資買, 4:資賣, 5:現償, 6:資餘額, 7:屬證金, 8:資使用率, 9:資限額
            # 10:前券餘額, 11:券賣, 12:券買, 13:券償, 14:券餘額, 15:券屬證金, 16:券使用率, 17:券限額
            # 18:資券相抵, 19:備註
            m_prev_bal = clean_number(r[2])
            m_buy = clean_number(r[3])
            m_sell = clean_number(r[4])
            m_cash_repay = clean_number(r[5])
            m_bal = clean_number(r[6])
            m_util = clean_number(r[8])
            m_limit = clean_number(r[9])

            s_prev_bal = clean_number(r[10])
            s_sell = clean_number(r[11])
            s_buy = clean_number(r[12])
            s_cash_repay = clean_number(r[13])
            s_bal = clean_number(r[14])
            s_util = clean_number(r[16])
            s_limit = clean_number(r[17])

            offset = clean_number(r[18])
            note = str(r[19]).strip() if len(r) > 19 else ""

            m_net = m_bal - m_prev_bal
            s_net = s_bal - s_prev_bal
            sm_ratio = round((s_bal / m_bal * 100.0), 2) if m_bal > 0 else 0.0

            records.append({
                "symbol": symbol,
                "name": name,
                "trade_date": trade_date,
                "market": "上櫃",
                "margin_buy": m_buy,
                "margin_sell": m_sell,
                "margin_cash_repay": m_cash_repay,
                "margin_prev_balance": m_prev_bal,
                "margin_balance": m_bal,
                "margin_limit": m_limit,
                "margin_utilization_pct": m_util,
                "short_buy": s_buy,
                "short_sell": s_sell,
                "short_cash_repay": s_cash_repay,
                "short_prev_balance": s_prev_bal,
                "short_balance": s_bal,
                "short_limit": s_limit,
                "short_utilization_pct": s_util,
                "offset_share": offset,
                "margin_net": m_net,
                "short_net": s_net,
                "short_margin_ratio_pct": sm_ratio,
                "note": note
            })

        df = pd.DataFrame(records)
        return df
    except Exception as e:
        print(f"[!] 抓取 TPEx 融資融券失敗 ({trade_date}): {e}")
        return pd.DataFrame()


def download_margin_for_date(trade_date: str, output_dir: str = "./output_margin", overwrite: bool = False) -> Optional[str]:
    """下載單一交易日之全市場融資融券資料並儲存為 Parquet"""
    os.makedirs(output_dir, exist_ok=True)
    out_filename = f"api_margin_{trade_date}_{trade_date}.parquet"
    out_path = os.path.join(output_dir, out_filename)

    if os.path.exists(out_path) and not overwrite:
        print(f"[✓] {trade_date} 融資券資料已存在，跳過: {out_filename}")
        return out_path

    print(f"[*] 正在抓取 {trade_date} 全市場融資融券明細...")
    df_twse = fetch_twse_margin(trade_date)
    time.sleep(0.5)
    df_tpex = fetch_tpex_margin(trade_date)

    if df_twse.empty and df_tpex.empty:
        print(f"[!] {trade_date} 查無上市櫃融資券資料 (可能為非交易日或未開盤)。")
        return None

    frames = [df for df in (df_twse, df_tpex) if not df.empty]
    df_all = pd.concat(frames, ignore_index=True)
    df_all.sort_values(by=["symbol"], inplace=True)
    df_all.reset_index(drop=True, inplace=True)

    df_all.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"[✓] {trade_date} 全市場融資券已儲存: {out_filename} (共 {len(df_all)} 檔，上市 {len(df_twse)}，上櫃 {len(df_tpex)})")
    return out_path


def backfill_margin_range(start_date: str, end_date: str, output_dir: str = "./output_margin", delay: float = 1.0):
    """批次回補歷史區間融資券資料"""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    cur_dt = start_dt

    dates = []
    while cur_dt <= end_dt:
        # 排除週末 (週六、週日)
        if cur_dt.weekday() < 5:
            dates.append(cur_dt.strftime("%Y-%m-%d"))
        cur_dt += timedelta(days=1)

    print("=" * 65)
    print(f"🚀 啟動融資融券歷史批次回補引擎")
    print(f"[*] 回補區間: {start_date} ~ {end_date} (共 {len(dates)} 個預計交易日)")
    print(f"[*] 輸出目錄: {output_dir}")
    print("=" * 65)

    success_count = 0
    for idx, d_str in enumerate(dates):
        print(f"\n[{idx+1}/{len(dates)}] 處理日期: {d_str}")
        res = download_margin_for_date(d_str, output_dir=output_dir)
        if res:
            success_count += 1
        time.sleep(delay)

    print("\n" + "★" * 65)
    print(f"[🎉] 融資融券歷史回補完畢！成功產出 {success_count}/{len(dates)} 個交易日檔案。")
    print("★" * 65)


def main():
    parser = argparse.ArgumentParser(description="台股每日融資融券與券資比爬蟲 (TWSE + TPEx)")
    parser.add_argument("--date", default="", help="指定單一交易日 (YYYY-MM-DD)")
    parser.add_argument("--start-date", default="", help="批次回補起始日 (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="", help="批次回補結束日 (YYYY-MM-DD，若未指定則為今日)")
    parser.add_argument("--output-dir", default="./output_margin", help="Parquet 儲存目錄")
    parser.add_argument("--delay", type=float, default=0.8, help="批次請求間隔延遲 (秒，預設: 0.8)")
    parser.add_argument("--overwrite", action="store_true", help="強制重新下載覆蓋現有檔案")
    parser.add_argument("--force", action="store_true", help="強制抓取，忽略營業日/開盤日休市檢查")
    parser.add_argument("--no-check-trading-day", action="store_true", help="停用營業日檢查")

    args = parser.parse_args()

    today_str = datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime("%Y-%m-%d")

    if args.start_date:
        end_d = args.end_date if args.end_date else today_str
        backfill_margin_range(args.start_date, end_d, output_dir=args.output_dir, delay=args.delay)
        return

    target_d = args.date if args.date else today_str
    if not args.no_check_trading_day:
        from trading_calendar import should_proceed_crawler
        if not should_proceed_crawler(target_d, force=args.force):
            print(f"[*] 今日 ({target_d}) 為休市日，融資券爬蟲已依設定優雅跳過。")
            return
    download_margin_for_date(target_d, output_dir=args.output_dir, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
