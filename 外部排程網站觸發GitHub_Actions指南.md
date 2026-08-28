# 🌐 外部定時排程網站觸發 GitHub Actions 完整設定指南 (秒級精準定時)

本指南專門用於解決 GitHub 內建 `schedule (cron)` 偶發的**隊列延遲**與**排程丟包**問題。透過免費、穩定、精確到秒級的外部定時排程服務（如 **Cron-job.org**），在指定時間直接呼叫 GitHub REST API 觸發工作流程！

---

## 📌 目錄
1. [前置準備：建立 GitHub 個人存取權杖 (PAT Token)](#1-前置準備建立-github-個人存取權杖-pat-token)
2. [推薦服務首選：Cron-job.org 設定教學 (100% 免費永久支援)](#2-推薦服務首選cron-joborg-設定教學-100-免費永久支援)
3. [GitHub Actions API 參數與 Payload 規格](#3-github-actions-api-參數與-payload-規格)
4. [雙專案 Webhook 呼叫配置範例](#4-雙專案-webhook-呼叫配置範例)
   - [4.1 台股分點爬蟲專案 (stock_data_downloader)](#41-台股分點爬蟲專案-stock_data_downloader)
   - [4.2 主力重押日報專案 (stock_data_analysis)](#42-主力重押日報專案-stock_data_analysis)
5. [常見錯誤與除錯排解 (FAQ)](#5-常見錯誤與除錯排解-faq)

---

## 1. 前置準備：建立 GitHub 個人存取權杖 (PAT Token)

外部排程網站需要一組具有觸發 Actions 權限的 GitHub Token：

1. 登入 GitHub，點擊右上角個人頭像 ➔ **Settings**。
2. 滾動至左側最下方，點擊 **Developer settings** ➔ **Personal access tokens** ➔ **Tokens (classic)**。
3. 點擊 **Generate new token (classic)**。
4. 設定項目：
   - **Note (名稱)**：`Cronjob-Trigger-Action`
   - **Expiration (有效期限)**：建議選擇 `No expiration`（無期限）或自訂長效期。
   - **Select scopes (權限勾選)**：
     - ✅ **`repo`**（若為私有庫）或至少勾選 ✅ **`workflow`**（更新與觸發 GitHub Actions 工作流程）。
5. 點擊頁面最下方綠色 **Generate token** 按鈕。
6. 📋 **複製並妥善保存 Token**（格式如 `ghp_xxxxxxxxxxxxxxxxxxxx`，離開頁面後將無法再次查看）。

---

## 2. 推薦服務首選：Cron-job.org 設定教學 (100% 免費永久支援)

[Cron-job.org](https://cron-job.org/en/) 是全球最老牌且功能最完整的免費排程網站，支援秒級定時、自訂 HTTP Headers、POST JSON Body 與失敗告警。

### 步驟一：註冊與建立 Cronjob
1. 前往 [Cron-job.org 註冊帳號](https://cron-job.org/en/signup/) 並登入。
2. 進入 Dashboard 點擊 **`Create Cronjob`**。

### 步驟二：基本設定 (Basic Settings)
* **Title (名稱)**：`台股爬蟲盤後自動定時觸發`
* **URL**：
  ```
  https://api.github.com/repos/ark945/stock_data_downloader/actions/workflows/daily_stock_crawler.yml/dispatches
  ```
  *(若為分析專案請參閱第 4 節的對應網址)*
* **Execution Schedule (排程時間)**：
  - **時區 (Timezone)**：選擇 `Asia/Taipei` (台灣時區)
  - **頻率**：選擇 `User-defined` 或自訂時間（例如每週一至週五 下午 `17:35` 或清晨 `05:31`）

### 步驟三：請求進階設定 (Advanced / Request Method)
點開下方 **Advanced** 或 **Request** 設定區：

1. **Request Method**：選擇 **`POST`**
2. **Request Headers (自訂標頭，務必設定 4 條)**：
   | Header Key (名稱) | Header Value (值) |
   | :--- | :--- |
   | `Accept` | `application/vnd.github+json` |
   | `Authorization` | `Bearer ghp_你的GitHub經典Token` |
   | `X-GitHub-Api-Version` | `2022-11-28` |
   | `User-Agent` | `CronJob-Trigger-Bot` |

3. **Request Body (請求內容)**：
   - 選擇 **`Raw data`** 或 **`JSON`**：
   ```json
   {
     "ref": "main",
     "inputs": {
       "target_date": "",
       "market": "all"
     }
   }
   ```

### 步驟四：儲存與測試
* 點擊 **`Create`** 儲存。
* 儲存後可點擊該任務右側的 **`Test run`（立即測試）**：
  - 若回傳 **`HTTP 204 No Content`** ➔ 表示**成功連線並已觸發 GitHub Actions 執行**！

---

## 3. GitHub Actions API 參數與 Payload 規格

GitHub `dispatches` 規範定義如下：

```http
POST /repos/{owner}/{repo}/actions/workflows/{workflow_id_or_file}/dispatches HTTP/1.1
Host: api.github.com
Accept: application/vnd.github+json
Authorization: Bearer ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
X-GitHub-Api-Version: 2022-11-28
User-Agent: CronJob-Trigger-Bot
Content-Type: application/json

{
  "ref": "main",
  "inputs": {
    "參數名稱": "參數值"
  }
}
```

---

## 4. 雙專案 Webhook 呼叫配置範例

### 4.1 台股分點爬蟲專案 (`stock_data_downloader`)

* **目標工作流程檔案**：`daily_stock_crawler.yml`
* **請求網址 (URL)**：
  ```
  https://api.github.com/repos/ark945/stock_data_downloader/actions/workflows/daily_stock_crawler.yml/dispatches
  ```
* **建議觸發時間 (台灣時間)**：
  - **主要採集**：每週一至週五 **17:35**
  - **備援補抓**：每週二至週六 **05:31**
* **Request Body**：
  ```json
  {
    "ref": "main",
    "inputs": {
      "target_date": "",
      "market": "all"
    }
  }
  ```

---

### 4.2 主力重押日報專案 (`stock_data_analysis`)

* **目標工作流程檔案**：`daily_heavy_accumulation_report.yml`
* **請求網址 (URL)**：
  ```
  https://api.github.com/repos/ark945/stock_data_analysis/actions/workflows/daily_heavy_accumulation_report.yml/dispatches
  ```
* **建議觸發時間 (台灣時間)**：
  - 每週一至週五 **20:05**
* **Request Body**：
  ```json
  {
    "ref": "main"
  }
  ```

---

## 5. 常見錯誤與除錯排解 (FAQ)

### Q1: 測試時收到 `404 Not Found` 錯誤？
> **原因與對策**：
> 1. Token 權限不足：請確認 PAT Token 有勾選 `repo`（私有庫必備）或 `workflow`。
> 2. 儲存庫名稱或 workflow 檔名拼錯：請檢查 URL 中的 `ark945`、專案名稱與 `.yml` 檔名是否大小寫完全一致。

### Q2: 測試時收到 `401 Unauthorized` 錯誤？
> **原因與對策**：
> 1. Token 填寫錯誤或已過期：請檢查 Header 中的 `Authorization: Bearer ghp_...` 是否有多餘空格或缺少 `Bearer ` 前綴。

### Q3: 測試時收到 `422 Unprocessable Entity` 錯誤？
> **原因與對策**：
> 1. 找不到分支：請確認 Request Body 中的 `"ref": "main"` 分支名稱是否正確。
> 2. YAML 未開啟手動觸發：請確認該 Workflow 的 `.yml` 內有宣告 `workflow_dispatch:` 觸發器。

### Q4: 收到 `204 No Content` 代表什麼？
> **解答**：這是 **100% 成功的標準代碼**！GitHub API 接收到工作流程啟動命令後固定回傳 HTTP 204，此時回到 GitHub 儲存庫的 Actions 頁面即可看到任務已即時啟動！
