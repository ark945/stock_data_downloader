# TPEX 券商買賣證券日報表 抓取工具

抓取臺灣證券櫃檯買賣中心（TPEX，上櫃市場）的**「券商買賣證券日報表」**資料，包含每檔股票當日各分點券商的買賣張數與成交金額。

資料來源頁面：<https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html>

---

## 為什麼要這麼複雜？

TPEX 這個頁面用 **Cloudflare Turnstile（invisible mode）** 保護：

- 每次點「查詢」都要一個**新鮮的 token** 塞進 POST 請求
- token 是 **一次性的**、幾秒就失效
- 純 `requests` / `curl_cffi` 打 API 會回 `{"stat":"操作逾時..."}`
- headless Playwright / patchright / nodriver **全部會被偵測擋掉**

經過大量測試，**只有 [DrissionPage](https://github.com/g1879/DrissionPage) 能穩定過**（用真實 Chrome fingerprint）。所以整個工具就是：

1. 用 DrissionPage 開一個真 Chrome（有頭）
2. 讓 Turnstile 自動過（幾秒鐘）
3. 用 JS 觸發「查詢」按鈕
4. 攔截瀏覽器對 API 的 POST 請求，讀回應 JSON

---

## 檔案結構

```
TPEX_DL/
├── crawl_all.py               # 【本機】批次爬 890 檔上櫃普通股（headed Chrome）
├── tpex_broker_bs.py          # 【本機】單/多檔抓取模組，可 CLI 也可 import
├── requirements.txt           # Python 依賴（DrissionPage）
├── ci/
│   ├── crawler.py             # 【CI】批次版，headless + --no-sandbox
│   └── fetch.py               # 【CI】單/多檔版，headless + --no-sandbox
├── data/
│   ├── otc_common_codes.json  # 890 檔上櫃普通股代號清單
│   ├── brokerBS/<YYYYMMDD>/*.json   # 每日抓下來的原始資料
│   ├── crawler_state_<YYYYMMDD>.json # 續跑用 state（已完成/失敗清單）
│   └── crawler_log_<YYYYMMDD>.log   # 執行 log
├── 05_fetch_stock_list.py     # 從 TWSE ISIN 服務更新股票清單
└── NOTES.md                   # 前置研究筆記（保留備查）
```

> **本機版**（`crawl_all.py` / `tpex_broker_bs.py`）：headed Chrome，會跳出瀏覽器視窗。
> **CI 版**（`ci/`）：headless，`--no-sandbox`，適合 GitHub Actions / Linux 容器。

---

## 安裝

```powershell
# Python 3.9+，Windows 需要有 Chrome 已安裝
cd d:\MyLab\TPEX_DL
pip install -r requirements.txt
```

---

## 使用方式（本機）

### 批次抓全部 890 檔

```powershell
python crawl_all.py           # 全部
python crawl_all.py 10        # 只跑前 10 檔（測試用）
```

特性：
- **可中斷續跑**：state 每檔立刻存 `data/crawler_state_<YYYYMMDD>.json`，Ctrl+C 後再執行同一指令會自動跳過已完成的
- **智慧復原**：
  - 連續 3 次失敗 → reload 頁面重取 token
  - 連續 6 次失敗 → 整個重開瀏覽器 + 冷卻 30 秒
  - 連續 20 次失敗 → 中止（避免白跑）
- 每檔完成後印 `[i/N] [OK] <code> (N 筆, 耗時s)`

執行時間：全 890 檔約 **1.5 小時**。

### 抓單一或少數幾檔

```powershell
# 存成 JSON 檔到 data/brokerBS/<今天>/
python tpex_broker_bs.py 1240
python tpex_broker_bs.py 1240 1259 1264

# 只印 JSON 到 stdout，不寫檔（可以 pipe 用）
python tpex_broker_bs.py 1240 --stdout

# 指定輸出資料夾
python tpex_broker_bs.py 1240 --out d:\tmp
```

### 當作 Python 模組 import

```python
from tpex_broker_bs import TPEXBrokerBSClient

# 用 with 保證瀏覽器會關掉
with TPEXBrokerBSClient() as client:
    data = client.fetch("1240")           # dict：完整 API JSON
    data2 = client.fetch("1259")          # 同一瀏覽器繼續抓，比較快
    print(len(data["tables"][1]["data"])) # 分點筆數
```

---

## 使用方式（GitHub Actions）

已附上 workflow：`.github/workflows/tpex_crawl.yml`

### 觸發方式

1. **手動觸發**（Actions 頁面點 "Run workflow"）
   - 空白 codes → 跑全 890 檔
   - 填 `1240 1259` → 只抓指定幾檔
2. **排程**：每個交易日台灣時間 16:30（收盤後）自動跑

### 運作原理

- runner 用 `ubuntu-latest`
- 安裝 Google Chrome + Xvfb 虛擬螢幕
- 在 Xvfb 下跑 CI 版 crawler，資料上傳為 **artifact**（保留 14 天）
- 若要把資料 commit 回 repo，取消 workflow 底部 commit step 的註解

### ⚠️ 已知風險

GitHub Actions 的 IP 段常被 Cloudflare 標為 datacenter，可能一開始就拿不到 Turnstile token。**第一次執行請手動觸發並填單一 code（例如 `1240`）驗證**，若拿得到就 OK，拿不到就要考慮：

- 換 **self-hosted runner**（用自家 IP）
- 加 residential proxy
- 放棄 CI 改用本機 Windows 排程

---

## 資料格式

單檔 JSON（例如 `data/brokerBS/20260825/1240.json`）：

```json
{
  "date": "1140825",
  "tables": [
    {
      "title": "個股資訊",
      "fields": ["股票代號", "股票名稱", "..."],
      "data": [["1240", "茂生農經", "..."]]
    },
    {
      "title": "券商買賣日報表（一般交易）",
      "fields": ["券商", "價格", "買進股數", "賣出股數", "..."],
      "data": [
        ["1020 元大", "27.05", "5000", "0", "..."],
        ...
      ],
      "total": {...}
    }
  ]
}
```

其中 `tables[1].data` 就是分點券商買賣明細。

---

## 常見問題

### Q: 為什麼失敗清單裡有些股票寫「該股票該日無交易資訊」？
A: 這些股票當日**停牌／暫停買賣**（除息、變更交易方式等），本來就沒有資料，不是抓取失敗。可以直接忽略。

### Q: 為什麼跑到一半突然全部失敗？
A: 大部分是 **IP rate limit**。程式會自動：
1. reload 頁面（改善 token）
2. 重開瀏覽器 + 冷卻 30 秒（改善 session）
3. 連續 20 次都不行就中止，避免白跑

再執行同一指令會從 state 續跑，通常隔 5~10 分鐘再跑就會恢復。

### Q: 要抓其他日期（不是今天）？
A: TPEX 這個 API 只提供**當日**資料，歷史資料要另外的端點。本工具只設計抓當日。

### Q: 也要抓上市（TWSE）？
A: 上市有 TWSE 自己的端點（無 Turnstile），較單純，本工具目前只做 TPEX 上櫃。

---

## 授權與注意事項

- 資料版權屬於 TPEX，僅供**個人研究學習**使用
- 請控制頻率，避免對 TPEX 網站造成負擔（程式已內建 2 秒間隔）
- 商業用途請購買 TPEX 授權
