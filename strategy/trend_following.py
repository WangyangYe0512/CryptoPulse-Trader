from typing import Dict, List, Optional
from datetime import datetime
from utils.logger import trading_logger

class TrendFollowingStrategy:
    """趋势跟踪策略"""
    
    def __init__(self,
                 min_price_change: float = 0.3,     # 最小价格变化百分比
                 min_volume_increase: float = 1.2,  # 最小成交量增加倍数
                 stop_loss_pct: float = 0.01,       # 止损百分比 1%
                 take_profit_pct: float = 0.02,     # 止盈百分比 2%
                 position_size: float = 100.0):     # 固定仓位大小(USDT)
        """
        初始化趋势跟踪策略
        
        Args:
            min_price_change: 最小价格变化百分比
            min_volume_increase: 最小成交量增加倍数
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            position_size: 固定仓位大小(USDT)
        """
        self.min_price_change = min_price_change
        self.min_volume_increase = min_volume_increase
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.position_size = position_size
        
        # 存储交易信号
        self.signals = {}
        
        # 存储K线历史数据
        self.kline_history = {}  # {symbol: [kline1, kline2, ...]}
        self.max_history_size = 5  # 保存最近5根K线，更短期的趋势
        
    def analyze_market(self, market_data: Dict) -> Optional[Dict]:
        """
        分析市场数据并生成交易信号
        
        Args:
            market_data: 市场数据字典，包含价格、成交量等信息
            
        Returns:
            Optional[Dict]: 交易信号，如果没有信号则返回None
        """
        try:
            symbol = market_data['symbol']
            current_price = market_data['price']
            current_volume = market_data['volume']
            
            # 更新K线历史数据
            if symbol not in self.kline_history:
                self.kline_history[symbol] = []
            self.kline_history[symbol].append(market_data)
            
            # 保持历史数据大小
            if len(self.kline_history[symbol]) > self.max_history_size:
                self.kline_history[symbol] = self.kline_history[symbol][-self.max_history_size:]
            
            # 如果没有足够的历史数据，跳过
            if len(self.kline_history[symbol]) < 2:
                return None
            
            # 获取前一根K线
            prev_kline = self.kline_history[symbol][-2]
            
            # 计算K线周期内的价格变化（从开盘到当前）
            price_change = ((current_price - market_data['open']) / market_data['open']) * 100
            
            # 计算成交量变化
            volume_change = current_volume / prev_kline['volume'] if prev_kline['volume'] > 0 else 0
            
            # 检查是否已经有该交易对的信号
            if symbol in self.signals:
                signal = self.signals[symbol]
                
                # 检查止损止盈
                if signal['type'] == 'LONG':
                    if current_price <= signal['entry_price'] * (1 - self.stop_loss_pct):
                        return {
                            'symbol': symbol,
                            'type': 'CLOSE_LONG',
                            'price': current_price,
                            'reason': 'Stop Loss',
                            'timestamp': datetime.now()
                        }
                    elif current_price >= signal['entry_price'] * (1 + self.take_profit_pct):
                        return {
                            'symbol': symbol,
                            'type': 'CLOSE_LONG',
                            'price': current_price,
                            'reason': 'Take Profit',
                            'timestamp': datetime.now()
                        }
                elif signal['type'] == 'SHORT':
                    if current_price >= signal['entry_price'] * (1 + self.stop_loss_pct):
                        return {
                            'symbol': symbol,
                            'type': 'CLOSE_SHORT',
                            'price': current_price,
                            'reason': 'Stop Loss',
                            'timestamp': datetime.now()
                        }
                    elif current_price <= signal['entry_price'] * (1 - self.take_profit_pct):
                        return {
                            'symbol': symbol,
                            'type': 'CLOSE_SHORT',
                            'price': current_price,
                            'reason': 'Take Profit',
                            'timestamp': datetime.now()
                        }
                return None
            
            # 生成新的交易信号
            if price_change > self.min_price_change and volume_change > self.min_volume_increase:  # 上涨趋势
                # 检查是否突破前高
                if current_price > max(k['high'] for k in self.kline_history[symbol][:-1]):
                    signal = {
                        'symbol': symbol,
                        'type': 'LONG',
                        'entry_price': current_price,
                        'stop_loss': current_price * (1 - self.stop_loss_pct),
                        'take_profit': current_price * (1 + self.take_profit_pct),
                        'position_size': self.position_size,  # 固定仓位100U
                        'timestamp': datetime.now()
                    }
                    self.signals[symbol] = signal
                    return signal
                
            elif price_change < -self.min_price_change and volume_change > self.min_volume_increase:  # 下跌趋势
                # 检查是否突破前低
                if current_price < min(k['low'] for k in self.kline_history[symbol][:-1]):
                    signal = {
                        'symbol': symbol,
                        'type': 'SHORT',
                        'entry_price': current_price,
                        'stop_loss': current_price * (1 + self.stop_loss_pct),
                        'take_profit': current_price * (1 - self.take_profit_pct),
                        'position_size': self.position_size,  # 固定仓位100U
                        'timestamp': datetime.now()
                    }
                    self.signals[symbol] = signal
                    return signal
            
            return None
            
        except Exception as e:
            trading_logger.error(f"分析市场数据时发生错误: {str(e)}")
            return None
            
    def update_market_data(self, market_data: Dict):
        """
        更新市场数据
        
        Args:
            market_data: 市场数据字典
        """
        symbol = market_data['symbol']
        if symbol in self.signals:
            self.signals[symbol]['current_price'] = market_data['price']
            self.signals[symbol]['last_update'] = datetime.now()
            
    def get_active_signals(self) -> List[Dict]:
        """
        获取当前活跃的交易信号
        
        Returns:
            List[Dict]: 活跃的交易信号列表
        """
        return list(self.signals.values())
        
    def remove_signal(self, symbol: str):
        """
        移除交易信号
        
        Args:
            symbol: 交易对符号
        """
        if symbol in self.signals:
            del self.signals[symbol] 