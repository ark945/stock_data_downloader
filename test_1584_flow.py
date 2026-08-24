import os
import sys
import glob
import time
from DrissionPage import ChromiumPage, ChromiumOptions

save_dir = os.path.join(os.path.dirname(__file__), "downloads_tpex_local", "test_1584")
os.makedirs(save_dir, exist_ok=True)

co = ChromiumOptions()
co.set_pref("profile.default_content_setting_values.automatic_downloads", 1)
co.set_pref("download.default_directory", save_dir)
co.set_pref("download.prompt_for_download", False)

page = ChromiumPage(co)
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 1584
for f in glob.glob(os.path.join(save_dir, "*")):
    try: os.remove(f)
    except: pass

inp = page.ele("css:input.code")
print("輸入 1584...")
inp.input("1584", clear=True, by_js=True)
time.sleep(0.5)

# 點擊右邊的 [查詢] 按鈕
# 在截圖中，按鈕文字是「查詢」，位於下載按鈕右邊
q_btn = page.ele("xpath://button[contains(text(),'查詢')]") or page.ele("text:查詢")
print("點擊查詢按鈕:", q_btn.text if q_btn else "None")
if q_btn:
    q_btn.click()

time.sleep(2.0)
print("查詢後頁面是否出現 1584 精剛:", bool(page.ele("text:1584")))
print("查詢後頁面是否出現成交筆數:", bool(page.ele("text:成交筆數")))

# 點擊 [下載 CSV (UTF-8)]
dl_btn = page.ele("xpath://button[contains(text(),'UTF-8')]") or page.ele("text:下載 CSV (UTF-8)")
print("點擊下載按鈕:", dl_btn.text if dl_btn else "None")
if dl_btn:
    dl_btn.click()

for i in range(10):
    time.sleep(0.5)
    files = glob.glob(os.path.join(save_dir, "*"))
    if files:
        print(f"第 {i+1} 次輪詢找到檔案:", files, "大小:", [os.path.getsize(f) for f in files])
        if any(os.path.getsize(f) > 30 and not f.endswith(".crdownload") for f in files):
            print(">>> 下載完全成功！")
            break

page.quit()
