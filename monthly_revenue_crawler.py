# -*- coding: utf-8 -*-
"""
台股全市場月營收資料自動化採集與標準化資料庫匯入模組 (MOPS Monthly Revenue)
=================================================================================
核心功能：
1. 官方資料源：從公開資訊觀測站 (MOPS) 完整採集全市場 6 大月營收報表：
   - 上市 (SII) 一般股 & KY 股
   - 上櫃 (OTC) 一般股 & KY 股
   - 興櫃 (ROTC) 一般股 & KY 股
2. 雙主機高可用 Fallback：
   - 主要：mopsov.twse.com.tw (近年/新版)
   - 備援：mops.twse.com.tw (歷史/舊版)
3. 容錯與強健清洗：
   - 自動適配 Big5 / UTF-8 編碼與 HTML 表格解析
   - 排除合計行與非數字代碼行
   - 數值清洗：移除千分位逗號、處理負號、破折號與缺失值
   - 同月同市場同標的去重
4. 欄位標準化與雙年月標註：
   - 民國年月 (report_month，如 '113_01') 與西元年月 (year_month，如 '2024-01') 同步收錄
   - 標準 snake_case 英文欄位，100% 相容 Colab 與量化資料庫
5. 多元輸出支援：
   - 標準 Parquet (output_revenue/api_revenue_*.parquet)
   - 標準 CSV (相容 Excel 之 utf_8_sig)
   - 本地 SQLite 資料庫 (local_taiwan_stock.db -> monthly_revenue 表) 並建立 4 大索引
   - Google Drive 自動備份同步
6. 內建 SQLite 診斷驗證工具 (檢視結構、總筆數、最新覆蓋區間與隨機抽樣)
"""

import os
import io
import re
import sys
import time
import argparse
import sqlite3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Dict, Any, Optional

import requests
import pandas as pd
from tqdm import tqdm

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# 欄位模糊配對基準字典
RENAME_MAP_BASE = {
    '公司 代號': 'stock_id',
    '公司代號': 'stock_id',
    '證券代號': 'stock_id',
    '股票代號': 'stock_id',
    '代號': 'stock_id',
    '公司名稱': 'stock_name',
    '公司簡稱': 'stock_name',
    '名稱': 'stock_name',
    '當月營收': 'rev_current',
    '本月營收': 'rev_current',
    '當月營業收入': 'rev_current',
    '上月營收': 'rev_last_month',
    '去年同月營收': 'rev_last_year',
    '去年當月營收': 'rev_last_year',
    '去年同期營收': 'rev_last_year',
    '去年同月營業收入': 'rev_last_year',
    '上月比較 增減(%)': 'mom_pct',
    '去年同月 增減(%)': 'yoy_pct',
    '當月累計營收': 'rev_accumulated',
    '去年累計營收': 'rev_accumulated_last_year',
    '前期比較 增減(%)': 'yoy_accumulated_pct',
    '前期累計比較 增減(%)': 'yoy_accumulated_pct',
    '前期比較 增減(%)累計': 'yoy_accumulated_pct',
    '備註': 'remark'
}

STANDARD_COLUMNS = [
    'stock_id', 'stock_name', 'report_month', 'year_month', 'market_type',
    'rev_current', 'rev_last_month', 'rev_last_year', 'mom_pct', 'yoy_pct',
    'rev_accumulated', 'rev_accumulated_last_year', 'yoy_accumulated_pct', 'remark'
]


def clean_text(text: Any) -> str:
    """清理文字欄位中的特殊空白與跳行符"""
    if text is None or pd.isna(text):
        return ""
    s = str(text).replace('\u3000', ' ').replace('　', ' ').replace('\xa0', ' ').strip()
    return re.sub(r'\s+', ' ', s)


def clean_number(val: Any) -> Optional[float]:
    """清理數值欄位 (移除千分位、負號、破折號)"""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().replace(',', '').replace('－', '-').replace('--', '').replace('+', '')
    if not s or s in ('-', 'N/A', 'null', 'None'):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def roc_to_greg_ym(roc_ym: str) -> str:
    """民國年月 '113_01' 轉西元年月 '2024-01'"""
    try:
        parts = roc_ym.split('_')
        y = int(parts[0]) + 1911
        m = int(parts[1])
        return f"{y:04d}-{m:02d}"
    except Exception:
        return ""


