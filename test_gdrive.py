"""
Google Drive 連線與權限測試腳本 (Google Drive Health Check)
專門用於驗證：
1. GCP 服務帳戶 (Service Account) 金鑰是否有效
2. Google Drive API 是否已啟用
3. 目標資料夾 (GDRIVE_FOLDER_ID) 是否存在且具備寫入/編輯權限
4. 測試建立、上傳與覆蓋檔案之完整流程
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

def test_google_drive_connection():
    now_str = datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"🚀 開始執行 Google Drive 雲端同步連線與權限測試 ({now_str})")
    print("=" * 60)

    # 1. 檢查環境變數
    folder_id = (os.environ.get("GDRIVE_FOLDER_ID") or "").strip()
    raw_key = (os.environ.get("GDRIVE_SERVICE_ACCOUNT_KEY") or "").strip()

    print("[*] [步驟 1/4] 檢查 GitHub Secrets 環境變數...")
    if not folder_id:
        print("❌ [失敗] 找不到 GDRIVE_FOLDER_ID！請至 GitHub 專案 Settings -> Secrets 設定。")
        sys.exit(1)
    else:
        masked_folder = folder_id[:6] + "..." + folder_id[-4:] if len(folder_id) > 10 else folder_id
        print(f"  [✓] 偵測到 GDRIVE_FOLDER_ID: {masked_folder}")

    if not raw_key:
        print("❌ [失敗] 找不到 GDRIVE_SERVICE_ACCOUNT_KEY！請至 GitHub 專案 Settings -> Secrets 設定。")
        sys.exit(1)
    else:
        print(f"  [✓] 偵測到 GDRIVE_SERVICE_ACCOUNT_KEY (長度: {len(raw_key)} 字元)")

    # 2. 驗證與解析 JSON 金鑰
    print("\n[*] [步驟 2/4] 解析服務帳戶 JSON 金鑰並驗證身分...")
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
            project_id = key_dict.get("project_id", "未知")
            print(f"  [✓] 服務帳戶 Email: {client_email}")
            print(f"  [✓] GCP 專案 ID: {project_id}")
    except Exception as e:
        print(f"❌ [失敗] 解析 JSON 金鑰失敗: {e}")
        print("💡 請確認在 GitHub Secret 中貼入的是完整的 JSON 字串 (包含大括號)。")
        sys.exit(1)

    # 3. 建立 Drive 服務實例並檢查資料夾權限
    print("\n[*] [步驟 3/4] 連線 Google Drive API 並檢查目標資料夾權限...")
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        folder_meta = service.files().get(fileId=folder_id, fields="id, name, mimeType, trashed, capabilities").execute()
        folder_name = folder_meta.get("name", "未命名")
        is_trashed = folder_meta.get("trashed", False)
        capabilities = folder_meta.get("capabilities", {})
        can_add_children = capabilities.get("canAddChildren", False)

        print(f"  [✓] 成功找到目標資料夾: 【{folder_name}】 (ID: {folder_id})")
        if is_trashed:
            print("❌ [失敗] 此資料夾已在垃圾桶中，請恢復或更換資料夾！")
            sys.exit(1)

        if not can_add_children:
            print(f"⚠️ [警告] 服務帳戶 ({client_email}) 對該資料夾可能沒有寫入權限！")
            print("💡 請至 Google Drive 將該資料夾「共用」給服務帳戶，並設定角色為「編輯者 (Editor)」。")
        else:
            print("  [✓] 寫入權限檢查通過 (具備 canAddChildren 權限)")

    except Exception as e:
        print(f"❌ [失敗] 無法存取目標資料夾: {e}")
        err_msg = str(e)
        if "404" in err_msg or "File not found" in err_msg:
            print(f"💡 原因排查：找不到資料夾 ID [{folder_id}]。")
            print(f"   請確認您是否已在 Google Drive 上將此資料夾「共用」給服務帳戶：{client_email}")
        elif "403" in err_msg or "has not enabled" in err_msg:
            print("💡 原因排查：GCP 專案尚未啟用 Google Drive API。")
            print("   請前往 Google Cloud Console 搜尋 'Google Drive API' 並點擊『啟用 (Enable)』。")
        sys.exit(1)

    # 4. 上傳健康檢查測試檔案
    print("\n[*] [步驟 4/4] 測試實際寫入檔案至 Google Drive...")
    test_file_name = f"gdrive_health_check_{datetime.now(timezone.utc).astimezone(TAIPEI_TZ).strftime('%Y%m%d_%H%M%S')}.txt"
    test_content = (
        f"台股分點爬蟲系統 - Google Drive 雲端同步連線測試\n"
        f"測試時間 (台灣): {now_str}\n"
        f"服務帳戶: {client_email}\n"
        f"目標資料夾: {folder_name} ({folder_id})\n"
        f"狀態: 寫入測試正常！\n"
    )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        tmp.write(test_content)
        tmp_path = tmp.name

    try:
        media = MediaFileUpload(tmp_path, mimetype="text/plain", resumable=True)
        file_metadata = {
            "name": test_file_name,
            "parents": [folder_id]
        }
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, size"
        ).execute()

        file_id = uploaded_file.get("id")
        view_link = uploaded_file.get("webViewLink")
        print(f"  [✓] 測試檔案上傳成功！")
        print(f"  [✓] 檔案名稱: {test_file_name}")
        print(f"  [✓] 檔案 ID: {file_id}")
        print(f"  [✓] 檢視連結: {view_link}")

        # 清理暫存檔
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        # 刪除遠端測試檔以保持資料夾整潔
        try:
            service.files().delete(fileId=file_id).execute()
            print("  [✓] 已自動清理測試用暫存檔案 (保持雲端資料夾乾淨)")
        except Exception:
            pass

    except Exception as e:
        print(f"❌ [失敗] 寫入測試檔案失敗: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("🎉 【恭喜】Google Drive 雲端同步功能測試全部通過！")
    print("👉 每日全市場爬蟲排程產出之 Parquet 資料庫將可正常自動備份至您的雲端硬碟。")
    print("=" * 60)


if __name__ == "__main__":
    test_google_drive_connection()
