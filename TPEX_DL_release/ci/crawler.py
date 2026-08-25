"""
TPEX 券商買賣證券日報表 - CI 版 crawler (headless + no-sandbox)

與 crawl_all.py 差異：
  - headless=True
  - 加上 --no-sandbox / --disable-dev-shm-usage（Linux CI 必備）
  - 資料/state/log 路徑仍指向 ../data，與本機版共用資料夾

在 GitHub Actions 走 Xvfb 時，也可用 headless=False；本檔預設 headless=True，
若要走 Xvfb headed 模式請把下方 HEADLESS 改為 False。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions

# CI 版旗標
HEADLESS = True

ROOT = Path(__file__).resolve().parent.parent
CODES_FILE = ROOT / "data" / "otc_common_codes.json"

TODAY = date.today().strftime("%Y%m%d")
OUT_DIR = ROOT / "data" / "brokerBS" / TODAY
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = ROOT / "data" / f"crawler_state_{TODAY}.json"
LOG_FILE = ROOT / "data" / f"crawler_log_{TODAY}.log"

PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"

INTER_STOCK_DELAY = 2.0
PER_STOCK_TIMEOUT = 40
TOKEN_TIMEOUT = 30
RELOAD_AFTER = 3
RESTART_AFTER = 6
ABORT_AFTER = 20
COOLDOWN_SEC = 30


def _build_options() -> ChromiumOptions:
    co = ChromiumOptions()
    co.set_download_path(str(OUT_DIR))
    co.set_argument("--lang=zh-TW")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-gpu")
    co.set_argument("--window-size=1920,1080")
    co.headless(HEADLESS)
    return co


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def count_broker_rows(data: dict) -> int:
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
    log(f"[CI] total={len(codes)}  todo={len(todo)}  done={len(done)}  headless={HEADLESS}")

    page = ChromiumPage(addr_or_opts=_build_options())
    page.listen.start(["afterTrading", "brokerBS"])

    log(f"open {PAGE}")
    page.get(PAGE)

    tok0 = wait_token(page, TOKEN_TIMEOUT)
    log(f"initial token len={len(tok0)}")
    if not tok0:
        log("[ERR] 首次 token 沒拿到（CI 常見 CF 阻擋）。3秒後重試 ...")
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
        p = ChromiumPage(addr_or_opts=_build_options())
        p.listen.start(["afterTrading", "brokerBS"])
        return p

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

            if fail_streak >= ABORT_AFTER:
                log(f"!! 連續失敗 {fail_streak} 次，視為被限速，中止本輪。")
                break

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
            elif fail_streak >= RELOAD_AFTER:
                log(f"!! 連續失敗 {fail_streak} 次，reload 頁面重取 token")
                page.get(PAGE)
                tok = wait_token(page, TOKEN_TIMEOUT)
                log(f"   reload token len={len(tok)}")

        state["done"] = sorted(done)
        state["failed"] = failed
        save_state(state)

        time.sleep(INTER_STOCK_DELAY)

    state["done"] = sorted(done)
    state["failed"] = failed
    save_state(state)
    log(f"[END] 本輪 OK={ok_count} FAIL={fail_count}  累計 done={len(done)}")

    time.sleep(2)
    page.quit()
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    sys.exit(main(n or None))
