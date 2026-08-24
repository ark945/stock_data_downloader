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

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_batch_fix")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)
co.set_pref("safebrowsing.enabled", True)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

test_codes = ["1240", "1294", "1295", "1565", "1580", "1586", "1591", "1595", "6488"]
success = []
failed = []

for code in test_codes:
    for f in glob.glob(os.path.join(save_dir, "*")):
        try: os.remove(f)
        except OSError: pass

    inp = page.ele("css:input.code", timeout=5) or page.ele("@name=code", timeout=5)
    inp.input(code, clear=True, by_js=True)
    page.run_js("var el=document.querySelector('input.code'); if(el){el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}")

    btn = page.ele("css:button.btn-search", timeout=3) or page.ele("text:查詢", timeout=3)
    if btn:
        btn.click(by_js=True)

    # 等待下載按鈕出現 (給予 5 秒充足 AJAX 載入期)
    d_btn = page.ele("text:下載 CSV (UTF-8)", timeout=5) or page.ele("text:下載 CSV", timeout=2)
    if d_btn:
        d_btn.click(by_js=True)
        found = False
        for _ in range(15):
            time.sleep(0.4)
            csvs = [f for f in glob.glob(os.path.join(save_dir, "*.csv")) if os.path.getsize(f) > 30]
            if csvs:
                print(f"[OK] {code} 下載成功！檔案: {os.path.basename(csvs[0])} (大小: {os.path.getsize(csvs[0])} bytes)")
                success.append(code)
                found = True
                break
        if not found:
            print(f"[下載超時] {code}")
            failed.append(code)
    else:
        print(f"[查無按鈕] {code}")
        failed.append(code)

page.quit()
print(f"\n==========================================")
print(f"總計測試 {len(test_codes)} 檔 | 成功: {len(success)} 檔 | 失敗: {len(failed)} 檔")
print(f"==========================================")
