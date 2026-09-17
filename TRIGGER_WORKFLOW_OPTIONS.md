╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║     🔴 激進 100% 爬蟲 - 工作流觸發指南                         ║
║                                                                ║
║              【選擇您最方便的啟動方式】                        ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝


## 🎯 三種啟動方式對比

| 方式 | 難度 | 自動監控 | 推薦度 |
|-----|------|---------|--------|
| **方式 A: GitHub Web UI** | ⭐ 最簡單 | ❌ 需手動 | ⭐⭐⭐⭐ |
| **方式 B: GitHub CLI (gh)** | ⭐⭐ 中等 | ✅ 自動 | ⭐⭐⭐⭐⭐ |
| **方式 C: REST API + curl** | ⭐⭐⭐ 複雜 | ✅ 自動 | ⭐⭐⭐ |

---

## ✨ 推薦：方式 A - GitHub Web UI (最簡單)

### 第 1 步：打開 GitHub Actions

瀏覽器打開：
```
https://github.com/ark945/stock_data_downloader/actions
```

### 第 2 步：找到工作流

在左側欄位找到：
```
🔴 激進 100% 成功率爬蟲 (實時監控)
  [aggressive-100percent-crawler.yml]
```

點擊進去。

### 第 3 步：觸發執行

點擊右上角的 **"Run workflow"** 按鈕

### 第 4 步：設定參數

會彈出表單，填入：

| 參數 | 值 | 說明 |
|-----|-----|------|
| `target_date` | **(留空)** | 自動使用今日日期 |
| `num_shards` | **1** | 單機模式（推薦） |
| `enable_notifications` | **true** | 啟用通知 |

### 第 5 步：確認啟動

點擊 **"Run workflow"** 綠色按鈕

### 第 6 步：實時監控

工作流會立即列在頁面頂部，點擊進去可看到即時日誌：

```
🔴 激進 100% 成功率爬蟲 (實時監控)
├─ Queued (1-2 分鐘)
├─ Pre-check (1 分鐘)
├─ Run crawler (30-70 分鐘)
└─ Finalize (1 分鐘)
```

---

## 🔧 進階：方式 B - GitHub CLI (自動監控)

### 前置條件

已安裝 GitHub CLI：
```powershell
gh --version
```

如果沒有，安裝：
```powershell
choco install gh
# 或
# winget install GitHub.cli
```

### 第 1 步：登入 GitHub

```powershell
gh auth login

# 選擇:
# ? What account do you want to log into? GitHub.com
# ? What is your preferred protocol for Git operations over HTTPS? HTTPS
# ? Authenticate Git with your GitHub credentials? Yes
# ? How would you like to authenticate GitHub CLI? Login with a web browser
```

### 第 2 步：觸發工作流

**方式 B1 - 自動化腳本（推薦）**

```powershell
cd D:\MyProject\stock_data_downloader
.\run_100percent_cloud.bat

# 腳本會自動:
# ✅ 檢查 GitHub CLI
# ✅ 驗證認証
# ✅ 觸發工作流
# ✅ 啟動實時監控
```

**方式 B2 - 手動 CLI 命令**

```powershell
gh workflow run aggressive-100percent-crawler.yml `
  -R ark945/stock_data_downloader `
  -f "target_date=" `
  -f "num_shards=1" `
  -f "enable_notifications=true"

# 回應:
# ✓ Created workflow_dispatch event
```

### 第 3 步：查詢執行狀態

```powershell
# 列出最新執行
gh run list -R ark945/stock_data_downloader -w aggressive-100percent-crawler.yml -L 1

# 輸出例：
# STATUS  CONCLUSION  WORKFLOW                                  ID           ACTOR     BRANCH
# completed  success     🔴 激進 100% 成功率爬蟲 (實時監控)  12345678901  ark945    main
```

### 第 4 步：即時日誌

```powershell
# 查看完整日誌
gh run view 12345678901 -R ark945/stock_data_downloader --log

# 或打開 Web 版
gh run view 12345678901 -R ark945/stock_data_downloader --web
```

### 第 5 步：下載結果

```powershell
# 列出所有 artifacts
gh run download 12345678901 -R ark945/stock_data_downloader -D results/

# 您將得到:
# results/
# ├─ crawler-logs-100percent/
# │  └─ crawler_output.log
# ├─ crawler-output-100percent/output/
# │  └─ api_absr1_YYYY-MM-DD_*.parquet  ⭐
# └─ execution-report/
```

---

## 💻 複雜：方式 C - REST API + curl

### 前置條件

需要 **GitHub Personal Access Token**：

1. 打開 https://github.com/settings/tokens/new
2. 點擊 **"Personal access tokens" → "Tokens (classic)"**
3. 點擊 **"Generate new token" → "Generate new token (classic)"**
4. 填入：
   - **Note**: `TWSE Crawler Token`
   - **Expiration**: 90 days
   - **Scopes**: 勾選 `workflow` (包含 `repo` 等)
5. 複製生成的 token (只會顯示一次！)

### 第 1 步：設定 Token 環境變數

