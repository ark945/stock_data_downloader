# -*- coding: utf-8 -*-
"""
FinMind 逐價分點明細轉換為 ABSR1 券商買賣彙總表工具 (finmind_to_absr1.py)

功能說明：
    將 FinMind 下載之分點逐價明細 (含有價位 price, 買進 buy, 賣出 sell)
    聚合彙總為證交所/櫃買格式之券商買賣日報彙總表 (ABSR1: 包含均價、金額、買賣超與市佔率)。
"""

import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def get_absr1_schema() -> pa.Schema:
    """定義與官方 ABSR1 完全一致的 PyArrow Schema"""
    return pa.schema([
        ('symbol', pa.string()),
        ('trade_date', pa.string()),
        ('broker_id', pa.string()),
        ('buy_vol', pa.float64()),
        ('sell_vol', pa.float64()),
        ('net_vol', pa.float64()),
        ('buy_amt', pa.float64()),
        ('sell_amt', pa.float64()),
        ('net_amt', pa.float64()),
        ('buy_avg_price', pa.float64()),
        ('sell_avg_price', pa.float64()),
        ('turnover', pa.float64()),
        ('market_share', pa.float64()),
    ])


def convert_finmind_to_absr1(input_path: str, output_path: str = None, target_date: str = None) -> str:
    """
    將 FinMind 分點逐價明細 Parquet 轉換為 ABSR1 彙總 Parquet。

    Args:
        input_path (str): 輸入的 FinMind Parquet 檔案路徑。
        output_path (str, optional): 輸出的 ABSR1 Parquet 檔案路徑。若無則自動產生。
        target_date (str, optional): 指定日期過濾 (YYYY-MM-DD)。

    Returns:
        str: 產生的 ABSR1 Parquet 檔案路徑。
    """
    start_time = time.time()
    print(f"[*] 開始讀取 FinMind 檔案: {input_path}")

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"找不到輸入檔案: {input_path}")

    df = pd.read_parquet(input_path)
    total_rows = len(df)
    print(f"    成功讀取 {total_rows:,} 筆逐價分點明細。")

    # 檢查必要欄位
    required_cols = {'stock_id', 'date', 'securities_trader_id', 'price', 'buy', 'sell'}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"輸入檔案缺少必要欄位: {missing}")

    # 篩選特定日期 (若有指定)
    if target_date:
        df = df[df['date'] == target_date]
        if df.empty:
            raise ValueError(f"指定的日期 {target_date} 在資料中無任何紀錄！")

    # 確保型態
    df['price'] = df['price'].astype(float)
    df['buy'] = df['buy'].astype(float)
    df['sell'] = df['sell'].astype(float)
    df['stock_id'] = df['stock_id'].astype(str)
    df['date'] = df['date'].astype(str)
    df['securities_trader_id'] = df['securities_trader_id'].astype(str)

    # 計算各成交價之成交金額 (元)
    df['buy_amt_raw'] = df['price'] * df['buy']
    df['sell_amt_raw'] = df['price'] * df['sell']

    print("[*] 進行分點彙總 (GroupBy: 股票, 日期, 券商代號)...")
    agg = df.groupby(
        ['stock_id', 'date', 'securities_trader_id'],
        as_index=False,
        observed=True
    ).agg(
        buy_vol=('buy', 'sum'),
        sell_vol=('sell', 'sum'),
        buy_amt_raw=('buy_amt_raw', 'sum'),
        sell_amt_raw=('sell_amt_raw', 'sum')
    ).rename(columns={
        'stock_id': 'symbol',
        'date': 'trade_date',
        'securities_trader_id': 'broker_id'
    })

    # 計算衍生指標
    agg['net_vol'] = agg['buy_vol'] - agg['sell_vol']
    agg['buy_amt'] = agg['buy_amt_raw'] / 1000.0   # 單位：千元
    agg['sell_amt'] = agg['sell_amt_raw'] / 1000.0 # 單位：千元
    agg['net_amt'] = agg['buy_amt'] - agg['sell_amt']

    # 計算買賣加權均價 (若成交股數為 0 則為 NaN)
    agg['buy_avg_price'] = np.where(
        agg['buy_vol'] > 0,
        agg['buy_amt_raw'] / agg['buy_vol'],
        np.nan
    )
    agg['sell_avg_price'] = np.where(
        agg['sell_vol'] > 0,
        agg['sell_amt_raw'] / agg['sell_vol'],
        np.nan
    )

    # 該分點在該股的總成交金額 (千元)
    agg['turnover'] = agg['buy_amt'] + agg['sell_amt']

    # 計算市佔率 (%)：該分點成交金額 / 該檔股票全市場分點成交總金額 * 100
    stock_total_turnover = agg.groupby('symbol')['turnover'].transform('sum')
    agg['market_share'] = np.where(
        stock_total_turnover > 0,
        (agg['turnover'] / stock_total_turnover) * 100.0,
        0.0
    )

    # 欄位順序對齊標準 api_absr1 規格 (13 欄)
    target_columns = [
        'symbol',
        'trade_date',
        'broker_id',
        'buy_vol',
        'sell_vol',
        'net_vol',
        'buy_amt',
        'sell_amt',
        'net_amt',
        'buy_avg_price',
        'sell_avg_price',
        'turnover',
        'market_share'
    ]
    result = agg[target_columns].copy()

    # 依 symbol 與 broker_id 排序
    result = result.sort_values(by=['symbol', 'broker_id']).reset_index(drop=True)

    # 決定輸出路徑
    if not output_path:
        date_str = result['trade_date'].iloc[0] if not result.empty else 'unknown'
        output_dir = os.path.join(os.path.dirname(input_path), 'output')
        output_path = os.path.join(output_dir, f'api_absr1_{date_str}_{date_str}.parquet')

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 透過 PyArrow Table 與固定 Schema 輸出，確保與官方產製的 Parquet Schema 完全一致 (pa.string / pa.float64)
    schema = get_absr1_schema()
    table = pa.Table.from_pandas(result, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='SNAPPY')

    elapsed = time.time() - start_time
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    num_stocks = result['symbol'].nunique()
    num_brokers = result['broker_id'].nunique()
    print("[+] 轉換成功！")
    print(f"    - 輸出檔案: {output_path}")
    print(f"    - 彙總後總列數: {len(result):,} 筆")
    print(f"    - 涵蓋股票數: {num_stocks:,} 檔")
    print(f"    - 涵蓋分點數: {num_brokers:,} 間")
    print(f"    - 檔案大小: {file_size_mb:.2f} MB")
    print(f"    - 耗時: {elapsed:.2f} 秒")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="將 FinMind 逐價分點明細 Parquet 轉換為標準 api_absr1 彙總表 Parquet"
    )
    parser.add_argument(
        "-i", "--input",
        default=r"D:\MyProject\stock_data_downloader\finmind_2026-09-17.parquet",
        help="來源 FinMind Parquet 檔案路徑"
    )
    parser.add_argument(
        "-o", "--output",
        default=r"D:\MyProject\stock_data_downloader\output\api_absr1_2026-09-17_2026-09-17.parquet",
        help="目標 ABSR1 Parquet 檔案路徑"
    )
    parser.add_argument(
        "-d", "--date",
        default=None,
        help="可選：限定轉換的交易日期 (YYYY-MM-DD)"
    )

    args = parser.parse_args()

    input_file = args.input
    if not os.path.exists(input_file):
        alt_path = os.path.join(r"D:\MyProject\stock_data_downloader\output", os.path.basename(input_file))
        if os.path.exists(alt_path):
            input_file = alt_path

    convert_finmind_to_absr1(input_file, args.output, args.date)


if __name__ == '__main__':
    main()
