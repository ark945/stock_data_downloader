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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_perfect_final")
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

    # 1. 確保在 BrokerBS 頁面
    if "brokerBS.html" not in page.url:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)

    # 2. 填寫代碼
    stk_input = page.ele("css:input.code")
    stk_input.input(code, clear=True, by_js=True)
    time.sleep(0.3)

    # 3. 精準點擊 form 內部的 submit 查詢按鈕 (絕不點到 title 或 header)
    q_btn = page.ele('xpath://form//button[@type="submit"]') or page.ele("css:form.formblock button[type=submit]")
    if q_btn:
        q_btn.click(by_js=True)

    # 4. 等待查詢完成 (表格渲染)
    time.sleep(1.2)

    # 5. 精準點擊 UTF-8 下載按鈕
    d_btn = page.ele('css:button[data-format="utf-8"]') or page.ele("xpath://button[contains(text(),'UTF-8')]")
    if d_btn:
        d_btn.click(by_js=True)
        found = False
        for _ in range(15):
            time.sleep(0.4)
            csvs = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 100]
            if csvs:
                fsize = os.path.getsize(csvs[0])
                print(f"[✓ 成功] {code} 下載完成！檔案: {os.path.basename(csvs[0])} 大小: {fsize} bytes (非 0B)")
                sys.stdout.flush()
                results[code] = fsize
                found = True
                break
        if not found:
            print(f"[❌ 失敗] {code} 下載超時或為 0B")
            sys.stdout.flush()
            results[code] = 0

page.quit()
print("\n==========================================")
print("測試總結:", results)
print("==========================================")
