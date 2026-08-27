"""
Google Drive 檔案存在性快速檢查模組 (Pre-check for Backup Schedule)
專門於定時排程 (如 17:37 主要排程、05:31 二次備援) 啟動時快速檢查 Google Drive 是否已有當日或前一日完整資料庫。
若已存在且大小正常 (>100KB)，則標記為可跳過 (SHOULD_SKIP=true)，避免浪費 GitHub Actions 運算資源。
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

TAIPEI_TZ = timezone(timedelta(hours=8))


def get_taipei_now() -> datetime:
    """取得台灣時間 (UTC+8)"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)


def get_expected_trade_date(now: Optional[datetime] = None) -> str:
    """
    根據當前台灣時間自動推算預期目標交易日：
    - 若台灣時間 < 12:00 (例如凌晨 05:31 備援排程)：目標為前一個交易日 (週二~週六對應週一~週五)
    - 若台灣時間 >= 12:00 (例如傍晚 17:37 主要排程)：目標為當天 (若遇週末則為上週五)
    """
    now = now or get_taipei_now()
    cur_weekday = now.weekday()  # 0=週一, 4=週五, 5=週六, 6=週日

    if now.hour < 12:
        # 清晨/凌晨排程 (目標是前一交易日)
        if cur_weekday == 0:  # 週一凌晨 -> 上週五
            target = now - timedelta(days=3)
        elif cur_weekday == 6:  # 週日凌晨 -> 上週五
            target = now - timedelta(days=2)
        else:  # 週二至週六凌晨 -> 昨天 (週一至週五)
            target = now - timedelta(days=1)
    else:
        # 傍晚/下午排程 (目標是當天交易日)
        if cur_weekday == 5:  # 週六傍晚 -> 週五
            target = now - timedelta(days=1)
        elif cur_weekday == 6:  # 週日傍晚 -> 週五
            target = now - timedelta(days=2)
        else:  # 週一至週五傍晚 -> 今天
            target = now

    return target.strftime("%Y-%m-%d")


def check_gdrive_via_gas(upload_url: str, folder_id: str, target_date_compact: str) -> bool:
    """透過 Google Apps Script Web App 查詢目標資料夾檔案"""
    try:
        payload = {
            "action": "check_exists",
            "folder_id": folder_id,
            "filename_pattern": f"api_absr1_{target_date_compact}"
        }
        headers = {"Content-Type": "application/json"}
        resp = requests.post(upload_url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get("exists") is True:
                print(f"[✓] GAS 查詢成功：Google Drive 已存在 {target_date_compact} 資料庫檔案。")
                return True
    except Exception as e:
        print(f"[*] GAS 查詢略過或異常: {e}")
    return False


def check_gdrive_via_service_account(folder_id: str, target_date_compact: str, target_date_hyphen: str) -> bool:
    """透過 Google Cloud Service Account API 查詢檔案"""
    try:
        from gdrive_sync import get_gdrive_service
        service = get_gdrive_service()
        if not service:
            return False

        # 查詢全市場、TWSE 或 TPEX 的 Parquet 檔案
        # 匹配: api_absr1_2026-08-27... 或 api_absr1_20260827...
        query = (
            f"'{folder_id}' in parents and "
            f"(name contains '{target_date_compact}' or name contains '{target_date_hyphen}') and "
            f"name contains '.parquet' and "
            f"trashed = false"
        )
        results = service.files().list(q=query, fields="files(id, name, size)", pageSize=10).execute()
        files = results.get("files", [])
        
        # 檢查是否有全市場整合檔或 TWSE 檔案且大小 > 50KB
        valid_files = [f for f in files if int(f.get("size", 0)) > 50000]
        if valid_files:
            print(f"[✓] Google Drive API 查詢成功：找到 {len(valid_files)} 個有效資料庫檔案：")
            for vf in valid_files:
                print(f"    - {vf.get('name')} (ID: {vf.get('id')}, Size: {int(vf.get('size', 0)):,} bytes)")
            return True
    except Exception as e:
        print(f"[*] Service Account 查詢異常: {e}")
    return False


def should_skip_crawler(specified_date: str = "") -> Tuple[bool, str]:
    """
    核心判定函數：
    回傳 (是否跳過, 目標日期 YYYY-MM-DD)
    """
    now = get_taipei_now()
    target_date = specified_date.strip() if specified_date else get_expected_trade_date(now)
    
    target_compact = target_date.replace("-", "")
    target_hyphen = target_date if "-" in target_date else f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"

    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    gas_url = os.environ.get("GDRIVE_UPLOAD_URL", "").strip()

    print(f"==================================================")
    print(f"[*] Google Drive 資料存在性快速檢查 (Pre-check)")
    print(f"[*] 當前台灣時間: {now.strftime('%Y-%m-%d %H:%M:%S')} (時區 UTC+8)")
    print(f"[*] 檢查目標交易日: {target_hyphen} (緊湊格式: {target_compact})")
    print(f"[*] Google Drive Folder ID: {folder_id or '(未配置)'}")
    print(f"==================================================")

    if not folder_id:
        print("[!] 未設定 GDRIVE_FOLDER_ID，無法檢查雲端，預設繼續執行爬蟲。")
        return False, target_hyphen

    # 1. 優先嘗試 GAS 查詢
    if gas_url:
        if check_gdrive_via_gas(gas_url, folder_id, target_compact) or check_gdrive_via_gas(gas_url, folder_id, target_hyphen):
            return True, target_hyphen

    # 2. 嘗試 Service Account 查詢
    if check_gdrive_via_service_account(folder_id, target_compact, target_hyphen):
        return True, target_hyphen

    print(f"[!] Google Drive 尚未檢測到 {target_hyphen} 的完整資料庫，需要執行採集！")
    return False, target_hyphen


if __name__ == "__main__":
    cli_date = sys.argv[1] if len(sys.argv) > 1 else ""
    skip, t_date = should_skip_crawler(cli_date)

    # 寫入 GitHub Actions Step Outputs 與環境變數
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output and os.path.exists(github_output):
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"should_skip={'true' if skip else 'false'}\n")
            f.write(f"target_date={t_date}\n")

    print(f"\n[SUMMARY] SHOULD_SKIP={'true' if skip else 'false'}")
    print(f"[SUMMARY] TARGET_DATE={t_date}")
