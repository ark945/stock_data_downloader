# -*- coding: utf-8 -*-
"""
台股營業日 (開盤日) 判定與行事曆管理中心 (Trading Calendar Manager)
===================================================================
核心功能：
1. 自動判斷指定日期 (預設為今天) 是否為台灣證券市場之「營業日 (開盤日)」。
2. 整合多重判定層級 (Multi-Tier Verification)：
   - Tier 1: 週末檢驗 (週六/週日預設不交易休市)。
   - Tier 2: TWSE 臺灣證券交易所官方市場開休市行事曆 (含本地快取機制)。
   - Tier 3: 內建萬年離線國定假日與民俗連續假期備援清單 (2024~2027)。
   - Tier 4: 收盤後即時市場探測 (針對颱風假、天然災害等突發臨時休市)。
3. 支援組態設定與強制開關：
   - 環境變數 CHECK_TRADING_DAY (預設 true)
   - 環境變數 FORCE_CRAWL (預設 false)
   - CLI 參數 --force / --no-check-trading-day
4. 提供實用函式：
   - is_trading_day(target_date) -> Tuple[bool, str]
   - get_latest_trading_date(ref_date) -> str
   - should_proceed_crawler(target_date, force) -> bool
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))
CACHE_FILE = os.path.join(os.path.dirname(__file__), "twse_holidays_cache.json")
CACHE_EXPIRE_SECONDS = 7 * 86400  # 快取存活期 7 天

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 內建已知休市日離線備援庫 (涵蓋 2024 ~ 2027 年已公告之固定與連續休市日)
BUILTIN_OFFLINE_HOLIDAYS: Dict[str, str] = {
    # 2024 年休市日
    "2024-01-01": "中華民國開國紀念日",
    "2024-02-06": "農曆春節封關休市",
    "2024-02-07": "農曆春節封關休市",
    "2024-02-08": "農曆除夕前一日",
    "2024-02-09": "農曆除夕",
    "2024-02-12": "農曆春節補假",
    "2024-02-13": "農曆春節補假",
    "2024-02-14": "農曆春節補假",
    "2024-02-28": "和平紀念日",
    "2024-04-04": "兒童節",
    "2024-04-05": "民族掃墓節(清明節)",
    "2024-05-01": "勞動節",
    "2024-06-10": "端午節",
    "2024-07-24": "凱米颱風停止上班休市",
    "2024-07-25": "凱米颱風停止上班休市",
    "2024-09-17": "中秋節",
    "2024-10-02": "山陀兒颱風停止上班休市",
    "2024-10-03": "山陀兒颱風停止上班休市",
    "2024-10-10": "國慶日",
    "2024-10-31": "康芮颱風停止上班休市",

    # 2025 年休市日
    "2025-01-01": "中華民國開國紀念日",
    "2025-01-23": "農曆春節無交易",
    "2025-01-24": "農曆春節無交易",
    "2025-01-27": "農曆春節彈性放假",
    "2025-01-28": "農曆除夕",
    "2025-01-29": "農曆春節初一",
    "2025-01-30": "農曆春節初二",
    "2025-01-31": "農曆春節初三",
    "2025-02-28": "和平紀念日",
    "2025-04-03": "兒童節彈性補假",
    "2025-04-04": "清明節",
    "2025-05-01": "勞動節",
    "2025-05-30": "端午節彈性補假",
    "2025-10-06": "中秋節彈性補假",
    "2025-10-10": "國慶日",

    # 2026 年休市日 (依據 TWSE 官方 115 年行事曆)
    "2026-01-01": "中華民國開國紀念日",
    "2026-02-12": "農曆春節市場無交易",
    "2026-02-13": "農曆春節市場無交易",
    "2026-02-15": "農曆除夕前假",
    "2026-02-16": "農曆除夕",
    "2026-02-17": "農曆春節初一",
    "2026-02-18": "農曆春節初二",
    "2026-02-19": "農曆春節初三",
    "2026-02-20": "農曆春節補假",
    "2026-02-27": "和平紀念日彈性放假",
    "2026-02-28": "和平紀念日",
    "2026-04-03": "兒童節彈性補假",
    "2026-04-04": "兒童節",
    "2026-04-05": "清明節",
    "2026-04-06": "民族掃墓節(清明補假)",
    "2026-05-01": "勞動節",
    "2026-06-19": "端午節",
    "2026-09-25": "中秋節",
    "2026-09-28": "教師節/連假調節",
    "2026-10-10": "國慶日",
    "2026-10-25": "臺灣光復節",
    "2026-10-26": "臺灣光復節補假",
    "2026-12-25": "行憲紀念日",

    # 2027 年已知固定休市日
    "2027-01-01": "中華民國開國紀念日",
    "2027-02-05": "農曆春節封關休市",
    "2027-02-08": "農曆春節假期",
    "2027-02-09": "農曆春節初一",
    "2027-02-28": "和平紀念日",
    "2027-04-05": "清明節",
    "2027-05-01": "勞動節",
    "2027-06-09": "端午節",
    "2027-09-15": "中秋節",
    "2027-10-10": "國慶日"
}


def get_taipei_now() -> datetime:
    """取得台北標準時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def get_taipei_today() -> str:
    """取得台北標準時間今日日期 (YYYY-MM-DD)"""
    return get_taipei_now().strftime("%Y-%m-%d")


