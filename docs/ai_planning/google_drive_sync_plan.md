# 自動同步 Parquet 資料庫至 Google Drive 實作規劃

本規劃旨在將每日台股全市場券商分點 Parquet 資料庫（`api_absr1_YYYY-MM-DD_YYYY-MM-DD_1.parquet`）在產出後，**全自動同步上傳至指定的 Google Drive 雲端硬碟資料夾**，實現跨平台永久歸檔與隨時存取。

---

## 🎯 目標 Google Drive 資料夾資訊

* **目標資料夾連結**：[Google Drive 目標資料夾](https://drive.google.com/drive/folders/1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a?usp=sharing)
* **資料夾 ID (Folder ID)**：`1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a`

---

## 🏗️ 系統架構與自動化流程

```mermaid
graph TD
    A[4-Runner 雲端分散式抓取完成] --> B[merge_shards.py 聚合全市場 Parquet]
    B --> C{檢查 Google Drive 設定}
    C -- 已配置 Service Account --> D[gdrive_sync.py 呼叫 Google Drive API]
    D --> E[自動上傳至目標資料夾 1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a]
    E --> F[取得雲端檔案直連/分享連結]
    F --> G[推播 Telegram / Email 通知 (附帶 GDrive 連結)]
    C -- 未配置/略過 --> H[保留本機/Artifact 並發送標準通知]
```

---

## 🛠️ 預計新增與修改之檔案

### 1. [NEW] `gdrive_sync.py`
* **職責**：封裝 Google Drive v3 API 操作。
* **功能**：
  1. 支援從環境變數 `GDRIVE_SERVICE_ACCOUNT_KEY`（JSON 字串）或本機 `credentials.json` 進行身分驗證。
  2. 自動上傳指定檔案至目標資料夾 `1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a`。
  3. 支援智慧覆蓋機制（若同日檔案已存在則自動更新版本，避免資料夾產生重複垃圾檔案）。
  4. 回傳檔案之 Google Drive 預覽/下載 URL。

### 2. [MODIFY] `merge_shards.py`
* 在完成 4 個分片的 Parquet 聚合後，主動呼叫 `gdrive_sync.py` 執行雲端同步。
* 將 Google Drive 連結整合進 Telegram 即時推播訊息中。

### 3. [MODIFY] `.github/workflows/daily_stock_crawler.yml`
* 在 `merge-and-notify` Job 中注入 Google Drive 相關 Secrets：
  - `GDRIVE_SERVICE_ACCOUNT_KEY`
  - `GDRIVE_FOLDER_ID`（預設為 `1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a`）

### 4. [MODIFY] `requirements.txt`
* 加入官方輕量依賴套件：
  - `google-api-python-client>=2.100.0`
  - `google-auth>=2.23.0`
  - `google-auth-httplib2>=0.1.1`

### 5. [MODIFY] `操作手冊.md` 與 `台股分點爬蟲雲端排程設置指南.md`
* 補充 Google Cloud 服務帳戶建立 3 分鐘簡易指引與 GitHub Secrets 設定步驟。

---

## 📋 使用者前置作業 (Google Cloud Service Account 設定)

要讓 GitHub Actions 無人值守自動上傳至您的 Google Drive 資料夾，只需以下 3 步：

1. **建立 Google 服務帳戶 (Service Account)**：
   * 前往 [Google Cloud Console](https://console.cloud.google.com/) 啟用 `Google Drive API`。
   * 在「憑證 (Credentials)」建立一個**服務帳戶 (Service Account)**，並為其建立一組 **JSON 格式的金鑰**（下載該 JSON 檔案）。
2. **分享資料夾給服務帳戶**：
   * 複製該服務帳戶的 Email（格式如 `xxx@project-id.iam.gserviceaccount.com`）。
   * 開啟您的 [Google Drive 資料夾](https://drive.google.com/drive/folders/1L6f9jQx9phz_ZoVfDmBQViEVnoDHh_0a?usp=sharing)，點擊右上角「共用」，將該 Email 加入為 **「編輯者 (Editor)」**。
3. **在 GitHub Secrets 貼上金鑰**：
   * 前往 GitHub 倉庫 ➡️ **Settings** ➡️ **Secrets and variables** ➡️ **Actions**。
   * 新增 Secret `GDRIVE_SERVICE_ACCOUNT_KEY`，將下載的 JSON 金鑰全文貼上即可！

---

## 🧪 驗證計畫

1. **模組單元測試**：在 Local 透過 `gdrive_sync.py` 測試上傳測試檔案至 Google Drive。
2. **覆蓋性測試**：驗證同名檔案再次上傳時是否能正確就地更新版本。
3. **端到端整合測試**：在 `merge_shards.py` 模擬聚合後自動上傳與 Telegram 帶有 GDrive 連結的推播效果。
