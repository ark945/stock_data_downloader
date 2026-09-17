# FinMind 逐價明細轉換為 ABSR1 彙總表技術規格說明書

- **模組名稱**：`finmind_to_absr1.py`
- **規劃路徑**：`docs/ai_planning/finmind_to_absr1_spec.md`
- **建立日期**：2026-09-17

---

## 1. 需求背景與目的
專案現有籌碼分析系統（如 `stock_data_analysis`）深度依賴證交所/櫃買中心的券商買賣日報彙總表格式（即 `api_absr1_YYYY-MM-DD_YYYY-MM-DD.parquet`）。
當官方爬蟲因反爬蟲機制、網路延遲或例行維護無法及時取得時，可透過第三方數據源（例如 FinMind 的分點交易明細）作為備援。

然而，FinMind 提供的資料為**逐價明細顆粒度**（包含 `price`, `buy`, `sell` 等各別成交價位），資料量高達數百萬列，與 `api_absr1` 的**分點單日彙總顆粒度**不同。
本模組旨在提供高效、精確的聚合轉換管線，在 2 秒內將數百萬筆逐價明細無損聚合為與官方完全相容的 13 欄位標準 Parquet 格式。

---

## 2. 資料結構與欄位映射規則

| 目標欄位 (api_absr1) | 型態 (PyArrow) | 來源 (FinMind) | 聚合/計算公式 | 單位與說明 |
| :--- | :--- | :--- | :--- | :--- |
| `symbol` | `pa.string()` | `stock_id` | 直讀 | 股票代碼 (例: 2330) |
| `trade_date` | `pa.string()` | `date` | 直讀 | 交易日期 (YYYY-MM-DD) |
| `broker_id` | `pa.string()` | `securities_trader_id` | 直讀 | 券商分點代碼 (4碼) |
| `buy_vol` | `pa.float64()` | `buy` | `sum(buy)` | 總買進股數 (股) |
| `sell_vol` | `pa.float64()` | `sell` | `sum(sell)` | 總賣出股數 (股) |
| `net_vol` | `pa.float64()` | - | `buy_vol - sell_vol` | 買賣超股數 (股) |
| `buy_amt` | `pa.float64()` | `price * buy` | `sum(price * buy) / 1000.0` | 買進總額 (千元) |
| `sell_amt` | `pa.float64()` | `price * sell` | `sum(price * sell) / 1000.0` | 賣出總額 (千元) |
| `net_amt` | `pa.float64()` | - | `buy_amt - sell_amt` | 買賣淨額 (千元) |
| `buy_avg_price` | `pa.float64()` | - | `(buy_amt * 1000) / buy_vol` | 買進加權均價 (元，若買量0則為NaN) |
| `sell_avg_price` | `pa.float64()` | - | `(sell_amt * 1000) / sell_vol` | 賣出加權均價 (元，若賣量0則為NaN) |
| `turnover` | `pa.float64()` | - | `buy_amt + sell_amt` | 該分點成交總額 (千元) |
| `market_share` | `pa.float64()` | - | `(turnover / sum_stock_turnover) * 100` | 該分點在該檔股票之市佔率 (%) |

---

## 3. 排序與儲存規格
- **排序**：依 `symbol` (升冪)、`broker_id` (升冪) 嚴格排序。
- **壓縮格式**：SNAPPY 壓縮 Parquet。
- **Schema 驗證**：完全符合標準官方 `api_absr1` Schema 規格，字串皆採用標準 `utf8/string`，數值皆為 `double/float64`。
