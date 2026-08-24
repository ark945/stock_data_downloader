import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

for i, el in enumerate(p.eles("text:查詢")):
    disp = el.states.is_displayed
    size = el.rect.size if disp else None
    print(f"[{i}] tag=<{el.tag}>, class='{el.attr('class')}', displayed={disp}, size={size}, html={el.html[:60]}")

p.quit()
