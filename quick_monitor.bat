@echo off
REM ============================================================================
REM 激進 100% 爬蟲 - 網頁觸發 + 自動監控完整流程
REM ============================================================================

setlocal enabledelayedexpansion

cls
echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                                                               ║
echo ║     🚀 激進 100%% 爬蟲 - 快速啟動監控                         ║
echo ║                                                               ║
echo ║              【您在網頁觸發後，執行此腳本】                   ║
echo ║                                                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.
echo.

REM 檢查 GitHub CLI
echo [檢查] GitHub CLI...
where gh >nul 2>&1
if errorlevel 1 (
    echo ❌ GitHub CLI 未安裝！
    echo.
    echo 請先安裝: https://cli.github.com/
    echo 或執行: choco install gh
    echo.
    pause
    exit /b 1
)
echo ✓ GitHub CLI 已安裝
echo.

REM 主選單
echo ════════════════════════════════════════════════════════════════
echo.
echo 【步驟】
echo.
echo 第 1 步：在網頁觸發工作流
echo   打開: https://github.com/ark945/stock_data_downloader/actions
echo   點擊: "🔴 激進 100%% 成功率爬蟲 (實時監控)"
echo   按: "Run workflow" 按鈕
echo.
echo 第 2 步：工作流已提交後，執行此腳本監控進度
echo.
echo ════════════════════════════════════════════════════════════════
echo.

:menu
echo.
echo 選擇操作:
echo.
echo [1] 🚀 啟動實時監控 (推薦)
echo [2] 🔗 打開 GitHub Actions 頁面
echo [3] ❌ 退出
echo.
set /p choice="輸入選擇 (1/2/3): "

if "%choice%"=="1" (
    echo.
    echo [啟動監控...] 🔄
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File monitor_live.ps1 -CheckInterval 30 -MaxDuration 7200 -DownloadLogs
    goto menu
)
else if "%choice%"=="2" (
    echo.
    echo 打開 GitHub Actions 頁面...
    start https://github.com/ark945/stock_data_downloader/actions
    timeout /t 2
    goto menu
)
else if "%choice%"=="3" (
    echo.
    echo 再見！
    exit /b 0
)
else (
    echo 無效的選擇，請重試。
    goto menu
)
