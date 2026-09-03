# -*- coding: utf-8 -*-
"""
期交所三大法人期貨未平倉與散戶小台多空比爬蟲 (TAIFEX)
=====================================================
功能特點：
1. 抓取期交所官方三大法人未平倉合約 (台股期貨 TX 與小型台指 MTX)。
2. 抓取小台全市場未平倉總口數，精確推算「散戶小台淨口數」與「散戶小台多空比 (%)」。
3. 自動產出「大盤微觀情緒標籤」(例如：高危誘多避險、極品軋空、偏多震盪、中性整理)。
4. 歷史批次回補：支援 `--start-date` 與 `--end-date` 補跑自 2026-06-01 至今任一交易日。
5. 產出規範：api_taifex_{YYYY-MM-DD}_{YYYY-MM-DD}.parquet (與分點規範統一)。
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import requests
import pandas as pd
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def clean_number(val: Any) -> float:
    """清理數值字串"""
    if val is None or pd.isna(val):
        return 0.0
    s = str(val).strip().replace(",", "").replace("+", "")
    if not s or s in ("-", "--", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def fetch_taifex_institutional_oi(trade_date: str) -> Dict[str, Any]:
    """
    抓取期交所三大法人未平倉契約 (TX 大台與 MTX 小台)
    API: https://www.taifex.com.tw/cht/3/futContractsDate?queryDate={YYYY%2FMM%2FDD}
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    date_query = f"{dt.year:04d}%2F{dt.month:02d}%2F{dt.day:02d}"
    url = f"https://www.taifex.com.tw/cht/3/futContractsDate?queryDate={date_query}"

    res = {
        "tx_foreign_oi": 0.0,
        "tx_investment_oi": 0.0,
        "tx_dealer_oi": 0.0,
        "tx_inst_total_oi": 0.0,
        "mtx_foreign_oi": 0.0,
        "mtx_investment_oi": 0.0,
        "mtx_dealer_oi": 0.0,
        "mtx_inst_total_oi": 0.0,
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return res

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="table_f")
        if not table:
            return res

        rows = table.find_all("tr")
        current_commodity = ""
        for r in rows:
            cols = [c.text.strip().replace("\xa0", " ") for c in r.find_all(["th", "td"])]
            if not cols:
                continue

            # 識別商品名稱
            row_text = " ".join(cols)
            if "臺股期貨" in row_text:
                current_commodity = "TX"
            elif "小型臺指期貨" in row_text:
                current_commodity = "MTX"
            elif any(k in row_text for k in ["電子期貨", "金融期貨", "台灣永續期貨"]):
                current_commodity = "OTHER"

            # 尋找三大法人行 (自營商 / 投信 / 外資)
            # 未平倉多空淨額通常在倒數第 1 或倒數第 2 欄
            for identity, key_prefix in [("自營商", "dealer"), ("投信", "investment"), ("外資", "foreign")]:
                if identity in cols:
                    # 未平倉多空淨額口數在倒數第 2 欄 (最後一欄為契約金額)
                    net_val = 0.0
                    if len(cols) >= 2:
                        net_val = clean_number(cols[-2])

                    if current_commodity == "TX":
                        res[f"tx_{key_prefix}_oi"] = net_val
                    elif current_commodity == "MTX":
                        res[f"mtx_{key_prefix}_oi"] = net_val

        res["tx_inst_total_oi"] = res["tx_foreign_oi"] + res["tx_investment_oi"] + res["tx_dealer_oi"]
        res["mtx_inst_total_oi"] = res["mtx_foreign_oi"] + res["mtx_investment_oi"] + res["mtx_dealer_oi"]
        return res
    except Exception as e:
        print(f"[!] 抓取 TAIFEX 三大法人失敗 ({trade_date}): {e}")
        return res


def fetch_taifex_market_total_oi(trade_date: str) -> Dict[str, float]:
    """
    抓取全市場 MTX 小台與 TX 大台未平倉總口數
    API: https://www.taifex.com.tw/cht/3/futDailyMarketReport?queryDate={YYYY%2FMM%2FDD}&MarketCode=0&commodity_id=MTX
    """
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    date_query = f"{dt.year:04d}%2F{dt.month:02d}%2F{dt.day:02d}"

    res = {"total_tx_oi": 0.0, "total_mtx_oi": 0.0}

    for comm_id in ["TX", "MTX"]:
        url = f"https://www.taifex.com.tw/cht/3/futDailyMarketReport?queryDate={date_query}&MarketCode=0&commodity_id={comm_id}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", class_="table_f")
            if not table:
                continue

            for r in table.find_all("tr"):
                cols = [c.text.strip() for c in r.find_all(["th", "td"])]
                if any("小計" in c for c in cols):
                    # 尋找未平倉數值
                    # 倒數欄位或數值欄
                    numeric_cols = []
                    for c in cols:
                        c_clean = c.replace(",", "")
                        try:
                            numeric_cols.append(float(c_clean))
                        except ValueError:
                            pass
                    if numeric_cols:
                        oi_val = numeric_cols[-1]
                        if comm_id == "TX":
                            res["total_tx_oi"] = oi_val
                        else:
                            res["total_mtx_oi"] = oi_val
        except Exception as e:
            print(f"[!] 抓取 TAIFEX 全市場 {comm_id} OI 失敗: {e}")

    return res


