# 🔐 GitHub Repository Secrets 申請與配置完整指南

本指南詳細說明專案在 **GitHub Actions 雲端自動化排程** 中所使用的 7 項機密環境變數（Repository Secrets）之申請管道、取得步驟與設定方法。

---

## 📌 Secrets 總覽清單

| Secret 名稱 | 所屬功能模組 | 說明 | 申請管道與來源 |
| :--- | :--- | :--- | :--- |
| **`GDRIVE_FOLDER_ID`** | 雲端備份 | Google Drive 存放 Parquet 資料庫的目標資料夾 ID | Google Drive 資料夾網址列 |
| **`GDRIVE_SERVICE_ACCOUNT_KEY`** | 雲端備份 | Google Cloud 服務帳戶 (Service Account) 金鑰全文 | Google Cloud Console (JSON 檔) |
| **`SMTP_USER`** | 郵件推播 | 寄送日報的 Gmail 信箱 | 您的 Google 帳號 Email |
| **`SMTP_PASSWORD`** | 郵件推播 | Google 帳號之「應用程式密碼 (App Password)」 | Google 帳戶安全性設定 (16 位英文字) |
| **`RECEIVER_EMAIL`** | 郵件推播 | 接收 HTML 視覺化日報的電子信箱 | 您欲收信的 Email（可與寄件者相同） |
| **`TELEGRAM_BOT_TOKEN`** | 即時推播 | Telegram 機器人金鑰 (Bot API Token) | Telegram 官方 `@BotFather` |
| **`TELEGRAM_CHAT_ID`** | 即時推播 | 接收推播通知的使用者或群組 ID | Telegram 官方 `@userinfobot` |

---

## ☁️ 一、Google Drive 雲端備份模組

此模組負責在每日爬蟲聚合完成後，自動將 `api_absr1_*.parquet` 上傳至您的 Google Drive 資料夾。

