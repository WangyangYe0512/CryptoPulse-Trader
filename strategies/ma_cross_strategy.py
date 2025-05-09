from typing import Dict
import pandas as pd
import numpy as np
from .base_strategy import BaseStrategy

class MACrossStrategy(BaseStrategy):
    """移动平均线交叉策略"""
    
    def __init__(self, short_window: int = 20, long_window: int = 50):
        """
        初始化策略
        
        Args:
            short_window: 短期移动平均线窗口
            long_window: 长期移动平均线窗口
        """
        super().__init__(name="MA Cross Strategy")
        self.short_window = short_window
        self.long_window = long_window
        
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含 OHLCV 数据的 DataFrame
            
        Returns:
            包含交易信号的 DataFrame
        """
        # 计算移动平均线
        data['short_ma'] = data['Close'].rolling(window=self.short_window).mean()
        data['long_ma'] = data['Close'].rolling(window=self.long_window).mean()
        
        # 生成信号
        data['signal'] = 0
        data.loc[data['short_ma'] > data['long_ma'], 'signal'] = 1  # 买入信号
        data.loc[data['short_ma'] < data['long_ma'], 'signal'] = -1  # 卖出信号
        
        # 计算持仓
        data['position'] = data['signal'].shift(1)
        
        return data
    
    def calculate_position_size(self, capital: float, risk_per_trade: float) -> float:
        """
        计算仓位大小
        
        Args:
            capital: 总资金
            risk_per_trade: 每笔交易风险比例
            
        Returns:
            建议仓位大小
        """
        return super().calculate_position_size(capital, risk_per_trade)
    
    def get_strategy_parameters(self) -> Dict:
        """
        获取策略参数
        
        Returns:
            策略参数字典
        """
        return {
            'short_window': self.short_window,
            'long_window': self.long_window
        } 