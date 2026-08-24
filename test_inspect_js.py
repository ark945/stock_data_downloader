import os
import sys
import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 檢查所有 script 和按鈕的 onclick
js_code = """
var btns = Array.from(document.querySelectorAll('button, a, input[type=button], input[type=submit]'));
return btns.map(b => ({
    text: b.innerText || b.value,
    cls: b.className,
    onclick: b.getAttribute('onclick'),
    type: b.type,
    id: b.id
}));
"""
res = p.run_js(js_code)
for item in res:
    print(item)

p.quit()
