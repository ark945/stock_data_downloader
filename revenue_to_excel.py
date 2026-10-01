# -*- coding: utf-8 -*-
"""
台股月營收 Parquet 轉高顏值專業 Excel 工具 (Revenue to Professional Excel Converter)
=================================================================================
核心特色：
1. 金融專業美化：
   - 深藍商務表頭 (Navy #1F4E78)、白字粗體、置中對齊
   - 自動開啟自動篩選 (AutoFilter) 與凍結首列 (Freeze Panes)
   - 自動最適欄寬計算 (Auto Column Widths)
2. 數值與條件格式化：
   - 營收金額千分位 (#,##0)
   - 成長率 (YoY% / MoM%) 兩位小數與正負號標註 (+0.00% / -0.00%)
   - 台股慣例配色：YoY > 0 亮眼紅字，YoY > 50% 淺粉底高成長醒目標記
3. 多分頁智慧量化視角：
   - 工作表 1：【全市場月營收明細】
   - 工作表 2：【營收雙增優質股】(YoY > 20% 且 MoM > 0%)
   - 工作表 3：【YoY 年增率前 50 強】
4. 支援單一檔案、指定年月 (--month 2026-09) 或目錄批次轉換
"""

import os
import sys
import glob
import argparse
from typing import Optional

import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 欄位中文名稱對照字典
HEADER_CHINESE_MAP = {
    "stock_id": "股票代號",
    "stock_name": "公司名稱",
    "report_month": "申報年月(民國)",
    "year_month": "西元年月",
    "market_type": "市場類別",
    "rev_current": "當月營收 (千元)",
    "rev_last_month": "上月營收 (千元)",
    "rev_last_year": "去年同月營收 (千元)",
    "mom_pct": "月增率 (MoM %)",
    "yoy_pct": "年增率 (YoY %)",
    "rev_accumulated": "當年累計營收 (千元)",
    "rev_accumulated_last_year": "去年同期累計 (千元)",
    "yoy_accumulated_pct": "累計年增率 (%)",
    "remark": "備註說明"
}

# 樣式定義
FONT_HEADER = Font(name="微軟正黑體", size=11, bold=True, color="FFFFFF")
FILL_HEADER = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
FILL_SUBHEADER = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")

FONT_DATA = Font(name="微軟正黑體", size=10)
FONT_BOLD = Font(name="微軟正黑體", size=10, bold=True)

# 台股紅漲綠跌慣例：正增長紅字、負增長綠字
FONT_RED = Font(name="微軟正黑體", size=10, bold=True, color="C00000")
FONT_GREEN = Font(name="微軟正黑體", size=10, bold=True, color="375623")
FILL_HIGH_GROWTH = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")  # 淺橘紅高成長底色

ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")

BORDER_THIN = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9")
)


def format_worksheet(ws, df: pd.DataFrame, is_summary: bool = False):
    """套用專業金融表格格式、數值格式與自動欄寬"""
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    # 1. 表頭格式
    for col_idx in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER if not is_summary else FILL_SUBHEADER
        cell.alignment = ALIGN_CENTER
        ws.row_dimensions[1].height = 28

    # 欄名映射
    col_names = list(df.columns)

    # 2. 資料列格式
    for row_idx, row_data in enumerate(df.itertuples(index=False), start=2):
        ws.row_dimensions[row_idx].height = 20
        yoy_val = getattr(row_data, "yoy_pct", None) if "yoy_pct" in col_names else None

        for col_idx, col_name in enumerate(col_names, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = BORDER_THIN
            val = getattr(row_data, col_name, None)

            # 金額欄位：套用千分位整數
            if col_name in ["rev_current", "rev_last_month", "rev_last_year", "rev_accumulated", "rev_accumulated_last_year"]:
                cell.number_format = "#,##0"
                cell.alignment = ALIGN_RIGHT
                cell.font = FONT_DATA

            # 百分比欄位：YoY / MoM / 累計 YoY
            elif col_name in ["mom_pct", "yoy_pct", "yoy_accumulated_pct"]:
                if pd.notna(val):
                    cell.number_format = '+0.00%;-0.00%;0.00%'
                    # 原始數據為百分比數字 (例如 15.05 代表 15.05%)，轉為 0.1505 供 Excel 百分比格式使用
                    cell.value = val / 100.0

                    if val > 0:
                        cell.font = FONT_RED
                        if col_name == "yoy_pct" and val >= 50.0:
                            cell.fill = FILL_HIGH_GROWTH
                    elif val < 0:
                        cell.font = FONT_GREEN
                    else:
                        cell.font = FONT_DATA
                else:
                    cell.font = FONT_DATA
                cell.alignment = ALIGN_RIGHT

            # 代碼與年月：置中
            elif col_name in ["stock_id", "report_month", "year_month", "market_type"]:
                cell.alignment = ALIGN_CENTER
                cell.font = FONT_BOLD if col_name == "stock_id" else FONT_DATA

            # 名稱與備註：靠左
            else:
                cell.alignment = ALIGN_LEFT
                cell.font = FONT_BOLD if col_name == "stock_name" else FONT_DATA

    # 3. 自動最適欄寬
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val_str = str(cell.value or '')
            # 處理中文寬度 (中文字算 2 個字元寬)
            cell_len = sum(2 if ord(c) > 127 else 1 for c in val_str)
            if cell_len > max_len:
                max_len = cell_len
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)


