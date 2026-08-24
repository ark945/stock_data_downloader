"""
Google Drive 連線與權限測試腳本 (Google Drive Health Check)
支援：
1. Google Apps Script (GAS) Web App 模式 (環境變數 GDRIVE_UPLOAD_URL)
2. Google Cloud Service Account (服務帳戶) 模式 (環境變數 GDRIVE_SERVICE_ACCOUNT_KEY)
"""

import os
import sys
import json
import base64
import tempfile
import requests
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

def test_google_drive_connection():
    now_str = datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"🚀 開始執行 Google Drive 雲端同步連線與權限測試 ({now_str})")
    print("=" * 60)

    folder_id = (os.environ.get("GDRIVE_FOLDER_ID") or "").strip()
    gas_url = (os.environ.get("GDRIVE_UPLOAD_URL") or "").strip()
    raw_key = (os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY") or "").strip()

    if not folder_id:
        print("❌ [失敗] 找不到 GDRIVE_FOLDER_ID！請至 GitHub 專案 Settings -> Secrets 設定。")
        sys.exit(1)

    masked_folder = folder_id[:6] + "..." + folder_id[-4:] if len(folder_id) > 10 else folder_id
    print(f"[*] 偵測到 GDRIVE_FOLDER_ID: {masked_folder}")

    # 模式 A: Google Apps Script Web App (推薦個人 Gmail 模式)
    gas_error = None
    if gas_url:
        print("\n[*] 💡 檢測到 【Google Apps Script Web App】 模式 (個人 Google 帳號推薦)")
        masked_url = gas_url[:25] + "..." + gas_url[-8:] if len(gas_url) > 35 else gas_url
        print(f"[*] Web App URL: {masked_url}")
        
        test_file_name = f"gdrive_health_check_{datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime('%Y%m%d_%H%M%S')}.txt"
        test_content = (
            f"台股分點爬蟲系統 - Google Apps Script 雲端同步測試\n"
            f"測試時間 (台灣): {now_str}\n"
            f"目標資料夾: {folder_id}\n"
            f"狀態: 寫入測試正常！\n"
        )

        print("[*] 正在發送測試檔案至 Google Apps Script...")
        file_b64 = base64.b64encode(test_content.encode("utf-8")).decode("utf-8")
        payload = {
            "folder_id": folder_id,
            "filename": test_file_name,
            "file_base64": file_b64,
            "mime_type": "text/plain"
        }

        try:
            session = requests.Session()
            resp = session.post(gas_url, json=payload, headers={"Content-Type": "application/json"}, timeout=40, allow_redirects=True)
            if resp.status_code == 200:
                res_json = None
                try:
                    res_json = resp.json()
                except Exception:
                    gas_error = f"GAS 回傳內容非 JSON: {resp.text[:300]}"
                if res_json and res_json.get("status") == "success":
                    print(f"  [✓] 測試檔案上傳成功！")
                    print(f"  [✓] 檔案 ID: {res_json.get('file_id')}")
                    print(f"  [✓] 檢視連結: {res_json.get('url')}")
                    print("\n" + "=" * 60)
                    print("🎉 【恭喜】Google Drive (GAS 模式) 雲端同步測試全部通過！")
                    print("👉 每日全市場爬蟲排程產出之 Parquet 資料庫將可正常自動備份至您的雲端硬碟。")
                    print("=" * 60)
                    return
                else:
                    gas_error = f"GAS 回傳錯誤: {res_json.get('message')}"
            else:
                gas_error = f"GAS 連線失敗 (HTTP {resp.status_code}): {resp.text[:300]}"
        except Exception as e:
            gas_error = f"發送請求至 GAS 失敗: {e}"

        if gas_error:
            print(f"⚠️ [警告] {gas_error}")
            if raw_key:
                print("[*] 將改用 Service Account 模式再次驗證寫入權限...")
            else:
                print("💡 請確認 Google Apps Script Web App 已部署為可匿名存取，或改用 Service Account 模式。")
                sys.exit(1)

    # 模式 B: Service Account 模式
    if raw_key:
        print("\n[*] 檢測到 【Google Cloud Service Account】 模式")
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            print("❌ [失敗] 缺少 Google 官方依賴庫，請執行: pip install google-api-python-client google-auth")
            sys.exit(1)

        scopes = ["https://www.googleapis.com/auth/drive"]
        try:
            if os.path.exists(raw_key):
                creds = service_account.Credentials.from_service_account_file(raw_key, scopes=scopes)
            else:
                key_dict = json.loads(raw_key)
                creds = service_account.Credentials.from_service_account_info(key_dict, scopes=scopes)
                client_email = key_dict.get("client_email", "未知")
                print(f"  [✓] 服務帳戶 Email: {client_email}")
        except Exception as e:
            print(f"❌ [失敗] 解析 JSON 金鑰失敗: {e}")
            sys.exit(1)

        try:
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            folder_meta = service.files().get(fileId=folder_id, fields="id, name, mimeType, trashed, capabilities").execute()
            print(f"  [✓] 成功找到目標資料夾: 【{folder_meta.get('name', '未命名')}】")
            
            # 測試上傳
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
                tmp.write(f"Health Check {now_str}")
                tmp_p = tmp.name

            media = MediaFileUpload(tmp_p, mimetype="text/plain", resumable=True)
            new_file = service.files().create(
                body={"name": "sa_health_check.txt", "parents": [folder_id]},
                media_body=media,
                fields="id, name, webViewLink"
            ).execute()
            print(f"  [✓] 上傳成功: {new_file.get('webViewLink')}")
            service.files().delete(fileId=new_file.get("id")).execute()
            if os.path.exists(tmp_p): os.remove(tmp_p)

            print("\n" + "=" * 60)
            print("🎉 【恭喜】Google Drive (Service Account 模式) 測試通過！")
            print("=" * 60)
            return
        except Exception as e:
            print(f"❌ [失敗] Service Account 操作失敗: {e}")
            sys.exit(1)

    if gas_error:
        print(f"❌ [失敗] GAS 測試失敗，且 Service Account 模式未成功: {gas_error}")
    else:
        print("❌ [失敗] 未設定 GDRIVE_UPLOAD_URL 或 GDRIVE_SERVICE_ACCOUNT_KEY！")
    sys.exit(1)


if __name__ == "__main__":
    test_google_drive_connection()
