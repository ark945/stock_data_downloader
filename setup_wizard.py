import os
import sys
import time
import shutil
import subprocess
from datetime import datetime

# 抑制 TensorFlow 與底層 C++ 冗長日誌
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

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
    time.sleep(0.2)

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


def read_current_env() -> dict:
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
    return current_env


def save_env_file(env_data: dict):
    env_content = f"""# ==========================================
# 台股券商分點爬蟲系統 — 本地環境變數設定檔
# 更新時間: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# ==========================================

# Google Drive 雲端同步
GDRIVE_UPLOAD_URL={env_data.get('GDRIVE_UPLOAD_URL', '')}
GDRIVE_FOLDER_ID={env_data.get('GDRIVE_FOLDER_ID', '')}

# Telegram 即時推播
TELEGRAM_BOT_TOKEN={env_data.get('TELEGRAM_BOT_TOKEN', '')}
TELEGRAM_CHAT_ID={env_data.get('TELEGRAM_CHAT_ID', '')}

# SMTP 郵件通知
SMTP_SERVER={env_data.get('SMTP_SERVER', 'smtp.gmail.com')}
SMTP_PORT={env_data.get('SMTP_PORT', '587')}
SMTP_USER={env_data.get('SMTP_USER', '')}
SMTP_PASSWORD={env_data.get('SMTP_PASSWORD', '')}
RECEIVER_EMAIL={env_data.get('RECEIVER_EMAIL', '')}
"""
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(env_content)


def interactive_setup_env():
    """互動式填寫設定並生成/更新 .env"""
    print("\n🛠️ 【環境變數與參數設定】")
    current_env = read_current_env()

    if current_env:
        print("📋 目前已存在的設定摘要：")
        gas = current_env.get("GDRIVE_UPLOAD_URL", "")
        fld = current_env.get("GDRIVE_FOLDER_ID", "")
        tg_t = current_env.get("TELEGRAM_BOT_TOKEN", "")
        tg_c = current_env.get("TELEGRAM_CHAT_ID", "")
        smtp_u = current_env.get("SMTP_USER", "")
        smtp_p = "***" if current_env.get("SMTP_PASSWORD") else ""
        rcv = current_env.get("RECEIVER_EMAIL", "")

        print(f"  ☁️ Google Drive : {'已設定 URL' if gas else '未設定'} | 資料夾 ID: {fld or '未設定'}")
        print(f"  📱 Telegram     : Token: {tg_t[:8]+'...' if tg_t else '未設定'} | Chat ID: {tg_c or '未設定'}")
        print(f"  📧 SMTP Email   : 寄件: {smtp_u or '未設定'} | 密碼: {smtp_p} | 收件: {rcv or '未設定'}")
        print("-" * 65)

        print("請選擇操作：")
        print("  0. 🚀 【全部略過 (Bypass)】維持目前設定，直接返回主選單")
        print("  1. ✏️ 重新完整設定所有項目 (依序填寫)")
        print("  2. ☁️ 僅修改 Google Drive 設定")
        print("  3. 📱 僅修改 Telegram 設定")
        print("  4. 📧 僅修改 Gmail SMTP 設定")

        sub_c = input("\n請選擇 (0-4，預設 0 跳過) > ").strip()
        if not sub_c or sub_c == "0":
            print("\n[✓] 已跳過 (Bypass)，維持既有設定！")
            return
        elif sub_c == "2":
            _setup_gdrive_part(current_env)
            save_env_file(current_env)
            print("\n🎉 [成功] Google Drive 設定已更新！")
            return
        elif sub_c == "3":
            _setup_telegram_part(current_env)
            save_env_file(current_env)
            print("\n🎉 [成功] Telegram 設定已更新！")
            return
        elif sub_c == "4":
            _setup_email_part(current_env)
            save_env_file(current_env)
            print("\n🎉 [成功] Email 設定已更新！")
            return

    # 完整循序設定
    print("\n👉 請依序填寫參數（按 Enter 保留原值 / 輸入 clear 清空）：\n")
    _setup_gdrive_part(current_env)
    _setup_telegram_part(current_env)
    _setup_email_part(current_env)

    save_env_file(current_env)
    print("\n" + "=" * 65)
    print(f"🎉 [成功] 已成功儲存設定檔: {ENV_PATH}")
    print("=" * 65)


