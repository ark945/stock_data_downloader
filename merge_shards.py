"""
全市場分點爬蟲分片聚合器 (Merge Shards)
專門將分散式 Matrix 矩陣產生的多個 Parquet 片段合併為 1 份完整的標準全市場資料庫
並自動觸發 Telegram / Email 即時推播報表
"""

import os
import sys
import glob
import time
from datetime import datetime
import pandas as pd
from notification_service import send_telegram_alert, send_email_alert

def merge_parquet_shards(output_dir: str = "output", trade_date: str = ""):
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), output_dir)

    print(f"[*] 正在掃描並聚合分片資料: {output_dir}")
    shard_files = sorted(glob.glob(os.path.join(output_dir, "*_shard_*.parquet")))

    if not shard_files:
        print("[!] 未找到任何分片檔案 (*_shard_*.parquet)")
        # 檢查是否已有完整版
        existing = glob.glob(os.path.join(output_dir, "api_absr1_*.parquet"))
        if existing:
            print(f"[✓] 已存在完整資料庫: {existing[0]}")
        return

    print(f"[+] 找到 {len(shard_files)} 個分片檔案:")
    for f in shard_files:
        print(f"  - {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")

    dfs = []
    for f in shard_files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
            print(f"  [✓] 讀取 {os.path.basename(f)}: {len(df):,} 列 (標的: {df['symbol'].nunique()} 檔)")
        except Exception as e:
            print(f"  [!] 讀取 {f} 失敗: {e}")

    if not dfs:
        print("[!] 無有效資料可供合併！")
        return

    full_df = pd.concat(dfs, ignore_index=True)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)

    if not trade_date and "trade_date" in full_df.columns:
        trade_date = full_df["trade_date"].iloc[0]

    final_parquet = os.path.join(output_dir, f"api_absr1_{trade_date}_{trade_date}_1.parquet")
    full_df.to_parquet(final_parquet, index=False)

    total_symbols = full_df["symbol"].nunique()
    total_rows = len(full_df)
    file_size_mb = os.path.getsize(final_parquet) / (1024 * 1024)

    print("==================================================")
    print(f"[✓] 全市場分片聚合完成！")
    print(f"[*] 交易日期: {trade_date}")
    print(f"[*] 涵蓋標的數: {total_symbols:,} 檔")
    print(f"[*] 總資料筆數: {total_rows:,} 列")
    print(f"[*] 最終檔案: {final_parquet} ({file_size_mb:.2f} MB)")
    print("==================================================")

    # 清理分片檔
    for f in shard_files:
        try: os.remove(f)
        except OSError: pass

    # 推播通知
    tg_bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_bot and tg_chat:
        tg_msg = (
            f"🚀 *【台股全市場分點日報表】4 矩陣分散極速採集完成！*\n\n"
            f"📅 *交易日期*：`{trade_date}`\n"
            f"📊 *涵蓋標的*：`{total_symbols:,}` 檔\n"
            f"📈 *明細筆數*：`{total_rows:,}` 筆\n"
            f"📦 *資料庫大小*：`{file_size_mb:.2f} MB` (Parquet 格式)\n"
            f"⚡ *雲端分散式矩陣*：4 個獨立 IP 節點平行極速完成！\n\n"
            f"✅ 資料已自動歸檔並開放下載！"
        )
        send_telegram_alert(tg_bot, tg_chat, tg_msg)

if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else ""
    merge_parquet_shards("output", t_date)
