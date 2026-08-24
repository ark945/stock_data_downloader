import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

# 測試 1240
p.ele("css:input.code").input("1240", clear=True, by_js=True)
p.run_js("document.querySelector('input.code').dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('input.code').dispatchEvent(new Event('change',{bubbles:true}));")

btn = p.ele("css:.searchset button")
print("找到的按鈕 text:", btn.text, "class:", btn.attr("class"), "tag:", btn.tag)
btn.click(by_js=True)
time.sleep(3)

print("點擊後 URL:", p.url)
print("是否有下載按鈕 (UTF-8):", bool(p.ele("text:下載 CSV (UTF-8)")))
print("所有按鈕:", [b.text for b in p.eles("tag:button")])

p.quit()
