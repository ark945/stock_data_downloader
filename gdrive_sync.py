"""
Google Drive 雲端同步模組 (Google Drive Sync Service)
專門將產出之台股全市場 Parquet / Excel 資料庫自動同步上傳至 Google Drive 目標資料夾
支援兩種認證上傳架構：
1. 【推薦】Google Apps Script (GAS) Web App 模式 (環境變數 GDRIVE_UPLOAD_URL)
   - 直接使用個人 Google 帳戶身分寫入 My Drive，徹底解決 Service Account 0 Quota 配額限制問題。
2. Google Cloud Service Account (服務帳戶) 模式 (環境變數 GDRIVE_SERVICE_ACCOUNT_KEY)
   - 適用於 Google Workspace 共用雲端硬碟 (Shared Drives)。
"""

import os
import sys
import json
import base64
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

# 目標 Google Drive 資料夾 ID：一律由環境變數 GDRIVE_FOLDER_ID 提供
DEFAULT_GDRIVE_FOLDER_ID = ""
SCOPES = ["https://www.googleapis.com/auth/drive"]


def upload_via_gas(local_file_path: str, upload_url: str, folder_id: str) -> Optional[Dict[str, Any]]:
    """
    透過 Google Apps Script Web App 上傳檔案 (支援個人 Google 帳戶 15GB 空間)
    """
    import requests

    file_name = os.path.basename(local_file_path)
    file_size_mb = os.path.getsize(local_file_path) / (1024 * 1024)

    print(f"[*] 正在透過 Google Apps Script 雲端橋接同步...")
    print(f"[*] 目標資料夾 ID: {folder_id}")
    print(f"[*] 同步檔案: {file_name} ({file_size_mb:.2f} MB)")

    try:
        with open(local_file_path, "rb") as f:
            file_bytes = f.read()

        file_b64 = base64.b64encode(file_bytes).decode("utf-8")
        payload = {
            "folder_id": folder_id,
            "filename": file_name,
            "file_base64": file_b64,
            "mime_type": "application/octet-stream"
        }

        headers = {"Content-Type": "application/json"}
        session = requests.Session()
        resp = session.post(upload_url, json=payload, headers=headers, timeout=60, allow_redirects=True)
        if resp.status_code == 200:
            try:
                res_data = resp.json()
            except Exception:
                # 兼容純文字或重定向返回
                print(f"[!] GAS 返回非 JSON 格式內容: {resp.text[:200]}")
                return None
            if res_data.get("status") == "success":
                file_id = res_data.get("file_id")
                view_link = res_data.get("url") or f"https://drive.google.com/file/d/{file_id}/view"
                print(f"[✓] Google Drive 檔案上傳成功 (GAS 模式)！")
                print(f"[*] 檔案 ID: {file_id}")
                print(f"[*] 檢視連結: {view_link}")
                return {
                    "file_id": file_id,
                    "name": file_name,
                    "web_view_link": view_link,
                    "size_mb": file_size_mb
                }
            else:
                print(f"[!] Google Apps Script 回傳錯誤: {res_data.get('message')}")
                return None
        else:
            print(f"[!] GAS 連線失敗 (HTTP {resp.status_code}): {resp.text}")
            return None

    except Exception as e:
        print(f"[!] GAS 上傳異常: {e}")
        return None


