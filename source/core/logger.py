"""
Logging system for DeltaFQ.
"""

import logging
import sys

class Logger:
    """日志工具。"""
    
    def __init__(self, name: str = "deltafq", level: str = "INFO"):
        """初始化日志器。"""
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '[%(asctime)s] %(levelname)-7s %(name)-20s >>> %(message)s',
                datefmt='%H:%M:%S'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def debug(self, message: str):
        """输出 debug 日志。"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """输出 info 日志。"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """输出 warning 日志。"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """输出 error 日志。"""
        self.logger.error(message)
    
    def critical(self, message: str):
        """输出 critical 日志。"""
        self.logger.critical(message)