def _setup_gdrive_part(env_data: dict):
    print("☁️ --- [Google Drive 雲端備份設定] ---")
    gas_def = env_data.get("GDRIVE_UPLOAD_URL", "")
    folder_def = env_data.get("GDRIVE_FOLDER_ID", "")

    print("👉 Google Apps Script Web App URL (結尾為 /exec)：")
    if gas_def:
        print(f"   [目前: {gas_def[:35]}...]")
    val = input("GDRIVE_UPLOAD_URL (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["GDRIVE_UPLOAD_URL"] = ""
    elif val: env_data["GDRIVE_UPLOAD_URL"] = val

    print("👉 Google Drive 目標資料夾 ID (網址列 folders/ 後方字串)：")
    if folder_def:
        print(f"   [目前: {folder_def}]")
    val = input("GDRIVE_FOLDER_ID (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["GDRIVE_FOLDER_ID"] = ""
    elif val: env_data["GDRIVE_FOLDER_ID"] = val


def _setup_telegram_part(env_data: dict):
    print("\n📱 --- [Telegram 即時推播設定] ---")
    tg_token_def = env_data.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_def = env_data.get("TELEGRAM_CHAT_ID", "")

    print("👉 Telegram Bot Token (由 @BotFather 提供)：")
    if tg_token_def:
        print(f"   [目前: {tg_token_def[:10]}...]")
    val = input("TELEGRAM_BOT_TOKEN (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["TELEGRAM_BOT_TOKEN"] = ""
    elif val: env_data["TELEGRAM_BOT_TOKEN"] = val

    print("👉 Telegram Chat ID (由 @userinfobot 提供之純數字)：")
    if tg_chat_def:
        print(f"   [目前: {tg_chat_def}]")
    val = input("TELEGRAM_CHAT_ID (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["TELEGRAM_CHAT_ID"] = ""
    elif val: env_data["TELEGRAM_CHAT_ID"] = val


def _setup_email_part(env_data: dict):
    print("\n📧 --- [Gmail SMTP 郵件報表設定] ---")
    smtp_user_def = env_data.get("SMTP_USER", "")
    smtp_pass_def = env_data.get("SMTP_PASSWORD", "")
    receiver_def = env_data.get("RECEIVER_EMAIL", "")

    print("👉 寄件 Gmail 信箱：")
    if smtp_user_def:
        print(f"   [目前: {smtp_user_def}]")
    val = input("SMTP_USER (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["SMTP_USER"] = ""
    elif val: env_data["SMTP_USER"] = val

    print("👉 Google 16 位應用程式密碼 (非一般登入密碼)：")
    if smtp_pass_def:
        print(f"   [目前已設定 16 位密碼]")
    val = input("SMTP_PASSWORD (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["SMTP_PASSWORD"] = ""
    elif val: env_data["SMTP_PASSWORD"] = val

    print("👉 收件 Email (若與寄件者相同可按 Enter)：")
    if receiver_def:
        print(f"   [目前: {receiver_def}]")
    val = input("RECEIVER_EMAIL (按 Enter 保留原值) > ").strip()
    if val.lower() == "clear": env_data["RECEIVER_EMAIL"] = ""
    elif val: env_data["RECEIVER_EMAIL"] = val
    elif not env_data.get("RECEIVER_EMAIL"):
        env_data["RECEIVER_EMAIL"] = env_data.get("SMTP_USER", "")


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
        subprocess.run([sys.executable, "-c", "from twse_bsr_crawler import TWSEBrokerCrawler; c = TWSEBrokerCrawler(); df, f, r = c.crawl_stocks(['2330'], '2026-08-21'); print('抓取結果:', len(df), '筆')"])
    elif choice == "4":
        print("\n[*] 正在測試上櫃 (TPEX) 6488 採集...")
        subprocess.run([sys.executable, "-c", "from tpex_bsr_crawler import TPEXBrokerCrawler; c = TPEXBrokerCrawler(); df, f = c.crawl_stocks_with_retry(['6488'], '2026-08-21'); print('抓取結果:', len(df), '筆')"])


def get_workers_selection(default_workers: int = 4) -> int:
    """選擇運行線程與速度模式"""
    print("\n⚡ 選擇採集速度與線程模式：")
    print(f"  1. 🛡️ 【安全穩健模式】4 Workers (極低負擔、零封鎖風險，約 20~25 分鐘) [推薦 ⭐]")
    print(f"  2. 🚀 【極速衝刺模式】6 Workers (多進程極速並行，約 15 分鐘)")
    print(f"  3. 🛠️ 【自訂 Workers】手動輸入線程數 (1 ~ 8)")
    print(f"  (按 Enter 直接套用預設: {default_workers} Workers)")

    w_choice = input(f"請選擇速度模式 (1-3，預設 1) > ").strip()
    if w_choice == "2":
        return 6
    elif w_choice == "3":
        custom_w = input("請輸入自訂 Workers 數量 (1-8) > ").strip()
        if custom_w.isdigit() and 1 <= int(custom_w) <= 8:
            return int(custom_w)
        print(f"[!] 輸入無效，自動採用安全模式 4 Workers")
        return 4
    return 4


def run_crawler_menu():
    """執行爬蟲任務選單"""
    print("\n🚀 選擇爬蟲任務：")
    print("  1. 一鍵採集全市場 (上市 + 上櫃) [最新交易日, 產出 Parquet 與 Excel]")
    print("  2. 一鍵採集全市場 (極速模式，僅產出 Parquet 不出 Excel)")
    print("  3. 僅採集上市股票 (TWSE)")
    print("  4. 僅採集上櫃股票 (TPEX)")
    print("  5. 指定歷史日期採集 (例如 2026-08-21)")
    print("  0. 返回主選單")

    c = input("\n請輸入選項 (0-5) > ").strip()
    if c in ["1", "2", "3", "4", "5"]:
        # 取得使用者期望的線程模式
        workers = get_workers_selection(default_workers=4)

        if c == "1":
            subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "all", "--workers", str(workers)])
        elif c == "2":
            subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "all", "--workers", str(workers), "--no-excel"])
        elif c == "3":
            twse_w = min(workers + 2, 8)  # 上市純 HTTP 請求可額外微增線程
            subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "twse", "--workers", str(twse_w)])
        elif c == "4":
            subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--market", "tpex", "--workers", str(workers)])
        elif c == "5":
            date_str = input("\n請輸入指定日期 (YYYY-MM-DD) > ").strip()
            if date_str:
                subprocess.run([sys.executable, "stock_crawler_coordinator.py", "--date", date_str, "--market", "all", "--workers", str(workers)])


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
