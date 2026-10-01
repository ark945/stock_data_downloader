# DGX SPARK：Cloudflare Tunnel + Zero Trust 全方位安全穿透實作指南
*(免開路由器 Port、免公網 IP、全防護連線 ComfyUI、LM Studio 與 RDP 遠端桌面)*

---

## 1. 架構優勢與安全防禦層級

利用你既有的網域（`ark945.ccwu.cc`），透過 **Cloudflare Tunnel（雲端穿透隧道）** 搭配 **Cloudflare Zero Trust（零信任安全架構）**，可以在完全不更改中華電信小烏龜與 Deco 防火牆的情況下，建構出銀行級的防護層：

```mermaid
graph TD
    subgraph 外部網路 (Internet)
        User[你的筆電 / 外部訪客]
        Bot[惡意掃描器 / 殭屍網路]
    end

    subgraph Cloudflare 邊緣防禦節點 (Edge)
        WAF[WAF 防火牆\n(阻擋高風險國家/惡意爬蟲)]
        Access[Zero Trust Access\n(Email PIN 碼 / Google SSO 驗證)]
    end

    subgraph 家中內網 (小烏龜 + Deco)
        TunnelDaemon[cloudflared 守護程序\n(僅主動對外連線，無對內開放 Port)]
        DGX[DGX SPARK 伺服器]
    end

    User -->|存取網址| WAF
    Bot -->|掃描探測| WAF
    WAF -->|攔截封鎖| Bot
    WAF -->|放行合法請求| Access
    Access -->|通過身分驗證| TunnelDaemon
    TunnelDaemon -->|內網本地轉發| DGX

    subgraph DGX 服務映射
        DGX --> S1[ComfyUI : 8188]
        DGX --> S2[LM Studio : 1234]
        DGX --> S3[XRDP 遠端桌面 : 3389]
    end
```

### 🛡️ 這套架構的五重安全防護：
1. **隱蔽本機 IP**：外界只看到 Cloudflare 的 Anycast 節點，家中的真實公網 IP 完全不洩漏。
2. **零連接埠暴露 (Zero Open Ports)**：小烏龜與 Deco 保持完全封閉，不對外開放任何 80、443、3389 埠。
3. **強制身份驗證門檻 (Zero Trust Access)**：在請求抵達 DGX 之前，訪客必須先在 Cloudflare 邊緣驗證 Email 動態碼或 Google 帳號。
4. **地理與機器人防禦 (WAF)**：直接在邊緣阻擋美國、歐洲等機房掃描器（你先前看到的 100 次探測會直接被消滅）。
5. **長連線傳輸優化**：支援 WebSocket（ComfyUI 畫圖進度）與大檔傳輸。

---

## 2. 第一階段：在 DGX 安裝與配置 `cloudflared`

### 2.1 安裝官方客戶端
在 DGX (Ubuntu) 終端機中執行：
```bash
# 下載官方 Debian/Ubuntu 套件
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb

# 安裝
sudo dpkg -i cloudflared.deb

# 驗證安裝
cloudflared --version
```

### 2.2 透過 Cloudflare 網頁介面建立 Tunnel（最直覺推薦）
1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/)。
2. 點擊左側選單最下方的 **「Zero Trust」**（首次進入若需綁定免費方案，選 $0 免費版即可，支援 50 位使用者）。
3. 進入 Zero Trust 後台後，點擊左側 **「Networks」➔ 「Tunnels」**。
4. 點擊 **「Add a tunnel」**（或 Create a tunnel）：
   * 選擇 **Cloudflared** ➔ 點擊 **Next**。
   * 輸入 Tunnel 名稱（例如：`dgx-spark`）➔ 點擊 **Save tunnel**。
5. **安裝並啟動 Connector**：
   * 在頁面中選擇 **Debian / 64-bit**。
   * 網頁會給出一行包含專屬 Token 的安裝指令，類似：
     ```bash
     sudo cloudflared service install eyJhIjoiXXXXXX...
     ```
   * 將該完整指令複製並在 DGX 終端機執行。
   * 執行完畢後，網頁下方會立即顯示 **Status: HEALTHY**（綠燈），代表連線成功！

---

