# -*- coding: utf-8 -*-
"""
輕量爬蟲失敗補齊與自動對齊調度器 (Reconciliation & Recovery Coordinator)
========================================================================
負責在雲端或本地自動檢查四大核心輕量數據：
1. 收盤價 (Close Price) -> api_close1_{date}_{date}.parquet
2. 融資融券與券資比 (Margin Trading) -> api_margin_{date}_{date}.parquet
3. 期交所大盤期權留倉 (TAIFEX Futures) -> api_taifex_{date}_{date}.parquet
4. 集保千張大戶股權分散表 (TDCC Shareholding) -> api_tdcc_{friday}_{friday}.parquet

具備：
- 缺檔自動補抓與重試 (Backoff Retry)
- Google Drive 雲端同步
- 假日與週次智能對齊 (TDCC 週六 09:00 官方發布時間差智慧防呆)
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def upload_if_available(file_path: str) -> bool:
    """如果存在 GDrive 設定，調用 gdrive_sync 上傳檔案"""
    if not os.path.exists(file_path):
        return False
    try:
        from gdrive_sync import upload_file_to_gdrive
        res = upload_file_to_gdrive(file_path)
        if res:
            print(f"[✓] 成功同步至 Google Drive: {os.path.basename(file_path)}")
            return True
    except Exception as e:
        print(f"[!] Google Drive 上傳提示 ({os.path.basename(file_path)}): {e}")
    return False


def reconcile_close_price(trade_date: str, max_retries: int = 3) -> bool:
    """補齊當日收盤價"""
    filename = f"api_close1_{trade_date}_{trade_date}.parquet"
    out_dir = "./output"
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path):
        print(f"[✓] {trade_date} 收盤價檔案已存在: {filename}")
        return True

    print(f"[*] 開始執行收盤價補齊 ({trade_date})...")
    for attempt in range(1, max_retries + 1):
        try:
            from close_price_crawler import run_close_price_crawler
            success = run_close_price_crawler(
                trade_date=trade_date,
                output_dir=out_dir,
                upload_gdrive=True
            )
            if success and os.path.exists(out_path):
                print(f"[✓] 收盤價補齊成功 (第 {attempt} 次嘗試)")
                return True
        except Exception as e:
            print(f"[!] 收盤價抓取異常 (嘗試 {attempt}/{max_retries}): {e}")
        
        if attempt < max_retries:
            delay = attempt * 10
            print(f"[*] 等待 {delay} 秒後重試...")
            time.sleep(delay)

    print(f"[X] {trade_date} 收盤價補齊失敗。")
    return False


def reconcile_margin(trade_date: str, max_retries: int = 3) -> bool:
    """補齊當日融資融券與券資比"""
    filename = f"api_margin_{trade_date}_{trade_date}.parquet"
    out_dir = "./output_margin"
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path):
        print(f"[✓] {trade_date} 融資券檔案已存在: {filename}")
        return True

    print(f"[*] 開始執行融資融券補齊 ({trade_date})...")
    for attempt in range(1, max_retries + 1):
        try:
            from margin_trading_crawler import download_margin_for_date
            res = download_margin_for_date(trade_date, output_dir=out_dir, overwrite=True)
            if res and os.path.exists(res):
                upload_if_available(res)
                print(f"[✓] 融資券補齊成功 (第 {attempt} 次嘗試)")
                return True
        except Exception as e:
            print(f"[!] 融資券抓取異常 (嘗試 {attempt}/{max_retries}): {e}")

        if attempt < max_retries:
            delay = attempt * 15
            print(f"[*] 官方可能尚未公布，等待 {delay} 秒後進行第 {attempt+1} 次重試...")
            time.sleep(delay)

    print(f"[X] {trade_date} 融資券補齊失敗 (官方可能延遲公布或休市)。")
    return False


def reconcile_taifex(trade_date: str, max_retries: int = 3) -> bool:
    """補齊當日期交所期貨與散戶小台指標"""
    filename = f"api_taifex_{trade_date}_{trade_date}.parquet"
    out_dir = "./output_taifex"
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path):
        print(f"[✓] {trade_date} 期交所期貨檔案已存在: {filename}")
        return True

    print(f"[*] 開始執行期交所期貨指標補齊 ({trade_date})...")
    for attempt in range(1, max_retries + 1):
        try:
            from taifex_futures_crawler import download_taifex_futures_for_date
            res = download_taifex_futures_for_date(trade_date, output_dir=out_dir, overwrite=True)
            if res and os.path.exists(res):
                upload_if_available(res)
                print(f"[✓] 期交所期貨指標補齊成功 (第 {attempt} 次嘗試)")
                return True
        except Exception as e:
            print(f"[!] 期交所期貨抓取異常 (嘗試 {attempt}/{max_retries}): {e}")

        if attempt < max_retries:
            delay = attempt * 10
            print(f"[*] 等待 {delay} 秒後重試...")
            time.sleep(delay)

    print(f"[X] {trade_date} 期交所期貨指標補齊失敗。")
    return False


def reconcile_tdcc(trade_date: str) -> bool:
    """
    補齊集保千張大戶股權分散表 (每週五基準，官方固定於週六 08:30~09:00 發布)
    邏輯：
    1. 計算相對於 trade_date 的最近基準週五 (target_friday)。
    2. 若 target_friday 的集保資料已存在，標記為就緒。
    3. 若缺失：
       - 若 trade_date 本身是週五 (平日盤後)：嘗試預先抓取。若官方尚未更新當週數據，則智能略過並提示週六排程補齊，不阻礙當日流程。
       - 若 trade_date 是其他日子 (如週一開盤補檢)：官方肯定已發布，執行補抓並上傳 GDrive。
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    if dt.weekday() == 4:
        target_friday = trade_date
    elif dt.weekday() < 4:
        prev_friday_dt = dt - timedelta(days=dt.weekday() + 3)
        target_friday = prev_friday_dt.strftime("%Y-%m-%d")
    else:
        this_friday_dt = dt - timedelta(days=dt.weekday() - 4)
        target_friday = this_friday_dt.strftime("%Y-%m-%d")

    filename = f"api_tdcc_{target_friday}_{target_friday}.parquet"
    out_dir = "./output_tdcc"
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path):
        print(f"[✓] {target_friday} 集保股權分散檔案已存在: {filename}")
        return True

    print(f"[*] 正在檢查集保股權分散表 (基準週五: {target_friday})...")
    try:
        from tdcc_shareholding_crawler import download_latest_tdcc
        res = download_latest_tdcc(
            output_dir=out_dir,
            overwrite=True,
            expected_date=target_friday if dt.weekday() == 4 else None,
            upload_gdrive=True
        )
        if res and os.path.exists(res):
            upload_if_available(res)
            print(f"[✓] {target_friday} 集保股權分散補齊成功！")
            return True
        elif dt.weekday() == 4:
            print(f"[ℹ️] 提示：今日為週五晚間，TDCC 官方通常於週六上午 08:30~09:00 發布當週資料。")
            print(f"    系統已配置週六 09:30 專屬排程與下週一開盤自動對齊，本次暫不阻擋流程。")
            return True
    except Exception as e:
        print(f"[!] 集保抓取異常: {e}")
        if dt.weekday() == 4:
            return True
    return False


