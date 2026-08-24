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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_form_scope")
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

    # 1. 確保在 BrokerBS 頁面 (若誤跳頁則自動導回)
    if "brokerBS.html" not in page.url:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)

    stk_input = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)
    if not stk_input:
        page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
        time.sleep(2.5)
        stk_input = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)

    stk_input.input(code, clear=True, by_js=True)
    page.run_js("var el=document.querySelector('input.code'); if(el){el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}")

    # 2. 嚴格限縮在 input.code 所在的同一個 form 表單內尋找查詢按鈕 (絕不點到頂部全站搜尋！)
    form_ele = stk_input.parent("tag:form")
    q_btn = form_ele.ele("css:button.btn-search") if form_ele else None
    if not q_btn:
        q_btn = page.ele("css:form.page-form button.btn-search")

    if q_btn:
        q_btn.click(by_js=True)

    # 等待資料表格渲染
    time.sleep(1.3)
    page.ele(f"text:{code}", timeout=3)

    # 3. 點擊下載按鈕
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
                print(f"[✓ OK] {code} 成功下載！檔案: {os.path.basename(csvs[0])} 大小: {os.path.getsize(csvs[0])} bytes (目前網址: {page.url[:45]}...)")
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