def greg_to_roc_ym(greg_ym: str) -> Tuple[int, int]:
    """西元年月 '2024-01' 轉 (roc_year, month)"""
    dt = datetime.strptime(greg_ym, "%Y-%m")
    return dt.year - 1911, dt.month


def get_latest_published_ym(target_prev_month: bool = False) -> str:
    """
    依據當前台灣時間推算月營收西元年月 (YYYY-MM)。
    MOPS 規範每月 10 日前公布上月營收。
    若 target_prev_month 為 True 或當日 > 10 號，取剛結束之上月份 (例: 10/1~10/10 取 9 月)；
    若今日 <= 10 號且 target_prev_month 為 False，取前 2 個月確保全市場資料完整度。
    """
    now = datetime.now(timezone.utc).astimezone(TAIPEI_TZ)
    # 先回到上個月底
    first_of_this_month = now.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    
    if target_prev_month or now.day > 10:
        return last_month_end.strftime("%Y-%m")
    else:
        second_last_month_end = last_month_end.replace(day=1) - timedelta(days=1)
        return second_last_month_end.strftime("%Y-%m")


def generate_ym_range(end_ym: str, n_months: int) -> List[Tuple[int, int]]:
    """根據結束西元年月往回推算 n 個月之 ROC 年月 (roc_year, month) 清單"""
    dt = datetime.strptime(end_ym, "%Y-%m")
    result = []
    y, m = dt.year, dt.month
    for i in range(n_months):
        cur_y = y
        cur_m = m - i
        while cur_m <= 0:
            cur_y -= 1
            cur_m += 12
        result.append((cur_y - 1911, cur_m))
    return result


def fetch_table_with_retry(url: str, max_retries: int = 4, delay: float = 1.2) -> Optional[List[pd.DataFrame]]:
    """嘗試下載並解析 MOPS 月營收 HTML 表格，失敗自動退避重試"""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()

            # 嘗試使用 big5 解碼 (MOPS 傳統編碼)
            resp.encoding = 'big5'
            txt = resp.text or ""
            if len(txt) < 80 or '<table' not in txt.lower():
                # 備援嘗試原始 UTF-8 解碼
                resp.encoding = 'utf-8'
                txt = resp.text or ""
                if len(txt) < 80 or '<table' not in txt.lower():
                    raise ValueError("回應內容過短或未包含 <table> 標籤")

            tables = pd.read_html(io.StringIO(txt))
            if tables:
                return tables
        except Exception as e:
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 1.5
    return None


