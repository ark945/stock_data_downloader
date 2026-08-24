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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_js_click")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)
co.set_pref("safebrowsing.enabled", True)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

test_codes = ["1240", "1259", "1264", "1268", "1294", "1295", "1336", "1565", "1595", "6488"]
success = []
failed = []

for code in test_codes:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except OSError: pass

    # 確保在 BrokerBS 頁面
    if "brokerBS.html" not in page.url:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)

    # 1. 填寫代碼並透過 JS 原生 closest 觸發查詢 (100% 物理隔絕頂部全站搜尋)
    stk_input = page.ele("css:input.code", timeout=5)
    stk_input.input(code, clear=True, by_js=True)
    page.run_js("""
        var input = document.querySelector('input.code');
        if (input) {
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
            var form = input.closest('form');
            if (form) {
                var btn = form.querySelector('button');
                if (btn) btn.click();
            }
        }
    """)

    # 2. 等待頁面資料刷新
    time.sleep(1.3)
    page.ele(f"text:{code}", timeout=3)

    # 3. 點擊下載按鈕
    d_btn = page.ele("text:下載 CSV (UTF-8)", timeout=4) or page.ele("text:下載 CSV", timeout=2) or page.ele("css:button.response", timeout=2)
    if d_btn:
        d_btn.click(by_js=True)
        found = False
        for _ in range(12):
            time.sleep(0.4)
            if glob.glob(os.path.join(save_dir, "*.crdownload")):
                continue
            csvs = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
            if csvs:
                print(f"[✓ OK] {code} 成功下載！大小: {os.path.getsize(csvs[0])} bytes (網址: {page.url})")
                sys.stdout.flush()
                success.append(code)
                found = True
                break
        if not found:
            print(f"[❌ 下載超時] {code}")
            sys.stdout.flush()
            failed.append(code)
    else:
        print(f"[❌ 查無按鈕] {code} (當前網址: {page.url})")
        sys.stdout.flush()
        failed.append(code)

page.quit()
print(f"\n==========================================")
print(f"總計測試 {len(test_codes)} 檔 | 成功: {len(success)} 檔 | 失敗: {len(failed)} 檔")
print(f"==========================================")
