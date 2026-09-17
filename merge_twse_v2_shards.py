#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全新 TWSE 雲端分片 Parquet 合併工具 (v2)
========================================
職責：
收集由 GitHub Actions 多 Runner 產出的各分片 parquet 檔案：
  `output/api_absr1_{DATE}_{DATE}_twse_shard_*.parquet`
執行聯集合併、欄位校驗、去重排序，並產出標準的 TWSE 上市總表：
  `output/api_absr1_{DATE}_{DATE}_twse.parquet`
"""

import os
import sys
import glob
import argparse
import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MergeTWSE_v2")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def merge_twse_shards(trade_date: str, search_dir: str = "output", output_dir: Optional[str] = None) -> str:
    out_dir = output_dir or search_dir
    os.makedirs(out_dir, exist_ok=True)

    pattern = os.path.join(search_dir, f"api_absr1_{trade_date}_{trade_date}_twse_shard_*.parquet")
    shard_files = sorted(glob.glob(pattern))

    # 亦支援遞迴搜尋子資料夾 (Actions 下載 artifacts 時常置於 download_shards/ 等子層)
    if not shard_files:
        pattern_rec = os.path.join(search_dir, "**", f"*twse_shard_*.parquet")
        shard_files = sorted(glob.glob(pattern_rec, recursive=True))

    if not shard_files:
        raise FileNotFoundError(f"[!] 找不到任何 TWSE 分片檔案 (搜尋路徑: {search_dir}, 日期: {trade_date})")

    logger.info(f"[*] 找到 {len(shard_files)} 個 TWSE 分片檔案，準備合併...")
    dfs = []
    for f in shard_files:
        try:
            df = pd.read_parquet(f)
            logger.info(f"  [+] 載入分片: {os.path.basename(f)} (共 {len(df):,} 筆, {df['symbol'].nunique()} 檔標的)")
            dfs.append(df)
        except Exception as e:
            logger.error(f"  [!] 讀取分片失敗: {f} ({e})")

    if not dfs:
        raise ValueError("[!] 所有分片檔案均無法讀取或為空")

    merged_df = pd.concat(dfs, ignore_index=True)
    merged_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id", "buy_vol", "sell_vol"], inplace=True)
    merged_df.sort_values(by=["symbol", "broker_id"], inplace=True)

    out_parquet = os.path.join(out_dir, f"api_absr1_{trade_date}_{trade_date}_twse.parquet")
    out_excel = os.path.join(out_dir, f"api_absr1_{trade_date}_{trade_date}_twse.xlsx")

    merged_df.to_parquet(out_parquet, index=False)
    logger.info(f"[✓] TWSE 上市總表合併成功: {out_parquet}")
    logger.info(f"    - 總成交明細: {len(merged_df):,} 筆")
    logger.info(f"    - 涵蓋上市標的: {merged_df['symbol'].nunique():,} 檔")

    if len(merged_df) <= 200000:
        try:
            merged_df.to_excel(out_excel, index=False)
            logger.info(f"[✓] 成功同步導出 Excel: {out_excel}")
        except Exception as e:
            logger.warning(f"[!] 導出 Excel 略過: {e}")

    return out_parquet


def main():
    parser = argparse.ArgumentParser(description="TWSE 雲端分片 Parquet 合併工具 (v2)")
    parser.add_argument("date", type=str, help="交易日期 (YYYY-MM-DD)")
    parser.add_argument("--search-dir", type=str, default="output", help="分片檔案搜尋目錄")
    parser.add_argument("--output-dir", type=str, default="output", help="輸出合併檔目錄")
    args = parser.parse_args()

    merge_twse_shards(trade_date=args.date, search_dir=args.search_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
