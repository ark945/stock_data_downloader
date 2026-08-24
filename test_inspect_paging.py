import time
from DrissionPage import ChromiumPage

p = ChromiumPage()
p.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
time.sleep(3)

p.ele("css:input.code").input("6488", clear=True, by_js=True)
q_btn = page_ele = p.ele("css:form.formblock button[type=submit]") or p.ele("xpath://form//button[@type='submit']")
if q_btn: q_btn.click(by_js=True)
time.sleep(2)

print("=== 6488 查詢後頁面上的分頁元素 ===")
pagins = p.eles("css:.pagination, .simplePagination, .page-item, ul.page, div.paging")
for i, el in enumerate(pagins):
    print(f"[{i}] class={el.attr('class')}, html={el.html[:200]}")

# 檢查總頁數或分頁按鈕
btns = p.eles("css:.page-link, .page-number, ul.pagination li, .simple-pagination li")
print(f"分頁按鈕個數: {len(btns)}")
for b in btns[:10]:
    print("  按鈕文字:", b.text)

p.quit()
