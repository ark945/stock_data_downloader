import time
import json
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 6488
res_str = p.run_js("""
    return new Promise((resolve) => {
        fetch('/www/zh-tw/afterTrading/brokerBS?code=6488&response=json', {credentials: 'include'})
            .then(r => r.text())
            .then(txt => resolve(txt))
            .catch(e => resolve(JSON.stringify({error: e.toString()})));
    });
""")
print("=== 6488 回應內容前 300 字 ===")
print(res_str[:300])

p.quit()
