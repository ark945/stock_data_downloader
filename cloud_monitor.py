#!/usr/bin/env python3
"""
激進 100% 爬蟲 - 雲端實時監控指令碼
監控 GitHub Actions 執行進度並實時顯示日誌
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import subprocess

TAIPEI_TZ = timezone(timedelta(hours=8))

def get_taipei_now() -> datetime:
    """取得台灣時間"""
    return datetime.now(timezone.utc).astimezone(TAIPEI_TZ)

def run_command(cmd: str, silent: bool = False) -> str:
    """執行 shell 命令並返回輸出"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout + result.stderr
        if not silent:
            print(output)
        return output
    except Exception as e:
        print(f"❌ 命令執行失敗: {str(e)}")
        return ""

def get_latest_workflow_run(repo: str, workflow: str) -> Optional[Dict[str, Any]]:
    """獲取最新工作流執行"""
    cmd = f'gh run list -R {repo} -w {workflow} --json id,status,name,createdAt,updatedAt -L 1'
    output = run_command(cmd, silent=True)
    
    if not output.strip():
        return None
    
    try:
        runs = json.loads(output)
        if runs:
            return runs[0]
    except json.JSONDecodeError:
        pass
    
    return None

def monitor_workflow(repo: str, workflow: str, check_interval: int = 30, max_duration: int = 7200):
    """
    監控工作流執行
    
    Args:
        repo: 倉庫 (owner/repo)
        workflow: 工作流檔案名
        check_interval: 檢查間隔 (秒)
        max_duration: 最大監控時間 (秒)
    """
    
    print("\n" + "="*70)
    print("🔴 激進 100% 爬蟲 - 雲端實時監控")
    print("="*70)
    print(f"倉庫: {repo}")
    print(f"工作流: {workflow}")
    print(f"開始時間: {get_taipei_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    
    start_time = time.time()
    last_status = None
    last_conclusion = None
    run_id = None
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > max_duration:
            print(f"\n⏰ 超過最大監控時間 ({max_duration//60} 分鐘)，停止監控")
            break
        
        # 獲取最新執行
        latest_run = get_latest_workflow_run(repo, workflow)
        
        if not latest_run:
            print(f"[{get_taipei_now().strftime('%H:%M:%S')}] ⏳ 等待工作流啟動...")
            time.sleep(check_interval)
            continue
        
        run_id = latest_run.get("id")
        status = latest_run.get("status", "unknown")
        conclusion = latest_run.get("conclusion", "")
        name = latest_run.get("name", "")
        created_at = latest_run.get("createdAt", "")
        
        # 狀態變化時顯示
        if status != last_status or conclusion != last_conclusion:
            last_status = status
            last_conclusion = conclusion
            
            ts = get_taipei_now().strftime("%H:%M:%S")
            
            status_icon = {
                "queued": "⏳",
                "in_progress": "🔄",
                "completed": "✅" if conclusion == "success" else "❌",
            }.get(status, "❓")
            
            conclusion_text = {
                "success": "成功",
                "failure": "失敗",
                "cancelled": "已取消",
                "skipped": "已跳過",
                "stale": "已過期",
                "startup_failure": "啟動失敗",
                "timed_out": "超時",
                "action_required": "需要操作",
            }.get(conclusion, "")
            
            print(f"[{ts}] {status_icon} 【狀態更新】")
            print(f"  工作流: {name}")
            print(f"  狀態: {status}")
            if conclusion_text:
                print(f"  結論: {conclusion_text}")
            print()
        
        # 顯示進度
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        ts = get_taipei_now().strftime("%H:%M:%S")
        
        if status == "in_progress":
            print(f"[{ts}] 🔄 執行中... (+{minutes}:{seconds:02d})", end="\r")
        elif status == "queued":
            print(f"[{ts}] ⏳ 排隊中... (+{minutes}:{seconds:02d})", end="\r")
        elif status == "completed":
            print(f"\n[{ts}] ✅ 工作流已完成")
            print(f"  總耗時: {minutes} 分 {seconds} 秒")
            print(f"  結論: {conclusion}")
            
            if run_id:
                print(f"\n📊 查看詳細日誌:")
                print(f"  https://github.com/{repo}/actions/runs/{run_id}")
            
            break
        
        sys.stdout.flush()
        time.sleep(check_interval)
    
    print("\n" + "="*70)
    print("🎉 監控任務完成！")
    print("="*70 + "\n")

def get_workflow_logs(repo: str, run_id: str):
    """下載工作流日誌"""
    print(f"\n📥 下載工作流日誌 (Run ID: {run_id})...")
    
    # 使用 GitHub API 獲取日誌
    cmd = f'gh run view {run_id} -R {repo} --log'
    output = run_command(cmd, silent=False)
    
    # 保存到本地檔案
    log_file = f"workflow_run_{run_id}.log"
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n💾 日誌已保存: {log_file}")
    except Exception as e:
        print(f"❌ 保存日誌失敗: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="激進 100% 爬蟲 - 雲端實時監控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 監控最新工作流執行
  python cloud_monitor.py

  # 指定倉庫和工作流
  python cloud_monitor.py --repo ark945/stock_data_downloader --workflow aggressive-100percent-crawler.yml

  # 調整檢查間隔 (每 60 秒檢查一次)
  python cloud_monitor.py --check-interval 60
        """
    )
    
    parser.add_argument(
        "--repo",
        default="ark945/stock_data_downloader",
        help="GitHub 倉庫 (預設: ark945/stock_data_downloader)"
    )
    parser.add_argument(
        "--workflow",
        default="aggressive-100percent-crawler.yml",
        help="工作流檔案名 (預設: aggressive-100percent-crawler.yml)"
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=30,
        help="檢查間隔 (秒，預設: 30)"
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=7200,
        help="最大監控時間 (秒，預設: 7200 = 2 小時)"
    )
    parser.add_argument(
        "--download-logs",
        action="store_true",
        help="完成後下載工作流日誌"
    )
    
    args = parser.parse_args()
    
    try:
        # 監控工作流
        monitor_workflow(
            repo=args.repo,
            workflow=args.workflow,
            check_interval=args.check_interval,
            max_duration=args.max_duration
        )
        
        # 下載日誌 (如需要)
        if args.download_logs:
            latest_run = get_latest_workflow_run(args.repo, args.workflow)
            if latest_run and latest_run.get("id"):
                get_workflow_logs(args.repo, latest_run["id"])
    
    except KeyboardInterrupt:
        print("\n\n⛔ 監控已中止")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 發生錯誤: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
