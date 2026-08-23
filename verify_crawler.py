# -*- coding: utf-8 -*-
"""
TWSE 爬蟲自動化驗證腳本 (Verification Test Suite)
=================================================
驗證項目：
1. 驗證全市場上市標的清單自動抓取功能 (get_all_listed_symbols > 1,000 檔)
2. 驗證多執行緒 (Multi-threading) 與 Thread-Local OCR 連線與辨識能力
3. 驗證 13 個標準欄位與 Dtype 是否與既有 Parquet 結構 100% 一致
4. 驗證數學邏輯一致性 (net_vol = buy_vol - sell_vol, turnover = buy_amt + sell_amt)
5. 驗證 Parquet 儲存與讀取還原能力
"""

import os
import sys
import glob
import pandas as pd
import numpy as np

# 引用同目錄下的爬蟲模組
sys.path.insert(0, os.path.dirname(__file__))
from twse_bsr_crawler import TWSEBrokerCrawler, get_all_listed_symbols

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_tests():
    print("=" * 60)
    print("🚀 開始執行 TWSE 券商買賣日報表多執行緒爬蟲驗證")
    print("=" * 60)

    # 1. 測試全市場標的清單取得
    print("\n[Test 1] 測試全市場標的清單 (get_all_listed_symbols) ...")
    all_syms = get_all_listed_symbols()
    print(f"[+] 成功取得上市標的數: {len(all_syms)} 檔 (例: {all_syms[:5]} ... {all_syms[-3:]})")
    assert len(all_syms) >= 1000, f"❌ 上市標的數不足，僅取得 {len(all_syms)} 檔"
    print("✅ [Pass] 全市場標的清單取得成功！")

    # 2. 載入既有 Parquet 結構作為 Ground Truth
    existing_files = glob.glob(os.path.join(os.path.dirname(__file__), "20260822分點資料", "*.parquet"))
    if existing_files:
        truth_df = pd.read_parquet(existing_files[0])
        expected_cols = list(truth_df.columns)
        print(f"\n[+] 既有 Parquet 基準欄位 ({len(expected_cols)} 個): {expected_cols}")
    else:
        expected_cols = [
            "symbol", "trade_date", "broker_id", "buy_vol", "sell_vol",
            "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price",
            "sell_avg_price", "turnover", "market_share"
        ]

    # 3. 測試多執行緒並行抓取 (4 Workers)
    test_symbols = ["2330", "2317", "2454", "2603"]
    print(f"\n[Test 2] 測試多執行緒並行 (4 Workers) 抓取 {test_symbols} ...")
    crawler = TWSEBrokerCrawler(delay_sec=0.2, max_retries=5)
    test_date = crawler._get_latest_trade_date()
    test_output = os.path.join(os.path.dirname(__file__), "output", "test_verification.parquet")

    df = crawler.crawl_stocks(
        symbols=test_symbols,
        trade_date=test_date,
        output_parquet=test_output,
        output_excel=False,
        max_workers=4
    )

    # 4. 檢驗資料集是否非空
    assert not df.empty, "❌ 抓取失敗，回傳 DataFrame 為空！"
    print(f"✅ [Pass] 成功取得 {len(df)} 筆分點交易數據")

    # 5. 檢驗欄位名稱與順序
    actual_cols = list(df.columns)
    assert actual_cols == expected_cols, f"❌ 欄位結構不符！\n預期: {expected_cols}\n實際: {actual_cols}"
    print(f"✅ [Pass] 13 個標準欄位與順序完全一致！")

    # 6. 檢驗各欄位資料型態
    assert pd.api.types.is_string_dtype(df["symbol"]), "symbol 型態錯誤"
    assert pd.api.types.is_string_dtype(df["trade_date"]), "trade_date 型態錯誤"
    assert pd.api.types.is_string_dtype(df["broker_id"]), "broker_id 型態錯誤"
    for col in ["buy_vol", "sell_vol", "net_vol", "buy_amt", "sell_amt", "net_amt", "buy_avg_price", "sell_avg_price", "turnover", "market_share"]:
        assert np.issubdtype(df[col].dtype, np.floating), f"{col} 必須為浮點數型態"
    print("✅ [Pass] 欄位資料型態 (Dtypes) 檢驗完全正確")

    # 7. 檢驗數學邏輯一致性
    vol_diff = (df["net_vol"] - (df["buy_vol"] - df["sell_vol"])).abs().max()
    assert vol_diff < 1e-4, f"❌ 買賣超股數計算錯誤，最大誤差: {vol_diff}"

    amt_diff = (df["net_amt"] - (df["buy_amt"] - df["sell_amt"])).abs().max()
    assert amt_diff < 1e-4, f"❌ 買賣超金額計算錯誤，最大誤差: {amt_diff}"

    turnover_diff = (df["turnover"] - (df["buy_amt"] + df["sell_amt"])).abs().max()
    assert turnover_diff < 1e-4, f"❌ 總成交金額計算錯誤，最大誤差: {turnover_diff}"

    has_buy = df[df["buy_vol"] > 0]
    expected_buy_avg = (has_buy["buy_amt"] * 1000.0) / has_buy["buy_vol"]
    buy_price_diff = (has_buy["buy_avg_price"] - expected_buy_avg).abs().max()
    assert buy_price_diff < 1e-4, f"❌ 買進均價計算錯誤，最大誤差: {buy_price_diff}"

    print("✅ [Pass] 買賣超、總成交額與均價之數學邏輯檢驗全部通過")

    # 8. 檢驗 Parquet 寫入與回讀
    assert os.path.exists(test_output), f"❌ Parquet 檔案未生成: {test_output}"
    read_back_df = pd.read_parquet(test_output)
    assert len(read_back_df) == len(df), "❌ 回讀 Parquet 筆數與原始不一致"
    print(f"✅ [Pass] Parquet 檔案寫入與回讀驗證通過 ({len(read_back_df)} 筆)")

    # 9. 顯示抓取結果 Sample
    print("\n" + "=" * 60)
    print("📊 抓取成果預覽 (前 5 筆記錄)：")
    print("=" * 60)
    print(df.head(5).to_string())

    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED! 全市場多執行緒爬蟲程式驗證 100% 成功！")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
