# TPEX 雲端爬蟲 Turnstile 預熱致命崩潰修復規劃

## 1. 問題核心分析
在 GitHub Actions 執行 `TPEX-上櫃-分片-1` 時，發生整組 126 檔完全未採集即崩潰（Exit Code 1），致命原因如下：
1. **首頁預熱過度嚴苛**：
   `_launch_browser_session()` 強制要求在打開首頁後 45 秒內必須簽發長度 > 50 的 `initial_token`。但在 TPEX 官網架構下，首頁常態在未輸入股票代碼與未觸發查詢時，Turnstile 處於靜止或未簽發狀態。連續 3 次長度為 0 即拋出 `RuntimeError: 首頁 Turnstile 初始 Token 未取得`。
2. **頂層例外處理盲目冒泡**：
   在 `crawl_stocks` 頂層捕捉了 `except RuntimeError: raise`，直接將預熱例外拋至頂層，且 `stock_crawler_coordinator.py` 未做防禦兜底，導致整個分片 Process 瞬間 Crash（Exit Code 1）。
3. **單檔查詢本已自帶 Token 取得機制**：
   在 `crawl_stocks` 迴圈中，每檔股票在查詢前皆會呼叫 `self._wait_token`，若過期也會自動刷新與重試。首頁預熱階段強制中斷完全是多餘且致命的單點故障（Single Point of Failure）。

## 2. 修復策略
1. **改造 `_launch_browser_session()` 判定邏輯**：
   - 首頁 Session 啟動成功之標準改為「頁面成功載入，且表單結構（DOM）就緒（如 `input.code` 或 `form.formblock`）」。
   - 若成功取得 `initial_token`，正常記錄長度；若未取得，記錄 `[*] TPEX 首頁 Session 預熱就緒 (Token 將於單檔查詢時動態簽發)`，**安全返回 `(page, temp_user_data)`，嚴禁拋出 RuntimeError 中斷！**
   - 強化首頁載入時的 Turnstile 喚醒：主動滾動至表單區塊並模擬觸發事件，提高首頁即簽發 Token 的機率。
2. **優化 `_wait_token()` 提取韌性**：
   - 支援更多 Turnstile response 提取途徑（包含隱藏 input、Widget 回傳、DOM 屬性）。
   - 當連續未取得 Token 時，主動微滑動頁面或觸發一次點擊，協助 Cloudflare 互動偵測順暢通過。
3. **防禦性重構 `crawl_stocks` 與 `crawl_stocks_with_retry`**：
   - 移除頂層破壞性的 `except RuntimeError: raise`。
   - 遇到任何未預期例外時，妥善清理瀏覽器資源，將未處理股票安全標記至 `failed_symbols`，並保證回傳 `(collected_dfs, failed_symbols)`。
4. **`stock_crawler_coordinator.py` 增強兜底**：
   - 呼叫 `crawl_stocks_with_retry` 處增加例外捕捉，保證即使引擎有未捕獲錯誤也能優雅完成分片記錄並落盤已收集資料，而非整動 Crash。
