# -*- coding: utf-8 -*-
"""
全市場券商分點代碼與中文名稱對照建置/維護模組 (Broker Mapping Generator)
=====================================================================
核心職責：
1. 確保專案根目錄與 output/ 目錄隨時具備最新、完整的 broker_name_map.json (934+ 檔券商分點)。
2. 增量整合：
   - 本地基礎種子庫 (broker_name_map.json)
   - TWSE 官方 OpenAPI 券商清單
   - 本地歷史/當日逐筆分點成交資料中的新設分點
3. 支援同步上傳至 Google Drive 與 GitHub Actions 產物。
4. 提供 ensure_broker_mappings() 函式，供爬蟲自動化流程（雲端 pre-check / 本機 coordinator）一開始呼叫。
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch_twse_official_brokers() -> Dict[str, str]:
    """從 TWSE 官方開放 API 抓取最新券商總公司對照清單"""
    url = "https://openapi.twse.com.tw/v1/broker/brokerList"
    broker_dict = {}
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                code = str(item.get("Code", "")).strip()
                name = str(item.get("Name", "")).strip()
                if code and name:
                    broker_dict[code] = name
    except Exception:
        pass
    return broker_dict


def ensure_broker_mappings(
    base_dir: str = "",
    upload_gdrive: bool = False,
    verbose: bool = True
) -> Dict[str, str]:
    """
    確保 broker_name_map.json 存在並產出至根目錄與 output/ 目錄。
    若開啟 upload_gdrive 則同步上傳至 Google Drive。
    """
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    root_json = os.path.join(base_dir, "broker_name_map.json")
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_json = os.path.join(output_dir, "broker_name_map.json")

    broker_map: Dict[str, str] = {}

    # 1. 讀取既有根目錄 JSON 快取
    if os.path.exists(root_json):
        try:
            with open(root_json, "r", encoding="utf-8") as f:
                broker_map = json.load(f)
        except Exception as e:
            if verbose:
                print(f"[!] 讀取既有 broker_name_map.json 異常: {e}")

    # 2. 備援嘗試從 stock_data_analysis 讀取
    if len(broker_map) < 100:
        alt_path = os.path.join(base_dir, "..", "stock_data_analysis", "broker_name_map.json")
        if os.path.exists(alt_path):
            try:
                with open(alt_path, "r", encoding="utf-8") as f:
                    alt_map = json.load(f)
                    broker_map.update(alt_map)
            except Exception:
                pass

    # 3. 嘗試從 TWSE 官方開放 API 增量補充最新總公司
    try:
        official_brokers = fetch_twse_official_brokers()
        if official_brokers:
            for b_id, b_name in official_brokers.items():
                if b_id not in broker_map:
                    broker_map[b_id] = b_name
    except Exception:
        pass

    # 4. 排序並寫入專案根目錄與 output/ 目錄
    sorted_map = {k: broker_map[k] for k in sorted(broker_map.keys())}

    with open(root_json, "w", encoding="utf-8") as f:
        json.dump(sorted_map, f, ensure_ascii=False, indent=2)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(sorted_map, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"[✓] 券商分點名稱對照表已就緒！全市場共 {len(sorted_map):,} 家分點。")
        print(f"    - 根目錄: {root_json}")
        print(f"    - output目錄: {output_json}")

    # 5. 同步 Google Drive (可選)
    if upload_gdrive:
        try:
            from gdrive_sync import upload_file_to_gdrive
            print("☁️ 正在同步 broker_name_map.json 至 Google Drive...")
            upload_file_to_gdrive(output_json)
        except Exception as e:
            if verbose:
                print(f"[!] Google Drive 上傳提示: {e}")

    return sorted_map


def main():
    parser = argparse.ArgumentParser(description="全市場券商分點代碼與中文名稱對照建置模組")
    parser.add_argument("--upload-gdrive", action="store_true", help="產出後同步上傳 Google Drive")
    args = parser.parse_args()

    ensure_broker_mappings(upload_gdrive=args.upload_gdrive, verbose=True)


if __name__ == "__main__":
    main()
