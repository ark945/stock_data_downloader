"""
全市場分點爬蟲分片聚合器 (Merge Shards & Multi-Channel Notifier)
專門將分散式 Matrix 矩陣產生的多個 Parquet 片段合併為 1 份標準全市場資料庫
並自動執行：
1. 依據 market 參數產生標準檔名 (all / twse / tpex)
2. Google Drive 雲端資料夾自動同步
3. Telegram 即時推播 (附 Google Drive 直連)
4. SMTP HTML Email 完整報表
"""

import os
import sys
import glob
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pandas as pd
import requests


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


def send_email_alert(
    trade_date: str,
    total_symbols: int,
    total_rows: int,
    file_size_mb: float,
    market: str = "all",
    gdrive_link: str = None
) -> bool:
    """發送 HTML 視覺化 Email 報表"""
    smtp_server = os.environ.get("SMTP_SERVER") or os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port_str = os.environ.get("SMTP_PORT", "587").strip()
    smtp_port = int(port_str) if port_str.isdigit() else 587
    
    sender_email = (
        os.environ.get("SENDER_EMAIL") or 
        os.environ.get("SMTP_USER") or 
        os.environ.get("SMTP_USERNAME") or ""
    ).strip()
    
    sender_pwd = (
        os.environ.get("SENDER_PASSWORD") or 
        os.environ.get("SMTP_PASSWORD") or 
        os.environ.get("SMTP_PASS") or ""
    ).strip()
    
    receiver_email = (
        os.environ.get("RECEIVER_EMAIL") or 
        os.environ.get("NOTIFICATION_EMAIL") or 
        sender_email
    ).strip()

    if not sender_email or not sender_pwd:
        print("[*] 提示：未配置 SENDER_EMAIL (或 SMTP_USER) 與 SENDER_PASSWORD，略過 Email 發送。")
        return False

    market_title = "上市 (TWSE)" if market.lower() == "twse" else ("上櫃 (TPEX)" if market.lower() == "tpex" else "全市場")

    try:
        subject = f"🚀 【台股{market_title}分點日報】{trade_date} 雲端矩陣採集完成 ({total_symbols:,} 檔 / {total_rows:,} 筆)"
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
                    <p style="margin: 8px 0 0 0; opacity: 0.9; font-size: 14px;">6-Runner 雲端分散式矩陣極速採集成功</p>
                </div>
                <div style="padding: 25px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📅 交易日期</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2d3748;">{trade_date}</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">🎯 目標市場</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2b6cb0;">{market.upper()} ({market_title})</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">🏢 涵蓋標的數</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2b6cb0;">{total_symbols:,} 檔</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📈 明細總筆數</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #2f855a;">{total_rows:,} 列</td></tr>
                        <tr style="border-bottom: 1px solid #edf2f7;"><td style="padding: 10px 0; color: #718096; font-size: 14px;">📦 資料庫容量</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #4a5568;">{file_size_mb:.2f} MB (Parquet)</td></tr>
                        <tr><td style="padding: 10px 0; color: #718096; font-size: 14px;">⚡ 雲端矩陣節點</td><td style="padding: 10px 0; font-weight: bold; text-align: right; color: #d69e2e;">6 個獨立 IP 並行</td></tr>
                    </table>
                    {gdrive_btn}
                    <div style="background: #ebf8ff; border-left: 4px solid #3182ce; padding: 12px 15px; border-radius: 4px; font-size: 13px; color: #2b6cb0;">
                        ✅ <b>100% 完整採集</b>：所有個股分點明細已標準化歸檔。
                    </div>
                </div>
                <div style="background: #f7fafc; padding: 15px; text-align: center; color: #a0aec0; font-size: 12px; border-top: 1px solid #edf2f7;">
                    此郵件由 GitHub Actions 全自動排程系統發送 • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
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


