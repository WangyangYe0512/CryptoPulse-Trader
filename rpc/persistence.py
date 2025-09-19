# 兼容 freqtrade 持久化模块
from datetime import datetime
from typing import Optional, Any, Dict
from dataclasses import dataclass


@dataclass
class Trade:
    """交易对象"""
    id: int
    exchange: str
    pair: str
    is_open: bool
    fee_open: float
    fee_close: Optional[float]
    open_rate: float
    close_rate: Optional[float]
    amount: float
    stake_amount: float
    strategy: str
    enter_tag: Optional[str]
    timeframe: int
    open_date: datetime
    close_date: Optional[datetime]
    profit_ratio: Optional[float]
    profit_abs: Optional[float]
    exit_reason: Optional[str]
    initial_stop_loss: Optional[float]
    stop_loss: Optional[float]
    max_rate: Optional[float]
    leverage: Optional[float]
    trading_mode: str = 'spot'
    
    def __post_init__(self):
        if self.fee_close is None:
            self.fee_close = 0.0
        if self.close_rate is None:
            self.close_rate = 0.0
        if self.profit_ratio is None:
            self.profit_ratio = 0.0
        if self.profit_abs is None:
            self.profit_abs = 0.0
    
    def calc_profit_ratio(self) -> float:
        """计算利润率"""
        if self.close_rate and self.open_rate:
            return (self.close_rate - self.open_rate) / self.open_rate
        return 0.0
    
    def calc_profit(self) -> float:
        """计算绝对利润"""
        if self.close_rate and self.amount:
            return (self.close_rate - self.open_rate) * self.amount
        return 0.0
    
    @property
    def base_currency(self) -> str:
        """基础货币"""
        return self.pair.split('/')[0] if '/' in self.pair else self.pair[:3]
    
    @property
    def quote_currency(self) -> str:
        """报价货币"""
        return self.pair.split('/')[1] if '/' in self.pair else self.pair[3:]
    
    @classmethod
    def rollback(cls):
        """回滚数据库会话（兼容性方法）"""
        pass
    
    class session:
        """数据库会话（兼容性属性）"""
        @staticmethod
        def remove():
            pass
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'trade_id': self.id,
            'pair': self.pair,
            'base_currency': self.base_currency,
            'quote_currency': self.quote_currency,
            'is_open': self.is_open,
            'amount': self.amount,
            'stake_amount': self.stake_amount,
            'open_rate': self.open_rate,
            'close_rate': self.close_rate,
            'profit_ratio': self.profit_ratio,
            'profit_abs': self.profit_abs,
            'open_date': self.open_date,
            'close_date': self.close_date,
            'exit_reason': self.exit_reason,
            'leverage': self.leverage or 1.0,
        }