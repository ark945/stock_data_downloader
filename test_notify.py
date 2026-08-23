"""
通知推播連線測試腳本 (Telegram Bot & Email SMTP)
用於：
- GitHub Actions 每日定時心跳檢測 (台灣時間 06:30)
- 手動一鍵驗證 Telegram 與 Email 連線狀態
"""

import os
import sys
from datetime import datetime
from notify_engine import send_telegram_report, send_crawler_report_email


def run_notification_test():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 50)
    print(f"🚀 開始執行通知推播連線測試 ({now_str})")
    print("=" * 50)

    # 模擬測試數據
    mock_trade_date = datetime.now().strftime("%Y-%m-%d")
    mock_failed = [
        {"symbol": "0000", "name": "測試標的A", "market": "TWSE", "reason": "此為連線測試範例，非真實短缺"},
    ]

    # 1. 測試 Telegram 推播
    print("\n[*] [1/2] 正在測試 Telegram Bot 推播...")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_cid = os.getenv("TELEGRAM_CHAT_ID", "")
    
    if tg_token and tg_cid:
        masked_token = tg_token[:6] + "..." + tg_token[-4:] if len(tg_token) > 10 else "***"
        print(f"[*] 偵測到 Token: {masked_token}, Chat ID: {tg_cid}")
        tg_success = send_telegram_report(
            trade_date=f"{mock_trade_date} (連線心跳測試)",
            total_target=2700,
            success_count=2699,
            no_trade_count=0,
            failed_stocks=mock_failed,
            total_rows=480000,
            elapsed_seconds=12.5,
            rounds_executed=1,
            bot_token=tg_token,
            chat_id=tg_cid
        )
        if tg_success:
            print("[✓] Telegram 推播測試成功！")
        else:
            print("[!] Telegram 推播測試未成功，請確認 Token 與 Chat ID。")
    else:
        print("[!] 未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，略過 Telegram 測試。")
        tg_success = False

    # 2. 測試 Email 寄送
    print("\n[*] [2/2] 正在測試 Email SMTP 發信...")
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASSWORD") or "").strip()
    receiver = (os.getenv("RECEIVER_EMAIL") or "").strip()

    if smtp_user and smtp_pass:
        print(f"[*] 偵測到 SMTP 帳號: {smtp_user}, 收件者: {receiver or smtp_user}")
        email_success = send_crawler_report_email(
            trade_date=f"{mock_trade_date} (連線心跳測試)",
            total_target=2700,
            success_count=2699,
            no_trade_count=0,
            failed_stocks=mock_failed,
            total_rows=480000,
            elapsed_seconds=12.5,
            rounds_executed=1,
            receiver_email=receiver
        )
        if email_success:
            print("[✓] Email 發信測試成功！")
        else:
            print("[!] Email 發信測試未成功，請確認 SMTP 設定。")
    else:
        print("[*] 未設定 SMTP_USER / SMTP_PASSWORD，略過 Email 測試。")
        email_success = False

    print("\n" + "=" * 50)
    print(f"[總結] Telegram 測試: {'✅ 成功' if tg_success else '⚠️ 略過/未通過'} | Email 測試: {'✅ 成功' if email_success else '⚠️ 略過/未通過'}")
    print("=" * 50)


if __name__ == "__main__":
    run_notification_test()
