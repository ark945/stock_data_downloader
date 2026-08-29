"""
TPEX 雲端環境多方案診斷測試腳本
"""
import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

def test_scheme_1():
    print("\n==========================================")
    print("[方案 1] 測試 Google Chrome + Xvfb 實體視窗模式 (Headless=False)")
    print("==========================================")
    co = ChromiumOptions()
    co.set_paths(browser_path="/usr/bin/google-chrome")
    co.set_argument("--lang=zh-TW")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--window-size=1920,1080")
    co.headless(False)
    
    page = ChromiumPage(co)
    page.listen.start("afterTrading/brokerBS")
    page.get("https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html")
    
    print("Page URL:", page.url)
    print("Page Title:", page.title)
    
    for i in range(30):
        t = page.run_js("""
            if (typeof window.turnstile !== 'undefined' && window.turnstile.getResponse) {
                const r = window.turnstile.getResponse();
                if (r && r.length > 50) return r;
            }
            const el = document.querySelector('form.formblock input[name="cf-turnstile-response"]') || 
                       document.querySelector('input[name="cf-turnstile-response"]');
            return el ? (el.value || '') : '';
        """)
        if t and len(t) > 50:
            print(f"[方案 1 成功] Turnstile Token 簽發成功 at {i*0.5}s, len={len(t)}")
            
            # 測試抓取 1240
            code_el = page.ele("@name=code")
            code_el.clear()
            code_el.input("1240")
            time.sleep(0.3)
            
            page.listen.clear()
            q_btn = page.ele('css:form.formblock button[type="submit"]') or page.ele('css:div.tables-tools button[type="submit"]')
            q_btn.click()
            
            pkt = page.listen.wait(timeout=20)
            if pkt:
                print("API 回應狀態:", pkt.response.body)
            else:
                print("API 封包逾時")
            page.quit()
            return True
        time.sleep(0.5)
        
    print("[方案 1 失敗] 未取得 Token")
    page.quit()
    return False

if __name__ == "__main__":
    test_scheme_1()
