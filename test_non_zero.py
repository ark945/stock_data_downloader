import os
import sys
import glob
import time
from DrissionPage import ChromiumPage, ChromiumOptions

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_real_data")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

test_codes = ["1294", "1295", "1565", "1584", "1595", "6488"]
results = {}

for code in test_codes:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except: pass

    # 1. 確保在主頁
    if "brokerBS.html" not in page.url:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)

    # 2. 輸入代碼
    stk_input = page.ele("css:input.code")
    stk_input.input(code, clear=True, by_js=True)
    time.sleep(0.3)

    # 3. 點擊查詢 (直接找 form 內的 submit 按鈕)
    q_btn = page.ele("css:form.formblock button[type=submit]") or page.ele("css:.searchset button[type=submit]")
    if not q_btn:
        q_btn = page.ele("text:查詢")
    if q_btn:
        q_btn.click(by_js=True)

    # 4. 等待查詢完成 (表格渲染出該代碼)
    time.sleep(1.2)

    # 5. 點擊下載
    d_btn = page.ele("css:button[data-format='utf-8']") or page.ele("text:下載 CSV (UTF-8)")
    if d_btn:
        d_btn.click(by_js=True)
        found = False
        for _ in range(12):
            time.sleep(0.4)
            csvs = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 100]
            if csvs:
                fsize = os.path.getsize(csvs[0])
                print(f"[✓ 成功] {code} 下載完成！大小: {fsize} bytes (非 0B)")
                results[code] = fsize
                found = True
                break
        if not found:
            print(f"[❌ 失敗] {code} 下載為 0B 或超時")
            results[code] = 0

page.quit()
print("\n測試總結:", results)
