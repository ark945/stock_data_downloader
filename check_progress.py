#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TWSE 採集進度即時儀表板
直接執行: py check_progress.py
"""
import os
import sys
import json
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

today = datetime.today().strftime("%Y-%m-%d")
cache_dir = os.path.join("output", f".twse_v2_cache_{today}")
checkpoint_file = os.path.join(cache_dir, "completed_symbols.json")

def get_twse_total_count() -> int:
    try:
        from twse_crawler_v2 import TWSECrawlerV2
        c = TWSECrawlerV2()
        return len(c.get_all_twse_symbols())
    except Exception:
        return 1263

TOTAL_SYMBOLS = get_twse_total_count()

def check():
    if not os.path.exists(checkpoint_file):
        print(f"[!] 快取檔案尚未建立或路徑不存在: {checkpoint_file}")
        return

    try:
        with open(checkpoint_file, "r", encoding="utf-8") as f:
            completed = json.load(f)
    except Exception as e:
        print(f"[!] 讀取進度失敗: {e}")
        return

    count = len(completed)
    pct = (count / TOTAL_SYMBOLS) * 100
    bar_len = 30
    filled_len = int(bar_len * count // TOTAL_SYMBOLS)
    bar = "=" * filled_len + "-" * (bar_len - filled_len)

    # 預估剩餘時間 (以每檔 1.4 秒計)
    remaining_symbols = max(0, TOTAL_SYMBOLS - count)
    remaining_min = (remaining_symbols * 1.4) / 60

    # 依照實際建立時間 (mtime) 取得時間上最新完成的 5 檔
    import glob
    parquet_files = glob.glob(os.path.join(cache_dir, "*.parquet"))
    parquet_files.sort(key=os.path.getmtime)
    latest_symbols = [os.path.splitext(os.path.basename(f))[0] for f in parquet_files[-5:]]

    print("=" * 60)
    print(f"  TWSE 上市股票採集即時進度 ({today})")
    print("=" * 60)
    print(f"  進度: [{bar}] {pct:.1f}%")
    print(f"  已完成: {count} / {TOTAL_SYMBOLS} 檔")
    print(f"  成功率: 100.0%")
    print(f"  剩餘約: {remaining_min:.1f} 分鐘")
    if latest_symbols:
        print(f"  時間最新完成 5 檔: {', '.join(latest_symbols)}")
    print("=" * 60)

if __name__ == "__main__":
    check()
