"""
Parquet 轉 Excel 工具 (Parquet to Excel Converter)
支援：
- 單一 Parquet 轉 Excel (.xlsx)
- 批次將 output/ 下所有 Parquet 轉成 Excel
- 自動處理 Excel 百萬行上限分頁保護
"""

import os
import sys
import glob
import time
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def convert_parquet_to_excel(parquet_path: str, excel_path: str = None) -> bool:
    if not os.path.exists(parquet_path):
        print(f"[!] 錯誤：找不到 Parquet 檔案: {parquet_path}")
        return False

    if excel_path is None:
        excel_path = os.path.splitext(parquet_path)[0] + ".xlsx"

    print(f"[*] 讀取 Parquet 檔案中: {parquet_path}")
    start_time = time.time()
    
    df = pd.read_parquet(parquet_path)
    rows, cols = df.shape
    symbols_cnt = df["symbol"].nunique() if "symbol" in df.columns else 0
    print(f"[+] 讀取完成！共 {rows:,} 列, {cols} 欄 (涵蓋標的: {symbols_cnt:,} 檔, 耗時 {time.time() - start_time:.2f} 秒)")

    # 檢查 Excel 行數上限 (1,048,576 列，含標題行最多 1,048,575 筆資料)
    EXCEL_LIMIT = 1048575
    if rows > EXCEL_LIMIT:
        print(f"[!] 提示：資料列數 ({rows:,}) 超過單一 Excel 工作表上限 ({EXCEL_LIMIT:,})，將自動分頁存檔...")
        chunk_size = EXCEL_LIMIT
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for i in range(0, rows, chunk_size):
                sheet_name = f"Sheet_{(i // chunk_size) + 1}"
                print(f"[*] 寫入工作表 {sheet_name} ({i:,} ~ {min(i + chunk_size, rows):,})...")
                df.iloc[i : i + chunk_size].to_excel(writer, sheet_name=sheet_name, index=False)
    else:
        print(f"[*] 正在輸出至 Excel 檔案: {excel_path} (資料量約 {rows:,} 筆，請稍候)...")
        write_start = time.time()
        df.to_excel(excel_path, engine="openpyxl", index=False)
        print(f"[+] 寫入完成！(耗時 {time.time() - write_start:.2f} 秒)")

    file_size_mb = os.path.getsize(excel_path) / (1024 * 1024)
    print(f"[OK] 轉換成功！輸出檔案: {excel_path} ({file_size_mb:.2f} MB)")
    print(f"[OK] 總耗時: {time.time() - start_time:.2f} 秒\n")
    return True


def batch_convert_output_dir(output_dir: str = "output"):
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), output_dir)

    parquets = sorted(glob.glob(os.path.join(output_dir, "*.parquet")))
    if not parquets:
        print(f"[!] 在 {output_dir} 目錄下未找到任何 .parquet 檔案！")
        return

    print(f"==================================================")
    print(f"[*] 開始批次轉換 Parquet 至 Excel (共 {len(parquets)} 個檔案)")
    print(f"==================================================")

    for pq in parquets:
        convert_parquet_to_excel(pq)

    print("==================================================")
    print(f"[OK] 全部 Parquet 檔案轉換完成！")
    print("==================================================")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
        if os.path.isdir(target):
            batch_convert_output_dir(target)
        else:
            out_excel = sys.argv[2] if len(sys.argv) > 2 else None
            convert_parquet_to_excel(target, out_excel)
    else:
        # 預設轉換 output/ 下的所有 parquet
        default_dir = os.path.join(os.path.dirname(__file__), "output")
        batch_convert_output_dir(default_dir)
