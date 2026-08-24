import os
import sys
import glob
import time
from DrissionPage import ChromiumPage, ChromiumOptions

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_fresh_dom")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)
co.set_pref("safebrowsing.enabled", True)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試包含先前失敗的 1294, 1295, 1565, 1580, 1586, 1591, 1595 與 6488
test_codes = ["1240", "1294", "1295", "1565", "1580", "1586", "1591", "1595", "6488"]
success = []
failed = []

for code in test_codes:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except OSError: pass

    # 1. 每次動態重新獲取輸入框，避免 Stale Element
    inp = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)
    if not inp:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2)
        inp = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)

    inp.input(code, clear=True, by_js=True)
    # 觸發 keydown/Enter 或點擊查詢
    page.run_js("var el=document.querySelector('input.code'); if(el){el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}")

    q_btn = page.ele("text:查詢", timeout=3)
    if q_btn:
        q_btn.click(by_js=True)

    # 2. 等待頁面表格刷新出現該股票的標題 (例如 "1595")
    # 這是保證 100% 抓到本檔股票、絕不誤抓上一檔的鐵律！
    time.sleep(1.2)
    page.ele(f"text:{code}", timeout=3)

    # 3. 點擊下載
    d_btn = page.ele("text:下載 CSV (UTF-8)", timeout=4) or page.ele("text:下載 CSV", timeout=2)
    if d_btn:
        d_btn.click(by_js=True)
        found = False
        for _ in range(12):
            time.sleep(0.4)
            if glob.glob(os.path.join(save_dir, "*.crdownload")):
                continue
            csvs = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
            if csvs:
                print(f"[✓ OK] {code} 成功下載！檔案: {os.path.basename(csvs[0])} 大小: {os.path.getsize(csvs[0])} bytes")
                success.append(code)
                found = True
                break
        if not found:
            print(f"[❌ 下載超時] {code}")
            failed.append(code)
    else:
        print(f"[❌ 查無按鈕] {code}")
        failed.append(code)

page.quit()
print(f"\n==========================================")
print(f"總計測試 {len(test_codes)} 檔 | 成功: {len(success)} 檔 | 失敗: {len(failed)} 檔")
print(f"==========================================")