def reconcile_single_day(trade_date: str) -> Dict[str, bool]:
    """針對單一交易日執行 4 項輕量數據對齊檢查與補齊"""
    print("=" * 65)
    print(f"🛡️ 啟動台股輕量數據健康檢查與補齊程序 (交易日: {trade_date})")
    print("=" * 65)

    results = {
        "close_price": reconcile_close_price(trade_date),
        "margin": reconcile_margin(trade_date),
        "taifex": reconcile_taifex(trade_date),
        "tdcc": reconcile_tdcc(trade_date)
    }

    all_ok = all(results.values())
    status_icon = "🎉 完美對齊" if all_ok else "⚠️ 部分缺失"
    print(f"\n[*] 檢查與補齊結果 ({trade_date}): {status_icon}")
    for k, v in results.items():
        print(f"    - {k}: {'✓ 就緒' if v else '✗ 缺失'}")
    return results


def reconcile_range(start_date: str, end_date: str):
    """批次回補歷史區間輕量數據"""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    cur_dt = start_dt

    dates = []
    while cur_dt <= end_dt:
        if cur_dt.weekday() < 5:
            dates.append(cur_dt.strftime("%Y-%m-%d"))
        cur_dt += timedelta(days=1)

    print("=" * 65)
    print(f"🚀 啟動歷史區間輕量數據自動補齊巡檢 (共 {len(dates)} 個交易日)")
    print(f"[*] 區間: {start_date} ~ {end_date}")
    print("=" * 65)

    for idx, d_str in enumerate(dates):
        print(f"\n[{idx+1}/{len(dates)}] 巡檢日期: {d_str}")
        reconcile_single_day(d_str)
        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="輕量爬蟲失敗補齊與自動對齊調度器")
    parser.add_argument("--date", default="", help="指定檢查與補齊之單一交易日 (YYYY-MM-DD)")
    parser.add_argument("--start-date", default="", help="批次補齊起始日 (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="", help="批次補齊結束日 (YYYY-MM-DD)")

    args = parser.parse_args()

    today_str = datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime("%Y-%m-%d")

    if args.start_date:
        end_d = args.end_date if args.end_date else today_str
        reconcile_range(args.start_date, end_d)
        return

    target_d = args.date if args.date else today_str
    reconcile_single_day(target_d)


if __name__ == "__main__":
    main()
