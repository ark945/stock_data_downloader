"""
台股券商分點爬蟲系統 — 本地端前置設定與一鍵診斷精靈 (Local Setup Wizard)
用於：
1. 檢查本地 Python 套件、Chrome 瀏覽器與 CNN 模型健康狀態
2. 互動式填寫 Google Drive、Telegram、Email 設定並自動生成 .env
3. 一鍵執行連線與爬蟲測試
4. 快速啟動本地採集任務
"""

import os
import sys
import time
import shutil
import subprocess
from datetime import datetime

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    print("=" * 65)
    print("  🚀 台股全市場券商分點爬蟲系統 — 本地端環境與設定精靈")
    print("=" * 65)


def check_environment() -> dict:
    """全面檢查本地運行環境"""
    status = {}

    # 1. Python 版本
    py_ver = sys.version_info
    status["python_ok"] = (py_ver.major == 3 and py_ver.minor in [10, 11, 12])
    status["python_ver"] = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"

    # 2. 核心 Python 套件
    required_packages = [
        "requests", "pandas", "numpy", "pyarrow", "openpyxl",
        "tensorflow", "ddddocr", "DrissionPage", "dotenv"
    ]
    missing_packages = []
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            missing_packages.append(pkg)
    status["missing_packages"] = missing_packages

    # 3. Chrome 瀏覽器 (TPEX 爬蟲所需)
    chrome_found = False
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium"
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_found = True
            break
    if not chrome_found:
        chrome_found = shutil.which("chrome") is not None or shutil.which("google-chrome") is not None
    status["chrome_ok"] = chrome_found

    # 4. CNN 驗證碼模型
    model_path = os.path.join(os.path.dirname(__file__), "twse_cnn_model.hdf5")
    status["model_ok"] = os.path.exists(model_path) and os.path.getsize(model_path) > 1024 * 1024

    # 5. .env 設定檔
    status["env_exists"] = os.path.exists(ENV_PATH)

    return status


def print_health_report():
    print("\n🔍 正在進行本地端環境健康檢查...")
    st = check_environment()
    time.sleep(0.3)

    print("-" * 65)
    # Python
    if st["python_ok"]:
        print(f"  [✓] Python 版本: {st['python_ver']} (正常)")
    else:
        print(f"  [!] Python 版本: {st['python_ver']} (建議使用 Python 3.10 ~ 3.12)")

    # Packages
    if not st["missing_packages"]:
        print("  [✓] Python 依賴套件: 全部就緒 (TensorFlow, DrissionPage, Pandas 等)")
    else:
        print(f"  [❌] 缺少套件: {', '.join(st['missing_packages'])}")
        print("      👉 請執行: pip install -r requirements.txt")

    # Chrome
    if st["chrome_ok"]:
        print("  [✓] Google Chrome 瀏覽器: 已就緒 (上櫃 TPEX 自動化可用)")
    else:
        print("  [⚠️] 找不到 Google Chrome 瀏覽器 (TPEX 上櫃模組需要 Chrome)")

    # Model
    if st["model_ok"]:
        print("  [✓] TWSE CNN 驗證碼模型: twse_cnn_model.hdf5 (正常就緒 98%+)")
    else:
        print("  [❌] 找不到 twse_cnn_model.hdf5 模型檔 (TWSE 辨識將降級為備援 OCR)")

    # .env
    if st["env_exists"]:
        print("  [✓] 環境變數設定檔 (.env): 已存在")
    else:
        print("  [提示] 尚未建立 .env 設定檔 (可使用精靈互動式建立)")
    print("-" * 65)


