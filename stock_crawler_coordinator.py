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
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import pandas as pd

from twse_bsr_crawler import TWSEBrokerCrawler, get_active_listed_symbols
from tpex_bsr_crawler import TPEXBrokerCrawler
from notify_engine import send_crawler_report_email

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


class TeeLogger:
    """同時輸出至控制台與帶有時間戳的日誌檔案 (UTF-8)"""
    def __init__(self, log_filepath: str):
        self.terminal = sys.stdout
        self.log_file = open(log_filepath, "a", encoding="utf-8", buffering=1)

    def write(self, message):
        try:
            self.terminal.write(message)
            self.terminal.flush()
        except Exception:
            pass
        try:
            self.log_file.write(message)
            self.log_file.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self.terminal.flush()
        except Exception:
            pass
        try:
            self.log_file.flush()
        except Exception:
            pass

    def close(self):
        if not self.log_file.closed:
            self.log_file.close()


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
    """輸出帶有精準台灣時間時戳的日誌"""
    ts = get_taipei_now().strftime("%Y-%m-%d %H:%M:%S")
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


def get_latest_trading_date() -> str:
    """
    精確計算台股最新交易日 (官方於每日 17:00 確定提供最新券商日報表)：
    - 週六 (5)：退回週五 (-1 天)
    - 週日 (6)：退回週五 (-2 天)
    - 週一 (0) 且未過 17:00 (盤前/盤中)：退回上週五 (-3 天)
    - 週二至週五 (1~4) 且未過 17:00：退回前一天 (-1 天)
    - 週一至週五 且已過 17:00 (盤後已就緒)：當天 (-0 天)
    """
    now = get_taipei_now()
    w = now.weekday()
    if w == 5:
        delta = 1
    elif w == 6:
        delta = 2
    elif w == 0:
        delta = 0 if now.hour >= 17 else 3
    else:
        delta = 0 if now.hour >= 17 else 1
    return (now - pd.Timedelta(days=delta)).strftime("%Y-%m-%d")


