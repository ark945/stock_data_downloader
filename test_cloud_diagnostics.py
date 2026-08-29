import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

def diagnose():
    co = ChromiumOptions()
    co.set_paths(browser_path="/usr/bin/google-chrome")
    co.set_argument("--lang=zh-TW")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--window-size=1920,1080")
    co.headless(False)
    
    page = ChromiumPage(co)
    page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
    time.sleep(8)
    
    # 檢查 DOM 中所有的 iframe、Turnstile 元素、狀態
    info = page.run_js("""
        return {
            url: window.location.href,
            title: document.title,
            iframes: Array.from(document.querySelectorAll('iframe')).map(f => ({
                src: f.src,
                id: f.id,
                name: f.name,
                width: f.offsetWidth,
                height: f.offsetHeight,
                display: window.getComputedStyle(f).display
            })),
            turnstileExists: typeof window.turnstile !== 'undefined',
            turnstileKeys: typeof window.turnstile !== 'undefined' ? Object.keys(window.turnstile) : [],
            turnstileInputs: Array.from(document.querySelectorAll('[name*="turnstile"], [name*="cf-"]')).map(el => ({
                name: el.name,
                id: el.id,
                value: el.value,
                form: el.closest('form') ? el.closest('form').className : 'none'
            })),
            cfChlWidgets: Array.from(document.querySelectorAll('[id*="cf-chl"]')).map(el => ({
                id: el.id,
                innerHTML: el.innerHTML.slice(0, 100)
            }))
        };
    """)
    print("=== DOM & Turnstile 診斷資訊 ===")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    
    page.quit()

if __name__ == "__main__":
    diagnose()
