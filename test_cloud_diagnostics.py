import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

def inspect_turnstile_full():
    co = ChromiumOptions()
    co.set_paths(browser_path="/usr/bin/google-chrome")
    co.set_argument("--lang=zh-TW")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--window-size=1920,1080")
    co.headless(False)
    
    page = ChromiumPage(co)
    page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
    time.sleep(5)
    
    print("=== 1. Inspecting all Iframes & Shadows ===")
    iframes_info = page.run_js("""
        const iframes = Array.from(document.querySelectorAll('iframe'));
        return iframes.map((f, i) => {
            return {
                index: i,
                src: f.src,
                id: f.id,
                name: f.name,
                rect: { w: f.offsetWidth, h: f.offsetHeight, x: f.offsetLeft, y: f.offsetTop },
                style: f.getAttribute('style')
            };
        });
    """)
    print("Iframes:", json.dumps(iframes_info, ensure_ascii=False, indent=2))
    
    # 搜尋所有可能是 turnstile / cloudflare 的元素
    cf_elements = page.run_js("""
        const els = Array.from(document.querySelectorAll('div, iframe, input')).filter(e => {
            const str = (e.id + ' ' + e.className + ' ' + (e.getAttribute('name')||'')).toLowerCase();
            return str.includes('turnstile') || str.includes('cf-') || str.includes('challenge');
        });
        return els.map(e => ({
            tag: e.tagName,
            id: e.id,
            className: e.className,
            name: e.getAttribute('name'),
            innerHTML: e.innerHTML.slice(0, 150),
            rect: { w: e.offsetWidth, h: e.offsetHeight }
        }));
    """)
    print("CF Elements:", json.dumps(cf_elements, ensure_ascii=False, indent=2))
    
    # 嘗試尋找 DrissionPage 中的 iframe 物件並點擊（如果需要點擊 checkbox）
    for ifr in page.eles('tag:iframe'):
        print("Found DrissionPage iframe:", ifr.attrs)
        try:
            # 嘗試檢查 iframe 內部元素
            box = ifr.ele('tag:input') or ifr.ele('tag:span') or ifr.ele('css:.ctp-checkbox-label')
            print("Element inside iframe:", box)
            if box:
                print("Clicking element inside iframe...")
                box.click()
        except Exception as e:
            print("Error checking iframe content:", e)
            
    time.sleep(5)
    
    # 再次檢查 Token
    tok = page.run_js("""
        if (typeof window.turnstile !== 'undefined' && window.turnstile.getResponse) {
            const r = window.turnstile.getResponse();
            if (r) return r;
        }
        const el = document.querySelector('input[name="cf-turnstile-response"]');
        return el ? el.value : '';
    """)
    print(f"Token after iframe interaction: len={len(tok)}")
    page.quit()

if __name__ == "__main__":
    inspect_turnstile_full()
