import os
import sys
import time
import pandas as pd
from DrissionPage import ChromiumPage, ChromiumOptions

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

page = ChromiumPage()
page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

test_codes = ["1584", "1595", "6488", "1294"]
for code in test_codes:
    inp = page.ele("css:form.formblock input.code") or page.ele("css:input.code")
    inp.input(code, clear=True, by_js=True)
    time.sleep(0.3)

    q_btn = page.ele("css:form.formblock button[type=submit]") or page.ele("xpath://form//button[@type='submit']")
    if q_btn:
        q_btn.click(by_js=True)

    time.sleep(1.5)

    # 原生提取表格每一列
    rows = page.eles("css:table tbody tr")
    if rows and len(rows) > 0:
        data = []
        for r in rows:
            tds = [td.text.strip() for td in r.eles("tag:td")]
            if len(tds) >= 5:
                # 序號, 券商, 價格, 買進股數, 賣出股數
                data.append(tds)
        if data:
            print(f"[✓ 原生 DOM 成功] {code} 抓到 {len(data)} 筆分點明細！第一筆:", data[0])
            continue
    print(f"[無交易/無明細] {code}")

page.quit()
