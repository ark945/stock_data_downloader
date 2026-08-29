"""
TPEX 雲端環境 (WARP 網絡加持) 診斷測試腳本
"""
import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

def test_tpex_under_warp():
    print("==========================================")
    print("啟動 Chrome (WARP 消費者網絡環境)")
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
    
    tok0 = ""
    for i in range(40):
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
            tok0 = t
            print(f"[WARP 加持成功！] Turnstile Token 簽發成功 at {i*0.5}s, len={len(t)}")
            break
        time.sleep(0.5)
        
    if not tok0:
        print("[WARP 測試失敗] 未能取得 Token")
        page.quit()
        return False

    # 測試抓取 1240
    print("\n--- 測試查詢標的 1240 ---")
    code_el = page.ele("@name=code")
    code_el.clear()
    code_el.input("1240")
    time.sleep(0.5)
    
    page.listen.clear()
    q_btn = page.ele('css:form.formblock button[type="submit"]') or page.ele('css:div.tables-tools button[type="submit"]')
    q_btn.click()
    
    pkt = page.listen.wait(timeout=25)
    if pkt:
        print("API 成功回應:", str(pkt.response.body)[:300])
        page.quit()
        return True
    else:
        print("API 封包逾時")
        page.quit()
        return False

if __name__ == "__main__":
    success = test_tpex_under_warp()
    sys.exit(0 if success else 1)