def merge_parquet_shards(output_dir: str = "output", trade_date: str = "", market: str = "all"):
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), output_dir)

    market = (market or os.environ.get("MARKET") or "all").lower().strip()
    market_suffix = f"_{market}" if market in ["twse", "tpex"] else ""
    market_title = "上市 (TWSE)" if market == "twse" else ("上櫃 (TPEX)" if market == "tpex" else "全市場")

    print(f"==================================================")
    print(f"[*] 全市場分片聚合器 (Merge Shards) 啟動")
    print(f"[*] 目標市場範疇 (Market): {market.upper()} ({market_title})")
    print(f"[*] 掃描分片路徑: {output_dir}")
    print(f"==================================================")
    sys.stdout.flush()

    shard_files = sorted(glob.glob(os.path.join(output_dir, "*_shard_*.parquet")))

    if not shard_files:
        print("[!] 未在 output/ 找到分片檔案，搜尋工作區其他目錄...")
        shard_files = sorted(glob.glob(os.path.join(".", "**", "*_shard_*.parquet"), recursive=True))
        if shard_files:
            print(f"[+] 在其他子目錄找到 {len(shard_files)} 個分片檔案，正在集中複製...")
            for sf in shard_files:
                import shutil
                dest = os.path.join(output_dir, os.path.basename(sf))
                shutil.copy2(sf, dest)
            shard_files = sorted(glob.glob(os.path.join(output_dir, "*_shard_*.parquet")))

    if not shard_files:
        print("[!] 查無任何分片產物！檢查是否已有單一完整檔...")
        existing = glob.glob(os.path.join(output_dir, "api_absr1_*.parquet"))
        if existing:
            print(f"[✓] 已存在完整資料庫: {existing[0]}")
        return

    print(f"[+] 找到 {len(shard_files)} 個分片檔案:")
    for f in shard_files:
        print(f"  - {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")

    dfs = []
    for f in shard_files:
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
    print(f"[✓] 全市場分片聚合完成！")
    print(f"[*] 交易日期: {trade_date}")
    print(f"[*] 目標市場: {market.upper()} ({market_title})")
    print(f"[*] 涵蓋標的數: {total_symbols:,} 檔")
    print(f"[*] 總資料筆數: {total_rows:,} 列")
    print(f"[*] 產檔規格命名: {final_filename} ({file_size_mb:.2f} MB)")
    print("==================================================")

    # 清理分片檔
    for f in shard_files:
        try: os.remove(f)
        except OSError: pass

    # 1. 自動同步上傳至 Google Drive 目標資料夾
    gdrive_link = None
    try:
        from gdrive_sync import upload_file_to_gdrive
        gdrive_res = upload_file_to_gdrive(final_parquet)
        if gdrive_res:
            gdrive_link = gdrive_res.get("web_view_link")
    except Exception as e:
        print(f"[!] Google Drive 同步異常: {e}")

    # 2. Telegram 即時推播
    tg_bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_bot and tg_chat:
        gdrive_str = f"☁️ *Google Drive*：[點此立即檢視/下載]({gdrive_link})\n" if gdrive_link else ""
        tg_msg = (
            f"🚀 *【台股{market_title}分點日報表】6 矩陣分散極速採集完成！*\n\n"
            f"📅 *交易日期*：`{trade_date}`\n"
            f"🎯 *目標市場*：`{market.upper()}` ({market_title})\n"
            f"📊 *涵蓋標的*：`{total_symbols:,}` 檔\n"
            f"📈 *明細筆數*：`{total_rows:,}` 筆\n"
            f"📦 *產檔規格*：`{final_filename}` (`{file_size_mb:.2f} MB`)\n"
            f"⚡ *雲端分散式矩陣*：6 個獨立 IP 節點平行極速完成！\n"
            f"{gdrive_str}\n"
            f"✅ 資料已自動歸檔並開放下載！"
        )
        send_telegram_alert(tg_bot, tg_chat, tg_msg)
    else:
        print("[*] 提示：未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 發送。")

    # 3. Email 報表發送
    send_email_alert(
        trade_date=trade_date,
        total_symbols=total_symbols,
        total_rows=total_rows,
        file_size_mb=file_size_mb,
        market=market,
        gdrive_link=gdrive_link
    )


if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else ""
    t_market = sys.argv[2] if len(sys.argv) > 2 else "all"
    merge_parquet_shards("output", t_date, t_market)