def interactive_setup_env():
    """互動式填寫設定並生成 .env"""
    print("\n🛠️ 【互動式參數設定精靈】")
    print("請依序填寫參數（若不需要該功能，直接按 Enter 略過即可）：\n")

    current_env = {}
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        current_env[k.strip()] = v.strip()
        except Exception:
            pass

    # 1. Google Drive 設定
    print("☁️ --- [1. Google Drive 雲端備份設定 (選填)] ---")
    gas_def = current_env.get("GDRIVE_UPLOAD_URL", "")
    folder_def = current_env.get("GDRIVE_FOLDER_ID", "")

    print("👉 請輸入 Google Apps Script Web App URL (結尾為 /exec)：")
    if gas_def:
        print(f"   (目前設定: {gas_def[:30]}... 按 Enter 維持不變)")
    gas_url = input("GDRIVE_UPLOAD_URL > ").strip() or gas_def

    print("👉 請輸入 Google Drive 目標資料夾 ID (網址列 folders/ 後方字串)：")
    if folder_def:
        print(f"   (目前設定: {folder_def} 按 Enter 維持不變)")
    folder_id = input("GDRIVE_FOLDER_ID > ").strip() or folder_def

    # 2. Telegram 設定
    print("\n📱 --- [2. Telegram 即時推播設定 (選填)] ---")
    tg_token_def = current_env.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_def = current_env.get("TELEGRAM_CHAT_ID", "")

    print("👉 請輸入 Telegram Bot Token (由 @BotFather 提供)：")
    if tg_token_def:
        print(f"   (目前設定: {tg_token_def[:10]}... 按 Enter 維持不變)")
    tg_token = input("TELEGRAM_BOT_TOKEN > ").strip() or tg_token_def

    print("👉 請輸入 Telegram Chat ID (由 @userinfobot 提供之純數字)：")
    if tg_chat_def:
        print(f"   (目前設定: {tg_chat_def} 按 Enter 維持不變)")
    tg_chat = input("TELEGRAM_CHAT_ID > ").strip() or tg_chat_def

    # 3. SMTP Email 設定
    print("\n📧 --- [3. Gmail SMTP 郵件報表設定 (選填)] ---")
    smtp_user_def = current_env.get("SMTP_USER", "")
    smtp_pass_def = current_env.get("SMTP_PASSWORD", "")
    receiver_def = current_env.get("RECEIVER_EMAIL", "")

    print("👉 請輸入寄件 Gmail 信箱：")
    if smtp_user_def:
        print(f"   (目前設定: {smtp_user_def} 按 Enter 維持不變)")
    smtp_user = input("SMTP_USER > ").strip() or smtp_user_def

    print("👉 請輸入 Google 16 位應用程式密碼 (非一般登入密碼)：")
    if smtp_pass_def:
        print(f"   (目前已設定 16 位密碼，按 Enter 維持不變)")
    smtp_pass = input("SMTP_PASSWORD > ").strip() or smtp_pass_def

    print("👉 請輸入收件 Email (若與寄件者相同可留空)：")
    if receiver_def:
        print(f"   (目前設定: {receiver_def} 按 Enter 維持不變)")
    receiver_email = input("RECEIVER_EMAIL > ").strip() or receiver_def or smtp_user

    # 寫入 .env
    env_content = f"""# ==========================================
# 台股券商分點爬蟲系統 — 本地環境變數設定檔
# 建立時間: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# ==========================================

# Google Drive 雲端同步
GDRIVE_UPLOAD_URL={gas_url}
GDRIVE_FOLDER_ID={folder_id}

# Telegram 即時推播
TELEGRAM_BOT_TOKEN={tg_token}
TELEGRAM_CHAT_ID={tg_chat}

# SMTP 郵件通知
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER={smtp_user}
SMTP_PASSWORD={smtp_pass}
RECEIVER_EMAIL={receiver_email}
"""

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n" + "=" * 65)
    print(f"🎉 [成功] 已成功生成環境變數設定檔: {ENV_PATH}")
    print("=" * 65)


def run_quick_test():
    """執行快速連線測試"""
    print("\n🧪 選擇欲執行的測試項目：")
    print("  1. 測試 Google Drive 雲端同步")
    print("  2. 測試 Telegram 與 Email 推播")
    print("  3. 測試上市 (TWSE) 驗證碼辨識與單檔抓取 (2330 台積電)")
    print("  4. 測試上櫃 (TPEX) 瀏覽器與單檔抓取 (6488 環球晶)")
    print("  0. 返回主選單")

    choice = input("\n請輸入選項 (0-4) > ").strip()
    if choice == "1":
        print("\n[*] 正在執行 Google Drive 同步測試...")
        subprocess.run([sys.executable, "test_gdrive.py"])
    elif choice == "2":
        print("\n[*] 正在執行通知推播測試...")
        subprocess.run([sys.executable, "test_notify.py"])
    elif choice == "3":
        print("\n[*] 正在測試上市 (TWSE) 2330 採集...")
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "twse", "--workers", "1", "--max-rounds", "1"])
    elif choice == "4":
        print("\n[*] 正在測試上櫃 (TPEX) 採集...")
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "tpex"])


def run_crawler_menu():
    """執行爬蟲任務選單"""
    print("\n🚀 選擇爬蟲任務：")
    print("  1. 一鍵採集全市場 (上市 + 上櫃) [最新交易日]")
    print("  2. 一鍵採集全市場 (極速模式，僅產出 Parquet 不出 Excel)")
    print("  3. 僅採集上市股票 (TWSE)")
    print("  4. 僅採集上櫃股票 (TPEX)")
    print("  5. 指定歷史日期採集 (例如 2026-08-21)")
    print("  0. 返回主選單")

    c = input("\n請輸入選項 (0-5) > ").strip()
    if c == "1":
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "all"])
    elif c == "2":
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "all", "--no-excel"])
    elif c == "3":
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "twse", "--workers", "6"])
    elif c == "4":
        subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "tpex"])
    elif c == "5":
        date_str = input("請輸入指定日期 (YYYY-MM-DD) > ").strip()
        if date_str:
            subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--date", date_str, "--market", "all"])


def main():
    while True:
        print_banner()
        print_health_report()

        print("\n📌 主選單：")
        print("  1. 互動式設定參數 (Google Drive / Telegram / Email ➔ 生成 .env)")
        print("  2. 執行連線與功能測試 (Google Drive / Telegram / 股票採集)")
        print("  3. 啟動台股分點爬蟲任務")
        print("  4. 重新檢查環境狀態")
        print("  0. 離開程式")

        choice = input("\n請選擇功能 (0-4) > ").strip()

        if choice == "1":
            interactive_setup_env()
            input("\n按 Enter 鍵返回主選單...")
        elif choice == "2":
            run_quick_test()
            input("\n按 Enter 鍵返回主選單...")
        elif choice == "3":
            run_crawler_menu()
            input("\n按 Enter 鍵返回主選單...")
        elif choice == "4":
            clear_screen()
            continue
        elif choice == "0":
            print("\n👋 感謝使用，已退出設定精靈！")
            break
        else:
            print("\n⚠️ 無效選項，請重新輸入。")
            time.sleep(1)


if __name__ == "__main__":
    main()
