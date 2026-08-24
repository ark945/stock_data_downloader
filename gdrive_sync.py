"""
Google Drive 雲端同步模組 (Google Drive Sync Service)
專門將產出之台股全市場 Parquet / Excel 資料庫自動同步上傳至 Google Drive 目標資料夾
支援：
1. Google Cloud Service Account (服務帳戶) JSON 金鑰自動驗證
2. 智慧查重與版本覆蓋 (避免資料夾重複推積雜檔)
3. 取得 Google Drive 檔案直接檢視/下載連結
"""

import os
import sys
import json
from typing import Optional, Dict, Any

# 目標 Google Drive 資料夾 ID：一律由環境變數 GDRIVE_FOLDER_ID 提供，避免將個人資料夾 ID 寫入公開原始碼
DEFAULT_GDRIVE_FOLDER_ID = ""

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_gdrive_service(service_account_info_or_path: Optional[str] = None):
    """
    建立並回傳 Google Drive API 服務實例
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("[!] 尚未安裝 Google Drive 官方依賴，請執行: pip install google-api-python-client google-auth")
        return None

    # 1. 優先由參數或環境變數取得
    raw_key = service_account_info_or_path or os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY")

    creds = None
    if raw_key:
        raw_key = raw_key.strip()
        # 若為 JSON 檔案路徑
        if os.path.exists(raw_key):
            creds = service_account.Credentials.from_service_account_file(raw_key, scopes=SCOPES)
        else:
            # 若為 JSON 字串
            try:
                key_dict = json.loads(raw_key)
                creds = service_account.Credentials.from_service_account_info(key_dict, scopes=SCOPES)
            except Exception as e:
                print(f"[!] 解析 GDRIVE_SERVICE_ACCOUNT_KEY JSON 失敗: {e}")
                return None
    else:
        # 2. 備援檢查本地常見名稱
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
    上傳或覆蓋檔案至 Google Drive 指定資料夾
    :param local_file_path: 本地檔案路徑 (例如 output/api_absr1_2026-08-21_2026-08-21_1.parquet)
    :param folder_id: Google Drive 資料夾 ID (若未提供，則由環境變數 GDRIVE_FOLDER_ID 讀取)
    :param service_account_key: 服務帳戶 JSON 金鑰內容或檔案路徑
    :return: 檔案資訊字典 {"file_id", "name", "web_view_link", "size_mb"} 或 None
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

    service = get_gdrive_service(service_account_key)
    if not service:
        print("[*] 提示：未配置 Google Drive Service Account 憑證，略過雲端同步。")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        print(f"[*] 正在連線 Google Drive (目標資料夾 ID: {target_folder})...")
        print(f"[*] 準備同步檔案: {file_name} ({file_size_mb:.2f} MB)")

        # 1. 檢查目標資料夾是否已有同名檔案 (避免產生重複檔)
        query = f"'{target_folder}' in parents and name = '{file_name}' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get("files", [])

        media = MediaFileUpload(local_file_path, resumable=True)

        if items:
            # 檔案已存在，執行覆蓋更新 (Update)
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
            # 檔案不存在，執行建立上傳 (Create)
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