def download_taifex_futures_for_date(trade_date: str, output_dir: str = "./output_taifex", overwrite: bool = False) -> Optional[str]:
    """下載並計算單一交易日之期交所期貨籌碼指標"""
    os.makedirs(output_dir, exist_ok=True)
    out_filename = f"api_taifex_{trade_date}_{trade_date}.parquet"
    out_path = os.path.join(output_dir, out_filename)

    if os.path.exists(out_path) and not overwrite:
        print(f"[✓] {trade_date} 期交所資料已存在，跳過: {out_filename}")
        return out_path

    print(f"[*] 正在抓取 {trade_date} 期交所三大法人與散戶小台部位...")
    inst_data = fetch_taifex_institutional_oi(trade_date)
    time.sleep(0.5)
    market_data = fetch_taifex_market_total_oi(trade_date)

    total_mtx = market_data.get("total_mtx_oi", 0.0)
    total_tx = market_data.get("total_tx_oi", 0.0)

    # 散戶小台未平倉 = 小台全市場未平倉總口數 - 三大法人小台淨口數合計
    # 若 total_mtx 抓取異常，採保守計算
    inst_mtx_net = inst_data.get("mtx_inst_total_oi", 0.0)
    retail_mtx_net = (total_mtx - inst_mtx_net) if total_mtx > 0 else (-inst_mtx_net)
    retail_mtx_ratio_pct = round((retail_mtx_net / total_mtx * 100.0), 2) if total_mtx > 0 else 0.0

    foreign_tx = inst_data.get("tx_foreign_oi", 0.0)

    # 綜合宏觀市場情緒歸納
    if foreign_tx < -35000 and retail_mtx_ratio_pct > 10.0:
        macro_sentiment = "⚠️ 高危誘多：外資空單重壓 + 散戶追多"
    elif foreign_tx > 0 and retail_mtx_ratio_pct < -10.0:
        macro_sentiment = "🚀 極品軋空：外資作多 + 散戶放空"
    elif foreign_tx < -25000:
        macro_sentiment = "偏空避險：外資期貨空單沉重"
    elif foreign_tx > 5000:
        macro_sentiment = "偏多進攻：外資期貨同步作多"
    else:
        macro_sentiment = "中性震盪：期貨無極端部位"

    row = {
        "trade_date": trade_date,
        "foreign_tx_oi": foreign_tx,
        "investment_tx_oi": inst_data.get("tx_investment_oi", 0.0),
        "dealer_tx_oi": inst_data.get("tx_dealer_oi", 0.0),
        "institutional_tx_total_oi": inst_data.get("tx_inst_total_oi", 0.0),
        "foreign_mtx_oi": inst_data.get("mtx_foreign_oi", 0.0),
        "investment_mtx_oi": inst_data.get("mtx_investment_oi", 0.0),
        "dealer_mtx_oi": inst_data.get("mtx_dealer_oi", 0.0),
        "institutional_mtx_total_oi": inst_mtx_net,
        "total_tx_oi": total_tx,
        "total_mtx_oi": total_mtx,
        "retail_mtx_net": retail_mtx_net,
        "retail_mtx_ratio_pct": retail_mtx_ratio_pct,
        "macro_sentiment": macro_sentiment
    }

    df = pd.DataFrame([row])
    df.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"[✓] {trade_date} 期交所期貨指標已儲存: {out_filename} (外資大台: {foreign_tx:+,.0f}口, 散戶小台多空比: {retail_mtx_ratio_pct:+.2f}%)")
    return out_path


def backfill_taifex_range(start_date: str, end_date: str, output_dir: str = "./output_taifex", delay: float = 0.8):
    """批次回補歷史區間期交所資料"""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    cur_dt = start_dt

    dates = []
    while cur_dt <= end_dt:
        if cur_dt.weekday() < 5:
            dates.append(cur_dt.strftime("%Y-%m-%d"))
        cur_dt += timedelta(days=1)

    print("=" * 65)
    print(f"🚀 啟動期交所期權微觀指標歷史批次回補引擎")
    print(f"[*] 回補區間: {start_date} ~ {end_date} (共 {len(dates)} 個預計交易日)")
    print(f"[*] 輸出目錄: {output_dir}")
    print("=" * 65)

    success_count = 0
    for idx, d_str in enumerate(dates):
        print(f"\n[{idx+1}/{len(dates)}] 處理日期: {d_str}")
        res = download_taifex_futures_for_date(d_str, output_dir=output_dir)
        if res:
            success_count += 1
        time.sleep(delay)

    print("\n" + "★" * 65)
    print(f"[🎉] 期交所指標歷史回補完畢！成功產出 {success_count}/{len(dates)} 個交易日檔案。")
    print("★" * 65)


def main():
    parser = argparse.ArgumentParser(description="期交所三大法人期貨未平倉與散戶小台多空比爬蟲")
    parser.add_argument("--date", default="", help="指定單一交易日 (YYYY-MM-DD)")
    parser.add_argument("--start-date", default="", help="批次回補起始日 (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="", help="批次回補結束日 (YYYY-MM-DD，若未指定則為今日)")
    parser.add_argument("--output-dir", default="./output_taifex", help="Parquet 儲存目錄")
    parser.add_argument("--delay", type=float, default=0.8, help="批次請求間隔延遲 (秒，預設: 0.8)")
    parser.add_argument("--overwrite", action="store_true", help="強制重新下載覆蓋現有檔案")

    args = parser.parse_args()

    today_str = datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime("%Y-%m-%d")

    if args.start_date:
        end_d = args.end_date if args.end_date else today_str
        backfill_taifex_range(args.start_date, end_d, output_dir=args.output_dir, delay=args.delay)
        return

    target_d = args.date if args.date else today_str
    download_taifex_futures_for_date(target_d, output_dir=args.output_dir, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
