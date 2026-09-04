"""
全市場分點爬蟲分片聚合器 (Merge Shards & Multi-Channel Notifier)
專門將分散式 Matrix 矩陣產生的多個 Parquet 片段與 Log 日誌合併為標準格式：
1. 依據 market 參數產生標準 Parquet 檔名：
   - 上市：api_absr1_YYYY-MM-DD_YYYY-MM-DD_twse.parquet
   - 上櫃：api_absr1_YYYY-MM-DD_YYYY-MM-DD_tpex.parquet
   - 全市場：api_absr1_YYYY-MM-DD_YYYY-MM-DD.parquet (TWSE + TPEX 雙市場聚合)
2. 彙整分片日誌並上傳至 Google Drive 的 Log 資料夾：
   - 上市：YYYY-MM-DD-twse.log
   - 上櫃：YYYY-MM-DD-tpex.log (相容 YYYY-MM-DD-tpse.log)
3. Google Drive 雲端同步 (資料庫放根目錄，Log 放 Log/ 目錄)
4. Telegram 即時推播 (附 Google Drive 直連)
5. SMTP HTML Email 完整視覺化報表
"""

import os
import re
import sys
import glob
import time
import shutil
import smtplib
from typing import Optional, Dict, Any, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> bool:
    """發送 Telegram 即時推播"""
    if not bot_token or not chat_id:
        print("[*] 提示：未配置 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 推播。")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        r = requests.post(url, json=payload, timeout=12)
        if r.status_code == 200:
            print("[✓] Telegram 推播通知發送成功！")
            return True
        else:
            print(f"[!] Telegram 推播失敗 (HTTP {r.status_code}): {r.text}")
            return False
    except Exception as e:
        print(f"[!] Telegram 發送異常: {e}")
        return False


