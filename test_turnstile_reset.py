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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_turnstile_reset")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

test_codes = ["1584", "1595", "6488", "1294"]
for code in test_codes:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except: pass

    # 1. 檢查並刷新 Turnstile Token
    token = page.run_js("return document.querySelector('[name=cf-turnstile-response]') ? document.querySelector('[name=cf-turnstile-response]').value : '';")
    print(f"[{code}] 當前 Turnstile Token 長度: {len(token)}")
    if not token:
        page.run_js("if (typeof turnstile !== 'undefined') { turnstile.reset(); }")
        time.sleep(1.5)
        token = page.run_js("return document.querySelector('[name=cf-turnstile-response]') ? document.querySelector('[name=cf-turnstile-response]').value : '';")
        print(f"[{code}] 重置後 Turnstile Token 長度: {len(token)}")

    # 2. 填寫代碼
    stk_input = page.ele("css:input.code")
    stk_input.input(code, clear=True, by_js=True)
    time.sleep(0.3)

    # 3. 點擊查詢
    q_btn = page.ele("css:form.formblock button[type=submit]") or page.ele("xpath://form//button[@type='submit']")
    if q_btn: q_btn.click(by_js=True)
    time.sleep(1.5)

    # 4. 點擊下載 CSV
    d_btn = page.ele('css:button[data-format="utf-8"]')
    if d_btn: d_btn.click(by_js=True)

    found_csv = None
    for _ in range(12):
        time.sleep(0.3)
        candidates = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
        if candidates:
            found_csv = candidates[0]
            break

    if found_csv:
        print(f"[✓ 成功下載 CSV] {code} 大小: {os.path.getsize(found_csv)} bytes")
        try: os.remove(found_csv)
        except: pass
    else:
        print(f"[❌ 下載失敗/0B] {code}")

page.quit()
