"""
TPEX 雲端環境 (WARP 網絡加持) 完整診斷與多檔連續採集測試腳本
"""
import os
import sys
import time
import json
from tpex_crawler_cloud import TPEXCloudCrawler

def test_tpex_single_and_batch():
    print("==========================================")
    print("🚀 TPEX 雲端環境 (WARP 通道) 診斷測試啟動")
    print("==========================================")

    test_symbols = ["1240", "6488", "6117", "3293", "8069", "3105", "5483", "6274", "3529", "8299", "6548", "3324", "4966", "5274", "6223"]
    trade_date = "2026-08-28"

    crawler = TPEXCloudCrawler()
    print(f"[*] 啟動 TPEXCloudCrawler 測試多檔連續採集: {test_symbols} (交易日: {trade_date})")
    dfs, failed = crawler.crawl_stocks(test_symbols, trade_date)

    print("\n==========================================")
    print(f"📊 採集結果統計: 成功產出 {len(dfs)} 檔 DataFrame, 失敗 {len(failed)} 檔")
    print("==========================================")

    for i, df in enumerate(dfs, 1):
        sym = df["symbol"].iloc[0] if not df.empty else "N/A"
        print(f"  [{i}] 標的 {sym}: {len(df)} 筆明細, 欄位: {list(df.columns)}")

    if failed:
        print(f"[❌] 測試失敗！以下標的未成功取得: {failed}")
        return False
    else:
        print(f"[✅] 測試圓滿成功！所有標的皆順暢抓取完成（含無成交自動略過），Turnstile 門禁與自癒機制運作正常！")
        return True

if __name__ == "__main__":
    success = test_tpex_single_and_batch()
    sys.exit(0 if success else 1)
