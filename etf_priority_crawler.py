"""
ETF 優先級爬蟲 - 100% 成功率方案 (非次日)
==========================================================

核心策略：
1. ETF 分層：短代碼(4位) vs 長代碼(5-6位) 分別處理
2. 優先級隊列：先抓簡單的，困難的持久重試
3. 漸進式延遲：短代碼從 0.8s 開始，長代碼從 0.4s 開始
4. 動態判定：每輪檢測是否需要切換到「超級延遲模式」
5. 平行重試：多個 Worker 針對不同分層同時推進

目標：在單次執行內透過 N 輪迭代達成 100%
"""

import os
import time
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import re

TAIPEI_TZ = timezone(timedelta(hours=8))


class ETFCategory(Enum):
    """ETF 分類"""
    SHORT_CODE = "short"      # 4位數字 (0050, 0051, 0053...)
    LONG_CODE = "long"        # 5-6位數字 (00631L, 00640L, 006208...)
    LEVERAGED = "leveraged"   # 尾數 L/R/K (槓桿/反向)
    HYBRID = "hybrid"         # 5位混合型 (00400A)
    UNKNOWN = "unknown"


@dataclass
class ETFSymbol:
    """ETF 標的"""
    code: str
    name: str
    category: ETFCategory = ETFCategory.UNKNOWN
    retry_count: int = 0
    last_failure_reason: Optional[str] = None
    first_round_result: Optional[str] = None  # "success", "failed", "no_data"
    
    def __post_init__(self):
        # 自動分類
        if self.category == ETFCategory.UNKNOWN:
            self.category = self._classify()
    
    def _classify(self) -> ETFCategory:
        code = self.code
        
        # 檢查尾數 (槓桿/反向)
        if code[-1] in ['L', 'R', 'K']:
            return ETFCategory.LEVERAGED
        
        # 檢查長度
        if len(code) == 4:
            return ETFCategory.SHORT_CODE
        elif len(code) == 5:
            if code[-1].isalpha():
                return ETFCategory.HYBRID  # 如 00400A
            return ETFCategory.SHORT_CODE
        elif len(code) >= 6:
            return ETFCategory.LONG_CODE
        
        return ETFCategory.UNKNOWN


