"""
Configuration management for DeltaFQ.
"""

import os
from typing import Dict, Any
from pathlib import Path


class Config:
    """配置管理器。"""
    
    def __init__(self, config_file: str = None):
        """初始化配置。"""
        self.config = self._load_default_config()
        if config_file and os.path.exists(config_file):
            self._load_config_file(config_file)
    
    def _load_default_config(self) -> Dict[str, Any]:
        """加载默认配置。"""
        return {
            "data": {
                "cache_dir": "data_cache",
                "default_source": "yahoo"
            },
            "trading": {
                "initial_capital": 1000000,
                "commission": 0.001,
                "slippage": 0.0005
            },
            "logging": {
                "level": "INFO",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        }
    
    def _load_config_file(self, config_file: str):
        """从文件加载配置。"""
        # 预留：从文件加载配置
        pass
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值。"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """设置配置值。"""
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def get_cache_dir(self) -> Path:
        """获取缓存目录路径。"""
        project_root = self._get_project_root()
        cache_dir_name = self.get("data.cache_dir", "data_cache")
        return project_root / cache_dir_name
    
    def _get_project_root(self) -> Path:
        """通过 setup.py 或 pyproject.toml 定位项目根目录。"""
        current = Path(__file__).resolve()
        # 从 deltafq/core/config.py 向上查找项目根目录
        # deltafq/core/config.py -> deltafq/core -> deltafq -> project_root
        for parent in current.parents:
            if (parent / "setup.py").exists() or (parent / "pyproject.toml").exists():
                return parent
        # 未找到时回退：config.py 向上两级为项目根
        # 正常情况下不会走到这里
        return current.parent.parent.parent

