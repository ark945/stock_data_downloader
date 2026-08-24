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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_debug_0b")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 1584 與 1595
for code in ["1584", "1595"]:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except: pass

    stk_input = page.ele("css:input.code")
    stk_input.input(code, clear=True, by_js=True)
    time.sleep(0.5)

    # 點擊查詢
    q_btn = page.ele("text:查詢")
    if q_btn:
        q_btn.click()
    time.sleep(2.0)

    # 點擊下載
    d_btn = page.ele("text:下載 CSV (UTF-8)")
    if d_btn:
        d_btn.click()
    time.sleep(2.0)

    files = glob.glob(os.path.join(save_dir, "*"))
    print(f"[{code}] 下載目錄檔案清單:", [(os.path.basename(f), os.path.getsize(f)) for f in files])

page.quit()
