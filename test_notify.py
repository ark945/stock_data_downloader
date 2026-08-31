"""
Notification smoke test for GitHub Actions.

The default mode sends a small test report through every configured channel.
Use ``--offline`` to validate imports and environment checks locally without
network access or secrets.
"""

import argparse
import os
import sys

from notify_engine import send_crawler_report_email, send_telegram_report


TELEGRAM_ENVS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
SMTP_ENVS = ("SMTP_USER", "SMTP_PASSWORD", "RECEIVER_EMAIL")


def has_all(names: tuple[str, ...]) -> bool:
    return all(os.environ.get(name, "").strip() for name in names)


def configured_channels() -> list[str]:
    channels = []
    if has_all(TELEGRAM_ENVS):
        channels.append("telegram")
    if has_all(SMTP_ENVS):
        channels.append("email")
    return channels


def run_offline_check() -> bool:
    channels = configured_channels()
    print("[*] Offline mode: verified test_notify.py imports and environment checks.")
    print(f"[*] Offline mode: configured channels detected: {', '.join(channels) if channels else '(none)'}")
    return True


def run_notification_check() -> bool:
    channels = configured_channels()
    if not channels:
        print("[!] No notification channel is fully configured.")
        print("    Telegram requires: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        print("    Email requires: SMTP_USER, SMTP_PASSWORD, RECEIVER_EMAIL")
        return False

    failures = []
    common_args = dict(
        trade_date="2026-08-31",
        total_target=1,
        success_count=1,
        no_trade_count=0,
        failed_stocks=[],
        total_rows=1,
        elapsed_seconds=1.0,
        rounds_executed=1,
        market="all",
        start_time_str="GitHub Actions smoke test",
        end_time_str="GitHub Actions smoke test",
        duration_str="1 秒",
    )

    if "telegram" in channels:
        print("[*] Sending Telegram smoke-test notification...")
        if not send_telegram_report(**common_args):
            failures.append("telegram")

    if "email" in channels:
        print("[*] Sending Email smoke-test notification...")
        if not send_crawler_report_email(**common_args):
            failures.append("email")

    if failures:
        print(f"[!] Notification smoke test failed for: {', '.join(failures)}")
        return False

    print(f"[✓] Notification smoke test passed for: {', '.join(channels)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate notification settings.")
    parser.add_argument("--offline", action="store_true", help="Run without secrets or network access.")
    args = parser.parse_args()

    success = run_offline_check() if args.offline else run_notification_check()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())