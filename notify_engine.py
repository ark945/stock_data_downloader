"""
台股分點爬蟲執行結果郵件通知模組 (Email Notification Engine)
支援：
- SMTP (Gmail, Office365, 自訂企業郵件伺服器)
- 視覺化 HTML 格式報表（包含摘要卡片、成功率進度條、短缺股票明細表格）
- 環境變數與設定檔載入
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from datetime import datetime


def get_email_config() -> Dict[str, str]:
    """讀取 Email SMTP 設定 (優先從環境變數讀取)"""
    return {
        "smtp_server": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "receiver_email": os.getenv("RECEIVER_EMAIL", os.getenv("SMTP_USER", "")),
    }


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
    """
    發送爬蟲執行成果與短缺股票明細 Email
    
    :param trade_date: 交易日期 (YYYY-MM-DD)
    :param total_target: 目標總標的數
    :param success_count: 成功抓取標的數
    :param no_trade_count: 當日無交易標的數
    :param failed_stocks: 最終短缺股票清單 [{"symbol": "2454", "name": "聯發科", "reason": "逾時"}]
    :param total_rows: 總分點明細筆數
    :param elapsed_seconds: 總耗時 (秒)
    :param rounds_executed: 執行總輪數 (最高 5 輪)
    :param receiver_email: 自訂收件者 Email
    """
    config = get_email_config()
    smtp_user = config["smtp_user"]
    smtp_password = config["smtp_password"]
    to_email = receiver_email or config["receiver_email"]

    if not smtp_user or not smtp_password or not to_email:
        print("[!] 未偵測到 SMTP 帳號密碼設定，略過 Email 發送。(可設定環境變數 SMTP_USER / SMTP_PASSWORD)")
        return False

    failed_count = len(failed_stocks)
    completion_rate = ((success_count + no_trade_count) / total_target * 100) if total_target > 0 else 0
    status_emoji = "✅" if failed_count == 0 else ("⚠️" if failed_count < 10 else "❌")
    status_text = "全市場 100% 完整產出" if failed_count == 0 else f"存在 {failed_count} 檔短缺標的"

    subject = f"{status_emoji} 【台股分點爬蟲日報】{trade_date} 執行成果 — {status_text}"

    # 生成短缺股票 HTML 表格
    if failed_count > 0:
        table_rows = ""
        for idx, item in enumerate(failed_stocks, 1):
            table_rows += f"""
            <tr style="border-bottom: 1px solid #e0e0e0;">
                <td style="padding: 8px 12px; text-align: center;">{idx}</td>
                <td style="padding: 8px 12px; font-weight: bold; color: #1a73e8;">{item.get('symbol', '')}</td>
                <td style="padding: 8px 12px;">{item.get('name', '未知')}</td>
                <td style="padding: 8px 12px; color: #d93025;">{item.get('reason', '達最大重試上限')}</td>
            </tr>
            """
        missing_section_html = f"""
        <div style="margin-top: 25px;">
            <h3 style="color: #d93025; border-left: 4px solid #d93025; padding-left: 10px; margin-bottom: 12px;">
                ⚠️ 最終短缺股票清單 (共 {failed_count} 檔)
            </h3>
            <table style="width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e0e0e0; font-size: 14px;">
                <thead>
                    <tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6; color: #495057;">
                        <th style="padding: 10px; text-align: center;">序號</th>
                        <th style="padding: 10px; text-align: left;">股票代碼</th>
                        <th style="padding: 10px; text-align: left;">股票名稱</th>
                        <th style="padding: 10px; text-align: left;">未成功原因</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        """
    else:
        missing_section_html = """
        <div style="margin-top: 25px; padding: 15px; background: #e6f4ea; border: 1px solid #ceead6; border-radius: 6px; color: #137333;">
            <b>🎉 完美達成！</b> 全市場所有標的皆已完整抓取或確認當日無交易，無任何短缺股票。
        </div>
        """

    # HTML 郵件模板
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: 'Segoe UI', Arial, 'Microsoft JhengHei', sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; color: #333;">
        <div style="max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; border: 1px solid #e9ecef;">
            <div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: #ffffff; padding: 24px 28px;">
                <h2 style="margin: 0; font-size: 22px;">📊 台股全市場券商分點爬蟲 — 執行成果日報</h2>
                <p style="margin: 6px 0 0 0; opacity: 0.85; font-size: 14px;">交易日期: {trade_date} | 執行總輪數: {rounds_executed}/5 輪</p>
            </div>
            
            <div style="padding: 24px 28px;">
                <!-- 數據概覽卡片 -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
                    <div style="background: #f8f9fa; padding: 14px; border-radius: 6px; border: 1px solid #e9ecef;">
                        <div style="font-size: 12px; color: #6c757d;">涵蓋達成率</div>
                        <div style="font-size: 20px; font-weight: bold; color: {'#137333' if failed_count == 0 else '#d93025'};">{completion_rate:.1f}%</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 14px; border-radius: 6px; border: 1px solid #e9ecef;">
                        <div style="font-size: 12px; color: #6c757d;">總分點明細筆數</div>
                        <div style="font-size: 20px; font-weight: bold; color: #1a73e8;">{total_rows:,} 列</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 14px; border-radius: 6px; border: 1px solid #e9ecef;">
                        <div style="font-size: 12px; color: #6c757d;">成功 / 無交易檔數</div>
                        <div style="font-size: 16px; font-weight: bold; color: #202124;">{success_count} 檔 / {no_trade_count} 檔</div>
                    </div>
                    <div style="background: #f8f9fa; padding: 14px; border-radius: 6px; border: 1px solid #e9ecef;">
                        <div style="font-size: 12px; color: #6c757d;">總執行耗時</div>
                        <div style="font-size: 16px; font-weight: bold; color: #202124;">{elapsed_seconds/60:.1f} 分鐘 ({elapsed_seconds:.0f}s)</div>
                    </div>
                </div>

                <!-- 短缺明細區塊 -->
                {missing_section_html}

                <div style="margin-top: 30px; font-size: 12px; color: #80868b; text-align: center; border-top: 1px solid #eee; padding-top: 15px;">
                    本郵件由台股分點自動化排程系統產出 | 發送時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email

        # 純文字版本
        plain_text = f"【台股分點爬蟲日報】{trade_date}\n達成率: {completion_rate:.1f}%\n成功: {success_count} 檔\n短缺: {failed_count} 檔\n總筆數: {total_rows:,} 列\n"
        if failed_count > 0:
            plain_text += "\n短缺標的清單:\n" + "\n".join([f"- {x.get('symbol')} {x.get('name')}" for x in failed_stocks])

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        print(f"[*] 正在連線至 SMTP 伺服器 ({config['smtp_server']}:{config['smtp_port']})...")
        with smtplib.SMTP(config["smtp_server"], config["smtp_port"], timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to_email], msg.as_string())

        print(f"[✓] Email 報表發送成功！已寄達: {to_email}")
        return True
    except Exception as e:
        print(f"[!] Email 發送失敗: {e}")
        return False
