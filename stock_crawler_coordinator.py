"""
全市場台股券商買賣日報表統一調度控制器 (Coordinator)
整合：
- 上市 (TWSE) 雙引擎爬蟲 + 2-Stage 自動補抓
- 上櫃 (TPEX) 瀏覽器自動化爬蟲
- 全市場標準 13 欄位聚合打包輸出 (Parquet / Excel)
"""

import os
import sys
import time
import argparse
from datetime import datetime
import pandas as pd

from twse_bsr_crawler import TWSEBrokerCrawler, get_active_listed_symbols
from tpex_bsr_crawler import TPEXBrokerCrawler


def run_full_market_crawler(
    trade_date: str = None,
    markets: str = "all",
    workers: int = 2,
    output_dir: str = None,
    export_excel: bool = True
):
    if not trade_date:
        today = datetime.now()
        if today.weekday() == 5:
            delta = 1
        elif today.weekday() == 6:
            delta = 2
        else:
            delta = 0 if today.hour >= 18 else 1
        trade_date = (today - pd.Timedelta(days=delta)).strftime("%Y-%m-%d")

    output_dir = output_dir or os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    print("==================================================")
    print("🚀 全市場台股券商分點買賣日報表抓取系統")
    print(f"[*] 目標交易日期: {trade_date}")
    print(f"[*] 執行市場範圍: {markets.upper()}")
    print(f"[*] 並行執行緒數: {workers} Workers")
    print(f"[*] 輸出目錄位置: {output_dir}")
    print("==================================================")
    sys.stdout.flush()

    start_total_t = time.time()
    collected_dfs = []

    # 1. 抓取上市 (TWSE)
    if markets in ["all", "twse"]:
        print("\n>>> [階段 1/2] 啟動 TWSE 上市股票分點抓取...")
        twse_symbols = get_active_listed_symbols(trade_date)
        print(f"[*] 取得當日有效交易上市標的: {len(twse_symbols)} 檔")
        
        twse_crawler = TWSEBrokerCrawler(delay_sec=0.3, max_retries=5)
        twse_dfs, twse_failed = twse_crawler.crawl_stocks(
            symbols=twse_symbols,
            trade_date=trade_date,
            max_workers=workers,
            auto_retry=True
        )
        collected_dfs.extend(twse_dfs)
        print(f"[✓] TWSE 上市抓取完成：成功 {len(twse_dfs)} 檔，未產出 {len(twse_failed)} 檔")

    # 2. 抓取上櫃 (TPEX)
    if markets in ["all", "tpex"]:
        print("\n>>> [階段 2/2] 啟動 TPEX 上櫃股票分點抓取...")
        tpex_symbols = TPEXBrokerCrawler.get_all_tpex_symbols()
        print(f"[*] 取得上櫃標的清單: {len(tpex_symbols)} 檔")
        
        tpex_crawler = TPEXBrokerCrawler()
        tpex_success = 0
        tpex_failed = []
        
        # 上櫃使用 DrissionPage 逐檔處理
        for i, sym in enumerate(tpex_symbols, 1):
            df_tpex = tpex_crawler.crawl_single_stock_browser(sym, trade_date)
            if df_tpex is not None and not df_tpex.empty:
                collected_dfs.append(df_tpex)
                tpex_success += 1
                print(f"  [{i}/{len(tpex_symbols)}] [OK] 上櫃 {sym} -> {len(df_tpex)} 筆")
            else:
                tpex_failed.append(sym)
                print(f"  [{i}/{len(tpex_symbols)}] [WARN] 上櫃 {sym} -> 無資料或略過")
            sys.stdout.flush()

        print(f"[✓] TPEX 上櫃抓取完成：成功 {tpex_success} 檔，未產出 {len(tpex_failed)} 檔")

    # 3. 聚合全市場資料並輸出
    if not collected_dfs:
        print("\n[!] 警告：本次執行未取得任何有效分點資料！")
        return

    print("\n>>> [數據整合] 彙整全市場分點資料中...")
    full_df = pd.concat(collected_dfs, ignore_index=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)
    
    total_rows = len(full_df)
    unique_symbols = full_df["symbol"].nunique()
    print(f"[+] 總標的數: {unique_symbols} 檔")
    print(f"[+] 總資料筆數: {total_rows:,} 列")

    # 輸出 Parquet 檔案 (檔名格式與標準 api_absr1 對齊)
    parquet_filename = f"api_absr1_{trade_date}_{trade_date}.parquet"
    parquet_path = os.path.join(output_dir, parquet_filename)
    full_df.to_parquet(parquet_path, index=False)
    p_size_mb = os.path.getsize(parquet_path) / (1024 * 1024)
    print(f"[✓] Parquet 檔案已儲存: {parquet_path} ({p_size_mb:.2f} MB)")

    # 輸出 Excel 檔案 (使用 openpyxl 引擎)
    if export_excel:
        excel_filename = f"api_absr1_{trade_date}_{trade_date}.xlsx"
        excel_path = os.path.join(output_dir, excel_filename)
        print(f"[*] 正在輸出 Excel 檔案: {excel_path} (請稍候)...")
        full_df.to_excel(excel_path, engine="openpyxl", index=False)
        x_size_mb = os.path.getsize(excel_path) / (1024 * 1024)
        print(f"[✓] Excel 檔案已儲存: {excel_path} ({x_size_mb:.2f} MB)")

    elapsed_total = time.time() - start_total_t
    print("==================================================")
    print(f"[OK] 全流程執行完畢！總耗時: {elapsed_total:.1f} 秒 ({elapsed_total/60:.1f} 分鐘)")
    print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="全市場台股分點買賣日報表爬蟲協調控制器")
    parser.add_argument("--date", type=str, default=None, help="目標交易日期 (格式 YYYY-MM-DD)")
    parser.add_argument("--market", "--markets", dest="market", type=str, choices=["all", "twse", "tpex"], default="all", help="執行市場 (all, twse, tpex)")
    parser.add_argument("--workers", type=int, default=2, help="TWSE 並行 Worker 數 (建議 2~3)")
    parser.add_argument("--no-excel", action="store_true", help="略過產出 Excel 檔")
    parser.add_argument("--output-dir", type=str, default=None, help="指定輸出目錄")

    args = parser.parse_args()
    run_full_market_crawler(
        trade_date=args.date,
        markets=args.market,
        workers=args.workers,
        output_dir=args.output_dir,
        export_excel=not args.no_excel
    )


if __name__ == "__main__":
    main()