def send_email_notification(
    trade_date: str,
    total_symbols: int,
    total_rows: int,
    file_size_mb: float,
    market: str = "all",
    gdrive_link: Optional[str] = None,
    market_details: Optional[dict] = None
):
    """發送全市場聚合完成 Email 推播通知 (含 TWSE 與 TPEX 獨立統計明細)"""
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com") or "smtp.gmail.com"
    port_str = (os.environ.get("SMTP_PORT") or "").strip()
    smtp_port = int(port_str) if port_str.isdigit() else 587
    
    sender_email = (
        os.environ.get("SENDER_EMAIL") or 
        os.environ.get("SMTP_USER") or 
        ""
    ).strip()
    
    sender_pwd = (
        os.environ.get("SENDER_PASSWORD") or 
        os.environ.get("SMTP_PASSWORD") or 
        ""
    ).strip()
    
    receiver_email = (
        os.environ.get("RECEIVER_EMAIL") or 
        os.environ.get("NOTIFICATION_EMAIL") or 
        sender_email
    ).strip()

    if not sender_email or not sender_pwd:
        print("[*] 提示：未配置 SENDER_EMAIL (或 SMTP_USER) 與 SENDER_PASSWORD，略過 Email 發送。")
        return False

    market_title = "上市 (TWSE)" if market.lower() == "twse" else ("上櫃 (TPEX)" if market.lower() == "tpex" else "全市場 (上市+上櫃)")
    node_desc = "6 個獨立 IP 並行" if market.lower() == "twse" else ("8 個獨立 IP 並行" if market.lower() == "tpex" else "14 個獨立矩陣節點並行")

    # 構建分市場細部數據表格 (TWSE vs TPEX)
    market_breakdown_html = ""
    if market_details and market.lower() == "all":
        tw_sym = market_details.get("twse_symbols", 0)
        tw_row = market_details.get("twse_rows", 0)
        tp_sym = market_details.get("tpex_symbols", 0)
        tp_row = market_details.get("tpex_rows", 0)
        market_breakdown_html = f"""
        <div style="margin-top: 15px; margin-bottom: 20px;">
            <div style="font-size: 13px; font-weight: bold; color: #4a5568; margin-bottom: 8px;">🏢 雙市場明細拆解 (TWSE 上市 vs TPEX 上櫃)</div>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; background: #fafbfc; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
                <thead>
                    <tr style="background: #edf2f7; color: #4a5568; text-align: left;">
                        <th style="padding: 8px 12px;">市場名稱</th>
                        <th style="padding: 8px 12px; text-align: right;">有效標的數</th>
                        <th style="padding: 8px 12px; text-align: right;">成交明細筆數</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid #edf2f7;">
                        <td style="padding: 8px 12px; font-weight: bold; color: #2b6cb0;">🏛️ 上市 (TWSE)</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2d3748; font-weight: bold;">{tw_sym:,} 檔</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2f855a; font-weight: bold;">{tw_row:,} 筆</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #edf2f7;">
                        <td style="padding: 8px 12px; font-weight: bold; color: #d69e2e;">🏪 上櫃 (TPEX)</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2d3748; font-weight: bold;">{tp_sym:,} 檔</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2f855a; font-weight: bold;">{tp_row:,} 筆</td>
                    </tr>
                    <tr style="background: #f7fafc; font-weight: bold;">
                        <td style="padding: 8px 12px; color: #1a202c;">🌐 全市場合計</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2b6cb0;">{total_symbols:,} 檔</td>
                        <td style="padding: 8px 12px; text-align: right; color: #2f855a;">{total_rows:,} 筆</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """

    try:
        is_gh = os.environ.get("GITHUB_ACTIONS") == "true"
        source_tag = "【雲端抓檔】" if is_gh else "【本機抓檔】"
        subject = f"🚀 {source_tag} 【台股{market_title}分點日報】{trade_date} 雲端矩陣採集完成 ({total_symbols:,} 檔 / {total_rows:,} 筆)"
        gdrive_btn = f"""
        <div style="margin: 25px 0; text-align: center;">
            <a href="{gdrive_link}" style="background-color: #1a73e8; color: #ffffff; padding: 12px 25px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">
                ☁️ 前往 Google Drive 檢視與下載資料庫
            </a>
        </div>
        """ if gdrive_link else ""

        html_body = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f6f9; padding: 25px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
                <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: #ffffff; padding: 25px; text-align: center;">
                    <h2 style="margin: 0; font-size: 22px;">📊 台股{market_title}分點買賣日報表</h2>
                    <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">雲端分散式矩陣極速採集成功</p>
                </div>
                <div style="padding: 25px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 10px;">
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📅 交易日期</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2d3748;">{trade_date}</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">🎯 目標市場</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2b6cb0;">{market.upper()} ({market_title})</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">🏢 總涵蓋標的數</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2b6cb0;">{total_symbols:,} 檔</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📈 總明細筆數</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2f855a;">{total_rows:,} 列</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📦 資料庫容量</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #4a5568;">{file_size_mb:.2f} MB (Parquet)</td></tr>
                        <tr><td style="padding: 10px 0; color: #718096; font-size: 14px;">⚡ 雲端矩陣節點</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #d69e2e;">{node_desc}</td></tr>
                    </table>

                    {market_breakdown_html}

                    {gdrive_btn}
                    <div style="background: #ebf8ff; border-left: 4px solid #3182ce; padding: 12px 15px; border-radius: 4px; font-size: 13px; color: #2b6cb0;">
                        ✅ <b>全市場完整採集</b>：所有上市與上櫃個股分點明細與執行日誌已標準化歸檔至 Google Drive。
                    </div>
                </div>
                <div style="background: #f7fafc; padding: 15px; text-align: center; color: #a0aec0; font-size: 12px; border-top: 1px solid #edf2f7;">
                    此郵件由 GitHub Actions 全自動排程系統發送 • {get_taipei_now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        print(f"[*] 正在連線 SMTP 伺服器 ({smtp_server}:{smtp_port}) 發送 Email 至 {receiver_email}...")
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
        server.starttls()
        server.login(sender_email, sender_pwd)
        server.sendmail(sender_email, [receiver_email], msg.as_string())
        server.quit()
        print(f"[✓] Email 報表發送成功！(收件人: {receiver_email})")
        return True

    except Exception as e:
        print(f"[!] Email 發送失敗: {e}")
        return False


def extract_shard_number(file_path: str) -> int:
    """從日誌檔名或路徑中提取 shard 編號以進行數值排序"""
    match = re.search(r"shard_(\d+)", file_path, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match_num = re.search(r"_(\d+)\.log", file_path, re.IGNORECASE)
    if match_num:
        return int(match_num.group(1))
    return 9999


def merge_log_shards(market: str = "twse", trade_date: str = "", output_dir: str = "output") -> Optional[str]:
    """
    彙整指定市場 (TWSE / TPEX) 的所有分片執行日誌，輸出為 YYYY-MM-DD-twse.log / YYYY-MM-DD-tpex.log
    並自動上傳至 Google Drive 的 Log 資料夾
    """
    market_lower = market.lower().strip()
    if market_lower not in ["twse", "tpex"]:
        print(f"[*] 市場 {market} 略過獨立分片 Log 彙整")
        return None

    if not trade_date:
        trade_date = get_taipei_now().strftime("%Y-%m-%d")

    print(f"\n==================================================")
    print(f"[*] 開始彙整 {market.upper()} 分片日誌 (Log Consolidation)...")
    print(f"[*] 交易日期: {trade_date}")
    print(f"==================================================")

    # 搜尋分片 Log 檔案 (支援 logs/, output/logs/, download_shards/ 等路徑)
    search_patterns = [
        os.path.join(output_dir, "logs", f"crawler_{market_lower}_shard_*.log"),
        os.path.join(output_dir, f"crawler_{market_lower}_shard_*.log"),
        os.path.join("logs", f"crawler_{market_lower}_shard_*.log"),
        os.path.join("download_shards", "**", f"crawler_{market_lower}_shard_*.log"),
    ]

    found_logs = set()
    for pat in search_patterns:
        for f in glob.glob(pat, recursive=True):
            found_logs.add(os.path.abspath(f))

    log_files = sorted(list(found_logs), key=extract_shard_number)

    if not log_files:
        print(f"[!] 未找到任何 {market.upper()} 分片日誌檔案 (crawler_{market_lower}_shard_*.log)")
        return None

    print(f"[+] 找到 {len(log_files)} 個 {market.upper()} 分片日誌檔案，正在按 Shard 順序彙整：")
    for f in log_files:
        print(f"  - Shard {extract_shard_number(f)}: {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")

    final_log_filename = f"{trade_date}-{market_lower}.log"
    out_logs_dir = os.path.join(output_dir, "logs")
    os.makedirs(out_logs_dir, exist_ok=True)
    final_log_path = os.path.join(out_logs_dir, final_log_filename)

    with open(final_log_path, "w", encoding="utf-8") as outfile:
        outfile.write(f"{'='*80}\n")
        outfile.write(f"📊 台股券商分點爬蟲 - 【{market.upper()}】全分片執行日誌整合報表\n")
        outfile.write(f"📅 交易日期: {trade_date}\n")
        outfile.write(f"🕒 彙整時戳: {get_taipei_now().strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)\n")
        outfile.write(f"⚡ 彙整分片數量: {len(log_files)} 個獨立節點\n")
        outfile.write(f"{'='*80}\n\n")

        for log_f in log_files:
            shard_id = extract_shard_number(log_f)
            outfile.write(f"\n{'='*80}\n")
            outfile.write(f">>> 【{market.upper()} 分片節點 Shard #{shard_id}】執行紀錄: {os.path.basename(log_f)}\n")
            outfile.write(f"{'='*80}\n")
            try:
                with open(log_f, "r", encoding="utf-8", errors="replace") as infile:
                    content = infile.read()
                    outfile.write(content)
                    if not content.endswith("\n"):
                        outfile.write("\n")
            except Exception as e:
                outfile.write(f"[!] 讀取日誌內容失敗: {e}\n")

    # 複製一份至 output 根目錄方便 Actions 產物收集
    root_log_path = os.path.join(output_dir, final_log_filename)
    try:
        shutil.copy2(final_log_path, root_log_path)
    except Exception:
        pass

    log_size_kb = os.path.getsize(final_log_path) / 1024
    print(f"[✓] {market.upper()} 分片日誌彙整完成: {final_log_path} ({log_size_kb:.1f} KB)")

    # 若為 tpex，同時產出一份相容別名 yyyy-mm-dd-tpse.log
    if market_lower == "tpex":
        tpse_alias_path = os.path.join(out_logs_dir, f"{trade_date}-tpse.log")
        try:
            shutil.copy2(final_log_path, tpse_alias_path)
            shutil.copy2(final_log_path, os.path.join(output_dir, f"{trade_date}-tpse.log"))
        except Exception:
            pass

    # 自動同步上傳至 Google Drive 的 "Log" 資料夾
    try:
        from gdrive_sync import upload_file_to_gdrive
        print(f"[*] 正在將彙整日誌 {final_log_filename} 上傳至 Google Drive 的 'Log' 資料夾...")
        gdrive_res = upload_file_to_gdrive(final_log_path, subfolder="Log")
        if gdrive_res:
            print(f"[✓] 日誌已成功同步至 Google Drive Log 資料夾！(ID: {gdrive_res.get('file_id')})")
    except Exception as e:
        print(f"[!] 上傳日誌至 Google Drive 異常: {e}")

    return final_log_path


def merge_parquet_shards(output_dir: str = "output", trade_date: str = "", market: str = "all"):
    """
    彙整 Parquet 分片檔案：
    - market == "twse": 合併上市分片 -> api_absr1_{date}_{date}_twse.parquet + 彙整 TWSE 日誌
    - market == "tpex": 合併上櫃分片 -> api_absr1_{date}_{date}_tpex.parquet + 彙整 TPEX 日誌
    - market == "all": 合併上市與上櫃資料庫 -> api_absr1_{date}_{date}.parquet (全市場整合檔)
    """
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), output_dir)
    os.makedirs(output_dir, exist_ok=True)

    market = (market or os.environ.get("MARKET") or "all").lower().strip()
    market_suffix = f"_{market}" if market in ["twse", "tpex"] else ""
    market_title = "上市 (TWSE)" if market == "twse" else ("上櫃 (TPEX)" if market == "tpex" else "全市場 (上市+上櫃整合)")

    print(f"==================================================")
    print(f"[*] 全市場分片聚合器 (Merge Shards) 啟動")
    print(f"[*] 目標市場範疇 (Market): {market.upper()} ({market_title})")
    print(f"[*] 掃描分片路徑: {output_dir}")
    print(f"==================================================")
    sys.stdout.flush()

    # 1. 搜尋待合併的 Parquet 檔案
    target_files = []
    if market == "all":
        # 全市場模式：優先尋找已產出的上市與上櫃標準檔，若無則搜尋全部分片檔
        twse_and_tpex = glob.glob(os.path.join(output_dir, "api_absr1_*_twse.parquet")) + \
                        glob.glob(os.path.join(output_dir, "api_absr1_*_tpex.parquet")) + \
                        glob.glob(os.path.join("download_shards", "**", "api_absr1_*_twse.parquet"), recursive=True) + \
                        glob.glob(os.path.join("download_shards", "**", "api_absr1_*_tpex.parquet"), recursive=True)
        target_files = sorted(list(set(twse_and_tpex)))
        if not target_files:
            # 備援搜尋全部分片檔
            target_files = sorted(glob.glob(os.path.join(output_dir, "*_shard_*.parquet")))
            if not target_files:
                target_files = sorted(glob.glob(os.path.join(".", "**", "*_shard_*.parquet"), recursive=True))
    else:
        shard_glob = f"*_{market}_shard_*.parquet"
        target_files = sorted(glob.glob(os.path.join(output_dir, shard_glob)))
        if not target_files:
            target_files = sorted(glob.glob(os.path.join(".", "**", shard_glob), recursive=True))
            if target_files:
                for sf in target_files:
                    dest = os.path.join(output_dir, os.path.basename(sf))
                    shutil.copy2(sf, dest)
                target_files = sorted(glob.glob(os.path.join(output_dir, shard_glob)))

    if not target_files:
        err_msg = f"[!] 嚴重錯誤: 未找到任何待聚合的 {market.upper()} 分片檔案！無法進行合併。"
        print(err_msg, file=sys.stderr)
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
        if tg_token and tg_chat:
            send_telegram_alert(tg_token, tg_chat, f"🚨 *【分片聚合中斷警報】*\n市場: `{market.upper()}`\n原因: 未找到任何待聚合分片！已強制阻斷以防殘缺資料。")
        sys.exit(1)

    # 嚴格分片完整性檢查 (Strict Integrity Guard)
    if market in ["twse", "tpex"]:
        expected_count = 6 if market == "twse" else 8
        found_shards = set()
        for f in target_files:
            m = re.search(rf"{market}_shard_(\d+)", os.path.basename(f), re.IGNORECASE)
            if m:
                found_shards.add(int(m.group(1)))
        
        expected_set = set(range(expected_count))
        missing_shards = expected_set - found_shards
        if missing_shards:
            sep = "=" * 70
            err_msg = (
                f"\n{sep}\n"
                f"❌ [嚴重錯誤] {market.upper()} 分片缺失！嚴禁產出殘缺資料庫！\n"
                f"   - 預期分片總數: {expected_count} 個 (Shard 0 ~ {expected_count - 1})\n"
                f"   - 實際取得分片: {len(found_shards)} 個 ({sorted(list(found_shards))})\n"
                f"   - 缺漏分片編號: {sorted(list(missing_shards))}\n"
                f"⚠️ 為確保全市場交易資料之 100% 完整性，流程立即中斷 (Fail-Closed)！\n"
                f"{sep}\n"
            )
            print(err_msg, file=sys.stderr)
            tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
            if tg_token and tg_chat:
                send_telegram_alert(
                    tg_token, tg_chat,
                    f"🚨 *【{market.upper()} 分片短缺致命警報】*\n"
                    f"📅 日期: `{trade_date or get_taipei_now().strftime('%Y-%m-%d')}`\n"
                    f"❌ 缺漏分片: `Shard {sorted(list(missing_shards))}`\n"
                    f"🛑 系統已主動中斷聚合，嚴防殘缺數據上傳覆蓋雲端資料庫！"
                )
            sys.exit(1)
    elif market == "all":
        has_twse = any("_twse" in os.path.basename(f).lower() for f in target_files)
        has_tpex = any("_tpex" in os.path.basename(f).lower() for f in target_files)
        if not (has_twse and has_tpex):
            err_msg = f"❌ [嚴重錯誤] 全市場聚合缺少市場檔案！(TWSE: {has_twse}, TPEX: {has_tpex})，立即中斷！\n"
            print(err_msg, file=sys.stderr)
            sys.exit(1)


    print(f"[+] 找到 {len(target_files)} 個待合併 Parquet 檔案:")
    for f in target_files:
        print(f"  - {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")

    dfs = []
    for f in target_files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
            print(f"  [✓] 讀取 {os.path.basename(f)}: {len(df):,} 列 (標的: {df['symbol'].nunique()} 檔)")
        except Exception as e:
            print(f"  [!] 讀取 {f} 失敗: {e}")

    if not dfs:
        print("[!] 無有效資料可供合併！")
        return

    full_df = pd.concat(dfs, ignore_index=True)
    full_df.drop_duplicates(subset=["symbol", "trade_date", "broker_id"], inplace=True)
    full_df.sort_values(by=["symbol", "broker_id"], inplace=True)

    if not trade_date and "trade_date" in full_df.columns:
        trade_date = str(full_df["trade_date"].iloc[0]).strip()

    final_filename = f"api_absr1_{trade_date}_{trade_date}{market_suffix}.parquet"
    final_parquet = os.path.join(output_dir, final_filename)
    full_df.to_parquet(final_parquet, compression="zstd", index=False)

    total_symbols = full_df["symbol"].nunique()
    total_rows = len(full_df)
    file_size_mb = os.path.getsize(final_parquet) / (1024 * 1024)

    print("==================================================")
    print(f"[✓] Parquet 資料聚合完成！")
    print(f"[*] 交易日期: {trade_date}")
    print(f"[*] 目標市場: {market.upper()} ({market_title})")
    print(f"[*] 涵蓋標的數: {total_symbols:,} 檔")
    print(f"[*] 總資料筆數: {total_rows:,} 列")
    print(f"[*] 產檔規格命名: {final_filename} ({file_size_mb:.2f} MB)")
    print("==================================================")

    # 2. 執行分片 Log 彙整 (TWSE 與 TPEX 模式下)
    if market in ["twse", "tpex"]:
        merge_log_shards(market=market, trade_date=trade_date, output_dir=output_dir)

    # 清理中間分片檔 (全市場整合檔保留 twse / tpex 檔，僅刪除 shard_ 檔案)
    for f in target_files:
        if "_shard_" in os.path.basename(f):
            try: os.remove(f)
            except OSError: pass

    # 3. 自動同步上傳 Parquet 資料庫至 Google Drive 根目錄
    gdrive_link = None
    try:
        from gdrive_sync import upload_file_to_gdrive
        gdrive_res = upload_file_to_gdrive(final_parquet)
        if gdrive_res:
            gdrive_link = gdrive_res.get("web_view_link")
    except Exception as e:
        print(f"[!] Google Drive 同步異常: {e}")

    # 4. Telegram 即時推播
    tg_bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_bot and tg_chat:
        gdrive_str = f"☁️ *Google Drive*：[點此立即檢視/下載]({gdrive_link})\n" if gdrive_link else ""
        node_str = "6 個獨立 IP 節點平行極速完成！" if market == "twse" else ("8 個獨立 IP 節點平行極速完成！" if market == "tpex" else "TWSE + TPEX 全市場 14 節點矩陣聚合完成！")
        tg_msg = (
            f"🚀 *【台股{market_title}分點日報表】雲端矩陣極速採集完成！*\n\n"
            f"📅 *交易日期*：`{trade_date}`\n"
            f"🎯 *目標市場*：`{market.upper()}` ({market_title})\n"
            f"📊 *涵蓋標的*：`{total_symbols:,}` 檔\n"
            f"📈 *明細筆數*：`{total_rows:,}` 筆\n"
            f"📦 *產檔規格*：`{final_filename}` (`{file_size_mb:.2f} MB`)\n"
            f"⚡ *雲端分散式矩陣*：{node_str}\n"
            f"{gdrive_str}\n"
            f"✅ 資料庫與日誌已自動歸檔至 Google Drive！"
        )
        send_telegram_alert(tg_bot, tg_chat, tg_msg)
    else:
        print("[*] 提示：未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 發送。")

    # 5. Email 報表發送 (含雙市場細部拆解)
    market_details = {}
    if market == "all":
        try:
            for f in target_files:
                base_n = os.path.basename(f).lower()
                if "twse" in base_n:
                    tdf = pd.read_parquet(f)
                    market_details["twse_symbols"] = tdf["symbol"].nunique()
                    market_details["twse_rows"] = len(tdf)
                elif "tpex" in base_n:
                    pdf = pd.read_parquet(f)
                    market_details["tpex_symbols"] = pdf["symbol"].nunique()
                    market_details["tpex_rows"] = len(pdf)
        except Exception:
            pass

    send_email_notification(
        trade_date=trade_date,
        total_symbols=total_symbols,
        total_rows=total_rows,
        file_size_mb=file_size_mb,
        market=market,
        gdrive_link=gdrive_link,
        market_details=market_details
    )


if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else ""
    t_market = sys.argv[2] if len(sys.argv) > 2 else "all"
    merge_parquet_shards("output", t_date, t_market)

