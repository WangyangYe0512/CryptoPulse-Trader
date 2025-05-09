from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from datetime import datetime
from strategies.base_strategy import BaseStrategy

class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 100000.0,
        commission: float = 0.001
    ):
        """
        初始化回测引擎
        
        Args:
            strategy: 交易策略
            initial_capital: 初始资金
            commission: 手续费率
        """
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.commission = commission
        self.positions: Dict[str, float] = {}
        self.cash = initial_capital
        self.trades: List[Dict] = []
        
    def run(self, data: pd.DataFrame) -> Dict:
        """
        运行回测
        
        Args:
            data: 历史数据
            
        Returns:
            回测结果
        """
        # 生成交易信号
        signals = self.strategy.generate_signals(data)
        
        # 初始化结果
        portfolio_value = []
        current_position = 0
        
        for i in range(len(signals)):
            if i == 0:
                continue
                
            current_price = signals['Close'].iloc[i]
            signal = signals['signal'].iloc[i]
            
            # 计算交易
            if signal != 0 and signal != current_position:
                # 计算交易数量
                trade_size = self._calculate_trade_size(
                    current_price,
                    signal,
                    current_position
                )
                
                # 执行交易
                if trade_size != 0:
                    self._execute_trade(
                        current_price,
                        trade_size,
                        signals.index[i]
                    )
                    
                current_position = signal
                
            # 更新投资组合价值
            portfolio_value.append(self._calculate_portfolio_value(current_price))
            
        # 计算回测结果
        return self._calculate_results(portfolio_value)
    
    def _calculate_trade_size(
        self,
        price: float,
        signal: int,
        current_position: int
    ) -> float:
        """
        计算交易数量
        
        Args:
            price: 当前价格
            signal: 交易信号
            current_position: 当前持仓
            
        Returns:
            交易数量
        """
        if signal == 0:
            return -current_position
            
        if current_position == 0:
            return signal * (self.cash * 0.95) / price
            
        return signal - current_position
    
    def _execute_trade(
        self,
        price: float,
        size: float,
        timestamp: datetime
    ):
        """
        执行交易
        
        Args:
            price: 交易价格
            size: 交易数量
            timestamp: 交易时间
        """
        commission = abs(size * price * self.commission)
        cost = size * price + commission
        
        if cost > self.cash:
            return
            
        self.cash -= cost
        self.positions['size'] = size
        
        self.trades.append({
            'timestamp': timestamp,
            'price': price,
            'size': size,
            'commission': commission,
            'cost': cost
        })
    
    def _calculate_portfolio_value(self, current_price: float) -> float:
        """
        计算投资组合价值
        
        Args:
            current_price: 当前价格
            
        Returns:
            投资组合总价值
        """
        position_value = self.positions.get('size', 0) * current_price
        return self.cash + position_value
    
    def _calculate_results(self, portfolio_value: List[float]) -> Dict:
        """
        计算回测结果
        
        Args:
            portfolio_value: 投资组合价值序列
            
        Returns:
            回测结果
        """
        portfolio_value = pd.Series(portfolio_value)
        returns = portfolio_value.pct_change()
        
        return {
            'initial_capital': self.initial_capital,
            'final_capital': portfolio_value.iloc[-1],
            'total_return': (portfolio_value.iloc[-1] - self.initial_capital) / self.initial_capital,
            'sharpe_ratio': returns.mean() / returns.std() if len(returns) > 1 else 0,
            'max_drawdown': self._calculate_max_drawdown(portfolio_value),
            'total_trades': len(self.trades),
            'win_rate': self._calculate_win_rate()
        }
    
    def _calculate_max_drawdown(self, portfolio_value: pd.Series) -> float:
        """
        计算最大回撤
        
        Args:
            portfolio_value: 投资组合价值序列
            
        Returns:
            最大回撤
        """
        running_max = portfolio_value.cummax()
        drawdown = (portfolio_value - running_max) / running_max
        return drawdown.min()
    
    def _calculate_win_rate(self) -> float:
        """
        计算胜率
        
        Returns:
            胜率
        """
        if not self.trades:
            return 0.0
            
        profitable_trades = sum(1 for trade in self.trades if trade['size'] > 0)
        return profitable_trades / len(self.trades) 