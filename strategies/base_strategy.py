from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.positions: Dict[str, float] = {}
        self.trades: List[Dict] = []
        
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        Args:
            data: 包含 OHLCV 数据的 DataFrame
            
        Returns:
            包含交易信号的 DataFrame
        """
        pass
    
    def calculate_position_size(self, capital: float, risk_per_trade: float) -> float:
        """
        计算仓位大小
        
        Args:
            capital: 总资金
            risk_per_trade: 每笔交易风险比例
            
        Returns:
            建议仓位大小
        """
        return capital * risk_per_trade
    
    def update_position(self, symbol: str, size: float):
        """
        更新持仓
        
        Args:
            symbol: 交易对符号
            size: 持仓大小
        """
        self.positions[symbol] = size
        
    def record_trade(self, trade: Dict):
        """
        记录交易
        
        Args:
            trade: 交易信息字典
        """
        self.trades.append(trade)
        
    def get_performance_metrics(self) -> Dict:
        """
        计算策略表现指标
        
        Returns:
            包含各项指标的字典
        """
        if not self.trades:
            return {}
            
        returns = pd.Series([t['return'] for t in self.trades])
        
        return {
            'total_trades': len(self.trades),
            'win_rate': len(returns[returns > 0]) / len(returns),
            'avg_return': returns.mean(),
            'sharpe_ratio': returns.mean() / returns.std() if len(returns) > 1 else 0,
            'max_drawdown': self._calculate_max_drawdown(returns)
        }
    
    def _calculate_max_drawdown(self, returns: pd.Series) -> float:
        """
        计算最大回撤
        
        Args:
            returns: 收益率序列
            
        Returns:
            最大回撤
        """
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        return drawdown.min() 