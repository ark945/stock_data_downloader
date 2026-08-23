"""
台股分點爬蟲通知引擎 (Notification Engine)
支援：
- Telegram Bot 即時推播 (極速、手機推播、零密碼風險)
- SMTP Email 報表 (HTML 視覺化表格)
"""

import os
import sys
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from datetime import datetime


def send_telegram_report(
    trade_date: str,
    total_target: int,
    success_count: int,
    no_trade_count: int,
    failed_stocks: List[Dict[str, str]],
    total_rows: int,
    elapsed_seconds: float,
    rounds_executed: int,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> bool:
    """發送 Telegram 即時推播報表"""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not cid:
        print("[*] 未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 推播。")
        return False

    failed_count = len(failed_stocks)
    completion_rate = ((success_count + no_trade_count) / total_target * 100) if total_target > 0 else 0
    status_icon = "✅" if failed_count == 0 else ("⚠️" if failed_count < 10 else "❌")
    status_text = "全市場 100% 完整產出" if failed_count == 0 else f"存在 {failed_count} 檔短缺"

    msg_lines = [
        f"{status_icon} *【台股全市場分點爬蟲日報】*",
        f"📅 *交易日期*: `{trade_date}`",
        f"🎯 *達成率*: `{completion_rate:.1f}%` ({status_text})",
        f"📊 *總資料筆數*: `{total_rows:,}` 列",
        f"📈 *成功/無交易*: `{success_count}` 檔 / `{no_trade_count}` 檔",
        f"⏱️ *執行耗時*: `{elapsed_seconds/60:.1f}` 分鐘 (共執行 `{rounds_executed}/5` 輪)",
    ]

    if failed_count > 0:
        msg_lines.append(f"\n⚠️ *最終短缺股票清單 (共 {failed_count} 檔)*:")
        for idx, item in enumerate(failed_stocks[:40], 1):
            msg_lines.append(f"  `{idx}.` *{item.get('symbol')}* {item.get('name', '未知')} ({item.get('market', '')})")
        if failed_count > 40:
            msg_lines.append(f"  _...其餘 {failed_count - 40} 檔已省略_")
    else:
        msg_lines.append("\n🎉 *全市場 0 遺漏，完美收工！*")

    msg_lines.append(f"\n🕒 _推播時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    full_msg = "\n".join(msg_lines)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": full_msg,
        "parse_mode": "Markdown"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[✓] Telegram 推播發送成功！(Chat ID: {cid})")
            return True
        else:
            print(f"[!] Telegram 推播失敗 (HTTP {resp.status_code}): {resp.text}")
            return False
    except Exception as e:
        print(f"[!] Telegram 推播異常: {e}")
        return False


def send_crawler_report_email(
    trade_date: str,
    total_target: int,
    success_count: int,
    no_trade_count: int,
    failed_stocks: List[Dict[str, str]],
    total_rows: int,
    elapsed_seconds: float,
    rounds_executed: int,
    receiver_email: Optional[str] = None,
) -> bool:
    """發送爬蟲執行成果與短缺股票明細 Email (若有設定 SMTP)"""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    to_email = receiver_email or os.getenv("RECEIVER_EMAIL", smtp_user)

    if not smtp_user or not smtp_password or not to_email:
        return False

    failed_count = len(failed_stocks)
    completion_rate = ((success_count + no_trade_count) / total_target * 100) if total_target > 0 else 0
    status_emoji = "✅" if failed_count == 0 else ("⚠️" if failed_count < 10 else "❌")
    status_text = "全市場 100% 完整產出" if failed_count == 0 else f"存在 {failed_count} 檔短缺標的"

    subject = f"{status_emoji} 【台股分點爬蟲日報】{trade_date} 執行成果 — {status_text}"

    if failed_count > 0:
        table_rows = "".join([
            f"<tr style='border-bottom:1px solid #eee;'><td style='padding:8px;text-align:center;'>{i}</td><td style='padding:8px;font-weight:bold;color:#1a73e8;'>{item.get('symbol')}</td><td style='padding:8px;'>{item.get('name')}</td><td style='padding:8px;color:#d93025;'>{item.get('reason')}</td></tr>"
            for i, item in enumerate(failed_stocks, 1)
        ])
        missing_section = f"<h3 style='color:#d93025;'>⚠️ 短缺股票清單 ({failed_count} 檔)</h3><table style='width:100%;border-collapse:collapse;border:1px solid #eee;'><thead><tr style='background:#f8f9fa;'><th>序號</th><th>代碼</th><th>名稱</th><th>原因</th></tr></thead><tbody>{table_rows}</tbody></table>"
    else:
        missing_section = "<div style='padding:15px;background:#e6f4ea;color:#137333;'><b>🎉 完美達成！</b> 全市場無短缺。</div>"

    html_content = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f6f9;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:#fff;padding:20px;border-radius:8px;">
        <h2>📊 台股分點爬蟲日報 ({trade_date})</h2>
        <p>達成率: <b>{completion_rate:.1f}%</b> | 總筆數: <b>{total_rows:,}</b> 列 | 耗時: <b>{elapsed_seconds/60:.1f}</b> 分鐘</p>
        {missing_section}
    </div></body></html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to_email], msg.as_string())
        print(f"[✓] Email 報表已寄達: {to_email}")
        return True
    except Exception as e:
        print(f"[!] Email 發送失敗: {e}")
        return False
