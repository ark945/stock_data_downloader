"""
TPEX 證券櫃檯買賣中心（上櫃股票）券商買賣日報表爬蟲 — 統一調度閘道 (Gateway / Facade)
架構職責分工：
1. 雲端環境 (GitHub Actions / CI)：自動調用 tpex_crawler_cloud (純淨單一會話、20-Shard 矩陣)
2. 本地端環境 (Local Desktop)：自動調用 tpex_crawler_local (4~8 Workers 極速並行、斷點續傳快取)
"""

import os
from typing import List, Optional, Tuple
import pandas as pd

from tpex_crawler_cloud import TPEXCloudCrawler
from tpex_crawler_local import TPEXLocalCrawler


def is_running_in_ci() -> bool:
    """判斷是否在 GitHub Actions 或雲端 CI 環境中執行"""
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


class TPEXBrokerCrawler:
    """
    TPEX 櫃買中心券商買賣日報表統一爬蟲介面
    自動依據執行環境（雲端 CI 或本地單機）無縫切換最佳化底層引擎
    """

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir
        self.cloud_engine = TPEXCloudCrawler(download_dir=download_dir)
        self.local_engine = TPEXLocalCrawler(download_dir=download_dir)

    @classmethod
    def get_all_tpex_symbols(cls) -> List[str]:
        """取得全市場上櫃標的清單"""
        return TPEXLocalCrawler.get_all_tpex_symbols()

    def parse_tpex_csv_to_dataframe(self, csv_file_or_text, stock_id: str, trade_date: str) -> Optional[pd.DataFrame]:
        """解析 TPEX CSV 為標準 13 欄位 DataFrame"""
        return self.local_engine.parse_tpex_csv_to_dataframe(csv_file_or_text, stock_id, trade_date)

    def crawl_stocks_with_retry(
        self,
        stock_codes: List[str],
        trade_date: str,
        max_rounds: int = 2,
        cooldown_sec: int = 15,
        workers: int = 4
    ) -> Tuple[List[pd.DataFrame], List[str]]:
        """
        全市場或分片上櫃股票採集 (自適應環境分流)
        - CI / 雲端分片環境：調用 Cloud 純淨持久會話引擎
        - 本地單機環境：調用 Local 極速多進程矩陣 + 斷點續傳引擎
        """
        if is_running_in_ci():
            # 雲端環境採用穩健單會話
            return self.cloud_engine.crawl_stocks(stock_codes, trade_date)
        else:
            # 本地環境採用多進程極速矩陣
            return self.local_engine.crawl_stocks_with_retry(
                stock_codes=stock_codes,
                trade_date=trade_date,
                max_rounds=max_rounds,
                cooldown_sec=cooldown_sec,
                workers=workers
            )