### 1. `GDRIVE_FOLDER_ID`（Google Drive 資料夾 ID）
1. 開啟 [Google Drive (Google 雲端硬碟)](https://drive.google.com/)。
2. 建立或開啟您欲存放股票資料的資料夾（例如命名為 `台股分點資料庫`）。
3. 查看瀏覽器上方的網址列，網址格式如下：
   ```text
   https://drive.google.com/drive/folders/1a2B3c4D5e6F7g8H9i0J_kLmNoPqRsTuV
   ```
4. 複製 `folders/` 後方的**那串英數字母與符號**（例如 `1a2B3c4D5e6F7g8H9i0J_kLmNoPqRsTuV`）。
5. 這串 ID 即為 `GDRIVE_FOLDER_ID`。

---

### 2. `GDRIVE_SERVICE_ACCOUNT_KEY`（服務帳戶 JSON 金鑰）
GitHub Actions 需透過 Google Cloud 服務帳戶在無人值守環境下進行驗證。

#### Step 1: 建立 GCP 專案並啟用 API
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 建立一個新專案（例如命名為 `stock-downloader`）。
3. 在上方搜尋欄輸入 **`Google Drive API`** ➔ 點選並按 **「啟用 (Enable)」**。

#### Step 2: 建立服務帳戶 (Service Account)
1. 點擊左側選單 **「IAM 與管理 (IAM & Admin)」** ➔ **「服務帳戶 (Service Accounts)」**。
2. 點擊上方的 **「建立服務帳戶 (Create Service Account)」**。
3. 輸入服務帳戶名稱（例如 `gdrive-bot`），點擊「建立並繼續」➔ 點擊「完成」。
4. 建立完成後，列表會產生一組機器人 Email（例如 `gdrive-bot@stock-downloader-xxxxx.iam.gserviceaccount.com`），**請先將此 Email 複製備用**。

#### Step 3: 產生並下載 JSON 金鑰
1. 在服務帳戶列表中，點擊剛剛建立的帳戶進入詳細頁面。
2. 切換至 **「金鑰 (Keys)」** 頁籤 ➔ 點擊 **「新增金鑰 (Add Key)」** ➔ **「建立新金鑰 (Create new key)」**。
3. 選擇 **`JSON`** 格式並點擊「建立」，系統會自動下載一個 `.json` 檔案至電腦。
4. 使用純文字編輯器（記事本、VS Code）打開此 `.json` 檔案，**複製裡面的全部內容**（含前後 `{ }` 大括號）。
5. 將此 JSON 全文貼至 GitHub Secret 的 `GDRIVE_SERVICE_ACCOUNT_KEY`。

#### Step 4: 至 Google Drive 開放權限（⚠️ 關鍵步驟）
1. 回到 Google Drive，找到在第 1 步建立的資料夾。
2. 於該資料夾點選右鍵 ➔ **「共用 (Share)」**。
3. 在使用者欄位貼上 **Step 2 複製的服務帳戶 Email**（`...iam.gserviceaccount.com`）。
4. 權限務必設定為 **「編輯者 (Editor)」**。
5. 取消勾選「通知共用對象」，點擊「共用 / 傳送」儲存。

---

## 📧 二、SMTP Email 郵件推播模組

此模組負責每日採集完成後，發送 HTML 視覺化日報表（含涵蓋標的數、總資料列數、Parquet 檔案容量與 Google Drive 直連按鈕）。

### 1. `SMTP_USER`
* 填入您的 Gmail 電子信箱地址（例如 `your_account@gmail.com`）。

### 2. `SMTP_PASSWORD`（Gmail 16 位應用程式密碼）
> ⚠️ **注意**：不可使用一般的 Gmail 登入密碼，必須使用 Google 專屬產生的「應用程式密碼」。

1. 前往 [Google 帳戶安全性管理](https://myaccount.google.com/security)。
2. 確認 Google 帳戶已開啟 **「兩步驟驗證 (2-Step Verification)」**。
3. 在安全性頁面搜尋 **「應用程式密碼 (App passwords)」**。
4. 應用程式名稱輸入自訂名稱（例如 `Stock-Crawler`），點擊 **「建立 (Create)」**。
5. 畫面會顯示一組 **16 位英文字母密碼**（例如 `abcd efgh ijkl mnop`）。
6. 複製該組密碼（可去除空格），貼至 GitHub Secret 的 `SMTP_PASSWORD`。

### 3. `RECEIVER_EMAIL`
* 填入您要接收每日報表的電子信箱（可以與 `SMTP_USER` 相同，也可以是其他信箱）。

---

## 📱 三、Telegram 即時推播模組

此模組負責在採集聚合完成時，向您的手機 Telegram 即時發送採集成果與雲端硬碟直連下載按鈕。

### 1. `TELEGRAM_BOT_TOKEN`（機器人 Token）
1. 在 Telegram 搜尋官方機器人管理員 **`@BotFather`** 並啟動對話。
2. 發送指令 `/newbot`。
3. 依提示輸入機器人名稱（Name）與使用者名稱（Username，必須以 `bot` 結尾，例如 `tw_stock_data_bot`）。
4. 建立成功後，`@BotFather` 會回覆一串 HTTP API Token，格式如下：
   ```text
   1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456
   ```
5. 複製整串字元，貼至 GitHub Secret 的 `TELEGRAM_BOT_TOKEN`。
6. **記得在 Telegram 中搜尋您剛建立的機器人並點擊「START」發送任意訊息給它**。

---

### 2. `TELEGRAM_CHAT_ID`（個人/群組 Chat ID）
1. 在 Telegram 搜尋查詢 ID 的機器人 **`@userinfobot`**（或 `@getidsbot`）並啟動對話。
2. 它會立即回覆您的帳戶資訊，其中 **`Id`** 後方的純數字（例如 `123456789`）即為您的 Chat ID。
3. 複製該純數字，貼至 GitHub Secret 的 `TELEGRAM_CHAT_ID`。

> 💡 **若想推播至 Telegram 群組/頻道**：
> 1. 將您的機器人加入該群組。
> 2. 將 `@userinfobot` 或 `@RawDataBot` 加入群組即可查得群組 ID（群組 ID 通常為負數，例如 `-1001234567890`）。

---

## ⚙️ 四、如何將 Secrets 設定到 GitHub 專案中？

1. 開啟您的 GitHub 專案儲存庫頁面。
2. 點選上方頁籤 **`Settings` (專案設定)**。
3. 點選左側選單 **`Secrets and variables`** ➔ **`Actions`**。
4. 點擊綠色的 **`New repository secret`** 按鈕：
   * **Name**：輸入 Secret 名稱（例如 `GDRIVE_SERVICE_ACCOUNT_KEY`）。
   * **Secret**：貼入對應申請到的數值內容。
5. 點擊 **`Add secret`** 儲存。
6. 重複上述步驟依序新增所有 7 項變數即可。

---

## ✅ 五、驗證配置是否成功

全部設定完成後，您可以進行即時測試：
1. 進入 GitHub 專案的 **`Actions`** 頁籤。
2. 點選左側的 **「通知推播連線測試 (Telegram & Email)」** 或 **「每日全市場券商分點爬蟲排程」**。
3. 點擊右側的 **「Run workflow」** ➔ **「Run workflow」** 手動觸發。
4. 檢視工作流程執行日誌：
   * Telegram 收到通知 ➔ ✅ Telegram 配置正確
   * 信箱收到 HTML 報表 ➔ ✅ SMTP 配置正確
   * Google Drive 資料夾出現新 Parquet 檔案 ➔ ✅ Google Drive 配置正確
