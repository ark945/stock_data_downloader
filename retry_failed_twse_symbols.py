import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from twse_bsr_crawler import TWSEBrokerCrawler


TAIPEI_TZ = timezone(timedelta(hours=8))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def get_taipei_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def extract_trade_date_from_log(log_path: str) -> Optional[str]:
    if not os.path.exists(log_path):
        return None

    patterns = [
        re.compile(r"執行交易日期:\s*(\d{4}-\d{2}-\d{2})"),
        re.compile(r"交易日期:\s*(\d{4}-\d{2}-\d{2})"),
    ]
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            for patt in patterns:
                m = patt.search(line)
                if m:
                    return m.group(1)

    base = os.path.basename(log_path)
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", base)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def extract_failed_symbols_from_log(log_path: str) -> List[Tuple[str, str]]:
    if not os.path.exists(log_path):
        raise FileNotFoundError(f"找不到 log 檔案: {log_path}")

    found = []
    seen = set()
    patt = re.compile(r"-\s*([0-9A-Z]+)\s*\((.*?)\):\s*(.+?)\s*$")

    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = patt.search(line.strip())
            if not m:
                continue
            symbol = m.group(1).strip()
            reason = m.group(3).strip()
            if not symbol or symbol in seen:
                continue
            found.append((symbol, reason))
            seen.add(symbol)

    return found


def parse_symbols_arg(symbols_text: Optional[str]) -> List[str]:
    if not symbols_text:
        return []
    return [item.strip().upper() for item in symbols_text.split(",") if item.strip()]


