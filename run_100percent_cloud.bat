@echo off
REM 激進 100% 爬蟲 - 一鍵雲端啟動 + 實時監控
REM Windows 批處理指令碼

setlocal enabledelayedexpansion

set REPO=ark945/stock_data_downloader
set WORKFLOW=aggressive-100percent-crawler.yml

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║                                                           ║
echo ║     🔴 激進 100%% 成功率爬蟲 - 雲端一鍵啟動                ║
echo ║                                                           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM 檢查 GitHub CLI
echo [1/3] 檢查 GitHub CLI...
where gh >nul 2>&1
if errorlevel 1 (
    echo ❌ GitHub CLI 未安裝
    echo.
    echo 請先安裝 GitHub CLI: https://cli.github.com/
    echo 或執行: choco install gh
    echo.
    pause
    exit /b 1
)
echo ✅ GitHub CLI 已安裝

REM 檢查認証
echo.
echo [2/3] 檢查 GitHub 認証...
gh auth status >nul 2>&1
if errorlevel 1 (
    echo ⚠️  未認証，正在啟動登入...
    call gh auth login
)
echo ✅ 已認証

REM 觸發工作流
echo.
echo [3/3] 觸發工作流...
echo.
echo 📢 執行命令:
echo gh workflow run %WORKFLOW% ^
echo   -R %REPO% ^
echo   -f target_date="" ^
echo   -f num_shards="1" ^
echo   -f enable_notifications="true"
echo.

call gh workflow run %WORKFLOW% ^
  -R %REPO% ^
  -f "target_date=" ^
  -f "num_shards=1" ^
  -f "enable_notifications=true"

if errorlevel 1 (
    echo.
    echo ❌ 工作流觸發失敗！
    pause
    exit /b 1
)

echo.
echo ✅ 工作流已成功提交到雲端！
echo.
echo ═══════════════════════════════════════════════════════════
echo 🎯 下一步：啟動實時監控
echo ═══════════════════════════════════════════════════════════
echo.
echo 即將啟動監控指令碼...
echo 按任意鍵繼續...
pause

REM 啟動監控
echo.
echo [監控中...] 🔄 實時追蹤爬蟲執行進度
echo.

python cloud_monitor.py ^
  --repo %REPO% ^
  --workflow %WORKFLOW% ^
  --check-interval 30 ^
  --max-duration 7200 ^
  --download-logs

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║         🎉 激進 100%% 爬蟲執行流程已完成！              ║
echo ║                                                           ║
echo ║   日誌已下載到本地: workflow_run_*.log                 ║
echo ║   請查看 GitHub Artifacts 獲取詳細結果                  ║
echo ║                                                           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
echo 打開 GitHub Actions: https://github.com/%REPO%/actions
echo.

pause
