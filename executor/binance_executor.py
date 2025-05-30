import aiohttp
from typing import Dict, Optional
from datetime import datetime
from utils.logger import trading_logger
from binance.client import Client
from binance.exceptions import BinanceAPIException
from utils.config_manager import ConfigManager

class BinanceExecutor:
    """币安交易执行器"""
    
    def __init__(self, config: ConfigManager):
        """
        初始化交易执行器
        
        Args:
            config: 配置管理器实例
        """
        self.config = config
        
        # 从配置中获取API密钥
        api_key = config.get('api.binance.api_key')
        api_secret = config.get('api.binance.api_secret')
        
        if not api_key or not api_secret:
            # trading_logger.error("Binance API密钥未配置") # Logger might not be set up yet
            raise ValueError("Binance API密钥未配置 (api_key or api_secret missing)")
            
        self.testnet = config.get('api.binance.testnet', True) # Determine if testnet before client init

        # 初始化币安客户端
        self.client = Client(api_key, api_secret)
        # For python-binance, if using testnet, you often need to set the base URL for the client
        # or use a specific testnet function if the library version supports it directly.
        # A common way is to adjust client.API_URL and client.FUTURES_URL (if applicable)

        trading_logger.info(f"BinanceExecutor initializing with testnet: {self.testnet}")
        
        # API配置 和 WebSocket URLS
        if self.testnet:
            # For Futures Testnet with python-binance client
            # The client.FUTURES_URL is what it uses for futures calls.
            # Client.API_URL is for spot. We are doing futures.
            self.client.FUTURES_URL = 'https://testnet.binancefuture.com/fapi'
            # self.client.FUTURES_DATA_URL for klines etc. if needed by client methods
            self.client.FUTURES_DATA_URL = 'https://testnet.binancefuture.com/futures/data' 

            # Base URL for your direct aiohttp calls to Futures Testnet REST API
            self.base_url = "https://testnet.binancefuture.com/fapi" 
            # WebSocket URL for Futures Testnet
            # Note: WebsocketScanner uses its own _ws_url, ensure it's also testnet if scanner is testnet
            self.ws_url = "wss://stream.binancefuture.com/ws" # For individual streams on futures testnet
            # For combined streams: "wss://stream.binancefuture.com/stream"
            trading_logger.info(f"BinanceExecutor configured for Futures Testnet. REST: {self.base_url}, WS: {self.ws_url}")
        else:
            # For Futures Live (Production)
            self.client.FUTURES_URL = 'https://fapi.binance.com/fapi'
            self.client.FUTURES_DATA_URL = 'https://fapi.binance.com/futures/data'

            self.base_url = "https://fapi.binance.com"
            self.ws_url = "wss://fstream.binance.com/ws"
            trading_logger.info(f"BinanceExecutor configured for Futures Live. REST: {self.base_url}, WS: {self.ws_url}")

        trading_logger.info("币安客户端初始化成功")
        
        # 会话管理
        self.session = None
        
        # 订单管理
        self.active_orders = {}  # {symbol: order_info}
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session:
            await self.session.close()
            
    async def execute_signal(self, signal: Dict) -> Optional[Dict]:
        """
        执行交易信号
        
        Args:
            signal: 交易信号字典
            
        Returns:
            Optional[Dict]: 订单信息，如果执行失败则返回None
        """
        try:
            symbol = signal['symbol']
            order_type = signal['type']
            
            # 检查是否已有该交易对的订单
            if symbol in self.active_orders:
                trading_logger.warning(f"{symbol} 已有活跃订单，跳过")
                return None
                
            # 获取当前价格
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/fapi/v1/ticker/price?symbol={symbol}") as response:
                    if response.status != 200:
                        trading_logger.error(f"获取{symbol}价格失败: {response.status}")
                        return None
                    price_data = await response.json()
                    current_price = float(price_data['price'])
            
            # 计算合约数量
            position_size = signal['position_size']
            quantity = position_size / current_price
            
            # 获取交易对精度信息
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/fapi/v1/exchangeInfo") as response:
                    if response.status != 200:
                        trading_logger.error(f"获取交易对信息失败: {response.status}")
                        return None
                    exchange_info = await response.json()
                    
                    # 找到对应交易对的精度信息
                    symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
                    if not symbol_info:
                        trading_logger.error(f"未找到{symbol}的交易对信息")
                        return None
                        
                    # 获取数量精度
                    quantity_precision = symbol_info['quantityPrecision']
                    quantity = round(quantity, quantity_precision)
            
            # 构建订单参数
            order_params = {
                'symbol': symbol,
                'side': 'BUY' if order_type == 'LONG' else 'SELL',
                'type': 'MARKET',
                'quantity': quantity
            }
            
            # 发送订单
            order = await self._send_order(order_params)
            
            if order:
                # 记录订单信息
                self.active_orders[symbol] = {
                    'order_id': order['orderId'],
                    'symbol': symbol,
                    'type': order_type,
                    'entry_price': float(order['price']),
                    'quantity': float(order['executedQty']),
                    'stop_loss': signal['stop_loss'],
                    'take_profit': signal['take_profit'],
                    'timestamp': datetime.now()
                }
                
                trading_logger.info(
                    f"订单执行成功: {symbol} {order_type} "
                    f"价格: {order['price']} "
                    f"数量: {order['executedQty']}"
                )
                
                return self.active_orders[symbol]
                
            return None
            
        except Exception as e:
            trading_logger.error(f"执行交易信号时发生错误: {str(e)}")
            return None
            
    async def close_position(self, signal: Dict) -> Optional[Dict]:
        """
        平仓
        
        Args:
            signal: 平仓信号字典
            
        Returns:
            Optional[Dict]: 平仓订单信息，如果执行失败则返回None
        """
        try:
            symbol = signal['symbol']
            order_type = signal['type']
            
            # 检查是否有该交易对的订单
            if symbol not in self.active_orders:
                trading_logger.warning(f"{symbol} 没有活跃订单，跳过")
                return None
                
            # 获取订单信息
            order_info = self.active_orders[symbol]
            
            # 构建平仓订单参数
            order_params = {
                'symbol': symbol,
                'side': 'SELL' if order_info['type'] == 'LONG' else 'BUY',
                'type': 'MARKET',
                'quantity': order_info['quantity']
            }
            
            # 发送平仓订单
            order = await self._send_order(order_params)
            
            if order:
                # 计算盈亏
                pnl = self._calculate_pnl(order_info, float(order['price']))
                
                # 记录平仓信息
                close_info = {
                    'symbol': symbol,
                    'type': order_info['type'],
                    'entry_price': order_info['entry_price'],
                    'exit_price': float(order['price']),
                    'quantity': float(order['executedQty']),
                    'pnl': pnl,
                    'reason': signal['reason'],
                    'timestamp': datetime.now()
                }
                
                # 移除活跃订单
                del self.active_orders[symbol]
                
                trading_logger.info(
                    f"平仓成功: {symbol} {order_info['type']} "
                    f"入场价: {order_info['entry_price']} "
                    f"出场价: {order['price']} "
                    f"盈亏: {pnl:.2f}U "
                    f"原因: {signal['reason']}"
                )
                
                return close_info
                
            return None
            
        except Exception as e:
            trading_logger.error(f"平仓时发生错误: {str(e)}")
            return None
            
    async def _send_order(self, params: Dict) -> Optional[Dict]:
        """
        发送订单
        
        Args:
            params: 订单参数
            
        Returns:
            Optional[Dict]: 订单信息，如果发送失败则返回None
        """
        try:
            # 添加时间戳
            params['timestamp'] = int(datetime.now().timestamp() * 1000)
            
            # 发送订单
            async with self.session.post(
                f"{self.base_url}/v1/order",
                params=params,
                headers={'X-MBX-APIKEY': self.client.API_KEY}
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    trading_logger.error(f"发送订单失败: {response.status}")
                    return None
                    
        except Exception as e:
            trading_logger.error(f"发送订单时发生错误: {str(e)}")
            return None
            
    def _calculate_quantity(self, symbol: str, position_size: float) -> float:
        """
        计算下单数量
        
        Args:
            symbol: 交易对
            position_size: 仓位大小(USDT)
            
        Returns:
            float: 下单数量
        """
        # TODO: 根据交易对精度计算数量
        return position_size
        
    def _calculate_pnl(self, order_info: Dict, exit_price: float) -> float:
        """
        计算盈亏
        
        Args:
            order_info: 订单信息
            exit_price: 出场价格
            
        Returns:
            float: 盈亏金额(USDT)
        """
        if order_info['type'] == 'LONG':
            return (exit_price - order_info['entry_price']) * order_info['quantity']
        else:
            return (order_info['entry_price'] - exit_price) * order_info['quantity']

    def place_order(self, symbol: str, side: str, quantity: float, price: Optional[float] = None) -> Optional[Dict]:
        """
        下单
        
        Args:
            symbol: 交易对
            side: 方向 ('buy' 或 'sell')
            quantity: 数量
            price: 价格（可选，市价单不需要）
            
        Returns:
            订单信息字典，失败时返回None
        """
        try:
            # 转换为币安API所需的格式
            side = side.upper()
            
            # 构建订单参数
            params = {
                'symbol': symbol.replace('/', ''),
                'side': side,
                'quantity': quantity,
                'type': 'LIMIT' if price else 'MARKET'
            }
            
            if price:
                params['price'] = price
                params['timeInForce'] = 'GTC'
                
            # 发送订单
            order = self.client.create_order(**params)
            trading_logger.info(f"下单成功: {order}")
            return order
            
        except BinanceAPIException as e:
            trading_logger.error(f"下单失败: {str(e)}", exc_info=True)
            return None
        except Exception as e:
            trading_logger.error(f"下单异常: {str(e)}", exc_info=True)
            return None
            
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        取消订单
        
        Args:
            symbol: 交易对
            order_id: 订单ID
            
        Returns:
            是否成功取消
        """
        try:
            result = self.client.cancel_order(
                symbol=symbol.replace('/', ''),
                orderId=order_id
            )
            trading_logger.info(f"取消订单成功: {result}")
            return True
            
        except BinanceAPIException as e:
            trading_logger.error(f"取消订单失败: {str(e)}", exc_info=True)
            return False
        except Exception as e:
            trading_logger.error(f"取消订单异常: {str(e)}", exc_info=True)
            return False
            
    def get_order(self, symbol: str, order_id: str) -> Optional[Dict]:
        """
        获取订单信息
        
        Args:
            symbol: 交易对
            order_id: 订单ID
            
        Returns:
            订单信息字典，失败时返回None
        """
        try:
            order = self.client.get_order(
                symbol=symbol.replace('/', ''),
                orderId=order_id
            )
            return order
            
        except BinanceAPIException as e:
            trading_logger.error(f"获取订单信息失败: {str(e)}", exc_info=True)
            return None
        except Exception as e:
            trading_logger.error(f"获取订单信息异常: {str(e)}", exc_info=True)
            return None
            
    def get_account(self) -> Optional[Dict]:
        """
        获取账户信息
        
        Returns:
            账户信息字典，失败时返回None
        """
        try:
            account = self.client.get_account()
            return account
            
        except BinanceAPIException as e:
            trading_logger.error(f"获取账户信息失败: {str(e)}", exc_info=True)
            return None
        except Exception as e:
            trading_logger.error(f"获取账户信息异常: {str(e)}", exc_info=True)
            return None 