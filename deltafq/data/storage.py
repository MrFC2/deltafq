"""
Data storage management for DeltaFQ.
"""

import pandas as pd
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from ..core.base import BaseComponent
from ..core.config import Config


class DataStorage(BaseComponent):
    """
    Data storage manager with categorized storage.
    
    Directory structure:
        data_cache/
        ├── price/          # 行情数据
        │   └── {ticker}/
        ├── backtest/       # 回测结果
        │   └── {ticker}/
        └── indicators/     # 技术指标
    """
    
    def __init__(self, base_path: str = None, **kwargs):
        """初始化数据存储。"""
        super().__init__(**kwargs)
        
        # 未传 base_path 时从 Config 获取缓存目录
        if base_path is None:
            config = Config()
            base_path = config.get_cache_dir()
        
        self.base_path = Path(base_path)
        self.logger.info(f"正在初始化数据存储，路径：{self.base_path}")
        self._init_directories()
    
    def _init_directories(self):
        """初始化目录结构。"""
        self.price_dir = self.base_path / "price"
        self.backtest_dir = self.base_path / "backtest"
        self.indicators_dir = self.base_path / "indicators"
        
        # 创建目录
        for dir_path in [self.price_dir, self.backtest_dir, 
                        self.indicators_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    
    # ============================================================================
    # 行情数据存储
    # ============================================================================
    
    def save_price_data(self, data: pd.DataFrame, ticker: str, 
                       start_date: Optional[str] = None, 
                       end_date: Optional[str] = None) -> Path:
        """保存行情数据。"""
        symbol_dir = self.price_dir / ticker.replace('.', '_')
        symbol_dir.mkdir(exist_ok=True)
        
        # 生成文件名
        if start_date and end_date:
            filename = f"{ticker}_{start_date}_{end_date}.csv"
        else:
            filename = f"{ticker}_{datetime.now().strftime('%Y%m%d')}.csv"
        
        filepath = symbol_dir / filename
        data.to_csv(filepath, encoding='utf-8-sig', index=True)
        self.logger.info(f"已保存价格数据至：{filepath}")
        return filepath
    
    def load_price_data(self, ticker: str, start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """加载行情数据。"""
        symbol_dir = self.price_dir / ticker.replace('.', '_')
        
        if start_date and end_date:
            filename = f"{ticker}_{start_date}_{end_date}.csv"
        else:
            # 查找最新文件
            files = list(symbol_dir.glob(f"{ticker}_*.csv"))
            if not files:
                self.logger.warning(f"未找到 {ticker} 的价格数据")
                return None
            filename = sorted(files)[-1].name
        
        filepath = symbol_dir / filename
        if filepath.exists():
            data = pd.read_csv(filepath, index_col=0, parse_dates=True)
            self.logger.info(f"已从以下路径加载价格数据：{filepath}")
            return data
        return None
    
    # ============================================================================
    # 回测结果存储
    # ============================================================================
    
    def save_backtest_results(self, trades_df: pd.DataFrame, 
                             values_df: pd.DataFrame, ticker: str,
                             strategy_name: Optional[str] = None) -> Dict[str, Path]:
        """保存回测结果。"""
        symbol_dir = self.backtest_dir / ticker.replace('.', '_')
        symbol_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        strategy_suffix = f"_{strategy_name}" if strategy_name else ""
        
        trades_path = symbol_dir / f"{ticker}_trades{strategy_suffix}_{timestamp}.csv"
        values_path = symbol_dir / f"{ticker}_values{strategy_suffix}_{timestamp}.csv"
        
        trades_df.to_csv(trades_path, encoding='utf-8-sig', index=False)
        values_df.to_csv(values_path, encoding='utf-8-sig', index=False)
        
        self.logger.info(f"已保存回测结果至：{symbol_dir}")
        return {'trades': trades_path, 'values': values_path}
    
    def load_backtest_results(self, ticker: str, strategy_name: Optional[str] = None,
                             latest: bool = True) -> Optional[Dict[str, pd.DataFrame]]:
        """加载回测结果。"""
        symbol_dir = self.backtest_dir / ticker.replace('.', '_')
        
        if not symbol_dir.exists():
            self.logger.warning(f"未找到 {ticker} 的回测结果")
            return None

        # 查找成交和净值文件
        if strategy_name:
            trades_files = list(symbol_dir.glob(f"{ticker}_trades_{strategy_name}_*.csv"))
            values_files = list(symbol_dir.glob(f"{ticker}_values_{strategy_name}_*.csv"))
        else:
            trades_files = list(symbol_dir.glob(f"{ticker}_trades*.csv"))
            values_files = list(symbol_dir.glob(f"{ticker}_values*.csv"))

        if not trades_files or not values_files:
            self.logger.warning(f"未找到 {ticker} 的回测结果")
            return None
        
        if latest:
            trades_file = sorted(trades_files)[-1]
            values_file = sorted(values_files)[-1]
            return {
                'trades': pd.read_csv(trades_file, encoding='utf-8-sig'),
                'values': pd.read_csv(values_file, encoding='utf-8-sig')
            }
        else:
            # 返回所有文件
            return {
                'trades': [pd.read_csv(f, encoding='utf-8-sig') for f in trades_files],
                'values': [pd.read_csv(f, encoding='utf-8-sig') for f in values_files]
            }
    
    # ============================================================================
    # 通用存储方法
    # ============================================================================
    
    def save_data(self, data: pd.DataFrame, filename: str, 
                 category: str = "indicators", subdir: Optional[str] = None) -> Path:
        """按分类保存数据。"""
        if category == "price":
            target_dir = self.price_dir
        elif category == "backtest":
            target_dir = self.backtest_dir
        elif category == "indicators":
            target_dir = self.indicators_dir
        else:
            raise ValueError(f"无效的分类：{category}，必须为 'price'、'backtest' 或 'indicators'")

        if subdir:
            target_dir = target_dir / subdir
            target_dir.mkdir(parents=True, exist_ok=True)

        filepath = target_dir / filename
        data.to_csv(filepath, encoding='utf-8-sig', index=False)
        self.logger.info(f"已保存数据至：{filepath}")
        return filepath
    
    # def load_data(self, filename: str, category: str = "indicators",
    #              subdir: Optional[str] = None) -> Optional[pd.DataFrame]:
    #     """从存储加载数据。"""
    #     if category == "price":
    #         target_dir = self.price_dir
    #     elif category == "backtest":
    #         target_dir = self.backtest_dir
    #     elif category == "indicators":
    #         target_dir = self.indicators_dir
    #     else:
    #         raise ValueError(f"无效的分类：{category}，必须为 'price'、'backtest' 或 'indicators'")
    #         data = pd.read_csv(filepath, encoding='utf-8-sig')
    #         self.logger.info(f"已加载数据: {filepath}")
    #         return data
    #     else:
    #         self.logger.warning(f"文件不存在: {filepath}")
    #         return None
    
    # ============================================================================
    # 工具方法
    # ============================================================================
    
    def list_files(self, category: Optional[str] = None, 
                  subdir: Optional[str] = None) -> list:
        """列出存储中的所有文件。"""
        if category == "price":
            target_dir = self.price_dir
        elif category == "backtest":
            target_dir = self.backtest_dir
        elif category == "indicators":
            target_dir = self.indicators_dir
        else:
            target_dir = self.base_path
        
        if subdir:
            target_dir = target_dir / subdir
        
        if not target_dir.exists():
            return []
        
        files = []
        for item in target_dir.rglob('*.csv'):
            if item.is_file():
                files.append(str(item.relative_to(self.base_path)))
        return files
    
    def get_storage_info(self) -> Dict[str, Any]:
        """获取存储信息。"""
        return {
            'base_path': str(self.base_path),
            'price_files': len(list(self.price_dir.rglob('*.csv'))),
            'backtest_files': len(list(self.backtest_dir.rglob('*.csv'))),
            'indicators_files': len(list(self.indicators_dir.rglob('*.csv'))),
            'total_size_mb': self._calculate_size()
        }
    
    def _calculate_size(self) -> float:
        """计算存储总大小（MB）。"""
        total_size = 0
        for file_path in self.base_path.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        return round(total_size / (1024 * 1024), 2)
