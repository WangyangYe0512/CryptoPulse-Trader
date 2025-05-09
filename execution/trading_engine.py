from typing import Dict, List, Optional
import ccxt
from datetime import datetime
from utils.logger import trading_logger

class TradingEngine:
    """交易执行引擎"""
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True
    ):
        """
        初始化交易引擎
        
        Args:
            api_key: API密钥
            api_secret: API密钥
            testnet: 是否使用测试网络
        """
        # 初始化交易所连接
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
                'testnet': testnet
            }
        })
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
            trading_logger.info("已启用Binance测试网络模式")
        
        self.positions: Dict[str, Dict] = {}  # 修改为更准确的类型提示
        self.trades: List[Dict] = []  # 修改为更准确的类型提示
        
    def get_balance(self, currency: str = 'USDT') -> float:
        """
        获取账户余额
        
        Args:
            currency: 货币类型
            
        Returns:
            可用余额
        """
        try:
            balance = self.exchange.fetch_balance()
            return float(balance[currency]['free'])
            
        except Exception as e:
            trading_logger.error(f"获取余额失败: {str(e)}")
            return 0.0  # 返回0而不是抛出异常，便于调用方处理
    
    def get_ticker(self, symbol: str) -> Dict:
        """
        获取当前行情
        
        Args:
            symbol: 交易对符号
            
        Returns:
            行情信息
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            trading_logger.error(f"获取行情失败: {str(e)}")
            raise
    
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: Optional[float] = None
    ) -> Optional[Dict]:
        """
        下单
        
        Args:
            symbol: 交易对符号
            side: 交易方向 ('buy' or 'sell')
            order_type: 订单类型 ('limit' or 'market')
            amount: 交易数量
            price: 价格（限价单必需）
            
        Returns:
            订单信息
        """
        try:
            params = {}
            if order_type == 'limit' and price is None:
                raise ValueError("限价单必须指定价格")
                
            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params
            )
            
            trading_logger.info(
                f"下单成功: {symbol} {side} {amount} @ {price if price else 'market'}"
            )
            
            self._update_position(symbol, side, amount, price)
            self._record_trade(order)
            
            return order
            
        except Exception as e:
            trading_logger.error(f"下单失败: {str(e)}")
            return None
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        取消订单
        
        Args:
            order_id: 订单ID
            symbol: 交易对符号
            
        Returns:
            是否成功取消
        """
        try:
            self.exchange.cancel_order(order_id, symbol)
            trading_logger.info(f"取消订单成功: {order_id}")
            return True
            
        except Exception as e:
            trading_logger.error(f"取消订单失败: {str(e)}")
            return False
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        获取未完成订单
        
        Args:
            symbol: 交易对符号（可选）
            
        Returns:
            未完成订单列表
        """
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return orders
            
        except Exception as e:
            trading_logger.error(f"获取未完成订单失败: {str(e)}")
            return []
    
    def get_order_status(self, order_id: str, symbol: str) -> Optional[Dict]:
        """
        获取订单状态
        
        Args:
            order_id: 订单ID
            symbol: 交易对符号
            
        Returns:
            订单状态信息
        """
        try:
            order = self.exchange.fetch_order(order_id, symbol)
            return order
            
        except Exception as e:
            trading_logger.error(f"获取订单状态失败: {str(e)}")
            return None
    
    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        获取交易历史
        
        Args:
            symbol: 交易对符号（可选）
            since: 开始时间（可选）
            limit: 获取数量
            
        Returns:
            交易历史列表
        """
        try:
            since_timestamp = int(since.timestamp() * 1000) if since else None
            trades = self.exchange.fetch_my_trades(
                symbol,
                since=since_timestamp,
                limit=limit
            )
            return trades
            
        except Exception as e:
            trading_logger.error(f"获取交易历史失败: {str(e)}")
            return []
    
    def _update_position(self, symbol: str, side: str, amount: float, price: Optional[float] = None):
        """
        更新持仓
        
        Args:
            symbol: 交易对符号
            side: 交易方向
            amount: 交易数量
            price: 成交价格
        """
        # 初始化持仓结构
        if symbol not in self.positions:
            self.positions[symbol] = {
                'amount': 0,
                'average_price': 0,
                'cost': 0
            }
        
        position = self.positions[symbol]
        
        if side == 'buy':
            # 计算新的平均价格
            if position['amount'] > 0:
                total_cost = position['cost'] + (amount * price if price else 0)
                total_amount = position['amount'] + amount
                position['average_price'] = total_cost / total_amount if total_amount > 0 else 0
                position['cost'] = total_cost
            else:
                position['average_price'] = price if price else 0
                position['cost'] = amount * (price if price else 0)
            position['amount'] += amount
        else:  # sell
            position['amount'] -= amount
            # 如果卖出全部，重置平均价格
            if position['amount'] <= 0:
                position['amount'] = 0
                position['average_price'] = 0
                position['cost'] = 0
    
    def _record_trade(self, order: Dict):
        """
        记录交易
        
        Args:
            order: 订单信息
        """
        trade_info = {
            'timestamp': datetime.now(),
            'order_id': order.get('id'),
            'symbol': order.get('symbol'),
            'type': order.get('type'),
            'side': order.get('side'),
            'price': order.get('price'),
            'amount': order.get('amount'),
            'cost': order.get('cost', 0),
            'status': order.get('status')
        }
        
        self.trades.append(trade_info)
        trading_logger.info(f"记录交易: {trade_info}") 