def run_full_market_crawler(
    trade_date: Optional[str] = None,
    markets: str = "all",
    workers: int = 8,
    twse_workers: Optional[int] = None,
    tpex_workers: Optional[int] = None,
    max_rounds: int = 7,
    output_dir: str = None,
    export_excel: bool = True,
    receiver_email: Optional[str] = None,
    shard_id: int = 0,
    num_shards: int = 1
):
    start_dt = get_taipei_now()
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    if not trade_date:
        trade_date = get_latest_trading_date()

    output_dir = output_dir or os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    name_map = load_stock_name_map()

    # 決定 TWSE 與 TPEX 各自獨立的線程數
    actual_twse_w = twse_workers if twse_workers is not None else int(os.environ.get("TWSE_WORKERS", workers or 8))
    actual_tpex_w = tpex_workers if tpex_workers is not None else int(os.environ.get("TPEX_WORKERS", 1 if num_shards > 1 else min(workers, 2)))
    if num_shards > 1:
        actual_tpex_w = 1  # 雲端分片模式固定單 Worker 避免衝突

    market_suffix = f"_{markets.lower()}" if markets.lower() in ["twse", "tpex"] else ""
    expected_final_name = f"api_absr1_{trade_date}_{trade_date}{market_suffix}.parquet"

    print("==================================================")
    log_msg("[*] 全市場台股分點買賣日報表統一調度控制器 (Coordinator) 啟動")
    log_msg(f"[*] 啟動時間: {start_str}")
    log_msg(f"[*] 執行交易日期: {trade_date}")
    log_msg(f"[*] 目標市場範疇 (Market): {markets.upper()} (產檔規格: {expected_final_name})")
    if num_shards > 1:
        log_msg(f"[*] 雲端分片模式: 節點 {shard_id + 1} / {num_shards} (Shard ID: {shard_id})")
    log_msg(f"[*] 併發配置: TWSE 上市 {actual_twse_w} Workers (純HTTP高速) | TPEX 上櫃 {actual_tpex_w} Workers (CDP瀏覽器穩健)")
    log_msg(f"[*] 上市最大補抓輪數: {max_rounds} 輪")
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
        log_msg(f">>> [階段 1/2] 啟動 TWSE 上市股票分點抓取 ({actual_twse_w} Workers, 最多 6 輪安全補抓)...")
        twse_symbols = get_active_listed_symbols()
        if num_shards > 1:
            twse_symbols = [s for i, s in enumerate(twse_symbols) if i % num_shards == shard_id]
        total_target_count += len(twse_symbols)
        log_msg(f"[*] 取得上市標的清單: {len(twse_symbols)} 檔 (分片 {shard_id + 1}/{num_shards})")
        
        twse_crawler = TWSEBrokerCrawler(delay_sec=0.3, max_retries=6)
        twse_dfs, twse_failed, r_exec = twse_crawler.crawl_stocks(
            symbols=twse_symbols,
            trade_date=trade_date,
            max_workers=actual_twse_w,
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
        twse_total_assigned = len(twse_symbols)
        twse_zero_vol = twse_total_assigned - len(twse_dfs) - len(twse_failed)
        log_msg(f"[✓] TWSE 上市採集完成：共分配 {twse_total_assigned} 檔 | 有效成交產出: {len(twse_dfs)} 檔 | 無成交/略過: {twse_zero_vol} 檔 | 失敗: {len(twse_failed)} 檔")

    # 2. 抓取上櫃 (TPEX)
    if markets in ["all", "tpex"]:
        log_msg(f">>> [階段 2/2] 啟動 TPEX 上櫃股票分點抓取 ({actual_tpex_w} Workers 瀏覽器防護模式)...")
        tpex_symbols = TPEXBrokerCrawler.get_all_tpex_symbols()
        if num_shards > 1:
            tpex_symbols = [s for i, s in enumerate(tpex_symbols) if i % num_shards == shard_id]
        total_target_count += len(tpex_symbols)
        
        tpex_crawler = TPEXBrokerCrawler()
        tpex_dfs, tpex_failed = tpex_crawler.crawl_stocks_with_retry(
            stock_codes=tpex_symbols,
            trade_date=trade_date,
            max_rounds=3,
            workers=actual_tpex_w
        )
        collected_dfs.extend(tpex_dfs)
        
        for sym in tpex_failed:
            all_failed_items.append({
                "symbol": sym,
                "name": name_map.get(sym, "未知"),
                "market": "TPEX",
                "reason": "上櫃無資料或下載逾時"
            })
            
        tpex_total_assigned = len(tpex_symbols)
        tpex_zero_vol = tpex_total_assigned - len(tpex_dfs) - len(tpex_failed)
        log_msg(f"[✓] TPEX 上櫃採集完成：共分配 {tpex_total_assigned} 檔 | 有效成交產出: {len(tpex_dfs)} 檔 | 無成交/略過: {tpex_zero_vol} 檔 | 失敗: {len(tpex_failed)} 檔")

    # 3. 聚合全市場資料並輸出
    if not collected_dfs:
        log_msg("[!] 提示：本分片分配之標的均無成交明細，產出標準空結構 Parquet 供聚合。")
        full_df = pd.DataFrame(columns=[
            "symbol", "trade_date", "broker_id", "buy_vol", "sell_vol", "net_vol",
            "buy_amt", "sell_amt", "net_amt", "buy_avg_price", "sell_avg_price", "turnover", "market_share"
        ])
        total_rows = 0
        unique_symbols = 0
    else:
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

    end_dt = get_taipei_now()
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    elapsed_total = (end_dt - start_dt).total_seconds()
    duration_str = format_duration(elapsed_total)

    print("==================================================")
    log_msg("[OK] 本節點爬蟲任務執行完畢！")
    log_msg(f"[*] 啟動時間: {start_str}")
    zero_trade_count = max(0, total_target_count - unique_symbols - len(all_failed_items))
    log_msg(f"[+] 全市場掃描: 100% 完成 (共 {total_target_count} 檔 | 有效成交產出: {unique_symbols} 檔 | 無成交/略過: {zero_trade_count} 檔)")

    # 4. 發送通知 (若為雲端分片模式則由最後聚合步驟統一推播，避免分片節點日誌混淆)
    if num_shards > 1:
        log_msg(f"[*] 雲端分片模式 (Shard {shard_id + 1}/{num_shards})：分片已生成，推播通知將於後續聚合步驟統一發送。")
        if all_failed_items:
            log_msg(f"[!] 嚴格品質檢查：本分片共有 {len(all_failed_items)} 檔採集失敗，判定本分片失敗！")
            for itm in all_failed_items:
                log_msg(f"    - {itm['symbol']} ({itm['name']}): {itm['reason']}")
            raise RuntimeError(f"分片品質檢查未通過：共 {len(all_failed_items)} 檔採集失敗，拒絕放行！")
        return

    log_msg(">>> [通知推播] 檢查並發送執行成果與短缺股票日報...")
    from notify_engine import send_telegram_report, send_crawler_report_email
    
    # 優先發送 Telegram 即時推播
    send_telegram_report(
        trade_date=trade_date,
        total_target=total_target_count,
        success_count=unique_symbols,
        no_trade_count=zero_trade_count,
        failed_stocks=all_failed_items,
        total_rows=total_rows,
        elapsed_seconds=elapsed_total,
        rounds_executed=rounds_executed,
        market=markets,
        start_time_str=start_str,
        end_time_str=end_str,
        duration_str=duration_str
    )

    # 次要發送 Email (若有設定 SMTP)
    send_crawler_report_email(
        trade_date=trade_date,
        total_target=total_target_count,
        success_count=unique_symbols,
        no_trade_count=zero_trade_count,
        failed_stocks=all_failed_items,
        total_rows=total_rows,
        elapsed_seconds=elapsed_total,
        rounds_executed=rounds_executed,
        market=markets,
        receiver_email=receiver_email,
        start_time_str=start_str,
        end_time_str=end_str,
        duration_str=duration_str
    )

    if all_failed_items:
        log_msg(f"[!] 本分片共有 {len(all_failed_items)} 檔無成交或下載逾時：")
        for itm in all_failed_items:
            log_msg(f"    - {itm['symbol']} ({itm['name']}): {itm['reason']}")


def main():
    parser = argparse.ArgumentParser(description="全市場台股分點買賣日報表爬蟲協調控制器 (含 5 輪補抓與 Email 短缺通知)")
    parser.add_argument("--date", type=str, default=None, help="目標交易日期 (格式 YYYY-MM-DD)")
    parser.add_argument("--market", "--markets", dest="market", type=str, choices=["all", "twse", "tpex"], default="all", help="執行市場 (all, twse, tpex)")
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="預設通用線程數 (預設: 8)",
    )
    parser.add_argument(
        "--twse-workers",
        type=int,
        default=None,
        help="TWSE 上市專用併發線程數 (預設: 8，純 HTTP 高速請求可開 8~12)",
    )
    parser.add_argument(
        "--tpex-workers",
        type=int,
        default=None,
        help="TPEX 上櫃專用併發線程數 (預設: 1，CDP 瀏覽器模式建議 1~2 最穩定)",
    )
    parser.add_argument("--max-rounds", type=int, default=7, help="上市最大安全補抓輪數 (預設 7 輪，含終極深層收斂)")
    parser.add_argument("--no-excel", action="store_true", help="略過產出 Excel 檔")
    parser.add_argument("--output-dir", type=str, default=None, help="指定輸出目錄")
    parser.add_argument("--email", type=str, default=None, help="指定接收短缺日報的收件 Email")
    parser.add_argument("--shard-id", type=int, default=0, help="分散式分片索引 (0-indexed)")
    parser.add_argument("--num-shards", type=int, default=1, help="分散式總分片數 (預設 1)")

    args = parser.parse_args()

    # 自動建立 logs/ 資料夾並啟用帶有時間戳的日誌記錄
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    out_logs_dir = os.path.join(args.output_dir or os.path.join(os.path.dirname(__file__), "output"), "logs")
    os.makedirs(out_logs_dir, exist_ok=True)

    ts_str = get_taipei_now().strftime("%Y%m%d_%H%M%S")
    market_tag = args.market
    if args.num_shards > 1:
        log_filename = f"crawler_{market_tag}_shard_{args.shard_id}.log"
    else:
        log_filename = f"crawler_{market_tag}_{ts_str}.log"
    log_filepath = os.path.join(logs_dir, log_filename)

    tee_logger = TeeLogger(log_filepath)
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    sys.stdout = tee_logger
    sys.stderr = tee_logger

    try:
        print(f"[*] [日誌系統] 執行日誌檔案已建立: {log_filepath}")
        sys.stdout.flush()

        run_full_market_crawler(
            trade_date=args.date,
            markets=args.market,
            workers=args.workers,
            twse_workers=args.twse_workers,
            tpex_workers=args.tpex_workers,
            max_rounds=args.max_rounds,
            output_dir=args.output_dir,
            export_excel=not args.no_excel,
            receiver_email=args.email,
            shard_id=args.shard_id,
            num_shards=args.num_shards
        )
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        tee_logger.close()
        # 同步複製一份至 output/logs 目錄以利 GitHub Actions 產物收集
        try:
            import shutil
            shutil.copy2(log_filepath, os.path.join(out_logs_dir, log_filename))
        except Exception:
            pass


if __name__ == "__main__":
    main()
