import os
import sys
import glob
import time
from DrissionPage import ChromiumPage, ChromiumOptions

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_pure_csv")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 10 檔股票
test_codes = ["6488", "1584", "1595", "1240", "1259", "1264", "1268", "1294", "1295", "1336"]
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

    # 3. 點擊查詢按鈕
    q_btn = page.ele("css:form.formblock button[type=submit]") or page.ele("xpath://form//button[@type='submit']")
    if q_btn:
        q_btn.click(by_js=True)

    # 4. 等待查詢完成 (表格渲染出該代碼)
    time.sleep(1.2)

    # 5. 點擊 [下載 CSV (UTF-8)] 按鈕
    d_btn = page.ele('css:button[data-format="utf-8"]') or page.ele("xpath://button[contains(text(),'UTF-8')]")
    if d_btn:
        d_btn.click(by_js=True)

        found_csv = None
        for _ in range(15):
            time.sleep(0.3)
            if glob.glob(os.path.join(save_dir, "*.crdownload")):
                continue
            candidates = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
            if candidates:
                found_csv = candidates[0]
                break

        if found_csv:
            fsize = os.path.getsize(found_csv)
            with open(found_csv, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            print(f"[✓ CSV 下載成功] {code} 大小: {fsize} bytes, 檔案行數: {len(lines)} 行 (全量數據)")
            results[code] = len(lines)
            try: os.remove(found_csv)
            except: pass
        else:
            # 檢查是否為無成交股票
            has_table = bool(page.ele("css:table tbody tr"))
            if not has_table:
                print(f"[無成交/無資料] {code}")
                results[code] = "無成交"
            else:
                print(f"[❌ 下載失敗/0B] {code}")
                results[code] = 0

page.quit()
print("\n==========================================")
print("純 CSV 下載測試總結:", results)
print("==========================================")
