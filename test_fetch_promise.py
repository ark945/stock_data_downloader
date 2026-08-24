import time
import json
import pandas as pd
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 6488, 1595, 1584
for code in ["6488", "1595", "1584"]:
    res_str = p.run_js(f"""
        return new Promise((resolve) => {{
            fetch('/www/zh-tw/afterTrading/brokerBS?code={code}&response=json', {{credentials: 'include'}})
                .then(r => r.json())
                .then(data => resolve(JSON.stringify(data)))
                .catch(e => resolve(JSON.stringify({{error: e.toString()}})));
        }});
    """)
    try:
        data = json.loads(res_str)
        if "tables" in data and data["tables"]:
            rows = data["tables"][0].get("data", [])
            print(f"[✓ JSON 提取成功] {code} 筆數: {len(rows)} 筆 (全量完整數據！)")
            if rows:
                print(f"   第一筆: {rows[0]}")
                print(f"   最後一筆: {rows[-1]}")
        else:
            print(f"[查無資料/無成交] {code}")
    except Exception as e:
        print(f"[❌ 失敗] {code}: {e}")

p.quit()
