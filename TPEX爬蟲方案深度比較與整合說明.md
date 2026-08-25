# 📊 TPEX 上櫃券商買賣日報表爬蟲 — 方案深度比較與整合說明書

本說明文件針對 `stock_data_downloader` 專案中**原生 TPEX 爬蟲模組**與新加入的 **`TPEX_DL_release` 模組（本機版 / GitHub Actions 版）** 進行技術架構剖析、採集原理對比與整合評估。

---

## 📌 一、兩大方案總覽與模組定位

| 模組分組 | 檔案位置 | 主要用途與執行模式 |
| :--- | :--- | :--- |
| **原生方案 (本地端)** | `tpex_crawler_local.py` | 本地極速多進程並行採集 (4~8 Workers)，輸出 Parquet / Excel |
| **原生方案 (雲端 CI)** | `tpex_crawler_cloud.py` | GitHub Actions 20 節點矩陣分片，雲端自動排程與 GDrive 同步 |
| **新增 `TPEX_DL_release` (本機版)** | `TPEX_DL_release/crawl_all.py`<br>`TPEX_DL_release/tpex_broker_bs.py` | 單進程長會話採集、提供 Python Client 模組與 CLI，輸出單檔 JSON |
| **新增 `TPEX_DL_release` (CI 版)** | `TPEX_DL_release/ci/crawler.py`<br>`TPEX_DL_release/ci/fetch.py` | Linux Headless / Xvfb 容器化設計，適配單一 Runner 執行 |

---

## 🔍 二、核心技術架構與抓取機制深度對比

### 1. 採集核心原理：【點擊下載 CSV】vs【監聽 API 網路封包】

這是兩個方案最根本的技術差異：

```
【原生 stock_data_downloader 機制】
輸入代碼 ➔ 點擊日報表 [查詢] ➔ 注入 Turnstile ➔ 點擊 [下載 CSV (UTF-8)] ➔ 檔案落盤監聽 ➔ 讀取 CSV 轉 DataFrame ➔ 刪除暫存檔

【新增 TPEX_DL_release 機制】
啟動 CDP 網路監聽 (page.listen.start) ➔ 輸入代碼 ➔ 等待 Turnstile Token ➔ 點擊 [查詢] ➔ 攔截 POST /afterTrading/brokerBS 回應 JSON ➔ 記憶體直接解析 JSON ➔ 存入 .json
```

* **原生方案（模擬按鈕下載 CSV）**：
  * **優點**：由 TPEX 伺服器直接產出完整 CSV 檔案，包含台股標準分點各價格買賣明細。
  * **缺點**：依賴瀏覽器下載事件與檔案系統 I/O（需建立暫存資料夾、輪詢監聽 `.csv` 檔案生成並刪除），若遇到瀏覽器下載視窗攔截或暫存殘留，容易增加 I/O 開銷。
* **`TPEX_DL_release`（CDP 網路封包監聽）**：
  * **優點**：利用 DrissionPage 的 `listen.start` 與 `listen.wait`，直接在 Chromium 底層抓取後端回傳的原始 JSON 封包。完全**不需要點擊下載 CSV 按鈕**，無磁碟下載 I/O 延遲，網路傳輸效率極高且不易受前端 DOM 變更影響。
  * **缺點**：取得的是原始未清洗的巢狀 JSON 資料結構（`tables` 陣列），後續需自行轉換或格式化。

---

### 2. 並行架構與採集吞吐量

* **原生方案 (`stock_data_downloader`)**：
  * **本地多進程並行**：支援 `multiprocessing` 啟動 4～8 個獨立 Chrome Worker（動態端口 `9501`~`9508`），全市場 890 檔僅需 **15 ~ 20 分鐘**。
  * **雲端 20-Shard 矩陣**：利用 GitHub Actions Matrix 同時啟動 20 台虛擬機並行，每台僅需處理約 45 檔，**5 ~ 8 分鐘** 即可收工。
* **`TPEX_DL_release`**：
  * **單一序列長會話**：採用單一 Chrome 實例循序依序查詢（內建 `INTER_STOCK_DELAY = 2.0s` 節流保護），抓取全市場 890 檔約需 **1.5 小時**。
  * **設計哲學**：優先考量**防風控穩定度**與單一 IP 的平穩請求，透過低頻長連線避免觸發 Cloudflare 嚴格頻率限制。

---

### 3. 反爬防禦與 Cloudflare Turnstile 攻防對策

TPEX 券商日報表頁面採用了 Cloudflare Turnstile Invisible 模式，兩者的應對策略如下：

| 防禦項目 | 原生方案 (`stock_data_downloader`) | 新增 `TPEX_DL_release` |
| :--- | :--- | :--- |
| **Token 激活方式** | 透過 JS 主動執行 `turnstile.execute()` 並輪詢隱藏 input | 輪詢 `input[name="cf-turnstile-response"]` 等待長度 > 20 的有效 token |
| **520 / 導向異常** | 檢查 URL 是否偏離或 Title 是否含 520，自動跳回首頁 | 判定回應封包之 `status == 520`，自動執行指數退避重試 (`time.sleep(2 + attempt*2)`) |
| **連續失敗自癒階梯** | 原地重試 3 次 ➔ 失敗轉入第 2 輪補抓佇列 | **三級智慧自癒階梯**：<br>1. 連續 3 次失敗：Reload 頁面刷新 Token<br>2. 連續 6 次失敗：重開瀏覽器 + 冷卻 30 秒<br>3. 連續 20 次失敗：安全熔斷中止，避免浪費額度 |