def read_symbols_file(symbols_file: Optional[str]) -> List[str]:
    if not symbols_file:
        return []
    if not os.path.exists(symbols_file):
        raise FileNotFoundError(f"找不到 symbols 檔案: {symbols_file}")

    symbols = []
    with open(symbols_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.strip().split("#", 1)[0].strip()
            if not raw:
                continue
            sym = raw.split()[0].strip().upper()
            if sym:
                symbols.append(sym)
    return symbols


def resolve_base_parquet(output_dir: str, trade_date: str, explicit_path: Optional[str]) -> Optional[str]:
    if explicit_path:
        return explicit_path

    candidates = [
        os.path.join(output_dir, f"api_absr1_{trade_date}_{trade_date}.parquet"),
        os.path.join(output_dir, f"api_absr1_{trade_date}_{trade_date}_twse.parquet"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def build_retry_output_paths(output_dir: str, trade_date: str) -> Tuple[str, str]:
    retry_dir = os.path.join(output_dir, "retries")
    os.makedirs(retry_dir, exist_ok=True)
    retry_parquet = os.path.join(retry_dir, f"api_absr1_{trade_date}_{trade_date}_twse_retry.parquet")
    failed_txt = os.path.join(retry_dir, f"twse_retry_remaining_failed_{trade_date}.txt")
    return retry_parquet, failed_txt


def merge_retry_into_base(base_parquet: str, retry_parquet: str, merged_output: Optional[str] = None) -> Tuple[str, int, int]:
    if not os.path.exists(base_parquet):
        raise FileNotFoundError(f"找不到基底 parquet: {base_parquet}")
    if not os.path.exists(retry_parquet):
        raise FileNotFoundError(f"找不到補跑 parquet: {retry_parquet}")

    base_df = pd.read_parquet(base_parquet)
    retry_df = pd.read_parquet(retry_parquet)
    full_df = pd.concat([base_df, retry_df], ignore_index=True)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)

    out_path = merged_output or base_parquet
    full_df.to_parquet(out_path, compression="zstd", index=False)
    return out_path, full_df["symbol"].nunique(), len(full_df)


def rewrite_excel_from_parquet(parquet_path: str, excel_path: Optional[str] = None) -> str:
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(f"找不到 parquet: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    out_excel = excel_path or os.path.splitext(parquet_path)[0] + ".xlsx"
    df.to_excel(out_excel, engine="openpyxl", index=False)
    return out_excel


def save_remaining_failed(failed_symbols: List[str], reason_map: dict, failed_txt: str):
    with open(failed_txt, "w", encoding="utf-8") as f:
        for sym in failed_symbols:
            reason = reason_map.get(sym, "unknown")
            f.write(f"{sym}\t{reason}\n")


def save_diagnostic_summary(diagnostics_dir: str, trade_date: str, stats: dict, target_symbols: List[str]):
    os.makedirs(diagnostics_dir, exist_ok=True)
    summary_path = os.path.join(diagnostics_dir, f"diagnostic_summary_{trade_date}.json")
    payload = {
        "trade_date": trade_date,
        "target_symbols": target_symbols,
        "status_counts": stats.get("status_counts", {}),
        "reason_counts": stats.get("reason_counts", {}),
        "technical_failure_reason_by_symbol": stats.get("technical_failure_reason_by_symbol", {}),
        "confirmed_no_data_symbols": stats.get("confirmed_no_data_symbols", []),
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return summary_path


def main():
    parser = argparse.ArgumentParser(description="TWSE 失敗標的補跑工具：可由 log 自動抽出失敗股票，補跑後合併回既有 parquet。")
    parser.add_argument("--date", type=str, default=None, help="交易日期 YYYY-MM-DD；未提供時會嘗試由 log 推斷")
    parser.add_argument("--log-path", type=str, default=None, help="來源執行 log；若提供可自動抽出失敗股票")
    parser.add_argument("--symbols", type=str, default=None, help="直接指定補跑股票清單，逗號分隔，如 2330,2317,2454")
    parser.add_argument("--symbols-file", type=str, default=None, help="每行一檔股票代碼的文字檔")
    parser.add_argument("--workers", type=int, default=1, help="TWSE 補跑 worker 數，預設 1")
    parser.add_argument("--max-rounds", type=int, default=10, help="TWSE 補跑輪數，預設 10")
    parser.add_argument("--output-dir", type=str, default=None, help="輸出目錄，預設為專案 output/")
    parser.add_argument("--diagnostics-dir", type=str, default=None, help="若提供，輸出單檔診斷 HTML / JSON 至指定資料夾")
    parser.add_argument("--diagnostic-symbols", type=str, default=None, help="只對指定股票輸出診斷檔，逗號分隔；未提供時代表對本次待補跑清單全部輸出")
    parser.add_argument("--base-parquet", type=str, default=None, help="要合併回去的基底 parquet；預設優先找全市場檔，再找 TWSE 檔")
    parser.add_argument("--merged-output", type=str, default=None, help="合併後 parquet 輸出路徑；未提供時直接覆寫 base parquet")
    parser.add_argument("--no-merge", action="store_true", help="只產出 retry parquet，不合併回基底 parquet")
    parser.add_argument("--rewrite-excel", action="store_true", help="合併成功後重建對應 Excel")
    args = parser.parse_args()

    root_dir = os.path.dirname(__file__)
    output_dir = args.output_dir or os.path.join(root_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    if not args.date and args.log_path:
        args.date = extract_trade_date_from_log(args.log_path)
    if not args.date:
        raise ValueError("無法判定交易日期，請提供 --date 或可解析交易日期的 --log-path")

    symbols = []
    symbols.extend(parse_symbols_arg(args.symbols))
    symbols.extend(read_symbols_file(args.symbols_file))

    failure_pairs = []
    if args.log_path:
        failure_pairs = extract_failed_symbols_from_log(args.log_path)
        symbols.extend([sym for sym, _ in failure_pairs])

    symbols = sorted(list(dict.fromkeys(symbols)))
    if not symbols:
        raise ValueError("未取得任何待補跑股票，請提供 --log-path、--symbols 或 --symbols-file")

    retry_parquet, failed_txt = build_retry_output_paths(output_dir, args.date)

    print("=" * 66)
    print("TWSE 失敗標的補跑工具啟動")
    print(f"[*] 交易日期: {args.date}")
    print(f"[*] 待補跑股票數: {len(symbols)} 檔")
    print(f"[*] 補跑 workers: {args.workers}")
    print(f"[*] 補跑輪數: {args.max_rounds}")
    if args.log_path:
        print(f"[*] 來源 log: {args.log_path}")
    if args.diagnostics_dir:
        print(f"[*] 診斷輸出目錄: {args.diagnostics_dir}")
    print("=" * 66)

    diagnostic_symbols = parse_symbols_arg(args.diagnostic_symbols) if args.diagnostic_symbols else symbols
    crawler = TWSEBrokerCrawler(
        delay_sec=0.3,
        max_retries=6,
        diagnostics_dir=args.diagnostics_dir,
        diagnostic_symbols=set(diagnostic_symbols) if args.diagnostics_dir else None,
    )
    dfs, failed_symbols, rounds = crawler.crawl_stocks(
        symbols=symbols,
        trade_date=args.date,
        max_workers=max(1, args.workers),
        max_retry_rounds=max(1, args.max_rounds),
    )

    if dfs:
        retry_df = pd.concat(dfs, ignore_index=True)
        retry_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
        retry_df.sort_values(by=["symbol", "broker_id"], inplace=True)
    else:
        retry_df = pd.DataFrame(columns=[
            "symbol", "trade_date", "broker_id", "buy_vol", "sell_vol", "net_vol",
            "buy_amt", "sell_amt", "net_amt", "buy_avg_price", "sell_avg_price", "turnover", "market_share"
        ])

    retry_df.to_parquet(retry_parquet, compression="zstd", index=False)
    retry_symbols = retry_df["symbol"].nunique() if not retry_df.empty else 0

    print(f"[OK] 補跑 parquet 已輸出: {retry_parquet}")
    print(f"[*] 補跑成功標的數: {retry_symbols} 檔 | 剩餘失敗: {len(failed_symbols)} 檔 | 執行輪數: {rounds}")

    reason_map = crawler.last_run_stats.get("technical_failure_reason_by_symbol", {}) if crawler.last_run_stats else {}
    save_remaining_failed(failed_symbols, reason_map, failed_txt)
    if failed_symbols:
        print(f"[!] 仍失敗標的清單已輸出: {failed_txt}")
    if args.diagnostics_dir and crawler.last_run_stats:
        summary_path = save_diagnostic_summary(args.diagnostics_dir, args.date, crawler.last_run_stats, symbols)
        print(f"[OK] 診斷摘要已輸出: {summary_path}")

    if args.no_merge:
        print("[*] 依設定略過合併回基底 parquet。")
        return

    base_parquet = resolve_base_parquet(output_dir, args.date, args.base_parquet)
    if not base_parquet:
        print("[!] 找不到可合併的基底 parquet，已保留 retry parquet 供後續手動處理。")
        return

    merged_path, merged_symbols, merged_rows = merge_retry_into_base(
        base_parquet=base_parquet,
        retry_parquet=retry_parquet,
        merged_output=args.merged_output,
    )
    print(f"[OK] 已合併回基底 parquet: {merged_path}")
    print(f"[*] 合併後標的數: {merged_symbols} 檔 | 合併後資料筆數: {merged_rows:,} 列")

    if args.rewrite_excel:
        excel_path = rewrite_excel_from_parquet(merged_path)
        print(f"[OK] 已重建 Excel: {excel_path}")


if __name__ == "__main__":
    main()
