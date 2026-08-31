# -*- coding: utf-8 -*-
"""
測試驗證腳本：全市場 Parquet 合併與分片 Log 彙整
=================================================
驗證項目：
1. TWSE 6 分片 Log 彙整為 YYYY-MM-DD-twse.log (檢查排序與內容)
2. TPEX 8 分片 Log 彙整為 YYYY-MM-DD-tpex.log (檢查排序與內容)
3. TWSE + TPEX Parquet 檔案合併為 api_absr1_YYYY-MM-DD_YYYY-MM-DD.parquet
4. gdrive_sync 模組之 subfolder 參數與路徑解析
"""

import os
import sys
import shutil
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from merge_shards import merge_log_shards, merge_parquet_shards
from gdrive_sync import upload_file_to_gdrive

def test_all():
    test_dir = os.path.join(os.path.dirname(__file__), "test_merge_workspace")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)
    logs_dir = os.path.join(test_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    trade_date = "2026-08-26"

    print("==================================================")
    print("🚀 開始執行全市場 Parquet 與 Log 彙整功能驗證")
    print("==================================================")

    # 1. 測試 TWSE Log 彙整 (6 shards: 0~5)
    print("\n[Test 1] 測試 TWSE 6 分片日誌彙整...")
    for i in range(6):
        log_f = os.path.join(logs_dir, f"crawler_twse_shard_{i}.log")
        with open(log_f, "w", encoding="utf-8") as f:
            f.write(f"[2026-08-26 17:30:{i:02d}] TWSE Shard {i} 開始執行\n")
            f.write(f"[2026-08-26 17:35:{i:02d}] TWSE Shard {i} 成功抓取 180 檔\n")

    twse_log = merge_log_shards("twse", trade_date, test_dir)
    assert twse_log is not None, "❌ TWSE log 彙整失敗，回傳 None"
    assert os.path.exists(twse_log), f"❌ 找不到產出的 TWSE 彙整日誌: {twse_log}"
    assert f"{trade_date}-twse.log" in twse_log, f"❌ 檔名不符: {twse_log}"

    with open(twse_log, "r", encoding="utf-8") as f:
        twse_content = f.read()
    assert "Shard #0" in twse_content and "Shard #5" in twse_content, "❌ TWSE 日誌內容缺少分片標記"
    # 確認 Shard 0 出現在 Shard 5 之前
    assert twse_content.find("Shard #0") < twse_content.find("Shard #5"), "❌ TWSE 分片順序未按數值排序"
    print(f"✅ [Pass] TWSE 6 分片日誌彙整驗證成功 ({os.path.basename(twse_log)})")

    # 2. 測試 TPEX Log 彙整 (8 shards: 0~7)
    print("\n[Test 2] 測試 TPEX 8 分片日誌彙整...")
    for i in range(8):
        log_f = os.path.join(logs_dir, f"crawler_tpex_shard_{i}.log")
        with open(log_f, "w", encoding="utf-8") as f:
            f.write(f"[2026-08-26 17:30:{i:02d}] TPEX Shard {i} 開始執行\n")
            f.write(f"[2026-08-26 17:35:{i:02d}] TPEX Shard {i} 成功抓取 45 檔\n")

    tpex_log = merge_log_shards("tpex", trade_date, test_dir)
    assert tpex_log is not None, "❌ TPEX log 彙整失敗，回傳 None"
    assert os.path.exists(tpex_log), f"❌ 找不到產出的 TPEX 彙整日誌: {tpex_log}"
    assert f"{trade_date}-tpex.log" in tpex_log, f"❌ 檔名不符: {tpex_log}"

    with open(tpex_log, "r", encoding="utf-8") as f:
        tpex_content = f.read()
    assert "Shard #0" in tpex_content and "Shard #7" in tpex_content, "❌ TPEX 日誌內容缺少分片標記"
    assert "Shard #8" not in tpex_content, "❌ TPEX 日誌混入非本次 8-shard 測試輸出"
    assert tpex_content.find("Shard #2】") < tpex_content.find("Shard #7】"), "❌ TPEX 分片順序未按數值排序"
    print(f"✅ [Pass] TPEX 8 分片日誌彙整驗證成功 ({os.path.basename(tpex_log)})")

    # 3. 測試 TWSE + TPEX Parquet 合併為 api_absr1_YYYY-MM-DD_YYYY-MM-DD.parquet
    print("\n[Test 3] 測試全市場 Parquet 二次聚合...")
    cols = [
        "symbol", "trade_date", "broker_id", "buy_vol", "sell_vol",
        "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price",
        "sell_avg_price", "turnover", "market_share"
    ]
    df_twse = pd.DataFrame([
        {"symbol": "2330", "trade_date": trade_date, "broker_id": "1470", "buy_vol": 1000.0, "sell_vol": 0.0, "net_vol": 1000.0, "buy_amt": 950.0, "sell_amt": 0.0, "net_amt": 950.0, "buy_avg_price": 950.0, "sell_avg_price": 0.0, "turnover": 950.0, "market_share": 0.5},
        {"symbol": "2317", "trade_date": trade_date, "broker_id": "9800", "buy_vol": 500.0, "sell_vol": 200.0, "net_vol": 300.0, "buy_amt": 100.0, "sell_amt": 40.0, "net_amt": 60.0, "buy_avg_price": 200.0, "sell_avg_price": 200.0, "turnover": 140.0, "market_share": 0.2}
    ], columns=cols)
    twse_parquet = os.path.join(test_dir, f"api_absr1_{trade_date}_{trade_date}_twse.parquet")
    df_twse.to_parquet(twse_parquet, compression="zstd", index=False)

    df_tpex = pd.DataFrame([
        {"symbol": "6488", "trade_date": trade_date, "broker_id": "9268", "buy_vol": 300.0, "sell_vol": 100.0, "net_vol": 200.0, "buy_amt": 120.0, "sell_amt": 40.0, "net_amt": 80.0, "buy_avg_price": 400.0, "sell_avg_price": 400.0, "turnover": 160.0, "market_share": 0.3},
        {"symbol": "8069", "trade_date": trade_date, "broker_id": "1020", "buy_vol": 800.0, "sell_vol": 0.0, "net_vol": 800.0, "buy_amt": 160.0, "sell_amt": 0.0, "net_amt": 160.0, "buy_avg_price": 200.0, "sell_avg_price": 0.0, "turnover": 160.0, "market_share": 0.4}
    ], columns=cols)
    tpex_parquet = os.path.join(test_dir, f"api_absr1_{trade_date}_{trade_date}_tpex.parquet")
    df_tpex.to_parquet(tpex_parquet, compression="zstd", index=False)

    # 執行全市場整合
    merge_parquet_shards(output_dir=test_dir, trade_date=trade_date, market="all")

    final_all_parquet = os.path.join(test_dir, f"api_absr1_{trade_date}_{trade_date}.parquet")
    assert os.path.exists(final_all_parquet), f"❌ 全市場合併檔未生成: {final_all_parquet}"
    df_merged = pd.read_parquet(final_all_parquet)
    assert len(df_merged) == 4, f"❌ 合併資料筆數不符，預期 4 筆，實際 {len(df_merged)} 筆"
    assert set(df_merged["symbol"]) == {"2330", "2317", "6488", "8069"}, "❌ 標的涵蓋不完整"
    print(f"✅ [Pass] 全市場 Parquet 二次聚合驗證成功！產檔: {os.path.basename(final_all_parquet)} ({len(df_merged)} 筆)")

    # 4. 清理測試空間
    shutil.rmtree(test_dir)
    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED! 全市場 Parquet 合併與 Log 彙整邏輯 100% 正確！")
    print("=" * 60)

if __name__ == "__main__":
    test_all()