---

### 4. 資料結構、清洗與持久化儲存

* **原生方案 (`stock_data_downloader`)**：
  * **結構化清洗**：內建 `parse_tpex_csv_to_dataframe`，將雙欄位（買進/賣出）對稱資料解析為標準 13 欄位大表（包含：證券代號、日期、券商代號、券商名稱、價格、買進股數、賣出股數、淨額、均價等）。
  * **高壓縮 Parquet 儲存**：全市場合併為單一 `TWSE_TPEX_BSR_YYYYMMDD.parquet`（Zstandard 壓縮後僅約 0.2~0.3 MB），方便大數據分析、DuckDB / Pandas 秒級查詢。
* **`TPEX_DL_release`**：
  * **原始 JSON 保存**：每檔股票獨立儲存為單一 JSON 檔案（例如 `data/brokerBS/20260825/1240.json`），保留 TPEX API 回傳的 100% 原始欄位與階層結構。
  * **中斷續跑 State**：即時維護 `crawler_state_YYYYMMDD.json`，記錄 `done` 與 `failed` 清單，中斷後重新執行可秒級跳過已完成個股。

---

## 📊 三、各維度全方位對比矩陣

| 評估維度 | 原生 `stock_data_downloader` | 新增 `TPEX_DL_release` | 綜合評析 |
| :--- | :--- | :--- | :--- |
| **採集觸發機制** | 模擬點擊「下載 CSV」按鈕 | 監聽 API 網路層 POST 封包 (`listen`) | 🌟 `TPEX_DL_release` 的 API 封包攔截更優雅、無檔案 I/O 開銷 |
| **採集全市場耗時** | ⚡ **15 ~ 20 分鐘**（本地多進程）<br>⚡ **5 ~ 8 分鐘**（雲端 20 分片） | ⏳ **約 1.5 小時**（單一長會話序列執行） | 🚀 原生方案在並行速度與大規模吞吐上具絕對優勢 |
| **模組化與 API 友善度** | 專案批次整合型腳本 | 提供 `TPEXBrokerBSClient` 與 CLI 參數 (`--stdout`, `--out`) | 🌟 `TPEX_DL_release` 模組化程度高，單檔查詢極為方便 |
| **資料儲存格式** | 全市場單一壓縮 Parquet ＋ Excel | 890 個獨立 JSON 原始檔案 | 原生方案適合量化回測與長年歸檔；`TPEX_DL_release` 適合留存原始封包 |
| **雲端 CI 策略** | 20-Shard 矩陣 + 自動合併 + GDrive 同步 | 單一 Runner 循序跑（依賴 Xvfb / Headless） | 原生方案的分片設計大幅降低單一 CI Runner 執行逾時與 IP 風險 |
| **容錯與自癒機制** | 多輪補抓閉環 + Checkpoint | 三級階梯自癒（Reload ➔ 重啟冷卻 ➔ 熔斷） | 🌟 `TPEX_DL_release` 的三級自癒邏輯極為細緻，抗風控能力強 |
| **上市/上櫃整合度** | 同步整合 TWSE (上市) ＋ TPEX (上櫃) | 專注於 TPEX (上櫃) 單一市場 | 原生方案具備全台股 (上市+上櫃) 雙市場採集協同能力 |

---

## 💡 四、優缺點深度剖析

### 1. 原生方案 (`stock_data_downloader`)
* **強項**：
  1. **極致速度**：支援多進程與雲端矩陣分片，採集時間縮短至分鐘級。
  2. **生產級輸出**：直接輸出 Parquet 壓縮檔，體積極小且內建完整清洗邏輯。
  3. **生態完整**：已打通 Google Drive 自動上傳、Telegram/Discord 通知與上市 (TWSE) 整合。
* **短板**：
  1. 依賴點擊前端「下載 CSV」按鈕，若官方調整按鈕 Selector 或下載觸發行為可能需要維護。

### 2. 新增方案 (`TPEX_DL_release`)
* **強項**：
  1. **底層封包攔截**：直接抓取 API JSON 回應，完全避開下載按鈕與檔案系統 I/O，技術架構更純粹穩定。
  2. **模組化封裝極佳**：`TPEXBrokerBSClient` 支援 Context Manager，易於以 Python 模組形式嵌入其他應用或作為 CLI 工具即時查詢單一股票。
  3. **健全的自癒階梯**：Reload ➔ 瀏覽器重啟冷卻 ➔ 熔斷機制，能有效因應 Cloudflare 短暫風控。
* **短板**：
  1. 序列執行耗時較長（890 檔需 1.5 小時），且產出大量單檔 JSON，長期累積會產生大量磁碟碎片與 I/O 負擔。

---

## 🛠️ 五、最佳融合與演進建議 (Integration Recommendations)

建議融合兩者之長，打造**次世代 TPEX 爬蟲引擎**：

1. **【採集核心升級】**：將 `TPEX_DL_release` 的 **CDP API 封包監聽技術 (`page.listen`)** 移植至原生方案中，取代原本的「點擊下載 CSV」步驟，徹底擺脫暫存檔案輪詢。
2. **【並行與儲存保留】**：維持原生方案的 **多進程並行 (4~8 Workers) / 雲端 20-Shard 分片** 與 **Parquet / Excel 統一清洗輸出**，兼顧分鐘級採集速度與高效率儲存。
3. **【保留獨立 Client 工具】**：將 `TPEX_DL_release/tpex_broker_bs.py` 保留作為日常「單檔快速除錯 / 即時查詢 CLI」之輕量化工具。