def get_gdrive_service(service_account_info_or_path: Optional[str] = None):
    """
    建立並回傳 Google Drive API 服務實例 (Service Account)
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("[!] 尚未安裝 Google Drive 官方依賴，請執行: pip install google-api-python-client google-auth")
        return None

    raw_key = service_account_info_or_path or os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY")
    creds = None
    if raw_key:
        raw_key = raw_key.strip()
        if os.path.exists(raw_key):
            creds = service_account.Credentials.from_service_account_file(raw_key, scopes=SCOPES)
        else:
            try:
                key_dict = json.loads(raw_key)
                creds = service_account.Credentials.from_service_account_info(key_dict, scopes=SCOPES)
            except Exception as e:
                print(f"[!] 解析 GDRIVE_SERVICE_ACCOUNT_KEY JSON 失敗: {e}")
                return None
    else:
        for fallback_f in ["credentials.json", "service_account.json", "gdrive_key.json"]:
            local_p = os.path.join(os.path.dirname(__file__), fallback_f)
            if os.path.exists(local_p):
                try:
                    creds = service_account.Credentials.from_service_account_file(local_p, scopes=SCOPES)
                    break
                except Exception:
                    pass

    if not creds:
        return None

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        print(f"[!] 建立 Google Drive 服務實例失敗: {e}")
        return None


def upload_file_to_gdrive(
    local_file_path: str,
    folder_id: Optional[str] = None,
    service_account_key: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    上傳或覆蓋檔案至 Google Drive 指定資料夾 (自適應 GAS 模式與 Service Account 模式)
    """
    if not os.path.exists(local_file_path):
        print(f"[!] 上傳失敗：找不到本地檔案 {local_file_path}")
        return None

    target_folder = folder_id or os.environ.get("GDRIVE_FOLDER_ID") or DEFAULT_GDRIVE_FOLDER_ID
    if not target_folder:
        print("[!] 未設定 GDRIVE_FOLDER_ID 環境變數，略過 Google Drive 上傳。")
        return None

    file_name = os.path.basename(local_file_path)
    file_size_mb = os.path.getsize(local_file_path) / (1024 * 1024)

    # 優先嘗試 1：Google Apps Script Web App 模式 (推薦，個人帳號無 quota 限制)
    gas_url = os.environ.get("GDRIVE_UPLOAD_URL", "").strip()
    if gas_url:
        return upload_via_gas(local_file_path, gas_url, target_folder)

    # 優先嘗試 2：Google Cloud Service Account 模式
    service = get_gdrive_service(service_account_key)
    if not service:
        print("[*] 提示：未配置 GDRIVE_UPLOAD_URL 或 GDRIVE_SERVICE_ACCOUNT_KEY，略過雲端同步。")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        print(f"[*] 正在連線 Google Drive API (目標資料夾 ID: {target_folder})...")
        print(f"[*] 準備同步檔案: {file_name} ({file_size_mb:.2f} MB)")

        # 1. 檢查目標資料夾是否已有同名檔案 (避免產生重複檔)
        query = f"'{target_folder}' in parents and name = '{file_name}' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get("files", [])

        media = MediaFileUpload(local_file_path, resumable=True)

        if items:
            existing_file_id = items[0]["id"]
            print(f"[+] 偵測到已有同名檔案，正在覆蓋更新版本 (File ID: {existing_file_id})...")
            updated_file = service.files().update(
                fileId=existing_file_id,
                media_body=media,
                fields="id, name, webViewLink"
            ).execute()
            file_id = updated_file.get("id")
            view_link = updated_file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
            print(f"[✓] Google Drive 檔案覆蓋更新成功！")
        else:
            print(f"[+] 正在上傳新檔案至 Google Drive 資料夾...")
            file_metadata = {
                "name": file_name,
                "parents": [target_folder]
            }
            new_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink"
            ).execute()
            file_id = new_file.get("id")
            view_link = new_file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
            print(f"[✓] Google Drive 檔案上傳成功！")

        print(f"[*] 檔案 ID: {file_id}")
        print(f"[*] 檢視連結: {view_link}")

        return {
            "file_id": file_id,
            "name": file_name,
            "web_view_link": view_link,
            "size_mb": file_size_mb
        }

    except Exception as e:
        print(f"[!] 上傳至 Google Drive 失敗: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_path = sys.argv[1]
        upload_file_to_gdrive(target_path)
    else:
        print("用法: python gdrive_sync.py <本地檔案路徑>")
