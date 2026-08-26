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
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def _get_market_display_name(market: str) -> str:
    """轉換市場代碼為易讀中文名稱"""
    m = (market or "all").lower().strip()
    if m == "twse":
        return "上市 (TWSE)"
    elif m == "tpex":
        return "上櫃 (TPEX)"
    else:
        return "全市場 (上市 TWSE + 上櫃 TPEX)"


def send_telegram_report(
    trade_date: str,
    total_target: int,
    success_count: int,
    no_trade_count: int,
    failed_stocks: List[Dict[str, str]],
    total_rows: int,
    elapsed_seconds: float,
    rounds_executed: int,
    market: str = "all",
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    start_time_str: Optional[str] = None,
    end_time_str: Optional[str] = None,
    duration_str: Optional[str] = None
) -> bool:
    """發送 Telegram 即時推播報表"""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not cid:
        print("[*] 未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 推播。")
        return False

    market_display = _get_market_display_name(market)
    failed_count = len(failed_stocks)
    # 達成率 = (有效成交產出 + 經確認無成交略過) / 總目標標的
    completion_rate = ((success_count + no_trade_count) / total_target * 100) if total_target > 0 else 0
    status_icon = "✅" if failed_count == 0 else ("⚠️" if failed_count < 10 else "❌")
    status_text = f"{market_display} 100% 完整產出" if failed_count == 0 else f"{market_display} 存在 {failed_count} 檔短缺"
    duration_display = duration_str or f"{elapsed_seconds/60:.1f} 分鐘"

    msg_lines = [
        f"{status_icon} *【台股分點爬蟲日報 — {market_display}】*",
        f"📅 *交易日期*: `{trade_date}`",
        f"🏢 *執行市場*: `{market_display}`",
        f"🎯 *採集達成率*: `{completion_rate:.1f}%` ({status_text})",
        f"📊 *總資料筆數*: `{total_rows:,}` 列",
        f"📋 *標的掃描統計*:",
        f"  • 總掃描檔數: `{total_target}` 檔",
        f"  • 有效成交產出: `{success_count}` 檔",
        f"  • 無成交/零交易: `{no_trade_count}` 檔",
        f"  • 短缺/失敗: `{failed_count}` 檔",
    ]

    if start_time_str and end_time_str:
        msg_lines.extend([
            f"🕒 *開始時間*: `{start_time_str}`",
            f"🏁 *結束時間*: `{end_time_str}`",
            f"⏱️ *總計耗時*: `{duration_display}` (共 `{rounds_executed}` 輪)",
        ])
    else:
        msg_lines.append(f"⏱️ *執行耗時*: `{duration_display}` (共 `{rounds_executed}` 輪)")

    if failed_count > 0:
        msg_lines.append(f"\n⚠️ *最終短缺股票清單 (共 {failed_count} 檔)*:")
        for idx, item in enumerate(failed_stocks[:40], 1):
            msg_lines.append(f"  `{idx}.` *{item.get('symbol')}* {item.get('name', '未知')} ({item.get('market', '')})")
        if failed_count > 40:
            msg_lines.append(f"  _...其餘 {failed_count - 40} 檔已省略_")
    else:
        msg_lines.append(f"\n🎉 *{market_display} 0 遺漏，全部掃描完畢！*")

    msg_lines.append(f"\n🕒 _推播時間: {get_taipei_now().strftime('%Y-%m-%d %H:%M:%S')}_")
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
    market: str = "all",
    receiver_email: Optional[str] = None,
    start_time_str: Optional[str] = None,
    end_time_str: Optional[str] = None,
    duration_str: Optional[str] = None
) -> bool:
    """發送爬蟲執行成果與短缺股票明細 Email (若有設定 SMTP)"""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com") or "smtp.gmail.com"
    port_str = (os.getenv("SMTP_PORT") or "").strip()
    smtp_port = int(port_str) if port_str.isdigit() else 587
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    to_email = (receiver_email or os.getenv("RECEIVER_EMAIL") or smtp_user).strip()

    if not smtp_user or not smtp_password or not to_email:
        return False

    market_display = _get_market_display_name(market)
    failed_count = len(failed_stocks)
    # 達成率 = (有效成交產出 + 經確認無成交略過) / 總目標標的
    completion_rate = ((success_count + no_trade_count) / total_target * 100) if total_target > 0 else 0
    status_emoji = "✅" if failed_count == 0 else ("⚠️" if failed_count < 10 else "❌")
    status_text = f"{market_display} 100% 完整產出" if failed_count == 0 else f"{market_display} 存在 {failed_count} 檔短缺"
    duration_display = duration_str or f"{elapsed_seconds/60:.1f} 分鐘"

    subject = f"{status_emoji} 【台股分點爬蟲日報】{trade_date} 執行成果 — {status_text}"

    if failed_count > 0:
        table_rows = "".join([
            f"<tr style='border-bottom:1px solid #eee;'><td style='padding:8px;text-align:center;'>{i}</td><td style='padding:8px;font-weight:bold;color:#1a73e8;'>{item.get('symbol')}</td><td style='padding:8px;'>{item.get('name')}</td><td style='padding:8px;color:#d93025;'>{item.get('reason')}</td></tr>"
            for i, item in enumerate(failed_stocks, 1)
        ])
        missing_section = f"<h3 style='color:#d93025;margin-top:20px;'>⚠️ 短缺股票清單 ({failed_count} 檔)</h3><table style='width:100%;border-collapse:collapse;border:1px solid #eee;'><thead><tr style='background:#f8f9fa;'><th>序號</th><th>代碼</th><th>名稱</th><th>原因</th></tr></thead><tbody>{table_rows}</tbody></table>"
    else:
        missing_section = f"<div style='padding:15px;background:#e6f4ea;color:#137333;border-radius:6px;margin-top:15px;'><b>🎉 完美達成！</b> {market_display} 無短缺遺漏，全部掃描完畢。</div>"

    time_meta = ""
    if start_time_str and end_time_str:
        time_meta = f"<div style='font-size:13px;color:#666;margin-top:5px;'>開始: {start_time_str} | 結束: {end_time_str}</div>"

    html_content = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f4f6f9;padding:25px;margin:0;">
    <div style="max-width:650px;margin:0 auto;background:#ffffff;padding:25px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.06);">
        <div style="border-bottom:2px solid #ea4335;padding-bottom:12px;margin-bottom:15px;">
            <h2 style="margin:0;color:#202124;font-size:22px;">📊 台股分點買賣日報表 ({trade_date})</h2>
            <div style="margin-top:6px;font-size:14px;color:#5f6368;">
                執行市場範疇：<span style="display:inline-block;padding:2px 8px;background:#e8f0fe;color:#1a73e8;border-radius:4px;font-weight:bold;">{market_display}</span>
            </div>
            {time_meta}
        </div>
        
        <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:10px;margin-bottom:15px;">
            <div style="background:#f8f9fa;padding:12px;border-radius:6px;border-left:4px solid #1a73e8;">
                <div style="font-size:12px;color:#70757a;">採集達成率</div>
                <div style="font-size:20px;font-weight:bold;color:#202124;margin-top:3px;">{completion_rate:.1f}%</div>
            </div>
            <div style="background:#f8f9fa;padding:12px;border-radius:6px;border-left:4px solid #34a853;">
                <div style="font-size:12px;color:#70757a;">總資料筆數</div>
                <div style="font-size:20px;font-weight:bold;color:#202124;margin-top:3px;">{total_rows:,} 列</div>
            </div>
        </div>

        <table style="width:100%;border-collapse:collapse;margin-bottom:15px;font-size:14px;background:#fafbfc;border:1px solid #e1e4e8;border-radius:6px;">
            <tr style="border-bottom:1px solid #eaecef;">
                <td style="padding:10px 14px;color:#586069;width:50%;">🎯 <b>總掃描標的數</b></td>
                <td style="padding:10px 14px;font-weight:bold;text-align:right;color:#24292e;">{total_target} 檔</td>
            </tr>
            <tr style="border-bottom:1px solid #eaecef;">
                <td style="padding:10px 14px;color:#586069;">📈 <b>有效成交產出</b></td>
                <td style="padding:10px 14px;font-weight:bold;text-align:right;color:#28a745;">{success_count} 檔</td>
            </tr>
            <tr style="border-bottom:1px solid #eaecef;">
                <td style="padding:10px 14px;color:#586069;">⚪ <b>無成交量 (零交易/略過)</b></td>
                <td style="padding:10px 14px;font-weight:bold;text-align:right;color:#6a737d;">{no_trade_count} 檔</td>
            </tr>
            <tr style="border-bottom:1px solid #eaecef;">
                <td style="padding:10px 14px;color:#586069;">⚠️ <b>採集短缺 / 失敗</b></td>
                <td style="padding:10px 14px;font-weight:bold;text-align:right;color:{'#d73a49' if failed_count > 0 else '#28a745'};">{failed_count} 檔</td>
            </tr>
            <tr>
                <td style="padding:10px 14px;color:#586069;">⏱️ <b>總計耗時</b></td>
                <td style="padding:10px 14px;text-align:right;color:#586069;">{duration_display}</td>
            </tr>
        </table>

        {missing_section}

        <div style="margin-top:20px;font-size:12px;color:#80868b;text-align:center;">
            本報告由台股全市場日報自動化調度引擎生成 • {get_taipei_now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
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
