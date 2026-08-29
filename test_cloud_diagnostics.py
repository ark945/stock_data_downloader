import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

def test_turnstile_execute():
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
    time.sleep(3)
    
    print("Executing window.turnstile.execute()...")
    res_exec = page.run_js("""
        if (typeof window.turnstile !== 'undefined' && window.turnstile.execute) {
            try {
                window.turnstile.execute();
                return 'executed';
            } catch(e) {
                return 'error: ' + e.message;
            }
        }
        return 'no-turnstile';
    """)
    print("turnstile.execute result:", res_exec)
    
    # 等待 Token 生成
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
            print(f"[SUCCESS] Token generated after turnstile.execute() at {i*0.5}s (len={len(t)})")
            
            # 測試查詢 1240
            code_el = page.ele("@name=code")
            code_el.clear()
            code_el.input("1240")
            time.sleep(0.3)
            
            page.listen.clear()
            q_btn = page.ele('css:form.formblock button[type="submit"]') or page.ele('css:div.tables-tools button[type="submit"]')
            q_btn.click()
            
            pkt = page.listen.wait(timeout=20)
            if pkt:
                print("API 回應結果:", str(pkt.response.body)[:300])
            else:
                print("API 封包逾時")
            page.quit()
            return True
        time.sleep(0.5)
        
    print("[FAILED] Token 依然未簽發")
    page.quit()
    return False

if __name__ == "__main__":
    test_turnstile_execute()