def convert_revenue_parquet_to_excel(
    parquet_path: str,
    output_excel_path: Optional[str] = None
) -> Optional[str]:
    """將月營收 Parquet 轉成多工作表高顏值 Excel"""
    if not os.path.exists(parquet_path):
        print(f"[!] 找不到來源 Parquet: {parquet_path}")
        return None

    if output_excel_path is None:
        output_excel_path = os.path.splitext(parquet_path)[0] + ".xlsx"

    print(f"[*] 正在讀取月營收資料: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    if df.empty:
        print(f"[!] 檔案為空，取消轉換: {parquet_path}")
        return None

    # 保留原始英文列供計算，篩選所需欄位順序
    cols_order = [
        "stock_id", "stock_name", "report_month", "year_month", "market_type",
        "rev_current", "mom_pct", "yoy_pct", "rev_last_month", "rev_last_year",
        "rev_accumulated", "rev_accumulated_last_year", "yoy_accumulated_pct", "remark"
    ]
    avail_cols = [c for c in cols_order if c in df.columns]
    df_main = df[avail_cols].copy()

    # 排序：按 YoY 年增率降序
    if "yoy_pct" in df_main.columns:
        df_main.sort_values(by="yoy_pct", ascending=False, inplace=True)
    df_main.reset_index(drop=True, inplace=True)

    # 建立量化衍生切片：
    # 1. 雙增優質股：YoY > 20% 且 MoM > 0
    df_double_growth = pd.DataFrame()
    if "yoy_pct" in df_main.columns and "mom_pct" in df_main.columns:
        cond = (df_main["yoy_pct"] >= 20.0) & (df_main["mom_pct"] > 0)
        df_double_growth = df_main[cond].copy().reset_index(drop=True)

    # 2. YoY Top 50
    df_top50 = df_main.head(50).copy().reset_index(drop=True)

    # 建立 Excel 活頁簿
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 移除預設空白頁

    # 寫入工作表 1：全市場明細
    ws_all = wb.create_sheet(title="全市場月營收明細")
    # 寫入中文表頭
    ws_all.append([HEADER_CHINESE_MAP.get(c, c) for c in df_main.columns])
    for row in df_main.itertuples(index=False):
        ws_all.append(list(row))
    format_worksheet(ws_all, df_main)

    # 寫入工作表 2：營收雙增標的 (若有)
    if not df_double_growth.empty:
        ws_growth = wb.create_sheet(title="營收雙增優質股 (YoY>20% & MoM>0)")
        ws_growth.append([HEADER_CHINESE_MAP.get(c, c) for c in df_double_growth.columns])
        for row in df_double_growth.itertuples(index=False):
            ws_growth.append(list(row))
        format_worksheet(ws_growth, df_double_growth, is_summary=True)

    # 寫入工作表 3：年增率前 50 強 (若總數 > 15)
    if len(df_main) > 15:
        ws_top = wb.create_sheet(title="年增率排行 Top 50")
        ws_top.append([HEADER_CHINESE_MAP.get(c, c) for c in df_top50.columns])
        for row in df_top50.itertuples(index=False):
            ws_top.append(list(row))
        format_worksheet(ws_top, df_top50, is_summary=True)

    wb.save(output_excel_path)
    file_size_kb = os.path.getsize(output_excel_path) / 1024
    print(f"[✓] 成功產製專業月營收 Excel: {output_excel_path} ({file_size_kb:.1f} KB, 共 {len(df_main):,} 檔)")
    if not df_double_growth.empty:
        print(f"    - 營收雙增優質股: {len(df_double_growth)} 檔")

    return output_excel_path


def main():
    parser = argparse.ArgumentParser(description="台股月營收 Parquet 轉高顏值專業 Excel 工具")
    parser.add_argument("parquet_file", nargs="?", default="", help="指定目標 Parquet 檔案路徑")
    parser.add_argument("--month", "-m", default="", help="指定年月 (如 2026-09)，自動尋找 output_revenue/api_revenue_YYYY-MM.parquet")
    parser.add_argument("--output", "-o", default="", help="輸出之 Excel 檔案路徑")
    parser.add_argument("--all", action="store_true", help="批次將 output_revenue/ 下所有月份 Parquet 轉成 Excel")

    args = parser.parse_args()

    revenue_dir = os.path.join(os.path.dirname(__file__), "output_revenue")

    if args.all:
        files = sorted(glob.glob(os.path.join(revenue_dir, "api_revenue_20*.parquet")))
        if not files:
            print(f"[!] 在 {revenue_dir} 未找到月營收 Parquet 檔案。")
            return
        print(f"[*] 開始批次產製月營收 Excel (共 {len(files)} 個月份)...")
        for f in files:
            convert_revenue_parquet_to_excel(f)
        return

    target_pq = args.parquet_file
    if not target_pq and args.month:
        target_pq = os.path.join(revenue_dir, f"api_revenue_{args.month}.parquet")

    if not target_pq:
        # 預設尋找最新月份
        pqs = sorted(glob.glob(os.path.join(revenue_dir, "api_revenue_20*.parquet")))
        if pqs:
            target_pq = pqs[-1]
            print(f"[*] 未指定檔案，自動鎖定最新月份: {os.path.basename(target_pq)}")
        else:
            print("[!] 未找到任何月營收 Parquet 檔案，請指定路徑或年月。")
            return

    convert_revenue_parquet_to_excel(target_pq, args.output if args.output else None)


if __name__ == "__main__":
    main()
