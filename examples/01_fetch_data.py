"""
数据拉取示例：使用 baostock 拉取沪深300日线数据。
"""

from source.data import BaostockDataFetcher


def main() -> None:
    # 沪深300指数，baostock 格式：sh.000300
    fetcher = BaostockDataFetcher()
    data = fetcher.fetch_data(ticker="sh.000300", start_date="2024-01-01", end_date="2024-06-30")
    print(data.head())
    print(f"\n共 {len(data)} 条记录")


if __name__ == "__main__":
    main()
