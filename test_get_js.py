import time
import requests
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 抓取頁面載入的所有 script 內容
scripts = p.run_js("""
    return Array.from(document.querySelectorAll('script')).map(s => s.src || s.innerText);
""")
print("=== 頁面 Script 清單 ===")
for s in scripts:
    if s.startswith("http"):
        print("Script URL:", s)
        if "broker" in s.lower() or "mainboard" in s.lower() or "trading" in s.lower():
            try:
                r = requests.get(s, timeout=5)
                print(f"--- {s} 內容摘要 ---")
                print(r.text[:500])
            except: pass

p.quit()
