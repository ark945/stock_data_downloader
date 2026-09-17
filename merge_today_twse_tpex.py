"""
2026-09-17 TWSE (上市) 與 TPEX (上櫃) 分點日報自動合併工具
整合 TWSE 產出的 api_absr1_2026-09-17_2026-09-17_twse.parquet 與現有 TPEX 數據，
輸出為標準全市場 api_absr1_2026-09-17_2026-09-17.parquet 與對應 Excel。
"""

import os
import sys
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def merge_20260917(date_str: str = "2026-09-17"):
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    twse_parquet = os.path.join(output_dir, f"api_absr1_{date_str}_{date_str}_twse.parquet")
    base_parquet = os.path.join(output_dir, f"api_absr1_{date_str}_{date_str}.parquet")
    final_excel = os.path.join(output_dir, f"api_absr1_{date_str}_{date_str}.xlsx")

    if not os.path.exists(twse_parquet):
        print(f"[!] 錯誤：找不到 TWSE 產物 {twse_parquet}")
        return False

    if not os.path.exists(base_parquet):
        print(f"[!] 錯誤：找不到現有基底檔案 {base_parquet}")
        return False

    print("=" * 60)
    print(f"[*] 開始合併 {date_str} TWSE 與 TPEX 分點數據...")
    print(f"  - TWSE 檔案: {twse_parquet}")
    print(f"  - 基底檔案: {base_parquet}")
    print("=" * 60)

    df_twse = pd.read_parquet(twse_parquet)
    df_base = pd.read_parquet(base_parquet)

    print(f"[+] 讀取 TWSE 筆數: {len(df_twse):,} 列 | 標的數: {df_twse['symbol'].nunique():,} 檔")
    print(f"[+] 讀取基底檔案筆數: {len(df_base):,} 列 | 標的數: {df_base['symbol'].nunique():,} 檔")

    # 聯集合併並去重
    full_df = pd.concat([df_base, df_twse], ignore_index=True)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)

    total_symbols = full_df["symbol"].nunique()
    total_rows = len(full_df)

    # 儲存最終全市場 Parquet
    full_df.to_parquet(base_parquet, compression="zstd", index=False)
    p_size = os.path.getsize(base_parquet) / (1024 * 1024)
    print(f"\n[✓] 全市場 Parquet 已成功輸出覆寫: {base_parquet}")
    print(f"    總標的數: {total_symbols:,} 檔 | 總筆數: {total_rows:,} 列 | 檔案大小: {p_size:.2f} MB")

    # 同步重建 Excel
    print(f"\n[*] 正在同步輸出 Excel 檔案: {final_excel} (請稍候)...")
    full_df.to_excel(final_excel, engine="openpyxl", index=False)
    x_size = os.path.getsize(final_excel) / (1024 * 1024)
    print(f"[✓] 全市場 Excel 檔案已儲存: {final_excel} ({x_size:.2f} MB)")
    print("=" * 60)
    print("🎉 [成功] 2026-09-17 全市場數據合併完成！")
    return True

if __name__ == "__main__":
    merge_20260917()
