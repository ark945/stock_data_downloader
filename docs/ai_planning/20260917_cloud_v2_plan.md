# 全新雲端 GitHub Actions 爬蟲排程 (v2) 架構規劃與設計書

## 1. 核心準則
- **舊程式與現有排程不動**：
  - 舊版 `daily_stock_crawler.yml` 保持原樣不變。
  - 舊版 `twse_bsr_crawler.py` 與 `stock_crawler_coordinator.py` 保持原樣不變。
- **全新獨立架構**：
  - 以實測 100% 成功的 `twse_crawler_v2.py` 為核心，打造全新 `.github/workflows/daily_stock_crawler_v2.yml`。

---

## 2. 雲端 V2 架構圖

```
[GitHub Actions 觸發 (Webhook / 手動 / 排程)]
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│  Stage 1: pre-check (營業日判定 + Google Drive 查重)     │
└──────────────────────┬─────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
┌──────────────────┐       ┌──────────────────┐
│  close-price     │       │  tpex-shards     │
│  (每日收盤行情)   │       │  (上櫃 8-Runner)  │
└──────────────────┘       └─────────┬────────┘
                                     │
         ┌───────────────────────────┤
         ▼                           │
┌──────────────────────────────────┐ │
│  twse-shards (全新 v2 分片矩陣)   │ │
│  - 4 個 Runner 分片 (各 315 檔)   │ │
│  - 採用 twse_crawler_v2.py       │ │
│  - 具備 ViewState 加密簽章補齊   │ │
│  - 單線程防禦 + Circuit Breaker   │ │
│  - 各節點 6~7 分鐘穩健跑完       │ │
└────────────────┬─────────────────┘ │
                 │                   │
                 ▼                   ▼
┌──────────────────┐       ┌──────────────────┐
│  merge-twse      │       │  merge-tpex      │
│  (合併上市分片)   │       │  (合併上櫃分片)   │
└────────────────┬─┘       └─────────┬────────┘
                 │                   │
                 └─────────┬─────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Stage 4: merge-all (全市場母表整合 + 上傳 Google Drive)  │
│  - 產出標準 api_absr1_{DATE}_{DATE}.parquet             │
│  - 發送 Telegram / LINE 推播通知與採集摘要              │
└────────────────────────────────────────────────────────┘
```

---

## 3. 雲端 V2 核心優化項目

1. **分片精簡（從 6 Runner 精簡至 4 Runner）**：
   - 舊版因為容易有 403 限流或缺按鈕，需要 6 個以上 Runner 反覆重試。
   - v2 具備 `__VIEWSTATEENCRYPTED` 補齊與 Circuit Breaker 冷卻保護，單節點成功率達 100%。
   - 4 個 Runner 平均分配 1,263 檔（每台約 315 檔），各跑單線程僅需 **6～7 分鐘**，可節省 GitHub Actions 33% 運算時間。
2. **`twse_crawler_v2.py` 原生支援分片參數**：
   - 新增 `--shard-id` 與 `--num-shards`。
   - 支援 `--output-shard` 產出 `api_absr1_{DATE}_{DATE}_twse_shard_{ID}.parquet`。
3. **專屬輕量分片合併器 `merge_twse_v2_shards.py`**：
   - 負責收集各分片 Artifacts，以 `symbol + broker_id` 聯集合併並導出上市總表。
4. **全市場總表與雲端備份**：
   - 產檔標準與既有格式 100% 相容，Google Drive 上傳與 Telegram 推播介面完全無縫接軌。