```powershell
$env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

或永久設定（需要重啟）：
```powershell
[Environment]::SetEnvironmentVariable("GITHUB_TOKEN", "ghp_xxx", "User")
```

### 第 2 步：觸發工作流

```powershell
$owner = "ark945"
$repo = "stock_data_downloader"
$workflow = "aggressive-100percent-crawler.yml"
$token = $env:GITHUB_TOKEN

$headers = @{
    "Authorization" = "Bearer $token"
    "Accept" = "application/vnd.github.v3+json"
    "Content-Type" = "application/json"
}

$body = @{
    ref = "main"
    inputs = @{
        target_date = ""
        num_shards = "1"
        enable_notifications = "true"
    }
} | ConvertTo-Json

curl -X POST `
  "https://api.github.com/repos/$owner/$repo/actions/workflows/$workflow/dispatches" `
  -H "Authorization: Bearer $token" `
  -H "Accept: application/vnd.github.v3+json" `
  -d $body

# 成功回應: HTTP 204 No Content
```

### 第 3 步：查詢執行

```powershell
# 列出執行
curl -s -H "Authorization: Bearer $token" `
  "https://api.github.com/repos/$owner/$repo/actions/runs" | ConvertFrom-Json

# 獲取最新執行 ID
$runs = curl -s -H "Authorization: Bearer $token" `
  "https://api.github.com/repos/$owner/$repo/actions/runs" | ConvertFrom-Json

$latest_run_id = $runs.workflow_runs[0].id
Write-Host "最新執行 ID: $latest_run_id"
```

### 第 4 步：監控進度

```powershell
# 輪詢執行狀態
while ($true) {
    $run = curl -s -H "Authorization: Bearer $token" `
      "https://api.github.com/repos/$owner/$repo/actions/runs/$latest_run_id" | ConvertFrom-Json
    
    $status = $run.status          # queued, in_progress, completed
    $conclusion = $run.conclusion  # success, failure, cancelled
    $elapsed = (New-TimeSpan -Start $run.created_at -End ([DateTime]::Now)).TotalSeconds
    
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 狀態: $status | 結論: $conclusion | 耗時: $($elapsed)s"
    
    if ($status -eq "completed") {
        Write-Host "✅ 執行完成！"
        break
    }
    
    Start-Sleep -Seconds 30
}
```

### 第 5 步：下載日誌

```powershell
# 獲取 artifacts
curl -s -H "Authorization: Bearer $token" `
  "https://api.github.com/repos/$owner/$repo/actions/runs/$latest_run_id/artifacts" | ConvertFrom-Json | Select-Object -ExpandProperty artifacts
```

---

## 📊 完整工作流 - 推薦流程

```
【方式 A - 最簡單】
1. 打開 GitHub Actions 頁面
2. 找到工作流，點 "Run workflow"
3. 選擇參數，點 "Run workflow"
4. 實時看日誌
5. 完成後下載 Artifacts

【方式 B - 最推薦】(自動監控)
1. 執行: .\run_100percent_cloud.bat
2. 批處理自動處理一切
3. 監控窗口實時顯示進度
4. 完成時自動下載日誌

【方式 C - 最強大】(API 自動化)
1. 設定 GITHUB_TOKEN 環境變數
2. 執行 curl 命令觸發
3. 執行監控腳本跟蹤
4. 解析 JSON 結果
```

---

## 🎯 立即開始

### 最快開始（<1 分鐘）

🔗 打開並按指示操作：
```
https://github.com/ark945/stock_data_downloader/actions
    ↓
點擊 "🔴 激進 100% 成功率爬蟲 (實時監控)"
    ↓
點擊 "Run workflow"
    ↓
設定參數，點 "Run workflow"
```

### 自動啟動（1-2 分鐘）

💻 執行批處理：
```powershell
cd D:\MyProject\stock_data_downloader
.\run_100percent_cloud.bat
```

---

## ⚠️ 常見問題

### Q: 我不知道 Personal Access Token？

**A**: 用 **方式 A (Web UI)** 或 **方式 B (GitHub CLI)**，都不需要！

只有 **方式 C (REST API)** 才需要 token。

### Q: 工作流頁面找不到？

**A**: 確認以下任意一項：

1. **方式 A**: 直接打開 https://github.com/ark945/stock_data_downloader/actions
2. **方式 B**: 執行 `gh workflow list -R ark945/stock_data_downloader`
3. **方式 C**: 查詢 API: `curl https://api.github.com/repos/ark945/stock_data_downloader/actions/workflows`

### Q: 批處理說「認証失敗」？

**A**: 執行 `gh auth login` 先登入 GitHub：

```powershell
gh auth login
# 選擇 GitHub.com
# 選擇 HTTPS
# 選擇 "Login with a web browser"
# 瀏覽器會打開，輸入代碼並授權
```

### Q: 我想要最自動化的方式？

**A**: 推薦 **方式 B (GitHub CLI)**：

```powershell
.\run_100percent_cloud.bat
# 一個命令搞定所有事！
```

---

## 🚀 選擇您的方式

**我只想最快開始？**
→ 打開瀏覽器，方式 A

**我想要自動監控？**
→ 執行批處理，方式 B

**我想用代碼自動化？**
→ 設定 token，方式 C

---

**選好方式後，立即開始！**

預期完成時間: 30-70 分鐘
成功率目標: 100% ✅