## 3. 第二階段：設定子網域與服務映射 (Public Hostname)

在剛才建立好的 Tunnel 頁面中，切換到 **「Public Hostname」** 分頁，依序新增以下三個服務：

### ① 映射 ComfyUI
* **Subdomain**：`comfy`
* **Domain**：選擇 `ark945.ccwu.cc`
* **Type**：`HTTP`
* **URL**：`localhost:8188`
* **Additional application settings (展開進階設定)**：
  * 點開 **HTTP Settings** ➔ 開啟 **No TLS Verify**（選用）。
  * *(備註：Cloudflare 預設已開啟 WebSocket 支援，可正常顯示即時出圖進度)*

### ② 映射 LM Studio (Qwen 27B)
* **Subdomain**：`ai`（或 `qwen`）
* **Domain**：選擇 `ark945.ccwu.cc`
* **Type**：`HTTP`
* **URL**：`localhost:1234`

### ③ 映射 Terminal Service (RDP 遠端桌面)
* **Subdomain**：`rdp`
* **Domain**：選擇 `ark945.ccwu.cc`
* **Type**：`RDP`（或 `TCP`）
* **URL**：`localhost:3389`

---

## 4. 第三階段：核心安全機制設定 (必做！)

若沒有設置安全機制，將網域名稱直接對外，依然會讓 ComfyUI 曝露於危險之中。請務必完成以下三道防線：

### 防線一：開啟 Zero Trust 應用程式身分驗證 (Access Application)

這能讓訪客在看到 ComfyUI 或登入畫面之前，必須先輸入一次性 Email 驗證碼：

1. 在 Zero Trust 後台，點擊左側 **「Access」➔ 「Applications」**。
2. 點擊 **「Add an application」** ➔ 選擇 **Self-hosted**。
3. **Application Configuration**：
   * Application name：`ComfyUI Secure Access`
   * Session Duration：設定 Cookie 有效期（例如：`24 Hours`，代表 24 小時內驗證一次即可）。
   * Application domain：輸入 `comfy` . `ark945.ccwu.cc`。
4. 點擊 **Next** 進入 **Policies (策略設定)**：
   * Policy name：`Allow-My-Email`
   * Action：選擇 `Allow`。
   * **Configure rules (設定規則)**：
     * Selector：選擇 **Emails**。
     * Value：輸入你的個人電子郵件地址（例如 `your_name@gmail.com`）。
5. 點擊 **Next** ➔ **Save application**。

> **效果測試**：現在用手機或筆電無痕視窗打開 `https://comfy.ark945.ccwu.cc`，會先跳出 Cloudflare 驗證頁面，輸入你的 Email 並填寫收到的 6 位數 PIN 碼後，才會顯示 ComfyUI 畫面！公網上的任何掃描機器人都會在此處被完全阻擋！

---

### 防線二：WAF 地理位置阻擋（封鎖境外惡意掃描）

如果你只會在台灣境內使用，可以直接阻擋台灣以外的所有請求：

1. 回到 Cloudflare 主儀表板（非 Zero Trust）➔ 點選 `ark945.ccwu.cc` 網域。
2. 點選左側 **「安全性 (Security)」➔ 「WAF」➔ 「自訂規則 (Custom Rules)」**。
3. 點擊 **「建立規則 (Create rule)」**：
   * 規則名稱：`Block Non-Taiwan Traffic`
   * 條件（運算式）：
     * 欄位：`國家/地區 (Country)`
     * 運算子：`不等於 (does not equal)`
     * 值：`台灣 (Taiwan)`
   * 採取動作：選擇 **`受控盤查 (Managed Challenge)`**（出驗證碼）或 **`封鎖 (Block)`**。
4. 點擊 **部署 (Deploy)**。
* **效果**：所有來自美國、俄羅斯、巴西的 IDC 自動化機房爬蟲，在連線第一步就會被 Cloudflare 邊緣直接丟棄！

---

### 防線三：開啟 Bot Fight Mode (機器人戰鬥模式)

1. 在網域主儀表板左側，點擊 **「安全性 (Security)」➔ 「Bots (機器人)」**。
2. 將 **「Bot Fight Mode (機器人戰鬥模式)」** 開關切換為 **開啟 (ON)**。
3. Cloudflare 會利用全球威脅情報庫，自動偵測並攔截惡意探測工具（如 sqlmap、nikto、特定爬蟲）。

