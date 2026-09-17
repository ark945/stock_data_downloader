# ============================================================================
# 激進 100% 爬蟲 - 實時監控腳本 (PowerShell 版)
# 說明: 工作流觸發後，執行此腳本自動監控進度
# ============================================================================

param(
    [int]$CheckInterval = 30,      # 檢查間隔 (秒)
    [int]$MaxDuration = 7200,      # 最大監控時間 (秒) = 2 小時
    [switch]$DownloadLogs = $true  # 完成後下載日誌
)

$REPO = "ark945/stock_data_downloader"
$WORKFLOW = "aggressive-100percent-crawler.yml"

Write-Host @"
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║     🔴 激進 100% 爬蟲 - 實時監控 (PowerShell)                 ║
║                                                                ║
║               【盯著進度直到完成】                             ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝

倉庫: $REPO
工作流: $WORKFLOW
檢查間隔: $CheckInterval 秒
最大監控: $MaxDuration 秒 (~$($MaxDuration/60) 分鐘)
下載日誌: $DownloadLogs

開始時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

══════════════════════════════════════════════════════════════════

" -ForegroundColor Cyan

# 獲取最新工作流執行
function Get-LatestWorkflowRun {
    try {
        $runs = gh run list -R $REPO -w $WORKFLOW -L 1 --json status,conclusion,number,createdAt,url --no-headers 2>$null
        
        if (-not $runs) {
            return $null
        }
        
        # 解析 JSON
        $runData = $runs | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($runData -is [array]) {
            return $runData[0]
        }
        return $runData
    }
    catch {
        return $null
    }
}

# 取得工作流詳細訊息
function Get-WorkflowStatus {
    param([int]$RunNumber)
    
    try {
        $run = gh run view $RunNumber -R $REPO --json status,conclusion,jobs --json-args 2>$null
        return $run | ConvertFrom-Json -ErrorAction SilentlyContinue
    }
    catch {
        return $null
    }
}

# 監控迴圈
$startTime = Get-Date
$lastStatus = $null
$runNumber = $null
$foundRun = $false

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 🔍 尋找最新工作流執行..." -ForegroundColor Cyan

while ($true) {
    $elapsed = (Get-Date) - $startTime
    
    if ($elapsed.TotalSeconds -gt $MaxDuration) {
        Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] ⏰ 超過最大監控時間 ($($MaxDuration/60) 分鐘)" -ForegroundColor Yellow
        break
    }
    
    # 獲取最新執行
    $run = Get-LatestWorkflowRun
    
    if ($run) {
        if (-not $foundRun) {
            $runNumber = $run.number
            $foundRun = $true
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ✅ 找到工作流執行: #$runNumber" -ForegroundColor Green
            Write-Host "  URL: $($run.url)" -ForegroundColor Cyan
        }
        
        $currentStatus = $run.status
        $conclusion = $run.conclusion
        
        # 狀態變化時輸出
        if ($currentStatus -ne $lastStatus) {
            $lastStatus = $currentStatus
            
            switch ($currentStatus) {
                "queued" {
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⏳ 狀態: 排隊中..." -ForegroundColor Yellow
                }
                "in_progress" {
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 🔄 狀態: 執行中..." -ForegroundColor Green
                }
                "completed" {
                    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ✅ 狀態: 完成！" -ForegroundColor Green
                    Write-Host "  結論: $conclusion" -ForegroundColor Cyan
                    
                    # 下載日誌
                    if ($DownloadLogs -and $conclusion -eq "success") {
                        Write-Host "`n[$(Get-Date -Format 'HH:mm:ss')] 📥 下載日誌中..." -ForegroundColor Cyan
                        
                        $artifactDir = "workflow_artifacts_$($runNumber)_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
                        New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
                        
                        try {
                            gh run download $runNumber -R $REPO -D $artifactDir
                            Write-Host "  ✓ 日誌已下載到: $artifactDir" -ForegroundColor Green
                            Write-Host "  內容:" -ForegroundColor Cyan
                            Get-ChildItem $artifactDir -Recurse | ForEach-Object {
                                Write-Host "    - $($_.FullName)" -ForegroundColor Gray
                            }
                        }
                        catch {
                            Write-Host "  ⚠ 日誌下載失敗: $_" -ForegroundColor Yellow
                        }
                    }
                    
                    $totalTime = New-TimeSpan -Start $startTime -End (Get-Date)
                    Write-Host "`n════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
                    Write-Host "✅ 監控完成！" -ForegroundColor Green
                    Write-Host "  總耗時: $($totalTime.Hours)h $($totalTime.Minutes)m $($totalTime.Seconds)s" -ForegroundColor Green
                    Write-Host "  查看詳細: $($run.url)" -ForegroundColor Cyan
                    Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
                    
                    exit 0
                }
            }
        }
        
        # 持續顯示進度
        if ($currentStatus -eq "in_progress") {
            $elapsedMin = [math]::Floor($elapsed.TotalSeconds / 60)
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 🔄 執行中... (+$elapsedMin 分鐘)" -ForegroundColor Green
        }
        elseif ($currentStatus -eq "queued") {
            $elapsedSec = [math]::Floor($elapsed.TotalSeconds)
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⏳ 等待中... (+$elapsedSec 秒)" -ForegroundColor Yellow
        }
    }
    else {
        if ($foundRun) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ⚠️  無法取得工作流狀態" -ForegroundColor Yellow
        }
    }
    
    # 等待後重新檢查
    Start-Sleep -Seconds $CheckInterval
}

Write-Host "`n監控已停止。" -ForegroundColor Yellow