def fetch_official_twse_holidays(force_refresh: bool = False) -> Dict[str, str]:
    """
    自 TWSE 官方取得全年市場開休市行事曆，並支援磁碟快取
    :param force_refresh: 是否強制重新向 TWSE 下載
    :return: 字典 { 'YYYY-MM-DD': '休市名稱/原因' }
    """
    # 1. 檢查本地快取是否存在且有效
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            if time.time() - mtime < CACHE_EXPIRE_SECONDS:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    if isinstance(cached_data, dict) and len(cached_data) > 0:
                        return cached_data
        except Exception:
            pass

    # 2. 發送請求至 TWSE 官方開放 API
    url = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json"
    holidays_map = dict(BUILTIN_OFFLINE_HOLIDAYS)

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            rows = data.get("data", [])
            for r in rows:
                if len(r) >= 2:
                    d_str, name = str(r[0]).strip(), str(r[1]).strip()
                    desc = str(r[2]).strip() if len(r) >= 3 else ""
                    
                    # 排除開始交易日與最後交易日
                    if "開始交易" in name or "最後交易" in name:
                        continue

                    # 判斷是否為休市日
                    is_closed = any(kw in name or kw in desc for kw in [
                        "無交易", "放假", "休市", "紀念日", "春節", "除夕", "節", "連假"
                    ])
                    if is_closed:
                        clean_date = d_str.replace("/", "-")
                        holidays_map[clean_date] = name

        # 寫入本地快取
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(holidays_map, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    except Exception as e:
        # 若網路不通或證交所維護，使用內建萬年備援清單
        pass

    return holidays_map


def probe_live_market_trading(target_date: str) -> Optional[bool]:
    """
    收盤後 (14:00 後) 輕量發送 1 次請求探測 TWSE 當日大盤收盤資料是否產出。
    用於精準識別行事曆未預載之「颱風假」、「天災臨時休市」。
    :return: True (有開盤交易), False (官方明確無交易/休市), None (無法確定或尚未收盤)
    """
    now = get_taipei_now()
    today_str = now.strftime("%Y-%m-%d")

    # 若查詢的是未來的日期，無法透過收盤行情探測
    if target_date > today_str:
        return None

    # 若查詢今天但尚未到收盤時間 (13:45 前)，無法透過日收盤檔案探測
    if target_date == today_str and now.hour < 14:
        return None

    date_compact = target_date.replace("-", "")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&date={date_compact}&type=ALLBUT0999"

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            stat = str(data.get("stat", ""))
            if "很抱歉" in stat or "沒有符合條件" in stat or "無交易" in stat:
                return False
            if stat.lower() == "ok" and data.get("tables"):
                return True
    except Exception:
        pass

    return None


def is_trading_day(target_date: Optional[str] = None, check_live_probe: bool = True) -> Tuple[bool, str]:
    """
    判定指定日期是否為台股營業日 (開盤日)
    :param target_date: YYYY-MM-DD，若為 None 則預設為今日 (台北標準時間)
    :param check_live_probe: 若為當天且已收盤，是否額外透過即時 API 探測天災颱風假
    :return: (is_open: bool, reason: str)
    """
    if not target_date:
        target_date = get_taipei_today()

    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return False, f"日期格式無效: {target_date} (請使用 YYYY-MM-DD)"

    # Tier 1: 週末檢驗 (週六 5、週日 6)
    w = dt.weekday()
    if w == 5:
        return False, f"週休二日休市 (星期六)"
    if w == 6:
        return False, f"週休二日休市 (星期日)"

    # Tier 2: 官方與離線行事曆比對
    holidays = fetch_official_twse_holidays()
    if target_date in holidays:
        holiday_name = holidays[target_date]
        return False, f"國定假日/特定休市日 ({holiday_name})"

    # Tier 3: 當日即時探測 (針對颱風假、不可抗力臨時休市)
    if check_live_probe:
        live_result = probe_live_market_trading(target_date)
        if live_result is False:
            return False, f"官方無交易記錄 (可能遭遇颱風假或臨時停市)"

    return True, "正常開盤營業日"


def get_latest_trading_date(ref_date: Optional[str] = None, max_lookback: int = 15) -> str:
    """
    自指定基準日 (預設為今日) 向前推算，取得「最近的一個台股真實開盤營業日」
    完美取代原本粗糙的 weekday 運算！
    :param ref_date: YYYY-MM-DD，預設為今日
    :param max_lookback: 最大回溯天數 (預設 15 天，足以跨越春節長假)
    :return: YYYY-MM-DD
    """
    now = get_taipei_now()
    if not ref_date:
        # 若今日已過 15:30，基準日可為今日；若尚未收盤或清晨，基準日應自昨天開始往前推算
        if now.hour >= 15:
            curr = now
        else:
            curr = now - timedelta(days=1)
    else:
        curr = datetime.strptime(ref_date, "%Y-%m-%d").replace(tzinfo=TAIPEI_TZ)

    for i in range(max_lookback):
        d_str = curr.strftime("%Y-%m-%d")
        open_flag, _ = is_trading_day(d_str, check_live_probe=False)
        if open_flag:
            return d_str
        curr -= timedelta(days=1)

    # 兜底退回上週五
    return (now - timedelta(days=(now.weekday() + 3) % 7)).strftime("%Y-%m-%d")


def should_proceed_crawler(
    target_date: Optional[str] = None,
    force: bool = False,
    allow_weekend: bool = False,
    config_prefix: str = "CHECK_TRADING_DAY",
    log_func=print
) -> bool:
    """
    高階整合決策：依據組態開關與開盤日檢驗，決定爬蟲是否應該繼續執行
    :param target_date: YYYY-MM-DD，若為 None 則以台北今日為準
    :param force: 是否強制執行 (忽略休市限制)
    :param allow_weekend: 是否允許週末執行
    :param config_prefix: 環境變數開關名 (預設 CHECK_TRADING_DAY)
    :param log_func: 日誌輸出函式
    :return: True (繼續抓取), False (休市跳過)
    """
    if not target_date:
        target_date = get_taipei_today()

    # 1. 檢查強制參數或環境變數 FORCE_CRAWL
    env_force = os.getenv("FORCE_CRAWL", "false").lower() in ("true", "1", "yes")
    if force or env_force:
        log_func(f"[ℹ️] 檢測到強制抓取旗標 (--force / FORCE_CRAWL)，忽略營業日檢查，繼續執行 ({target_date})。")
        return True

    # 2. 檢查是否開啟營業日檢驗 (預設開啟)
    check_enabled = os.getenv(config_prefix, "true").lower() in ("true", "1", "yes")
    if not check_enabled:
        log_func(f"[ℹ️] 環境變數 {config_prefix}=false，營業日檢查已關閉，繼續執行。")
        return True

    # 3. 執行開盤日判定
    is_open, reason = is_trading_day(target_date, check_live_probe=True)
    if is_open:
        log_func(f"[✓] 【開盤日確認】{target_date} 為台股正常營業日，爬蟲正常啟動！")
        return True
    else:
        log_func("=" * 65)
        log_func(f"[⏸️] 【本日休市提醒】{target_date} 非台股營業日 (開盤日)")
        log_func(f"[*] 原因說明: {reason}")
        log_func(f"[*] 系統決策: 優雅跳過今日抓取排程，不進行無效連線與寫入。")
        log_func(f"[*] 提示: 若需強制回補資料，請附加參數 `--force` 或設定環境變數 FORCE_CRAWL=true。")
        log_func("=" * 65)
        return False


def main():
    parser = argparse.ArgumentParser(description="台股開盤營業日檢查工具 (Trading Calendar)")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD，預設為今日)")
    parser.add_argument("--check-today", action="store_true", help="檢查今日是否開盤，回傳 exit code (0:開盤, 1:休市)")
    parser.add_argument("--latest", action="store_true", help="查詢最近一個開盤營業日")
    parser.add_argument("--list-holidays", action="store_true", help="列出全年已知休市日清單")
    parser.add_argument("--force", action="store_true", help="強制模擬執行 (無視開盤日)")
    parser.add_argument("--refresh-cache", action="store_true", help="強制重新自 TWSE 下載最新開休市行事曆")

    args = parser.parse_args()

    if args.refresh_cache:
        print("[*] 正在向 TWSE 官方伺服器同步最新市場開休市行事曆...")
        h_map = fetch_official_twse_holidays(force_refresh=True)
        print(f"[✓] 同步完成！共獲取 {len(h_map)} 筆休市資料，已快取至 {CACHE_FILE}")
        return

    if args.list_holidays:
        h_map = fetch_official_twse_holidays()
        print(f"=== 台灣證券交易所 市場休市行事曆 (共 {len(h_map)} 天) ===")
        for d in sorted(h_map.keys()):
            print(f"  📅 {d}: {h_map[d]}")
        return

    if args.latest:
        latest_d = get_latest_trading_date(args.date)
        print(f"最近一個開盤營業日為: {latest_d}")
        return

    target = args.date or get_taipei_today()
    proceed = should_proceed_crawler(target, force=args.force)

    if args.check_today:
        sys.exit(0 if proceed else 1)


if __name__ == "__main__":
    main()
