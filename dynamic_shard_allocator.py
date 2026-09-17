"""
動態分片重新分配系統 - 100% 成功率方案
================================================================

核心策略：
1. 第 1 輪後分析失敗率，動態重新分配失敗標的
2. 優先度隊列：按失敗輪數倒序，失敗越多的越優先推進
3. 跨分片調度：失敗標的分散給多個 Worker 平行抓取
4. 漸進式延遲和策略切換：根據失敗類型調整參數

目標：整個爬蟲執行中，通過 N 輪迭代達成 100% 成功（不等次日）
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib

TAIPEI_TZ = timezone(timedelta(hours=8))


class FailureCategory(Enum):
    """失敗分類"""
    NO_DATA = "no_data_reported"  # 明確無資料（正常情況）
    TRANSIENT_HTTP = "http_exception"  # 暫時性 HTTP 錯誤（應重試）
    PERSISTENT_403 = "menu_http_error:403"  # 永久 403（需要特殊處理）
    LINK_MISSING = "post_missing_download_link"  # POST 成功但無連結（延遲不足）
    UNKNOWN = "unknown"  # 未知


@dataclass
class ShardTask:
    """單個分片的任務"""
    symbol: str
    retry_count: int = 0
    last_failure_reason: Optional[str] = None
    last_failure_time: Optional[float] = None
    assigned_shard_id: int = 0


@dataclass
class RoundResult:
    """每一輪的執行結果"""
    round_num: int
    shard_id: int
    successful: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)  # (symbol, reason)
    no_data: List[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    def duration_sec(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return 0.0
    
    def success_rate(self) -> float:
        total = len(self.successful) + len(self.failed) + len(self.no_data)
        if total == 0:
            return 0.0
        return len(self.successful) / total


@dataclass
class AllocationStrategy:
    """分片分配策略"""
    use_balanced_round_robin: bool = True  # True: 每個分片分配相等數量
    use_sequential_blocks: bool = False    # True: 每個分片分配連續塊（減少 IP 特徵）
    use_adaptive_retry: bool = True        # True: 重試優先分配給成功率高的分片
    delay_multiplier_per_retry: float = 1.2  # 每重試 1 次延遲增加 20%
    max_concurrent_per_symbol: int = 1    # 單個標的最多並行幾個 worker（為 1 時單線）


class DynamicShardAllocator:
    """
    動態分片重新分配器
    
    負責：
    1. 初始分片分配（可選固定或動態均勻）
    2. 每輪結束後分析失敗並重新分配
    3. 計算適應性延遲和重試策略
    4. 生成分片配置文件供各 Worker 讀取
    """
    
    def __init__(
        self,
        all_symbols: List[str],
        num_shards: int,
        strategy: Optional[AllocationStrategy] = None,
        state_dir: str = "./shard_state"
    ):
        self.all_symbols = all_symbols
        self.num_shards = num_shards
        self.strategy = strategy or AllocationStrategy()
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        
        # 每個分片的當前任務清單
        self.shard_tasks: Dict[int, List[ShardTask]] = {i: [] for i in range(num_shards)}
        
        # 執行歷史
        self.round_results: List[RoundResult] = []
        
        # 全局追蹤
        self.global_successful: Set[str] = set()
        self.global_no_data: Set[str] = set()
        self.global_failed: Dict[str, Tuple[str, int]] = {}  # symbol -> (reason, final_retry_count)
        
        # 初始分配
        self._initial_allocation()
    
    def _initial_allocation(self):
        """初始分片分配"""
        if self.strategy.use_sequential_blocks:
            # 順序塊分配：每個分片分配連續塊
            # 優點：分片內的標的相近，可能共享更多特徵
            block_size = len(self.all_symbols) // self.num_shards
            for shard_id in range(self.num_shards):
                start_idx = shard_id * block_size
                end_idx = start_idx + block_size if shard_id < self.num_shards - 1 else len(self.all_symbols)
                symbols_for_shard = self.all_symbols[start_idx:end_idx]
                self.shard_tasks[shard_id] = [
                    ShardTask(sym, assigned_shard_id=shard_id) 
                    for sym in symbols_for_shard
                ]
        else:
            # 均勻輪詢分配（保持與現有邏輯相同）
            for i, symbol in enumerate(self.all_symbols):
                shard_id = i % self.num_shards
                self.shard_tasks[shard_id].append(
                    ShardTask(symbol, assigned_shard_id=shard_id)
                )
    
    def get_shard_symbols(self, shard_id: int) -> List[str]:
        """取得某個分片應該抓取的標的清單"""
        return [task.symbol for task in self.shard_tasks[shard_id]]
    
    def record_round_result(
        self,
        round_num: int,
        shard_id: int,
        successful: List[str],
        failed: List[Tuple[str, str]],
        no_data: List[str]
    ) -> RoundResult:
        """
        記錄某一輪的執行結果
        
        Args:
            round_num: 輪次編號（1-based）
            shard_id: 分片編號
            successful: 成功的標的清單
            failed: 失敗的 (symbol, reason) 清單
            no_data: 無資料的標的清單
        """
        result = RoundResult(
            round_num=round_num,
            shard_id=shard_id,
            successful=successful,
            failed=failed,
            no_data=no_data,
            end_time=time.time()
        )
        self.round_results.append(result)
        
        # 更新全局追蹤
        self.global_successful.update(successful)
        self.global_no_data.update(no_data)
        for sym, reason in failed:
            if sym not in self.global_successful and sym not in self.global_no_data:
                retry_count = self.global_failed.get(sym, (reason, 0))[1] + 1
                self.global_failed[sym] = (reason, retry_count)
        
        # 更新分片內的任務狀態
        for sym in successful:
            self._mark_task_status(shard_id, sym, "success")
        for sym in no_data:
            self._mark_task_status(shard_id, sym, "no_data")
        for sym, reason in failed:
            self._mark_task_status(shard_id, sym, "failed", reason)
        
        return result
    
    def _mark_task_status(
        self,
        shard_id: int,
        symbol: str,
        status: str,
        reason: Optional[str] = None
    ):
        """更新任務狀態"""
        tasks = self.shard_tasks.get(shard_id, [])
        for task in tasks:
            if task.symbol == symbol:
                task.retry_count += 1
                if status == "failed":
                    task.last_failure_reason = reason
                    task.last_failure_time = time.time()
                break
    
    def compute_next_round_allocation(
        self,
        max_retries_per_symbol: int = 10,
        focus_on_high_failure_rate: bool = True
    ) -> Dict[int, List[ShardTask]]:
        """
        計算下一輪的分片分配
        
        策略：
        1. 成功的標的移除
        2. 無資料的標的移除
        3. 失敗的標的重新分配：優先度排序（失敗次數多的先）
        4. 分散到所有分片（減輕單個分片的負擔）
        """
        # 收集待重試的標的
        to_retry: List[Tuple[str, str, int]] = []  # (symbol, reason, retry_count)
        
        for shard_id in range(self.num_shards):
            tasks_to_remove = []
            for task in self.shard_tasks[shard_id]:
                if task.symbol in self.global_successful or task.symbol in self.global_no_data:
                    tasks_to_remove.append(task)
                elif task.retry_count < max_retries_per_symbol:
                    to_retry.append(
                        (task.symbol, task.last_failure_reason or "unknown", task.retry_count)
                    )
                    tasks_to_remove.append(task)
            
            for task in tasks_to_remove:
                self.shard_tasks[shard_id].remove(task)
        
        if not to_retry:
            # 沒有待重試的，全部完成
            return self.shard_tasks
        
        # 按失敗次數排序（多次失敗的優先）
        to_retry.sort(key=lambda x: (-x[2], x[0]))
        
        # 重新分配：輪詢方式分散到各分片
        new_allocation = {i: [] for i in range(self.num_shards)}
        for idx, (symbol, reason, retry_count) in enumerate(to_retry):
            target_shard = idx % self.num_shards
            new_allocation[target_shard].append(
                ShardTask(symbol, retry_count=retry_count, last_failure_reason=reason, assigned_shard_id=target_shard)
            )
        
        self.shard_tasks = new_allocation
        return self.shard_tasks
    
    def get_adaptive_delay(
        self,
        shard_id: int,
        round_num: int,
        base_delay: float = 0.3
    ) -> float:
        """
        計算自適應延遲
        
        根據：
        1. 目前輪數
        2. 該分片的成功率
        3. 重試次數
        """
        # 尋找該分片在此輪的結果
        round_results_for_shard = [
            r for r in self.round_results 
            if r.shard_id == shard_id and r.round_num == round_num
        ]
        
        if not round_results_for_shard:
            # 無此輪結果，使用默認
            return base_delay * (1.0 + (round_num - 1) * 0.3)
        
        result = round_results_for_shard[0]
        success_rate = result.success_rate()
        
        # 基礎延遲 + 輪數遞增
        base_with_rounds = base_delay * (1.0 + (round_num - 1) * 0.3)
        
        # 根據成功率調整
        if success_rate < 0.3:
            # 成功率低於 30%，大幅增加延遲
            return base_with_rounds * 2.0
        elif success_rate < 0.5:
            # 成功率 30-50%，適度增加
            return base_with_rounds * 1.5
        elif success_rate < 0.8:
            # 成功率 50-80%，小幅增加
            return base_with_rounds * 1.2
        else:
            # 成功率 > 80%，保持或略微增加
            return base_with_rounds * 1.1
    
    def get_global_stats(self) -> Dict:
        """取得全局統計"""
        total = len(self.all_symbols)
        successful = len(self.global_successful)
        no_data = len(self.global_no_data)
        failed = len(self.global_failed)
        
        return {
            "total_symbols": total,
            "successful": successful,
            "no_data": no_data,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0.0,
            "effective_rate": (successful + no_data) / total if total > 0 else 0.0,
            "failure_reasons": {
                reason: count
                for reason, (_, count) in self.global_failed.items()
            } if isinstance(self.global_failed, dict) else {}
        }
    
    def save_state(self, filename: Optional[str] = None):
        """保存分片狀態到文件"""
        if filename is None:
            timestamp = datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S")
            filename = f"{self.state_dir}/allocator_state_{timestamp}.json"
        
        state = {
            "timestamp": datetime.now(TAIPEI_TZ).isoformat(),
            "all_symbols": self.all_symbols,
            "num_shards": self.num_shards,
            "global_stats": self.get_global_stats(),
            "shard_tasks": {
                str(shard_id): [asdict(task) for task in tasks]
                for shard_id, tasks in self.shard_tasks.items()
            },
            "round_results": [
                {
                    "round_num": r.round_num,
                    "shard_id": r.shard_id,
                    "successful_count": len(r.successful),
                    "failed_count": len(r.failed),
                    "no_data_count": len(r.no_data),
                    "success_rate": r.success_rate(),
                    "duration_sec": r.duration_sec()
                }
                for r in self.round_results
            ]
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        
        return filename
    
    def print_summary(self):
        """打印執行摘要"""
        stats = self.get_global_stats()
        print("\n" + "="*60)
        print("【動態分片執行摘要】")
        print("="*60)
        print(f"總標的數: {stats['total_symbols']}")
        print(f"成功:     {stats['successful']} ({stats['success_rate']*100:.1f}%)")
        print(f"無資料:   {stats['no_data']}")
        print(f"失敗:     {stats['failed']} ({(1-stats['success_rate'])*100:.1f}%)")
        print(f"有效率:   {stats['effective_rate']*100:.1f}% (成功+無資料)/總數")
        print("="*60 + "\n")
        
        if self.round_results:
            print("【按輪次統計】")
            for r in self.round_results:
                print(
                    f"  第 {r.round_num} 輪 (Shard {r.shard_id}): "
                    f"成功 {len(r.successful)} | 失敗 {len(r.failed)} | "
                    f"無資料 {len(r.no_data)} | 成功率 {r.success_rate()*100:.1f}% | "
                    f"耗時 {r.duration_sec():.1f}s"
                )


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    # 示例：100 檔標的，6 個分片
    test_symbols = [f"SYM{i:04d}" for i in range(100)]
    
    allocator = DynamicShardAllocator(
        all_symbols=test_symbols,
        num_shards=6,
        strategy=AllocationStrategy(use_balanced_round_robin=True)
    )
    
    print(f"初始分配: 分片 0 有 {len(allocator.get_shard_symbols(0))} 檔")
    print(f"分片 0 的標的: {allocator.get_shard_symbols(0)}")
    
    # 模擬第 1 輪的結果
    successful_r1 = [f"SYM{i:04d}" for i in range(0, 10)]
    failed_r1 = [(f"SYM{i:04d}", "post_missing_download_link") for i in range(10, 15)]
    no_data_r1 = [f"SYM{i:04d}" for i in range(15, 18)]
    
    allocator.record_round_result(
        round_num=1,
        shard_id=0,
        successful=successful_r1,
        failed=failed_r1,
        no_data=no_data_r1
    )
    
    print(f"\n第 1 輪執行完成")
    allocator.print_summary()
    
    # 計算第 2 輪分配
    allocator.compute_next_round_allocation(max_retries_per_symbol=5)
    print(f"\n第 2 輪重新分配: 分片 0 需重試 {len(allocator.get_shard_symbols(0))} 檔")
    
    # 保存狀態
    state_file = allocator.save_state()
    print(f"\n狀態已保存: {state_file}")
