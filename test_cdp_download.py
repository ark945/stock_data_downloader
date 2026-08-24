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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_cdp_download")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.run_cdp('Browser.setDownloadBehavior', behavior='allow', downloadPath=save_dir, eventsEnabled=True)

page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 1584, 1595, 6488
for code in ["1584", "1595", "6488"]:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except: pass

    # 1. 填寫代碼
    stk_input = page.ele("css:input.code")
    stk_input.input(code, clear=True, by_js=True)
    time.sleep(0.3)

    # 2. 點擊日報表查詢按鈕
    q_btn = page.ele("xpath://div[contains(@class,'formblock')]//button[contains(text(),'查詢')]") or page.ele("css:form.formblock button[type=submit]")
    if q_btn: q_btn.click(by_js=True)
    time.sleep(1.5)

    # 3. 點擊下載按鈕
    d_btn = page.ele('css:button[data-format="utf-8"]') or page.ele("xpath://button[contains(text(),'UTF-8')]")
    if d_btn:
        print(f"[{code}] 正在點擊下載按鈕...")
        d_btn.click(by_js=True)

    found_csv = None
    for _ in range(15):
        time.sleep(0.3)
        candidates = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
        if candidates:
            found_csv = candidates[0]
            break

    if found_csv:
        fsize = os.path.getsize(found_csv)
        print(f"[✓ 實體 CSV 下載成功] {code} 大小: {fsize} bytes")
    else:
        files = glob.glob(os.path.join(save_dir, "*"))
        print(f"[❌ 下載失敗] {code} 目錄內現有檔案:", [(os.path.basename(f), os.path.getsize(f)) for f in files])

page.quit()
