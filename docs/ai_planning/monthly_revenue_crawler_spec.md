# 公開資訊觀測站 (MOPS) 月營收採集與標準化資料庫匯入模組技術規格書

- **模組名稱**：`monthly_revenue_crawler.py`
- **規劃路徑**：`docs/ai_planning/monthly_revenue_crawler_spec.md`
- **建立日期**：2026-09-26
- **參考來源**：Colab「財報儀表板相關程式碼」Cell 2 & Cell 3 (`oabG6l4rZqs3`)

---

## 1. 需求背景與目的
台股公開資訊觀測站 (MOPS) 規定所有公開發行公司須於每月 10 日前申報上月份營業收入。月營收為台股基本面分析中頻率最高、時效性最強之核心數據指標。

本模組旨在將原先於 Google Colab 實驗環境之月營收爬蟲與資料庫匯入程式碼，無縫整合進 `stock_data_downloader` 專案流水線：
1. 支援自動從 MOPS 抓取上市 (SII)、上櫃 (OTC)、興櫃 (ROTC) 與各別之 KY 股（共 6 大報表）之月營收明細。
2. 支援「雙主機 Fallback」機制（`mopsov.twse.com.tw` 與 `mops.twse.com.tw`），確保歷史資料與最新資料皆能穩定取得。
3. 具備多執行緒加速與指數退避重試，自動處理 Big5 / UTF-8 編碼與 HTML 表格解析。
4. 統一清洗與標準化：排除合計行、去除千分位逗號、標準化民國與西元年月、欄位映射為標準 snake_case 英文。
5. 多元輸出規格：
   - **標準 Parquet**：相容專案整體分析規範（`output_revenue/api_revenue_{YYYY-MM}.parquet`）。
   - **標準 CSV**：支援繁體中文與 Excel 相容之 `utf_8_sig` 匯出。
   - **SQLite 本地資料庫**：自動寫入/更新 `local_taiwan_stock.db` 中的 `monthly_revenue` 表，並建立關鍵查詢索引。
   - **雲端備份**：支援 Google Drive 同步上傳。

---

## 2. 爬蟲架構與網路請求設計

### 2.1 目標端點與報表類型
MOPS 月營收 HTML 靜態報表路徑結構：
`https://{host}/nas/t21/{market}/t21sc03_{roc_year}_{month}_{is_ky}.html`

| 市場標記 | 市場類別 | is_ky | 網址子路徑範例 |
| :--- | :--- | :--- | :--- |
| `sii` | 上市一般股票 | 0 | `t21/sii/t21sc03_{y}_{m}_0.html` |
| `sii_ky` | 上市 KY 股票 | 1 | `t21/sii/t21sc03_{y}_{m}_1.html` |
| `otc` | 上櫃一般股票 | 0 | `t21/otc/t21sc03_{y}_{m}_0.html` |
| `otc_ky` | 上櫃 KY 股票 | 1 | `t21/otc/t21sc03_{y}_{m}_1.html` |
| `rotc` | 興櫃一般股票 | 0 | `t21/rotc/t21sc03_{y}_{m}_0.html` |
| `rotc_ky` | 興櫃 KY 股票 | 1 | `t21/rotc/t21sc03_{y}_{m}_1.html` |

### 2.2 雙主機容錯輪詢
- **新版主機**：`mopsov.twse.com.tw`（優先，近年資料主要存放處）
- **舊版主機**：`mops.twse.com.tw`（備援，歷史舊年資料相容處）

---

## 3. 資料標準化與欄位映射規則

整合 Colab 原有中文表格欄位與專案標準化英文欄位（與 Cell 3 `oabG6l4rZqs3` 保持 100% 相容）：

| 輸出欄位 (DB / Parquet) | 原始中文欄名 | 型態 | 說明 |
| :--- | :--- | :--- | :--- |
| `stock_id` | 公司代號 / 證券代號 | string | 股票代碼 (例: 2330) |
| `stock_name` | 公司名稱 / 公司簡稱 | string | 公司名稱 (例: 台積電) |
| `report_month` | 資料年月 | string | 民國年月 (例: 113_01) |
| `year_month` | (衍生西元) | string | 西元年月 (例: 2024-01) |
| `market_type` | 資料類型 | string | 市場板塊 (例: sii@mopsov.twse.com.tw) |
| `rev_current` | 當月營收 / 本月營收 | double | 當月營業收入 (千元) |
| `rev_last_month` | 上月營收 | double | 上月營業收入 (千元) |
| `rev_last_year` | 去年同月營收 / 去年當月營收 | double | 去年同月營業收入 (千元) |
| `mom_pct` | 上月比較 增減(%) | double | 上月增減百分比 (%) |
| `yoy_pct` | 去年同月 增減(%) | double | 去年同月增減百分比 (%) |
| `rev_accumulated` | 當月累計營收 | double | 當年累計營業收入 (千元) |
| `rev_accumulated_last_year` | 去年累計營收 | double | 去年同期累計營業收入 (千元) |
| `yoy_accumulated_pct` | 前期比較 增減(%) | double | 累計營業收入前期比較增減 (%) |
| `remark` | 備註 | string | 營收變動備註或重大訊息 |

---

## 4. SQLite 資料庫索引設計
建立 SQLite 資料表 `monthly_revenue` 時，自動建立下列索引加速查詢：
1. `idx_rev_id`: `stock_id`（個股歷史營收快速檢索）
2. `idx_rev_date`: `report_month`（按民國年月批次查詢）
3. `idx_rev_ym`: `year_month`（按西元年月時間序列查詢）
4. `idx_yoy_high`: `yoy_pct`（高成長股篩選排行優化）

---

## 5. CLI 操作介面設計
支援靈活參數：
- `--month` / `-m`: 指定抓取西元年月 (YYYY-MM) 或民國 (ROC_M，如 113_01)
- `--months` / `-n`: 指定回溯抓取 N 個月（預設 1 個月；歷史回補可設 80 個月）
- `--start-ym` / `--end-ym`: 指定年月區間回補
- `--output-dir`: 輸出目錄（預設 `./output_revenue`）
- `--db-path`: 本地 SQLite 資料庫檔案路徑（預設 `./local_taiwan_stock.db`）
- `--no-sqlite`: 停用 SQLite 匯入（僅輸出 Parquet/CSV）
- `--export-csv`: 額外匯出 CSV 檔案
- `--workers`: 多執行緒並發數（預設 6）
- `--upload-gdrive`: 完成後自動同步上傳至 Google Drive
- `--diagnose`: 執行 SQLite 資料庫診斷工具（檢視 Schema、統計筆數、抽樣檢視）
