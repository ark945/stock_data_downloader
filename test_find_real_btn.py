import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

inp = p.ele("css:input.code")
curr = inp
print("--- 逐層向上尋找容器與所有按鈕 ---")
for level in range(6):
    curr = curr.parent()
    if not curr: break
    btns = curr.eles("tag:button")
    print(f"Level {level+1}: <{curr.tag} class='{curr.attr('class')}'> 內含 button 數: {len(btns)}")
    for b in btns:
        print(f"   -> button: text='{b.text}', class='{b.attr('class')}', id='{b.attr('id')}', html={b.html[:60]}")

p.quit()
