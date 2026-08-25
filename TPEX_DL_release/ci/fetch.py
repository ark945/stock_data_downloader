"""
TPEX 券商買賣證券日報表 - CI 版 單/多檔抓取 (headless + no-sandbox)

CLI:
    python ci/fetch.py 1240
    python ci/fetch.py 1240 1259 1264
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from DrissionPage import ChromiumPage, ChromiumOptions

HEADLESS = True

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "brokerBS" / date.today().strftime("%Y%m%d")

PAGE = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"
PER_STOCK_TIMEOUT = 40
TOKEN_TIMEOUT = 30


def _build_options() -> ChromiumOptions:
    co = ChromiumOptions()
    co.set_argument("--lang=zh-TW")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-gpu")
    co.set_argument("--window-size=1920,1080")
    co.headless(HEADLESS)
    return co


class TPEXBrokerBSClientCI:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.page: ChromiumPage | None = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def open(self) -> None:
        if self.page is not None:
            return
        self.page = ChromiumPage(addr_or_opts=_build_options())
        self.page.listen.start(["afterTrading", "brokerBS"])
        self._log(f"open {PAGE}")
        self.page.get(PAGE)
        tok = self._wait_token(TOKEN_TIMEOUT)
        self._log(f"initial token len={len(tok)}")
        if not tok:
            time.sleep(3)
            tok = self._wait_token(TOKEN_TIMEOUT)
            if not tok:
                raise RuntimeError("initial turnstile token not obtained")

    def close(self) -> None:
        if self.page is not None:
            try:
                self.page.quit()
            except Exception:
                pass
            self.page = None

    def fetch(self, code: str, retries: int = 2) -> dict:
        if self.page is None:
            self.open()
        err = ""
        for attempt in range(retries + 1):
            ok, data, err = self._one_shot(code)
            if ok:
                return data
            if err == "cf520":
                time.sleep(2 + attempt * 2)
                continue
            break
        raise RuntimeError(f"fetch {code} failed: {err}")

    def _log(self, msg: str) -> None:
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}", flush=True)

    def _wait_token(self, timeout: int) -> str:
        assert self.page is not None
        for _ in range(timeout * 2):
            t = self.page.run_js(
                "return (document.querySelector('input[name=\"cf-turnstile-response\"]') || {}).value || ''"
            )
            if t and len(t) > 20:
                return t
            time.sleep(0.5)
        return ""

    def _click_query(self) -> None:
        assert self.page is not None
        self.page.run_js("""
            const els = Array.from(document.querySelectorAll('button, a'));
            const t = els.find(e => (e.innerText || '').trim() === '查詢');
            if (t) t.click();
        """)

    def _one_shot(self, code: str) -> tuple[bool, dict | None, str]:
        assert self.page is not None
        code_el = self.page.ele("@name=code", timeout=5)
        if not code_el:
            return False, None, "code input not found"
        code_el.clear()
        code_el.input(code)
        time.sleep(0.2)

        tok = self._wait_token(TOKEN_TIMEOUT)
        if not tok:
            return False, None, "no turnstile token"

        self.page.listen.clear()
        self._click_query()

        pkt = self.page.listen.wait(timeout=PER_STOCK_TIMEOUT)
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
                return False, None, f"api err: {body.get('stat', '')[:80]}"
            return False, None, f"unexpected body: {str(body)[:120]}"
        return False, None, f"unknown body type: {type(body).__name__}"


def _count_rows(data: dict) -> int:
    try:
        tables = data.get("tables", [])
        for t in tables:
            if "券商" in str(t.get("title", "")) or "買賣" in str(t.get("title", "")):
                return len(t.get("data", []))
        if len(tables) >= 2:
            return len(tables[1].get("data", []))
    except Exception:
        pass
    return 0


def _cli() -> int:
    ap = argparse.ArgumentParser(description="TPEX 券商買賣日報表 單/多檔抓取 (CI 版)")
    ap.add_argument("codes", nargs="+", help="股票代號（可多個）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"輸出資料夾（預設: {DEFAULT_OUT}）")
    ap.add_argument("--stdout", action="store_true",
                    help="印出 JSON 到 stdout，不寫檔")
    ap.add_argument("--quiet", action="store_true", help="靜音")
    args = ap.parse_args()

    verbose = not args.quiet
    results: list[dict] = []
    fail_count = 0

    with TPEXBrokerBSClientCI(verbose=verbose) as client:
        for code in args.codes:
            code = str(code).strip()
            t0 = time.time()
            try:
                data = client.fetch(code)
                elapsed = time.time() - t0
                rows = _count_rows(data)
                if args.stdout:
                    results.append({"code": code, "data": data})
                else:
                    args.out.mkdir(parents=True, exist_ok=True)
                    out_path = args.out / f"{code}.json"
                    out_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    if verbose:
                        print(f"[OK] {code} ({rows} 筆, {elapsed:.1f}s) -> {out_path}", flush=True)
            except Exception as e:
                fail_count += 1
                elapsed = time.time() - t0
                if verbose:
                    print(f"[FAIL] {code} — {e} ({elapsed:.1f}s)", file=sys.stderr, flush=True)
                if args.stdout:
                    results.append({"code": code, "error": str(e)})

    if args.stdout:
        if len(args.codes) == 1 and "data" in results[0]:
            print(json.dumps(results[0]["data"], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(results, ensure_ascii=False, indent=2))

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(_cli())
