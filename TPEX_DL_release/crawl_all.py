"""
TPEX 券商買賣證券日報表 - Production Crawler

流程：
  1. DrissionPage 開瀏覽器 → 自動過 CF Turnstile
  2. 從 data/otc_common_codes.json 讀 890 檔上櫃普通股
  3. 每檔：
       - 填代碼
       - 等 turnstile token 就緒
       - 點『查詢』按鈕
       - 攔截 POST /www/zh-tw/afterTrading/brokerBS 的 JSON 回應
       - 存成 data/brokerBS/<YYYYMMDD>/<code>.json
  4. State file 支援中斷續跑
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions

ROOT = Path(__file__).parent
CODES_FILE = ROOT / "data" / "otc_common_codes.json"

TODAY = date.today().strftime("%Y%m%d")
OUT_DIR = ROOT / "data" / "brokerBS" / TODAY
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = ROOT / "data" / f"crawler_state_{TODAY}.json"
LOG_FILE = ROOT / "data" / f"crawler_log_{TODAY}.log"

PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"

# 節流：每檔間隔（秒）
INTER_STOCK_DELAY = 2.0
# 單檔最多等待時間（秒）
PER_STOCK_TIMEOUT = 40
# token 等待
TOKEN_TIMEOUT = 30
# 連續失敗門檻
RELOAD_AFTER = 3           # 連續 3 次 → reload 頁面
RESTART_AFTER = 6          # 連續 6 次 → 重開瀏覽器 + 冷卻
ABORT_AFTER = 20           # 連續 20 次 → 中止，不再白跑
COOLDOWN_SEC = 30          # 重開瀏覽器前冷卻秒數


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def count_broker_rows(data: dict) -> int:
    """從 API JSON 抽出券商買賣分點筆數（tables[1].data 的 rows）。"""
    try:
        for t in data.get("tables", []):
            if "券商" in str(t.get("title", "")) or "買賣" in str(t.get("title", "")):
                return len(t.get("data", []))
        tables = data.get("tables", [])
        if len(tables) >= 2:
            return len(tables[1].get("data", []))
    except Exception:
        pass
    return 0


def load_codes() -> list[str]:
    return json.loads(CODES_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"done": [], "failed": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def wait_token(page, timeout: int = TOKEN_TIMEOUT) -> str:
    for _ in range(timeout * 2):
        t = page.run_js(
            "return (document.querySelector('input[name=\"cf-turnstile-response\"]') || {}).value || ''"
        )
        if t and len(t) > 20:
            return t
        time.sleep(0.5)
    return ""


def click_query(page) -> None:
    page.run_js("""
        const els = Array.from(document.querySelectorAll('button, a'));
        const t = els.find(e => (e.innerText || '').trim() === '查詢');
        if (t) t.click();
    """)


def _one_shot(page, code: str) -> tuple[bool, dict | None, str]:
    code_el = page.ele("@name=code", timeout=5)
    if not code_el:
        return False, None, "code input not found"
    code_el.clear()
    code_el.input(code)
    time.sleep(0.2)

    tok = wait_token(page, TOKEN_TIMEOUT)
    if not tok:
        return False, None, "no turnstile token"

    page.listen.clear()
    click_query(page)

    pkt = page.listen.wait(timeout=PER_STOCK_TIMEOUT)
    if not pkt:
        return False, None, "no api packet"

    time.sleep(0.5)
    try:
        body = pkt.response.body
    except Exception as e:
        return False, None, f"read body err: {e}"

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return False, None, f"not json: {body[:120]}"

    if isinstance(body, dict):
        if "tables" in body:
            return True, body, ""
        # CF 520 / 應用層錯誤
        if str(body.get("status")) == "520" or "520" in str(body.get("title", "")):
            return False, None, "cf520"
        if "stat" in body:
            return False, None, f"api err: {body.get('stat', '')[:60]}"
        return False, None, f"unexpected body: {str(body)[:120]}"
    return False, None, f"unknown body type: {type(body).__name__}"


def fetch_one(page, code: str, retries: int = 2) -> tuple[bool, dict | None, str]:
    err = ""
    for attempt in range(retries + 1):
        ok, data, err = _one_shot(page, code)
        if ok:
            return True, data, ""
        if err == "cf520":
            time.sleep(2 + attempt * 2)
            continue
        # 其他錯誤不重試
        break
    return False, None, err


def main(limit: int | None = None) -> int:
    codes = load_codes()
    if limit:
        codes = codes[:limit]

    state = load_state()
    done = set(state.get("done", []))
    failed = state.get("failed", [])

    todo = [c for c in codes if c not in done]
    log(f"total={len(codes)}  todo={len(todo)}  done={len(done)}")

    # 開瀏覽器
    co = ChromiumOptions()
    co.set_download_path(str(OUT_DIR))
    co.set_argument("--lang=zh-TW")
    co.headless(False)

    page = ChromiumPage(addr_or_opts=co)
    page.listen.start(["afterTrading", "brokerBS"])

    log(f"open {PAGE}")
    page.get(PAGE)

    # 首次等 turnstile
    tok0 = wait_token(page, TOKEN_TIMEOUT)
    log(f"initial token len={len(tok0)}")
    if not tok0:
        log("[ERR] 首次 token 沒拿到，可能 CF 阻擋。3秒後重試 ...")
        time.sleep(3)
        tok0 = wait_token(page, TOKEN_TIMEOUT)
        if not tok0:
            log("[FATAL] 還是沒 token，退出")
            page.quit()
            return 2

    total = len(todo)
    ok_count = 0
    fail_count = 0
    fail_streak = 0

    def open_browser():
        co = ChromiumOptions()
        co.set_download_path(str(OUT_DIR))
        co.set_argument("--lang=zh-TW")
        co.headless(False)
        p = ChromiumPage(addr_or_opts=co)
        p.listen.start(["afterTrading", "brokerBS"])
        return p

    # 上面已經 open + 拿到 token，page 變數已存在

    for i, code in enumerate(todo, 1):
        t0 = time.time()
        ok, data, err = fetch_one(page, code)
        elapsed = time.time() - t0

        if ok and data:
            out_path = OUT_DIR / f"{code}.json"
            out_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            rows = count_broker_rows(data)
            done.add(code)
            ok_count += 1
            fail_streak = 0
            log(f"[{i}/{total}] [OK] {code} ({rows} 筆, {elapsed:.1f}s)")
        else:
            failed.append({"code": code, "err": err, "at": datetime.now().isoformat()})
            fail_count += 1
            fail_streak += 1
            log(f"[{i}/{total}] [FAIL] {code} — {err} ({elapsed:.1f}s, streak={fail_streak})")

            # 需要中止（避免白跑）
            if fail_streak >= ABORT_AFTER:
                log(f"!! 連續失敗 {fail_streak} 次，視為被限速，中止本輪。state 已存，稍後重跑即可續跑。")
                break

            # 重開瀏覽器 + 冷卻
            if fail_streak >= RESTART_AFTER:
                log(f"!! 連續失敗 {fail_streak} 次，重開瀏覽器並冷卻 {COOLDOWN_SEC}s")
                try:
                    page.quit()
                except Exception:
                    pass
                time.sleep(COOLDOWN_SEC)
                page = open_browser()
                page.get(PAGE)
                tok = wait_token(page, TOKEN_TIMEOUT)
                log(f"   restart token len={len(tok)}")
                fail_streak = 0
            # 輕度：reload 頁面
            elif fail_streak >= RELOAD_AFTER:
                log(f"!! 連續失敗 {fail_streak} 次，reload 頁面重取 token")
                page.get(PAGE)
                tok = wait_token(page, TOKEN_TIMEOUT)
                log(f"   reload token len={len(tok)}")
                # 不清零，若 reload 後還失敗才能累積到 RESTART_AFTER

        # 每檔都存 state，中斷也不會遺失進度
        state["done"] = sorted(done)
        state["failed"] = failed
        save_state(state)

        time.sleep(INTER_STOCK_DELAY)

    # 收尾
    state["done"] = sorted(done)
    state["failed"] = failed
    save_state(state)
    log(f"[END] 本輪 OK={ok_count} FAIL={fail_count}  累計 done={len(done)}")

    time.sleep(2)
    page.quit()
    return 0


if __name__ == "__main__":
    # 用法：
    #   python crawl_all.py       # 跑全部
    #   python crawl_all.py 10    # 只跑前 10 檔（測試用）
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    sys.exit(main(n or None))
