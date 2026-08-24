import os
import sys
import glob
import time
from DrissionPage import ChromiumPage, ChromiumOptions

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_net_sniff")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 1584
inp = page.ele("css:input.code")
inp.input("1584", clear=True, by_js=True)
time.sleep(0.3)

# 透過現代標準 requestSubmit 觸發查詢 (100% 執行事件且不跳頁)
page.run_js("""
    var el = document.querySelector('input.code');
    if (el && el.form) {
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        if (typeof el.form.requestSubmit === 'function') {
            el.form.requestSubmit();
        } else {
            el.form.dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}));
        }
    }
""")
time.sleep(2.0)

print("是否渲染出 1584:", bool(page.ele("text:1584")))
print("是否渲染出成交筆數:", bool(page.ele("text:成交筆數")))

# 點擊下載
d_btn = page.ele("xpath://button[contains(text(),'UTF-8')]") or page.ele("text:下載 CSV (UTF-8)")
print("下載按鈕 text:", d_btn.text if d_btn else "None")
if d_btn:
    d_btn.click(by_js=True)

time.sleep(2.0)
files = glob.glob(os.path.join(save_dir, "*"))
print("下載目錄檔案:", [(os.path.basename(f), os.path.getsize(f)) for f in files])

page.quit()
