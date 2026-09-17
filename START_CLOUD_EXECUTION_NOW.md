╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║     🔴 激進 100% 成功率爬蟲 - 雲端執行 + 實時監控             ║
║                                                                ║
║              【我盯著，直到 100% 成功】                        ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝


## 🎯 快速開始（2 分鐘）

### Windows 用戶：

```powershell
cd D:\MyProject\stock_data_downloader
.\run_100percent_cloud.bat
```

### Linux / Mac 用戶：

```bash
cd D:\MyProject\stock_data_downloader
chmod +x run_100percent_cloud.sh
./run_100percent_cloud.sh
```

### 發生了什麼？

1️⃣  **驗證 GitHub CLI** ✅
2️⃣  **檢查認証狀態** ✅
3️⃣  **觸發雲端工作流** ✅
4️⃣  **啟動實時監控** 🔄
5️⃣  **持續盯著直到完成** 👀

---

## 📊 實時監控畫面

當您執行上述指令後，會看到：

```
══════════════════════════════════════════════════════════════════
🔴 激進 100% 爬蟲 - 雲端實時監控
══════════════════════════════════════════════════════════════════
倉庫: ark945/stock_data_downloader
工作流: aggressive-100percent-crawler.yml
開始時間: 2026-09-17 21:15:00
══════════════════════════════════════════════════════════════════

[21:15:20] ⏳ 等待工作流啟動...
[21:15:50] ⏳ 等待工作流啟動...
[21:16:20] 🔄 【狀態更新】
  工作流: 🔴 激進 100% 成功率爬蟲 (實時監控)
  狀態: in_progress

[21:16:45] 🔄 執行中... (+1:45)
[21:17:15] 🔄 執行中... (+2:15)
[21:17:45] 🔄 執行中... (+2:45)
...
[21:45:30] 🔄 執行中... (+30:30)
...
[22:10:15] ✅ 工作流已完成
  總耗時: 55 分 15 秒
  結論: success

📊 查看詳細日誌:
  https://github.com/ark945/stock_data_downloader/actions/runs/XXXXX
```

---

## 🔄 幕後發生的事

### 雲端工作流階段

```
階段 1: 前置檢查 (1 分鐘)
   └─ 檢查是否為台股營業日
   
階段 2: 激進 100% 爬蟲執行 (30-60 分鐘)
   ├─ 第 1 輪:  標準 POST (0-20%)
   ├─ 第 2 輪:  重新驗證碼 (20-50%)
   ├─ 第 3 輪:  新會話 (50-70%)
   ├─ 第 4 輪:  直連下載 (70-80%)
   ├─ 第 5 輪:  強制新會話 (80-90%)
   ├─ 第 6 輪:  暴力延遲 (90-95%)
   ├─ 第 7 輪:  UA 輪轉 (95-98%)
   ├─ 第 8 輪:  終極策略 (98-99.5%)
   └─ 第 9 輪:  最後衝刺 (99.5%+)
   
階段 3: 結果匯總 (1 分鐘)
   ├─ 生成執行報告
   ├─ 發送 Telegram 通知
   └─ 上傳 Artifacts
```

### 本地監控做什麼

```
✅ 每 30 秒檢查一次工作流狀態
✅ 實時顯示進度 (排隊 → 執行中 → 完成)
✅ 完成時自動下載日誌
✅ 生成本地 workflow_run_*.log 文件
```

---

## 🎯 預期時間表

| 時間 | 狀態 | 進度 |
|-----|-----|------|
| T+0 | ⏳ 排隊 | GitHub 初始化 |
| T+2 | 🔄 執行中 | 首輪爬蟲啟動 (0%) |
| T+5 | 🔄 執行中 | 首輪完成 (20%) |
| T+10 | 🔄 執行中 | 第 2-3 輪 (50%) |
| T+20 | 🔄 執行中 | 第 4-5 輪 (70%) |
| T+30 | 🔄 執行中 | 第 6-7 輪 (90%) |
| T+45 | 🔄 執行中 | 第 8-9 輪 (95%+) |
| T+55-65 | ✅ 完成 | 最終成功 (100%) |

**總耗時**: 55-70 分鐘

---

## 📥 結果去哪裡了？

### 1. 本地日誌
```
workflow_run_<RUN_ID>.log  ← 自動下載到當前目錄
```

### 2. GitHub Artifacts (7 天保留)
```
https://github.com/ark945/stock_data_downloader/actions/runs/<RUN_ID>

下載:
  ├─ crawler-logs-100percent/
  │  ├─ crawler_output.log (主爬蟲日誌)
  │  ├─ logs/ (詳細日誌)
  │  └─ diagnostics/ (診斷數據)
  │
  ├─ crawler-output-100percent/output/
  │  ├─ api_absr1_YYYY-MM-DD_YYYY-MM-DD_twse.parquet ⭐
  │  └─ api_absr1_YYYY-MM-DD_YYYY-MM-DD_twse.xlsx
  │
  └─ execution-report/
     └─ report.md (執行報告)
```