def normalize_and_map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """處理 MultiIndex 表頭、清理欄名空白並對齊映射至標準 snake_case 英文"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)

    cleaned_cols = []
    for c in df.columns:
        c_str = clean_text(c)
        cleaned_cols.append(c_str)
    df.columns = cleaned_cols

    rename_dict = {}
    for c in df.columns:
        # 動態正則配對
        if re.search(r'去年.*同月.*增減', c):
            rename_dict[c] = 'yoy_pct'
        elif re.search(r'上月.*比較.*增減', c):
            rename_dict[c] = 'mom_pct'
        elif re.search(r'前期.*比較.*增減', c) or re.search(r'累計.*增減', c):
            rename_dict[c] = 'yoy_accumulated_pct'
        elif c in RENAME_MAP_BASE:
            rename_dict[c] = RENAME_MAP_BASE[c]

    df = df.rename(columns=rename_dict)
    # 防呆：若仍有重複欄名，保留第一個出現的欄位
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated(keep='first')]

    return df


def parse_mops_tables(tables: List[pd.DataFrame], market_tag: str, roc_y: int, m: int) -> List[pd.DataFrame]:
    """解析 MOPS 回傳之多個表格，過濾合計行與無效列，轉換數值欄位"""
    roc_ym_str = f"{roc_y}_{m:02d}"
    greg_ym_str = roc_to_greg_ym(roc_ym_str)
    valid_dfs = []

    for t in tables:
        if t.empty or len(t) < 1:
            continue

        df = normalize_and_map_columns(t.copy())

        # 檢驗必要欄位 (至少要有 stock_id 或 stock_name，且有 rev_current)
        cols = set(df.columns)
        if not (('stock_id' in cols or 'stock_name' in cols) and 'rev_current' in cols):
            continue

        # 過濾合計列與全部列
        if 'stock_name' in df.columns:
            df = df[~df['stock_name'].astype(str).str.contains('合計|全部|總計', na=False)]

        # 代號處理與過濾 (代號須包含數字)
        if 'stock_id' in df.columns:
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            df = df[df['stock_id'].str.contains(r'\d', na=False)]
            # 排除非上市櫃主板或非興櫃等純文字備註代號
            df = df[df['stock_id'].str.len() >= 4]

        if df.empty:
            continue

        # 補齊可能缺失之欄位
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        # 數值清洗轉換
        num_fields = [
            'rev_current', 'rev_last_month', 'rev_last_year',
            'mom_pct', 'yoy_pct',
            'rev_accumulated', 'rev_accumulated_last_year', 'yoy_accumulated_pct'
        ]
        for nf in num_fields:
            if nf in df.columns:
                df[nf] = df[nf].map(clean_number)

        # 文字清洗
        for tf in ['stock_id', 'stock_name', 'remark']:
            if tf in df.columns:
                df[tf] = df[tf].map(clean_text)

        df['report_month'] = roc_ym_str
        df['year_month'] = greg_ym_str
        df['market_type'] = market_tag

        valid_dfs.append(df[STANDARD_COLUMNS])

    return valid_dfs


def fetch_single_month_all_markets(roc_y: int, m: int) -> pd.DataFrame:
    """
    抓取指定月份全市場 (上市/上櫃/興櫃 x 一般/KY) 共 6 類報表，雙主機自動 Fallback
    """
    report_types = [
        ('sii', 'sii', 0),
        ('sii_ky', 'sii', 1),
        ('otc', 'otc', 0),
        ('otc_ky', 'otc', 1),
        ('rotc', 'rotc', 0),
        ('rotc_ky', 'rotc', 1)
    ]
    hosts = [
        'mopsov.twse.com.tw',  # 近年主要主機
        'mops.twse.com.tw'     # 歷史備援主機
    ]

    all_month_dfs = []

    for tag, market, is_ky in report_types:
        path = f"nas/t21/{market}/t21sc03_{roc_y}_{m}_{is_ky}.html"
        fetched_tables = None
        used_host = ""

        for host in hosts:
            url = f"https://{host}/{path}"
            tables = fetch_table_with_retry(url)
            if tables:
                fetched_tables = tables
                used_host = host
                break

        if fetched_tables:
            full_tag = f"{tag}@{used_host}"
            parsed = parse_mops_tables(fetched_tables, full_tag, roc_y, m)
            all_month_dfs.extend(parsed)

    if not all_month_dfs:
        return pd.DataFrame()

    df_month = pd.concat(all_month_dfs, ignore_index=True)
    # 去除重複 (同一月份、同代碼、同市場只保留一筆)
    df_month.drop_duplicates(subset=['report_month', 'stock_id', 'market_type'], keep='first', inplace=True)
    df_month.sort_values(by=['stock_id'], inplace=True)
    df_month.reset_index(drop=True, inplace=True)
    return df_month


def save_to_sqlite(df: pd.DataFrame, db_path: str = "./local_taiwan_stock.db", if_exists: str = "append"):
    """
    將月營收資料寫入 SQLite 資料庫 (monthly_revenue 表) 並建立高效索引
    """
    if df.empty:
        return

    print(f"📦 正在寫入 SQLite 資料庫: {db_path} (模式: {if_exists})...")
    conn = sqlite3.connect(db_path, timeout=30.0)

    try:
        # 如果是 append 模式，為避免重跑重複插入，先刪除已存在之相同 (report_month, stock_id)
        if if_exists == "append":
            # 先確認 table 是否存在
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monthly_revenue'")
            if cursor.fetchone():
                months_in_df = df['report_month'].unique().tolist()
                placeholders = ','.join(['?'] * len(months_in_df))
                del_sql = f"DELETE FROM monthly_revenue WHERE report_month IN ({placeholders})"
                cursor.execute(del_sql, months_in_df)
                conn.commit()

        # 寫入資料
        df.to_sql('monthly_revenue', conn, if_exists=if_exists, index=False)

        # 建立索引優化查詢 (與 Colab Cell 3 完全一致並擴充 year_month)
        print("⚡ 正在建立/檢查 SQLite 索引 (Index)...")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rev_id ON monthly_revenue (stock_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rev_date ON monthly_revenue (report_month)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rev_ym ON monthly_revenue (year_month)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_yoy_high ON monthly_revenue (yoy_pct)")

        conn.commit()
        print(f"[✓] SQLite 寫入完成！目前批次共寫入 {len(df):,} 筆資料。")
    finally:
        conn.close()


def diagnose_sqlite(db_path: str = "./local_taiwan_stock.db"):
    """
    SQLite 資料庫診斷工具 (整合 Colab Cell 4 功能)
    檢視表結構、總筆數、最新月份統計與隨機抽樣
    """
    if not os.path.exists(db_path):
        print(f"[!] 找不到資料庫檔案: {db_path}")
        return

    print("=" * 70)
    print(f"🔍 啟動 SQLite 資料庫診斷分析: {db_path}")
    print("=" * 70)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            print("📭 資料庫中查無任何資料表。")
            return

        print(f"📋 包含資料表: {tables}\n")

        for table in tables:
            print(f"--- 資料表: 【{table}】 ---")
            cursor.execute(f"PRAGMA table_info({table})")
            cols_info = cursor.fetchall()
            col_names = [c[1] for c in cols_info]
            col_types = [c[2] for c in cols_info]
            print(f"欄位清單 ({len(col_names)} 欄): {col_names}")
            print(f"欄位型別: {col_types}")

            # 總筆數
            cnt = pd.read_sql(f"SELECT COUNT(*) AS cnt FROM {table}", conn).iloc[0]['cnt']
            print(f"總資料筆數: {cnt:,} 筆")

            if cnt > 0 and 'report_month' in col_names:
                min_m = pd.read_sql(f"SELECT MIN(report_month) as m FROM {table}", conn).iloc[0]['m']
                max_m = pd.read_sql(f"SELECT MAX(report_month) as m FROM {table}", conn).iloc[0]['m']
                print(f"涵蓋年月範圍: {min_m} ~ {max_m}")

                # 最新月份隨機抽樣 3 筆
                print(f"\n📊 最新月份隨機 3 筆抽樣：")
                sample_df = pd.read_sql(
                    f"SELECT * FROM {table} WHERE report_month = '{max_m}' ORDER BY RANDOM() LIMIT 3", conn
                )
                print(sample_df.to_string(index=False))
            elif cnt > 0:
                sample_df = pd.read_sql(f"SELECT * FROM {table} ORDER BY RANDOM() LIMIT 3", conn)
                print(sample_df.to_string(index=False))
            print("\n" + "-" * 70)

    except Exception as e:
        print(f"[!] 診斷過程發生錯誤: {e}")
    finally:
        conn.close()


def run_monthly_revenue_crawler(
    target_ym: str = "",
    months: int = 1,
    output_dir: str = "./output_revenue",
    db_path: str = "./local_taiwan_stock.db",
    save_sqlite: bool = True,
    export_csv: bool = False,
    workers: int = 6,
    upload_gdrive: bool = False,
    overwrite: bool = False
) -> Optional[pd.DataFrame]:
    """
    月營收採集與匯入主流程
    """
    os.makedirs(output_dir, exist_ok=True)

    # 決定目標月份清單
    if target_ym:
        # 判斷是民國還是西元
        if "_" in target_ym:
            # 格式為 113_01
            parts = target_ym.split("_")
            y, m = int(parts[0]), int(parts[1])
            greg_end_ym = roc_to_greg_ym(target_ym)
        else:
            greg_end_ym = target_ym
            y, m = greg_to_roc_ym(target_ym)
        tasks = generate_ym_range(greg_end_ym, months)
    else:
        latest_ym = get_latest_published_ym()
        print(f"[*] 系統智慧推導最新營收發布年月: {latest_ym}")
        tasks = generate_ym_range(latest_ym, months)

    print("=" * 70)
    print("🚀 啟動台股全市場月營收 (MOPS) 採集引擎")
    print(f"[*] 預計處理月份數: {len(tasks)} 個月 (起始: {tasks[-1]} ~ 結束: {tasks[0]})")
    print(f"[*] 輸出目錄: {output_dir}")
    print(f"[*] SQLite 匯入: {'啟用 (' + db_path + ')' if save_sqlite else '停用'}")
    print("=" * 70)

    all_results = []
    saved_single_pqs = []
    stats = {"total_months": len(tasks), "success": 0, "empty": 0}

    # 單月與多月執行緒調度
    if len(tasks) == 1:
        y, m = tasks[0]
        ym_label = f"{y}_{m:02d}"
        greg_label = roc_to_greg_ym(ym_label)
        print(f"[*] 正在採集單月數據: 民國 {ym_label} (西元 {greg_label})...")
        df_month = fetch_single_month_all_markets(y, m)
        if not df_month.empty:
            all_results.append(df_month)
            stats["success"] += 1
            # 存單月 Parquet (依月份切檔)
            single_pq = os.path.join(output_dir, f"api_revenue_{greg_label}.parquet")
            df_month.to_parquet(single_pq, index=False, engine="pyarrow")
            saved_single_pqs.append(single_pq)
            print(f"[✓] 單月 Parquet (依月份切檔) 已儲存: {single_pq} (共 {len(df_month):,} 檔)")
            if export_csv:
                single_csv = os.path.join(output_dir, f"api_revenue_{greg_label}.csv")
                df_month.to_csv(single_csv, index=False, encoding="utf_8_sig")
                print(f"[✓] 單月 CSV 已儲存: {single_csv}")
        else:
            stats["empty"] += 1
            print(f"[!] 月份 {ym_label} 查無有效資料。")
    else:
        def _worker(item):
            y_sub, m_sub = item
            try:
                return (y_sub, m_sub, fetch_single_month_all_markets(y_sub, m_sub))
            except Exception as e:
                return (y_sub, m_sub, pd.DataFrame())

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(_worker, t): t for t in tasks}
            with tqdm(total=len(tasks), desc="月營收進度", unit="月") as pbar:
                for future in as_completed(future_to_task):
                    y_sub, m_sub, df_sub = future.result()
                    ym_label = f"{y_sub}_{m_sub:02d}"
                    greg_label = roc_to_greg_ym(ym_label)

                    if not df_sub.empty:
                        all_results.append(df_sub)
                        stats["success"] += 1
                        # 亦為各月獨立存檔供日後增量使用 (依月份切檔)
                        single_pq = os.path.join(output_dir, f"api_revenue_{greg_label}.parquet")
                        df_sub.to_parquet(single_pq, index=False, engine="pyarrow")
                        saved_single_pqs.append(single_pq)
                    else:
                        stats["empty"] += 1

                    pbar.set_postfix({"成功": stats["success"], "空值": stats["empty"]})
                    pbar.update(1)

    if not all_results:
        print("[!] 本次採集未獲取任何有效月營收資料。")
        return None

    merged_df = pd.concat(all_results, ignore_index=True)
    merged_df.drop_duplicates(subset=['report_month', 'stock_id', 'market_type'], keep='first', inplace=True)
    merged_df.sort_values(by=['year_month', 'stock_id'], ascending=[False, True], inplace=True)
    merged_df.reset_index(drop=True, inplace=True)

    # 輸出彙總總表 Parquet (增量安全合併，避免單月執行沖掉歷史全量)
    all_pq_path = os.path.join(output_dir, "api_revenue_all.parquet")
    if os.path.exists(all_pq_path) and len(tasks) < 20:
        try:
            existing_all = pd.read_parquet(all_pq_path)
            combined_all = pd.concat([merged_df, existing_all], ignore_index=True)
            combined_all.drop_duplicates(subset=['report_month', 'stock_id', 'market_type'], keep='first', inplace=True)
            combined_all.sort_values(by=['year_month', 'stock_id'], ascending=[False, True], inplace=True)
            combined_all.to_parquet(all_pq_path, index=False, engine="pyarrow")
            print(f"\n[✓] 全量彙總 Parquet 增量合併成功: {all_pq_path} (累積共 {len(combined_all):,} 筆)")
        except Exception as e:
            print(f"[!] 彙總合併異常，直接覆蓋最新批次: {e}")
            merged_df.to_parquet(all_pq_path, index=False, engine="pyarrow")
    else:
        merged_df.to_parquet(all_pq_path, index=False, engine="pyarrow")
        print(f"\n[✓] 全量彙總 Parquet 儲存成功: {all_pq_path} (共 {len(merged_df):,} 筆)")

    # 輸出 CSV
    if export_csv:
        csv_filename = f"tw_monthly_revenue_{len(tasks)}m.csv" if len(tasks) > 1 else f"tw_monthly_revenue_{tasks[0][0]}_{tasks[0][1]:02d}.csv"
        csv_path = os.path.join(output_dir, csv_filename)
        merged_df.to_csv(csv_path, index=False, encoding="utf_8_sig")
        print(f"[✓] 彙總 CSV 儲存成功: {csv_path}")

    # 寫入 SQLite
    if save_sqlite:
        save_to_sqlite(merged_df, db_path=db_path, if_exists="append")

    # 同步 Google Drive (含依月份切檔 Parquet、彙總總表與 SQLite)
    if upload_gdrive:
        try:
            from gdrive_sync import upload_file_to_gdrive
            print("☁️ 正在同步月營收檔案至 Google Drive...")
            # 依月份切檔逐一同步上傳
            for pq_file in saved_single_pqs:
                if os.path.exists(pq_file):
                    print(f"[*] 正在上傳單月切檔: {os.path.basename(pq_file)}")
                    upload_file_to_gdrive(pq_file)

            if os.path.exists(all_pq_path):
                upload_file_to_gdrive(all_pq_path)
            if os.path.exists(db_path):
                upload_file_to_gdrive(db_path)
        except Exception as e:
            print(f"[!] Google Drive 上傳提示: {e}")

    print("\n" + "★" * 70)
    print(f"[🎉] 月營收採集與匯入完成！涵蓋 {stats['success']}/{stats['total_months']} 個月份，總筆數: {len(merged_df):,} 筆。")
    print("★" * 70)

    return merged_df


def main():
    parser = argparse.ArgumentParser(description="台股公開資訊觀測站 (MOPS) 月營收採集與標準化資料庫匯入系統")
    parser.add_argument("--month", "-m", default="", help="指定目標年月，可為西元 (2024-01) 或民國 (113_01)，預設自動推算最新月份")
    parser.add_argument("--months", "-n", type=int, default=1, help="回溯月份數 (預設: 1，如回補歷史可指定 80)")
    parser.add_argument("--output-dir", default="./output_revenue", help="檔案輸出目錄 (預設: ./output_revenue)")
    parser.add_argument("--db-path", default="./local_taiwan_stock.db", help="本地 SQLite 資料庫檔案路徑 (預設: ./local_taiwan_stock.db)")
    parser.add_argument("--no-sqlite", action="store_true", help="停用 SQLite 資料庫寫入")
    parser.add_argument("--export-csv", action="store_true", help="同時匯出標準 CSV 檔案")
    parser.add_argument("--workers", type=int, default=6, help="並發工作執行緒數 (預設: 6)")
    parser.add_argument("--current-cycle", action="store_true", help="強制鎖定當前申報週期之上月 (例: 10/1~10/10 鎖定 9 月營收動態申報)")
    parser.add_argument("--upload-gdrive", action="store_true", help="完成後上傳至 Google Drive 備份")
    parser.add_argument("--diagnose", action="store_true", help="僅執行本地 SQLite 資料庫結構與數據診斷工具")

    args = parser.parse_args()

    if args.diagnose:
        diagnose_sqlite(args.db_path)
        return

    target_ym = args.month
    if not target_ym and args.current_cycle:
        target_ym = get_latest_published_ym(target_prev_month=True)

    run_monthly_revenue_crawler(
        target_ym=target_ym,
        months=args.months,
        output_dir=args.output_dir,
        db_path=args.db_path,
        save_sqlite=not args.no_sqlite,
        export_csv=args.export_csv,
        workers=args.workers,
        upload_gdrive=args.upload_gdrive
    )


if __name__ == "__main__":
    main()
