import os
import sys
import io
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

    # 直接從 DOM 讀取表格資料
    table_ele = page.ele("css:table")
    if table_ele:
        try:
            dfs = pd.read_html(io.StringIO(table_ele.html))
            if dfs:
                df = dfs[0]
                print(f"[✓ DOM 讀取成功] {code} 成功讀取 {len(df)} 筆明細！")
                print(df.head(3))
                continue
        except Exception as e:
            print(f"[!] 解析失敗: {e}")
    print(f"[查無表格] {code}")

page.quit()