class ETFPriorityCrawler:
    """
    ETF 優先級爬蟲調度器
    
    負責：
    1. 將 ETF 按分類分層
    2. 為每層分配不同的延遲和重試策略
    3. 監控每輪進度，動態調整參數
    4. 生成 100% 成功的執行計畫
    """
    
    def __init__(self, etf_symbols: List[Tuple[str, str]]):
        """
        Args:
            etf_symbols: [(code, name), ...]
        """
        self.etf_objects = [
            ETFSymbol(code=c, name=n) 
            for c, n in etf_symbols
        ]
        
        # 按分類分層
        self.by_category: Dict[ETFCategory, List[ETFSymbol]] = {
            cat: [] for cat in ETFCategory
        }
        for etf in self.etf_objects:
            self.by_category[etf.category].append(etf)
        
        # 執行狀態
        self.completed: set = set()  # 已成功的代碼
        self.pending: Dict[str, ETFSymbol] = {e.code: e for e in self.etf_objects}
        self.round_results: List[Dict] = []
    
    def get_strategy_for_round(self, round_num: int) -> Dict:
        """
        根據輪次生成策略
        
        策略規則：
        - 第 1 輪：低延遲探測 (0.3s 長/0.6s 短)
        - 第 2-3 輪：中延遲補抓 (0.8-1.0s)
        - 第 4+ 輪：高延遲強化 (1.5-3.0s)
        """
        
        # 計算前幾輪的成功率
        current_success_rate = self._calculate_success_rate()
        
        strategy = {
            "round": round_num,
            "by_category": {}
        }
        
        if round_num == 1:
            # 探測輪：快速識別可抓的標的
            strategy["by_category"] = {
                ETFCategory.LONG_CODE: {
                    "delay": 0.3,
                    "timeout": 8,
                    "max_retries": 1
                },
                ETFCategory.SHORT_CODE: {
                    "delay": 0.6,  # 短代碼本來就難
                    "timeout": 8,
                    "max_retries": 1
                },
                ETFCategory.LEVERAGED: {
                    "delay": 0.4,
                    "timeout": 8,
                    "max_retries": 1
                },
                ETFCategory.HYBRID: {
                    "delay": 1.0,  # 混合型最難，給最高延遲
                    "timeout": 10,
                    "max_retries": 2
                }
            }
        
        elif round_num in [2, 3]:
            # 補抓輪：針對第 1 輪失敗的
            strategy["by_category"] = {
                ETFCategory.LONG_CODE: {
                    "delay": 0.8,
                    "timeout": 8,
                    "max_retries": 2
                },
                ETFCategory.SHORT_CODE: {
                    "delay": 1.2,  # 短代碼加倍延遲
                    "timeout": 10,
                    "max_retries": 2
                },
                ETFCategory.LEVERAGED: {
                    "delay": 0.9,
                    "timeout": 8,
                    "max_retries": 2
                },
                ETFCategory.HYBRID: {
                    "delay": 1.5,
                    "timeout": 12,
                    "max_retries": 3
                }
            }
        
        elif round_num in [4, 5]:
            # 強化輪：成功率還在低檔
            strategy["by_category"] = {
                ETFCategory.LONG_CODE: {
                    "delay": 1.5,
                    "timeout": 10,
                    "max_retries": 3
                },
                ETFCategory.SHORT_CODE: {
                    "delay": 2.0,  # 大幅增加
                    "timeout": 12,
                    "max_retries": 3
                },
                ETFCategory.LEVERAGED: {
                    "delay": 1.5,
                    "timeout": 10,
                    "max_retries": 3
                },
                ETFCategory.HYBRID: {
                    "delay": 2.5,
                    "timeout": 15,
                    "max_retries": 5
                }
            }
        
        else:  # round_num >= 6
            # 終極輪：盡力救回所有
            strategy["by_category"] = {
                ETFCategory.LONG_CODE: {
                    "delay": 2.5,
                    "timeout": 12,
                    "max_retries": 5
                },
                ETFCategory.SHORT_CODE: {
                    "delay": 3.0,  # 最高延遲
                    "timeout": 15,
                    "max_retries": 5
                },
                ETFCategory.LEVERAGED: {
                    "delay": 2.5,
                    "timeout": 12,
                    "max_retries": 5
                },
                ETFCategory.HYBRID: {
                    "delay": 3.5,  # 最高
                    "timeout": 20,
                    "max_retries": 10
                }
            }
        
        # 動態調整：如果成功率太低，全體增加延遲
        if current_success_rate < 0.2:
            print(f"[警告] 第 {round_num} 輪成功率 {current_success_rate*100:.1f}% < 20%，激發超級延遲模式")
            for cat in strategy["by_category"]:
                strategy["by_category"][cat]["delay"] *= 1.5  # +50% 延遲
                strategy["by_category"][cat]["max_retries"] = min(
                    strategy["by_category"][cat]["max_retries"] + 2,
                    10  # 最多 10 次重試
                )
        
        return strategy
    
    def _calculate_success_rate(self) -> float:
        """計算當前成功率"""
        if not self.etf_objects:
            return 0.0
        successful = len(self.completed)
        return successful / len(self.etf_objects)
    
    def record_round_result(
        self,
        round_num: int,
        successful_codes: List[str],
        failed_codes: List[Tuple[str, str]],  # (code, reason)
        no_data_codes: List[str]
    ):
        """記錄每一輪的結果"""
        result = {
            "round": round_num,
            "timestamp": datetime.now(TAIPEI_TZ).isoformat(),
            "successful": successful_codes,
            "failed": failed_codes,
            "no_data": no_data_codes
        }
        self.round_results.append(result)
        
        # 更新狀態
        for code in successful_codes:
            self.completed.add(code)
            if code in self.pending:
                self.pending[code].first_round_result = "success"
                del self.pending[code]
        
        for code in no_data_codes:
            self.completed.add(code)
            if code in self.pending:
                self.pending[code].first_round_result = "no_data"
                del self.pending[code]
        
        for code, reason in failed_codes:
            if code in self.pending:
                self.pending[code].retry_count += 1
                self.pending[code].last_failure_reason = reason
        
        self._print_round_summary(round_num)
    
    def _print_round_summary(self, round_num: int):
        """打印輪次摘要"""
        if not self.round_results:
            return
        
        result = self.round_results[-1]
        total = len(self.etf_objects)
        successful = len(result["successful"])
        failed = len(result["failed"])
        no_data = len(result["no_data"])
        success_rate = successful / (successful + failed + no_data) if (successful + failed + no_data) > 0 else 0
        
        print(f"\n【第 {round_num} 輪結果】")
        print(f"  成功: {successful} / {total} ({success_rate*100:.1f}%)")
        print(f"  失敗: {failed}")
        print(f"  無資料: {no_data}")
        print(f"  待重試: {len(self.pending)}")
        
        # 按分類顯示失敗詳情
        if failed > 0 and failed <= 10:
            print(f"  失敗詳情:")
            for code, reason in result["failed"][:10]:
                etf = next((e for e in self.etf_objects if e.code == code), None)
                if etf:
                    print(f"    - {code} ({etf.category.value}): {reason}")
    
    def get_pending_by_category(self) -> Dict[ETFCategory, List[ETFSymbol]]:
        """取得待重試的標的（按分類）"""
        pending_by_cat = {cat: [] for cat in ETFCategory}
        for etf in self.pending.values():
            pending_by_cat[etf.category].append(etf)
        return pending_by_cat
    
    def get_summary(self) -> Dict:
        """取得執行摘要"""
        total = len(self.etf_objects)
        completed = len(self.completed)
        pending = len(self.pending)
        
        # 統計失敗原因
        failure_reasons: Dict[str, int] = {}
        for etf in self.pending.values():
            if etf.last_failure_reason:
                failure_reasons[etf.last_failure_reason] = failure_reasons.get(etf.last_failure_reason, 0) + 1
        
        return {
            "total": total,
            "completed": completed,
            "success_rate": completed / total if total > 0 else 0,
            "pending": pending,
            "pending_by_category": {
                cat.value: len(etfs)
                for cat, etfs in self.get_pending_by_category().items()
            },
            "failure_reasons": failure_reasons,
            "rounds_executed": len(self.round_results)
        }
    
    def print_final_report(self):
        """打印最終報告"""
        summary = self.get_summary()
        
        print("\n" + "="*60)
        print("【ETF 100% 爬蟲最終報告】")
        print("="*60)
        print(f"總 ETF 數: {summary['total']}")
        print(f"已完成: {summary['completed']} ({summary['success_rate']*100:.1f}%)")
        print(f"待重試: {summary['pending']}")
        print(f"執行輪數: {summary['rounds_executed']}")
        print(f"\n失敗分佈 (按分類):")
        for cat, count in summary["pending_by_category"].items():
            if count > 0:
                print(f"  {cat}: {count} 檔")
        print(f"\n失敗原因 Top 3:")
        sorted_reasons = sorted(summary["failure_reasons"].items(), key=lambda x: -x[1])
        for reason, count in sorted_reasons[:3]:
            print(f"  {reason}: {count} 檔")
        print("="*60 + "\n")


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    # 示例 ETF 清單
    sample_etfs = [
        ("0050", "元大台灣50"),
        ("0051", "元大中型100"),
        ("0053", "元大電子"),
        ("0056", "元大高股息"),
        ("00400A", "主動國泰動能高息"),
        ("006208", "富邦台50"),
        ("00631L", "元大台灣50正2"),
        ("00640L", "富邦日本正2"),
        ("00638R", "元大滬深300反1"),
        ("00657K", "國泰日經225+U"),
    ]
    
    crawler = ETFPriorityCrawler(sample_etfs)
    
    print(f"已註冊 {len(crawler.etf_objects)} 檔 ETF")
    print(f"\n按分類分佈:")
    for cat, etfs in crawler.by_category.items():
        if etfs:
            print(f"  {cat.value}: {len(etfs)} 檔 - {', '.join(e.code for e in etfs[:3])}...")
    
    # 模擬第 1 輪執行
    print(f"\n【模擬執行】")
    strategy_r1 = crawler.get_strategy_for_round(1)
    print(f"\n第 1 輪策略:")
    for cat, params in strategy_r1["by_category"].items():
        if params:
            print(f"  {cat.value}: 延遲={params['delay']}s, timeout={params['timeout']}s")
    
    # 模擬第 1 輪結果 (假設只有某些成功)
    successful_r1 = ["00638R", "00640L"]
    failed_r1 = [
        ("0050", "post_missing_download_link"),
        ("0051", "post_missing_download_link"),
        ("00400A", "post_missing_download_link"),
    ]
    no_data_r1 = []
    
    crawler.record_round_result(1, successful_r1, failed_r1, no_data_r1)
    
    # 第 2 輪
    strategy_r2 = crawler.get_strategy_for_round(2)
    print(f"\n第 2 輪策略 (自動調整):")
    for cat, params in strategy_r2["by_category"].items():
        if params:
            print(f"  {cat.value}: 延遲={params['delay']}s (與第1輪比較)")
    
    print(f"\n待重試標的 (按分類):")
    pending = crawler.get_pending_by_category()
    for cat, etfs in pending.items():
        if etfs:
            print(f"  {cat.value}: {', '.join(e.code for e in etfs)}")
    
    # 最終報告
    crawler.print_final_report()