---

## 5. 第四階段：外網筆電如何連線各服務？

### 1. 存取 ComfyUI (免安裝任何軟體)
* 直接用外網筆電瀏覽器打開：`https://comfy.ark945.ccwu.cc`。
* 輸入 Email 取得一次性驗證碼登入。
* 登入後即可直接產生圖片、加載工作流，體驗與本機無異。

---

### 2. 外部程式調用 LM Studio API (Qwen 27B)
如果是外部的 Python 程式、VS Code 外掛或聊天客戶端需要直接連線 LM Studio，因無法進行瀏覽器 Email 驗證，有兩種安全解法：

#### 方法 A：使用 Service Token (推薦)
1. 在 Zero Trust 後台 ➔ **Access** ➔ **Service Credentials** ➔ 建立一個 **Service Token**（命名為 `Python-API-Token`）。
2. 系統會產生一組 `Client ID` 與 `Client Secret`（請妥善保存）。
3. 在 Access Application 中為 `ai.ark945.ccwu.cc` 新增一條 Policy：Action 選 `Non-identity`，Selector 選 `Service Token`。
4. 在外部 Python 呼叫時帶上自訂 Header 即可安全穿透：
   ```python
   from openai import OpenAI

   client = OpenAI(
       base_url="https://ai.ark945.ccwu.cc/v1",
       api_key="lm-studio",
       default_headers={
           "CF-Access-Client-Id": "你的_CLIENT_ID.access",
           "CF-Access-Client-Secret": "你的_CLIENT_SECRET"
       }
   )

   response = client.chat.completions.create(
       model="qwen",
       messages=[{"role": "user", "content": "你好！"}]
   )
   print(response.choices[0].message.content)
   ```

---

### 3. 外網筆電連線 Terminal Service (RDP 3389)
因為 RDP 是二進位 TCP 協定，瀏覽器無法直接渲染，必須透過筆電端的 `cloudflared` 建立安全轉發：

1. **筆電端下載 cloudflared**：
   * 前往 [Cloudflare 官方下載](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) 下載 Windows 版 `cloudflared.exe`。
2. **在筆電啟動本地 RDP 監聽**：
   開啟 PowerShell，執行：
   ```powershell
   .\cloudflared.exe access rdp --hostname rdp.ark945.ccwu.cc --url localhost:3389
   ```
   *(指令執行後，它會自動彈出瀏覽器要求你進行 Email 身分驗證)*
3. **開啟 Windows 遠端桌面**：
   * 按下 `Win + R` ➔ 輸入 `mstsc`。
   * 電腦名稱輸入：`localhost:3389`。
   * 點選連線，即可透過 Cloudflare 加密通道登入 DGX 的桌面！

---

## 6. 方案對比：何時用 Cloudflare？何時用 Tailscale？

| 比較項目 | Cloudflare Tunnel + Zero Trust | Tailscale 專網 |
| :--- | :--- | :--- |
| **連線 ComfyUI** | **極致便利**（任何裝置打開瀏覽器就能用） | 需先在裝置安裝登入 Tailscale |
| **遠端桌面 (RDP)** | 筆電需執行 `cloudflared access` 命令 | **最順暢**（直接開 mstsc 打 IP 即可） |
| **安全認證層** | 擁有 Email OTP、Google 登入、WAF 地理封鎖 | 依賴 Tailscale 帳號權限 |
| **防爬蟲與掃描** | **極強**（全球節點在邊緣直接擋掉所有雜訊） | 不在公網公開，直接隱形 |
| **適合對象** | 分享給朋友、免客戶端網頁作業、標準 API 呼叫 | 自己外出開發、VS Code 遠端寫碼、高頻 RDP 操作 |

> **最佳實踐建議**：
> 平時自己工作開發推薦使用 **Tailscale** 直連 RDP 與模型 API（速度最直接）；
> 若要用平板、公司電腦或出門在外快速開網頁跑 **ComfyUI**，使用 **Cloudflare Tunnel + Zero Trust** 體驗最棒且最安全！
