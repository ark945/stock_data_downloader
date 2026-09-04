# -*- coding: utf-8 -*-
"""
集保股權分散表與千張大戶持股比例爬蟲 (TDCC)
==============================================
功能特點：
1. 抓取集保結算所官方股權分散表 (TDCC Open Data CSV)。
2. 全市場 2,000+ 檔個股一次性向量化清洗與聚合：
   - `large_shareholder_pct`: 1,000 張以上大戶持股比例 (%)
   - `large_shareholder_count`: 1,000 張以上大戶股東人數
   - `retail_shareholder_pct`: 50 張以下散戶持股比例 (%) (持股分級 1~5 累計)
   - `retail_shareholder_count`: 50 張以下散戶股東人數
   - `total_shareholders`: 總股東人數 (持股分級 17)
   - `total_shares`: 總股數
3. 支援 `--date` (expected_date) 版本比對防呆：
   - 官方通常於每週六 08:30~09:00 公布當週五數據。
   - 週五晚間若未發布，能精準辨識並避免覆蓋舊檔案。
4. 支援 `--upload-gdrive` 直接雲端同步。
5. 產出規範：api_tdcc_{YYYY-MM-DD}_{YYYY-MM-DD}.parquet。
"""

import os
import io
import sys
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import requests
import pandas as pd
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def clean_number(val: Any) -> float:
    """清理數值字串"""
    if val is None or pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "").replace("+", "")
    if not s or s in ("-", "--", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_latest_tdcc_opendata() -> pd.DataFrame:
    """
    抓取集保最新一週全市場 Open Data CSV
    URL: https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5
    """
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    for attempt in range(1, 4):
        try:
            print(f"[*] 正在從 TDCC Open Data 串流下載全市場股權分散 CSV (嘗試 {attempt}/3)...")
            resp = requests.get(url, headers=HEADERS, timeout=45)
            if resp.status_code != 200:
                print(f"[!] TDCC Open Data 狀態碼異常: {resp.status_code}")
                time.sleep(3)
                continue

            df_raw = pd.read_csv(io.StringIO(resp.text), dtype={"證券代號": str, "持股分級": int})
            return df_raw
        except Exception as e:
            print(f"[!] 下載 TDCC Open Data 異常 (嘗試 {attempt}/3): {e}")
            time.sleep(3)
    return pd.DataFrame()


def process_tdcc_raw_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """將集保 18 分級之長表結構轉換為每檔個股一行之籌碼指標寬表"""
    if df_raw.empty:
        return pd.DataFrame()

    # 欄位重新命名對齊: 資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
    df = df_raw.copy()
    df.columns = [c.strip() for c in df.columns]
    
    col_map = {
        "資料日期": "date_raw",
        "證券代號": "symbol",
        "持股分級": "level",
        "人數": "people",
        "股數": "shares",
        "占集保庫存數比例%": "ratio_pct"
    }
    for orig, target in col_map.items():
        for c in df.columns:
            if orig in c:
                df.rename(columns={c: target}, inplace=True)
                break

    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["level"] = pd.to_numeric(df["level"], errors="coerce").fillna(0).astype(int)
    df["people"] = pd.to_numeric(df["people"], errors="coerce").fillna(0)
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").fillna(0)
    df["ratio_pct"] = pd.to_numeric(df["ratio_pct"], errors="coerce").fillna(0.0)

    # 提取日期 YYYY-MM-DD
    raw_date_str = str(df["date_raw"].iloc[0]).strip()
    if len(raw_date_str) == 8:
        trade_date = f"{raw_date_str[:4]}-{raw_date_str[4:6]}-{raw_date_str[6:8]}"
    else:
        trade_date = raw_date_str

    # 1. 1000張以上大戶 (持股分級 15)
    df_large = df[df["level"] == 15][["symbol", "ratio_pct", "people", "shares"]].rename(
        columns={
            "ratio_pct": "large_shareholder_pct",
            "people": "large_shareholder_count",
            "shares": "large_shareholder_shares"
        }
    )

    # 2. 50張以下散戶 (持股分級 1~5 累加)
    df_retail = df[df["level"].isin([1, 2, 3, 4, 5])].groupby("symbol").agg(
        retail_shareholder_pct=("ratio_pct", "sum"),
        retail_shareholder_count=("people", "sum"),
        retail_shareholder_shares=("shares", "sum")
    ).reset_index()

    # 3. 總計 (持股分級 17)
    df_total = df[df["level"] == 17][["symbol", "people", "shares"]].rename(
        columns={
            "people": "total_shareholders",
            "shares": "total_shares"
        }
    )

    # 合併為寬表
    merged = pd.merge(df_total, df_large, on="symbol", how="left")
    merged = pd.merge(merged, df_retail, on="symbol", how="left")
    merged["trade_date"] = trade_date

    # 補空值
    merged["large_shareholder_pct"] = merged["large_shareholder_pct"].fillna(0.0).round(2)
    merged["large_shareholder_count"] = merged["large_shareholder_count"].fillna(0).astype(int)
    merged["retail_shareholder_pct"] = merged["retail_shareholder_pct"].fillna(0.0).round(2)
    merged["retail_shareholder_count"] = merged["retail_shareholder_count"].fillna(0).astype(int)
    merged["total_shareholders"] = merged["total_shareholders"].fillna(0).astype(int)
    merged["total_shares"] = merged["total_shares"].fillna(0)

    # 重新排序欄位
    cols_order = [
        "symbol", "trade_date", "large_shareholder_pct", "large_shareholder_count",
        "retail_shareholder_pct", "retail_shareholder_count", "total_shareholders", "total_shares"
    ]
    merged = merged[cols_order].sort_values(by="symbol").reset_index(drop=True)
    return merged


def download_latest_tdcc(
    output_dir: str = "./output_tdcc",
    overwrite: bool = False,
    expected_date: Optional[str] = None,
    upload_gdrive: bool = False
) -> Optional[str]:
    """
    下載最新週次全市場集保股權分散資料並存為 Parquet。
    :param output_dir: 輸出目錄
    :param overwrite: 是否覆蓋已存在檔案
    :param expected_date: 期望的基準週五日期 (YYYY-MM-DD)。若官方尚未公布本週資料，則優雅返回 None，避免寫入過期舊檔。
    :param upload_gdrive: 完成後是否同步至 Google Drive
    """
    os.makedirs(output_dir, exist_ok=True)
    df_raw = fetch_latest_tdcc_opendata()
    if df_raw.empty:
        print("[!] 無法取得 TDCC 數據，請稍後重試。")
        return None

    df_clean = process_tdcc_raw_df(df_raw)
    if df_clean.empty:
        print("[!] TDCC 資料清洗結果為空。")
        return None

    actual_date = df_clean["trade_date"].iloc[0]

    # 防呆校驗：若指定期望日期，但官方尚未更新至該日期
    if expected_date and actual_date < expected_date:
        print(f"[!] TDCC 官方尚未發布目標日期 ({expected_date}) 之資料 (目前最新為: {actual_date})。")
        print("[!] 提示：集保股權分散表通常於每週六 08:30~09:00 由官方產出，系統將由週六專屬排程或下週一開盤前自動補齊。")
        return None

    trade_date = actual_date
    out_filename = f"api_tdcc_{trade_date}_{trade_date}.parquet"
    out_path = os.path.join(output_dir, out_filename)

    if os.path.exists(out_path) and not overwrite:
        print(f"[✓] {trade_date} 集保資料已存在，跳過: {out_filename}")
        return out_path

    df_clean.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"[✓] {trade_date} 全市場集保股權分散已儲存: {out_filename} (共 {len(df_clean)} 檔標的)")

    if upload_gdrive:
        try:
            from gdrive_sync import upload_file_to_gdrive
            res = upload_file_to_gdrive(out_path)
            if res:
                print(f"[✓] 成功同步集保分散表至 Google Drive: {out_filename}")
        except Exception as e:
            print(f"[!] Google Drive 上傳提示: {e}")

    return out_path


def main():
    parser = argparse.ArgumentParser(description="集保股權分散表與千張大戶持股比例爬蟲 (TDCC)")
    parser.add_argument("--output-dir", default="./output_tdcc", help="Parquet 儲存目錄")
    parser.add_argument("--date", default="", help="期望的目標日期 (YYYY-MM-DD，官方未發布則自動跳過)")
    parser.add_argument("--overwrite", action="store_true", help="強制覆蓋現有檔案")
    parser.add_argument("--upload-gdrive", action="store_true", help="下載完成後同步至 Google Drive")

    args = parser.parse_args()
    download_latest_tdcc(
        output_dir=args.output_dir,
        overwrite=args.overwrite,
        expected_date=args.date if args.date else None,
        upload_gdrive=args.upload_gdrive
    )


if __name__ == "__main__":
    main()
