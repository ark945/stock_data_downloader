import json
import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

js_1595 = """
    return (async () => {
        var resp = await fetch("/www/zh-tw/afterTrading/brokerBS?code=1595&response=json", {credentials: "include"});
        return await resp.json();
    })();
"""
res = p.run_js(js_1595)
print("=== 1595 JSON API 回傳 ===")
if isinstance(res, dict) and "tables" in res and res["tables"]:
    table = res["tables"][0]
    data = table.get("data", [])
    print(f"表格標題: {table.get('title')}")
    print(f"總筆數: {len(data)} 筆 (全量數據！)")
    print("前 3 筆:")
    for row in data[:3]:
        print("  ", row)

# 測試 6488 環球晶
js_6488 = """
    return (async () => {
        var resp = await fetch("/www/zh-tw/afterTrading/brokerBS?code=6488&response=json", {credentials: "include"});
        return await resp.json();
    })();
"""
res_6488 = p.run_js(js_6488)
if isinstance(res_6488, dict) and "tables" in res_6488 and res_6488["tables"]:
    data_6488 = res_6488["tables"][0].get("data", [])
    print(f"\n=== 6488 環球晶 總筆數: {len(data_6488)} 筆 (全量數據！) ===")
    print("前 3 筆:")
    for row in data_6488[:3]:
        print("  ", row)

p.quit()
