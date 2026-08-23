"""
全市場台股券商買賣日報表統一調度控制器 (Coordinator)
整合：
- 上市 (TWSE) 雙引擎爬蟲 + 5-Stage 自適應安全補抓閉環
- 上櫃 (TPEX) 瀏覽器自動化爬蟲
- 全市場標準 13 欄位聚合打包輸出 (Parquet / Excel)
- 智慧 Email 通知引擎 (寄送短缺標的清單與執行成果)
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

from twse_bsr_crawler import TWSEBrokerCrawler, get_active_listed_symbols
from tpex_bsr_crawler import TPEXBrokerCrawler
from notify_engine import send_crawler_report_email


def load_stock_name_map() -> Dict[str, str]:
    """載入股票名稱對照快取"""
    map_path = os.path.join(os.path.dirname(__file__), "stock_name_map.json")
    if os.path.exists(map_path):
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def log_msg(msg: str):
    """輸出帶有精準時戳的日誌"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    sys.stdout.flush()


def format_duration(seconds: float) -> str:
    """將秒數格式化為 幾時幾分幾秒"""
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} 小時")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes} 分")
    parts.append(f"{secs} 秒")
    return "".join(parts)


def run_full_market_crawler(
    trade_date: Optional[str] = None,
    markets: str = "all",
    workers: int = 4,
    max_rounds: int = 6,
    output_dir: str = None,
    export_excel: bool = True,
    receiver_email: Optional[str] = None,
    shard_id: int = 0,
    num_shards: int = 1
):
    start_dt = datetime.now()
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")

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
    name_map = load_stock_name_map()

    market_suffix = f"_{markets.lower()}" if markets.lower() in ["twse", "tpex"] else ""
    expected_final_name = f"api_absr1_{trade_date}_{trade_date}{market_suffix}.parquet"

    print("==================================================")
    log_msg("[*] 全市場台股分點買賣日報表統一調度控制器 (Coordinator) 啟動")
    log_msg(f"[*] 啟動時間: {start_str}")
    log_msg(f"[*] 執行交易日期: {trade_date}")
    log_msg(f"[*] 目標市場範疇 (Market): {markets.upper()} (產檔規格: {expected_final_name})")
    if num_shards > 1:
        log_msg(f"[*] 雲端分片模式: 節點 {shard_id + 1} / {num_shards} (Shard ID: {shard_id})")
    log_msg(f"[*] TWSE 線程數: {workers} Workers | 上市最大補抓: {max_rounds} 輪")
    log_msg(f"[*] 成果輸出路徑: {output_dir}")
    print("==================================================")
    sys.stdout.flush()

    start_total_t = time.time()
    collected_dfs = []
    total_target_count = 0
    all_failed_items = []
    rounds_executed = 1

    # 1. 抓取上市 (TWSE)
    if markets in ["all", "twse"]:
        log_msg(">>> [階段 1/2] 啟動 TWSE 上市股票分點抓取 (最多 6 輪安全補抓)...")
        twse_symbols = get_active_listed_symbols()
        if num_shards > 1:
            twse_symbols = [s for i, s in enumerate(twse_symbols) if i % num_shards == shard_id]
        total_target_count += len(twse_symbols)
        log_msg(f"[*] 取得上市標的清單: {len(twse_symbols)} 檔 (分片 {shard_id + 1}/{num_shards})")
        
        twse_crawler = TWSEBrokerCrawler(delay_sec=0.4, max_retries=6)
        twse_dfs, twse_failed, r_exec = twse_crawler.crawl_stocks(
            symbols=twse_symbols,
            trade_date=trade_date,
            max_workers=workers,
            max_retry_rounds=max_rounds
        )
        collected_dfs.extend(twse_dfs)
        rounds_executed = max(rounds_executed, r_exec)
        
        for sym in twse_failed:
            all_failed_items.append({
                "symbol": sym,
                "name": name_map.get(sym, "未知"),
                "market": "TWSE",
                "reason": f"達第 {r_exec} 輪重試上限"
            })
        log_msg(f"[✓] TWSE 上市抓取完成：成功 {len(twse_dfs)} 檔，未產出 {len(twse_failed)} 檔")

    # 2. 抓取上櫃 (TPEX)
    if markets in ["all", "tpex"]:
        log_msg(">>> [階段 2/2] 啟動 TPEX 上櫃股票分點抓取 (單一純淨持久加速模式)...")
        tpex_symbols = TPEXBrokerCrawler.get_all_tpex_symbols()
        if num_shards > 1:
            tpex_symbols = [s for i, s in enumerate(tpex_symbols) if i % num_shards == shard_id]
        total_target_count += len(tpex_symbols)
        log_msg(f"[*] 取得上櫃標的清單: {len(tpex_symbols)} 檔 (分片 {shard_id + 1}/{num_shards})")
        
        tpex_crawler = TPEXBrokerCrawler()
        tpex_dfs, tpex_failed = tpex_crawler.crawl_all_stocks_session(
            stock_codes=tpex_symbols,
            trade_date=trade_date,
            workers=1
        )
        collected_dfs.extend(tpex_dfs)
        
        for sym in tpex_failed:
            all_failed_items.append({
                "symbol": sym,
                "name": name_map.get(sym, "未知"),
                "market": "TPEX",
                "reason": "上櫃無資料或下載逾時"
            })
            
        log_msg(f"[✓] TPEX 上櫃抓取完成：成功 {len(tpex_dfs)} 檔，未產出 {len(tpex_failed)} 檔")

    # 3. 聚合全市場資料並輸出
    if not collected_dfs:
        log_msg("[!] 警告：本次執行未取得任何有效分點資料！")
        return

    log_msg(">>> [數據整合] 彙整分點資料中...")
    full_df = pd.concat(collected_dfs, ignore_index=True)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)
    
    total_rows = len(full_df)
    unique_symbols = full_df["symbol"].nunique()
    log_msg(f"[+] 總標的數: {unique_symbols} 檔")
    log_msg(f"[+] 總資料筆數: {total_rows:,} 列")

    # 輸出 Parquet 檔案
    if num_shards > 1:
        parquet_filename = f"api_absr1_{trade_date}_{trade_date}{market_suffix}_shard_{shard_id}.parquet"
    else:
        parquet_filename = f"api_absr1_{trade_date}_{trade_date}{market_suffix}.parquet"
        
    parquet_path = os.path.join(output_dir, parquet_filename)
    full_df.to_parquet(parquet_path, compression="zstd", index=False)
    p_size_mb = os.path.getsize(parquet_path) / (1024 * 1024)
    log_msg(f"[✓] Parquet 檔案已儲存: {parquet_path} ({p_size_mb:.2f} MB, ZSTD 高度壓縮)")

    # 輸出 Excel 檔案
    if export_excel:
        excel_filename = f"api_absr1_{trade_date}_{trade_date}{market_suffix}.xlsx"
        excel_path = os.path.join(output_dir, excel_filename)
        log_msg(f"[*] 正在輸出 Excel 檔案: {excel_path} (請稍候)...")
        full_df.to_excel(excel_path, engine="openpyxl", index=False)
        x_size_mb = os.path.getsize(excel_path) / (1024 * 1024)
        log_msg(f"[✓] Excel 檔案已儲存: {excel_path} ({x_size_mb:.2f} MB)")

    end_dt = datetime.now()
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    elapsed_total = (end_dt - start_dt).total_seconds()
    duration_str = format_duration(elapsed_total)

    print("==================================================")
    log_msg("[OK] 本節點爬蟲任務執行完畢！")
    log_msg(f"[*] 啟動時間: {start_str}")
    log_msg(f"[*] 結束時間: {end_str}")
    log_msg(f"[*] 總計耗時: {duration_str} (共 {elapsed_total:.1f} 秒)")
    log_msg(f"[+] 標的採集率: {unique_symbols}/{total_target_count} ({unique_symbols/total_target_count*100:.1f}%)")
    print("==================================================")

    # 4. 發送通知 (若為雲端分片模式則由最後聚合步驟統一推播，避免分片節點日誌混淆)
    if num_shards > 1:
        log_msg(f"[*] 雲端分片模式 (Shard {shard_id + 1}/{num_shards})：分片已生成，推播通知將於後續聚合步驟統一發送。")
        return

    log_msg(">>> [通知推播] 檢查並發送執行成果與短缺股票日報...")
    from notify_engine import send_telegram_report, send_crawler_report_email
    
    # 優先發送 Telegram 即時推播
    send_telegram_report(
        trade_date=trade_date,
        total_target=total_target_count,
        success_count=unique_symbols,
        no_trade_count=0,
        failed_stocks=all_failed_items,
        total_rows=total_rows,
        elapsed_seconds=elapsed_total,
        rounds_executed=rounds_executed,
        start_time_str=start_str,
        end_time_str=end_str,
        duration_str=duration_str
    )

    # 次要發送 Email (若有設定 SMTP)
    send_crawler_report_email(
        trade_date=trade_date,
        total_target=total_target_count,
        success_count=unique_symbols,
        no_trade_count=0,
        failed_stocks=all_failed_items,
        total_rows=total_rows,
        elapsed_seconds=elapsed_total,
        rounds_executed=rounds_executed,
        receiver_email=receiver_email,
        start_time_str=start_str,
        end_time_str=end_str,
        duration_str=duration_str
    )