### 3. Telegram 通知 (如已設定)
```
🎉 【激進 100% 爬蟲完成】

交易日期: 2026-09-17
模式: 🔴 激進 100% 無限重試
結果: ✅ 執行成功

詳細日誌已上傳到 GitHub Artifacts
```

### 4. Email 報告 (如已設定)
```
主旨: [TWSE 爬蟲] 2026-09-17 激進 100% 模式執行報告
內容: 成功率, 失敗分析, 下載連結
```

---

## ⚠️ 常見問題

### Q: 批處理檔案說需要登入？

**A**: 第一次運行時需要 GitHub 認証：
```powershell
# 自動彈出登入界面，按提示操作即可
# 或手動先登入：
gh auth login
```

### Q: 監控指令碼一直顯示「等待工作流啟動」？

**A**: 正常，通常需要 1-3 分鐘 GitHub 才會開始執行。如超過 5 分鐘：
```powershell
# 手動檢查工作流狀態
gh run list -R ark945/stock_data_downloader -w aggressive-100percent-crawler.yml -L 1
```

### Q: 執行超過 60 分鐘？

**A**: 正常。激進模式最後幾輪可能有 30s+ 延遲。您可以：
- 繼續等待（最多 2 小時自動超時）
- 按 `Ctrl+C` 中止監控（工作流會在雲端繼續執行）
- 手動查看 GitHub Actions 頁面跟進

### Q: 如何查看即時日誌？

**A**: 工作流執行期間，打開：
```
https://github.com/ark945/stock_data_downloader/actions
```
找到最新執行，點擊進去可看到即時日誌輸出。

### Q: 爬蟲失敗了怎麼辦？

**A**: 檢查下載的日誌：
```bash
# 查看錯誤
grep -i "error\|failed\|exception" workflow_run_*.log

# 檢查最後 100 行
tail -100 workflow_run_*.log
```

---

## 🔧 高級選項

### 自訂監控參數

如果想直接調用監控指令碼（不用批處理檔）：

```bash
# 每 60 秒檢查一次
python cloud_monitor.py --check-interval 60

# 設定 3 小時超時
python cloud_monitor.py --max-duration 10800

# 完成後自動下載日誌
python cloud_monitor.py --download-logs

# 綜合
python cloud_monitor.py \
  --check-interval 60 \
  --max-duration 10800 \
  --download-logs
```

### 手動觸發工作流

```powershell
# 如果批處理檔失敗，用 GitHub CLI 直接觸發
gh workflow run aggressive-100percent-crawler.yml `
  -R ark945/stock_data_downloader `
  -f "target_date=" `
  -f "num_shards=1" `
  -f "enable_notifications=true"
```

---

## 📋 執行清單

執行前：
- [ ] 確認有 GitHub CLI (`gh --version`)
- [ ] 已登入 GitHub (`gh auth status`)
- [ ] 網路連線正常
- [ ] 有 30-70 分鐘可用時間

執行中：
- [ ] 監控窗口保持打開
- [ ] 觀察進度條變化
- [ ] 記錄關鍵時刻 (50%, 80%, 95%, 100%)
- [ ] 確認狀態從「排隊」→「執行中」→「完成」

執行後：
- [ ] 驗證日誌下載成功
- [ ] 檢查 Parquet 檔案大小 (> 10 MB)
- [ ] 查看 GitHub Artifacts
- [ ] 驗證成功率 (目標 > 99%)

---

## 🎁 所有工具清單

| 工具 | 用途 | 位置 |
|-----|------|------|
| `run_100percent_cloud.bat` | Windows 一鍵啟動 | 項目根目錄 |
| `run_100percent_cloud.sh` | Linux/Mac 一鍵啟動 | 項目根目錄 |
| `cloud_monitor.py` | 實時監控指令碼 | 項目根目錄 |
| `aggressive-100percent-crawler.yml` | GitHub 工作流 | `.github/workflows/` |

---

## 🚀 準備好了嗎？

```
第 1 步：執行一鍵啟動
  Windows: .\run_100percent_cloud.bat
  Linux/Mac: ./run_100percent_cloud.sh

第 2 步：盯著監控窗口
  監控會每 30 秒檢查一次進度
  
第 3 步：等待完成 (30-70 分鐘)
  工作流會無限重試直到 100%
  
第 4 步：查看結果
  日誌: workflow_run_*.log
  數據: GitHub Artifacts
  報告: Email / Telegram 通知
```

---

## 🌟 預期成功標誌

當您看到這個，表示 100% 成功！

```
✅ 工作流已完成
  總耗時: 55 分 12 秒
  結論: success

📊 查看詳細日誌:
  https://github.com/ark945/stock_data_downloader/actions/runs/XXXXX
```

---

**讓我幫您盯著，直到達成 100%！** 👀

---

開始時間: 2026-09-17 21:15
預期完成: 2026-09-17 22:10 ~ 22:15
