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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_true_query")
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

    # 1. 確保在 BrokerBS 頁面
    if "brokerBS.html" not in page.url:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)

    stk_input = page.ele("css:form.formblock input.code", timeout=5) or page.ele("css:input.code", timeout=5)
    stk_input.input(code, clear=True, by_js=True)
    page.run_js("var el=document.querySelector('input.code'); if(el){el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}")

    # 2. 真正的日報表查詢按鈕 (form.formblock 內部的 submit 按鈕，絕不帶 btn-search)
    q_btn = page.ele("css:form.formblock button[type=submit]", timeout=3)
    if q_btn:
        q_btn.click(by_js=True)

    # 3. 等待下載按鈕 (UTF-8)
    time.sleep(1.2)
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
