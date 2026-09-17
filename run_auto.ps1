# ============================================================================
# 激進 100% 爬蟲 - 完全自動化執行器
# 說明: 只需提供 GitHub token，即可全自動觸發 + 監控
# ============================================================================

param(
    [string]$GithubToken = "",
    [string]$Repo = "ark945/stock_data_downloader",
    [string]$Workflow = "aggressive-100percent-crawler.yml"
)

# 顏色定義
function Write-Title {
    param([string]$Text)
    Write-Host ""
    Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║ $($Text.PadRight(62)) ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Text, [int]$Step, [int]$Total)
    Write-Host "[第 $Step/$Total 步] $Text" -ForegroundColor Green
}

# 主程式
Write-Title "🔴 激進 100% 爬蟲 - 完全自動化執行器"

# 步驟 1: 取得 GitHub Token
Write-Step "取得 GitHub Token" 1 4

if (-not $GithubToken) {
    if ($env:GITHUB_TOKEN) {
        $GithubToken = $env:GITHUB_TOKEN
        Write-Host "✓ 從環境變數取得 token" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "❌ 未找到 GitHub Token" -ForegroundColor Red
        Write-Host ""
        Write-Host "【解決方案】" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "1. 建立 Personal Access Token:" -ForegroundColor Cyan
        Write-Host "   打開: https://github.com/settings/tokens/new" -ForegroundColor Gray
        Write-Host "   選擇 scopes: ✓ workflow (包含 repo)" -ForegroundColor Gray
        Write-Host "   複製生成的 token (格式: ghp_...)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "2. 設定環境變數:" -ForegroundColor Cyan
        Write-Host '   $env:GITHUB_TOKEN = "ghp_your_token_here"' -ForegroundColor Gray
        Write-Host ""
        Write-Host "3. 重新執行此指令碼:" -ForegroundColor Cyan
        Write-Host "   .\run_auto.ps1" -ForegroundColor Gray
        Write-Host ""
        exit 1
    }
}

Write-Host "✓ Token 已設定 (前 10 字元: $($GithubToken.Substring(0, 10))...)" -ForegroundColor Green

# 步驟 2: 觸發工作流
Write-Step "觸發工作流" 2 4

$apiUrl = "https://api.github.com/repos/$Repo/actions/workflows/$Workflow/dispatches"
$headers = @{
    "Authorization" = "Bearer $GithubToken"
    "Accept" = "application/vnd.github.v3+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$body = @{
    ref = "main"
    inputs = @{
        target_date = ""
        num_shards = "1"
        enable_notifications = "true"
    }
} | ConvertTo-Json

Write-Host "發送請求到: $apiUrl" -ForegroundColor Gray

try {
    $response = Invoke-WebRequest -Uri $apiUrl -Method POST -Headers $headers -Body $body -ErrorAction Stop
    Write-Host "✓ 工作流已成功觸發！" -ForegroundColor Green
    Write-Host "  HTTP 狀態: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "❌ 觸發失敗: $_" -ForegroundColor Red
    exit 1
}

# 步驟 3: 取得最新執行 ID
Write-Step "取得工作流執行 ID" 3 4

Start-Sleep -Seconds 3
$runsUrl = "https://api.github.com/repos/$Repo/actions/workflows/$Workflow/runs?per_page=1&status=queued,in_progress"
$headers_get = @{
    "Authorization" = "Bearer $GithubToken"
    "Accept" = "application/vnd.github.v3+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

try {
    $runsResponse = Invoke-WebRequest -Uri $runsUrl -Method GET -Headers $headers_get -ErrorAction Stop
    $runsData = $runsResponse.Content | ConvertFrom-Json
    
    if ($runsData.workflow_runs.Count -gt 0) {
        $latestRun = $runsData.workflow_runs[0]
        $runId = $latestRun.id
        Write-Host "✓ 找到執行: ID = $runId" -ForegroundColor Green
        Write-Host "  狀態: $($latestRun.status)" -ForegroundColor Green
    } else {
        Write-Host "⚠ 未找到執行，等待 5 秒後重試..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        $runsResponse = Invoke-WebRequest -Uri $runsUrl -Method GET -Headers $headers_get -ErrorAction Stop
        $runsData = $runsResponse.Content | ConvertFrom-Json
        $latestRun = $runsData.workflow_runs[0]
        $runId = $latestRun.id
    }
} catch {
    Write-Host "❌ 取得執行 ID 失敗: $_" -ForegroundColor Red
    exit 1
}

# 步驟 4: 實時監控
Write-Step "實時監控工作流執行" 4 4
Write-Host "執行 ID: $runId" -ForegroundColor Gray
Write-Host "檢查間隔: 30 秒" -ForegroundColor Gray
Write-Host "最大監控: 2 小時" -ForegroundColor Gray
Write-Host ""

$startTime = Get-Date
$maxDuration = 7200
$lastStatus = $null

while ($true) {
    $elapsed = (Get-Date) - $startTime
    
    if ($elapsed.TotalSeconds -gt $maxDuration) {
        Write-Host ""
        Write-Host "⏰ 超過最大監控時間" -ForegroundColor Yellow
        break
    }
    
    try {
        $detailUrl = "https://api.github.com/repos/$Repo/actions/runs/$runId"
        $detailResponse = Invoke-WebRequest -Uri $detailUrl -Method GET -Headers $headers_get -ErrorAction Stop
        $detail = $detailResponse.Content | ConvertFrom-Json
        
        $status = $detail.status
        $conclusion = $detail.conclusion
        
        if ($status -ne $lastStatus) {
            $lastStatus = $status
            
            if ($status -eq "queued") {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⏳ 狀態: 排隊中" -ForegroundColor Yellow
            } elseif ($status -eq "in_progress") {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 🔄 狀態: 執行中" -ForegroundColor Green
            } elseif ($status -eq "completed") {
                Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ✅ 狀態: 完成" -ForegroundColor Green
                Write-Host "  結論: $conclusion" -ForegroundColor Green
                
                $totalTime = New-TimeSpan -Start $startTime -End (Get-Date)
                Write-Host ""
                Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Green
                Write-Host "✅ 激進 100% 爬蟲執行完成！" -ForegroundColor Green
                Write-Host "  耗時: $($totalTime.Hours)h $($totalTime.Minutes)m $($totalTime.Seconds)s" -ForegroundColor Green
                Write-Host "  結論: $conclusion" -ForegroundColor Green
                Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Green
                Write-Host ""
                Write-Host "檢查結果: https://github.com/$Repo/actions/runs/$runId" -ForegroundColor Cyan
                break
            }
        }
        
        if ($status -eq "in_progress") {
            $elapsedMin = [math]::Floor($elapsed.TotalSeconds / 60)
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 🔄 執行中 (已耗時 +$elapsedMin 分鐘)" -ForegroundColor Green
        }
    } catch {
        # 忽略暫時錯誤
    }
    
    Start-Sleep -Seconds 30
}

Write-Host ""
Write-Host "監控已完成。" -ForegroundColor Cyan