def main():
    parser = argparse.ArgumentParser(description="全市場台股分點買賣日報表爬蟲協調控制器 (含 5 輪補抓與 Email 短缺通知)")
    parser.add_argument("--date", type=str, default=None, help="目標交易日期 (格式 YYYY-MM-DD)")
    parser.add_argument("--market", "--markets", dest="market", type=str, choices=["all", "twse", "tpex"], default="all", help="執行市場 (all, twse, tpex)")
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="TWSE 併發下載線程數 (預設: 8，兼顧極速與防封鎖)",
    )
    parser.add_argument("--max-rounds", type=int, default=5, help="上市最大安全補抓輪數 (預設 5 輪)")
    parser.add_argument("--no-excel", action="store_true", help="略過產出 Excel 檔")
    parser.add_argument("--output-dir", type=str, default=None, help="指定輸出目錄")
    parser.add_argument("--email", type=str, default=None, help="指定接收短缺日報的收件 Email")
    parser.add_argument("--shard-id", type=int, default=0, help="分散式分片索引 (0-indexed)")
    parser.add_argument("--num-shards", type=int, default=1, help="分散式總分片數 (預設 1)")

    args = parser.parse_args()
    run_full_market_crawler(
        trade_date=args.date,
        markets=args.market,
        workers=args.workers,
        max_rounds=args.max_rounds,
        output_dir=args.output_dir,
        export_excel=not args.no_excel,
        receiver_email=args.email,
        shard_id=args.shard_id,
        num_shards=args.num_shards
    )


if __name__ == "__main__":
    main()
