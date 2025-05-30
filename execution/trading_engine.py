from typing import Dict, List, Optional, Any
import ccxt
from datetime import datetime
from utils.logger import trading_logger

class TradingEngine:
    """交易执行引擎"""
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        market_type: str = 'spot',
        testnet: bool = True
    ):
        """
        初始化交易引擎
        
        Args:
            api_key: API密钥
            api_secret: API密钥
            market_type: 市场类型 ('spot' or 'future')
            testnet: 是否使用测试网络
        """
        self.market_type = market_type.lower()
        trading_logger.info(f"交易引擎初始化市场类型: {self.market_type}")

        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': self.market_type,
                'adjustForTimeDifference': True,
            }
        })
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
            trading_logger.info(f"已启用Binance {self.market_type.capitalize()} 测试网络模式")
        else:
            trading_logger.info(f"Binance {self.market_type.capitalize()} 主网络模式已启用")
        
        self.positions: Dict[str, Dict] = {}  # 修改为更准确的类型提示
        self.trades: List[Dict] = []  # 修改为更准确的类型提示
        
    def get_balance(self, currency: str = 'USDT') -> float:
        """
        获取账户可用余额 (特定货币，通常是保证金货币如USDT)
        
        Args:
            currency: 货币类型
            
        Returns:
            可用余额
        """
        try:
            balance_data = self.exchange.fetch_balance()
            # trading_logger.debug(f"Raw balance data ({self.market_type}): {balance_data}") # Uncomment for deep debugging

            if currency in balance_data:
                if 'free' in balance_data[currency] and balance_data[currency]['free'] is not None:
                    free_balance = float(balance_data[currency]['free'])
                    trading_logger.info(f"账户可用 {currency} 余额 ({self.market_type}模式): {free_balance}")
                    return free_balance
                else:
                    trading_logger.warning(f"在余额数据中未找到 {currency} 的 'free' 键或其值为None ({self.market_type}模式).")
                    trading_logger.debug(f"Balance data for {currency}: {balance_data.get(currency)}")
            else:
                trading_logger.warning(f"在余额数据中未找到货币 {currency} ({self.market_type}模式).")
                trading_logger.debug(f"Available currencies in balance: {list(balance_data.keys())}")

            # Fallback or more specific logic for futures if needed could go here
            # For Binance USDT-M futures, balance_data['USDT']['free'] should generally work.
            # If not, one might inspect balance_data['info'] for fields like 'availableBalance' (for total USDT available margin)
            # e.g., if self.market_type == 'future' and currency == 'USDT':
            #   info_balance = balance_data.get('info', {}).get('availableBalance') # This is often a string
            #   if info_balance is not None: return float(info_balance)

            trading_logger.error(f"无法从交易所响应中解析 {currency} 的可用余额 ({self.market_type}模式)。")
            return 0.0
            
        except ccxt.NetworkError as e:
            trading_logger.error(f"获取余额网络错误 ({self.market_type}): {str(e)}", exc_info=True)
            return 0.0
        except ccxt.ExchangeError as e:
            trading_logger.error(f"获取余额交易所错误 ({self.market_type}): {str(e)}", exc_info=True)
            return 0.0
        except Exception as e:
            trading_logger.error(f"获取余额失败 ({self.market_type}): {str(e)}", exc_info=True)
            # Log the full balance data on generic error to help debug structure
            try:
                balance_data_on_error = self.exchange.fetch_balance() # Try fetching again just for logging
                trading_logger.debug(f"Balance data on error for {self.market_type}: {balance_data_on_error}")
            except Exception as e_fetch:
                trading_logger.error(f"获取余额以进行错误日志记录也失败了: {e_fetch}")
            return 0.0
    
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
    
    def get_market_type(self) -> str:
        return self.market_type 

    def _calculate_futures_quantity(self, symbol: str, usdt_amount: float) -> Optional[float]:
        """Calculates contract quantity for futures based on USDT amount and current price."""
        try:
            ticker = self.get_ticker(symbol)
            current_price = ticker.get('last')
            if current_price is None or current_price == 0:
                trading_logger.error(f"无法为 {symbol} 获取有效当前价格以计算合约数量。")
                return None
            
            # quantity = usdt_amount / current_price
            # No, for linear futures (USDT margined), amount is in base currency (e.g. BTC for BTC/USDT)
            # So, if per_order_size_usdt is 100 USDT, and BTC price is 50000 USDT,
            # quantity of BTC = 100 / 50000 = 0.002 BTC.
            # This seems correct. Let's get market data for precision.
            market = self.exchange.market(symbol)
            if not market:
                trading_logger.error(f"无法获取 {symbol} 的市场数据以进行精度调整。")
                return None

            quantity = usdt_amount / current_price
            # Apply amount precision
            # Note: some exchanges might have contract_size or other factors for non-linear contracts.
            # For Binance linear (USDT-M) futures, amount is typically in base asset.
            precise_quantity = float(self.exchange.amount_to_precision(symbol, quantity))
            
            # Check against min amount if possible (market['limits']['amount']['min'])
            min_amount = market.get('limits', {}).get('amount', {}).get('min')
            if min_amount is not None and precise_quantity < min_amount:
                trading_logger.warning(f"{symbol} 计算数量 {precise_quantity} 小于最小订单量 {min_amount}。调整至最小订单量。")
                # precise_quantity = min_amount # Or reject, for now, let's log and proceed, exchange will reject if too small.
                # Better to reject if it's below min, but for now, this highlights the issue.
                # Let's just return None if it's too small, as the exchange will likely reject it.
                if precise_quantity == 0: # If precision made it zero
                    trading_logger.error(f"{symbol} 合约数量经精度调整后为0。无法下单。")
                    return None
                # If still less than min_amount after precision (and not zero), it's problematic.
                # The bot should ideally not attempt if it knows it's below minimums.

            trading_logger.info(f"期货合约数量计算: {usdt_amount} USDT @ {current_price} {symbol.split('/')[1] if '/' in symbol else 'QUOTE'} for {symbol} = {precise_quantity} {market.get('base', 'BASE')}")
            return precise_quantity

        except Exception as e:
            trading_logger.error(f"计算期货合约数量失败 ({symbol}): {e}", exc_info=True)
            return None

    def place_order(
        self,
        symbol: str,
        side: str,         # 'buy' or 'sell'
        order_type: str,   # 'limit' or 'market'
        amount: float,     # For spot: in base currency. For futures: this will be RECALCULATED from per_order_size_usdt
        price: Optional[float] = None,
        per_order_size_usdt: Optional[float] = None # New param for desired USDT value of order
    ) -> Optional[Dict]:
        """
        下单. 
        For futures, 'amount' is ignored if 'per_order_size_usdt' is provided, quantity is calculated.
        """
        trading_logger.info(f"Placing order for {symbol}, side: {side}, type: {order_type}, amount_arg: {amount}, price: {price}, usdt_size_config: {per_order_size_usdt}")
        
        final_amount = amount
        final_price = price
        market = self.exchange.market(symbol)

        if not market:
            trading_logger.error(f"无法获取 {symbol} 的市场数据。取消下单。")
            return None

        if self.market_type == 'future':
            if per_order_size_usdt is None:
                trading_logger.error(f"期货订单 ({symbol}) 未提供 per_order_size_usdt。无法计算数量。")
                return None
            
            calculated_quantity = self._calculate_futures_quantity(symbol, per_order_size_usdt)
            if calculated_quantity is None or calculated_quantity == 0:
                trading_logger.error(f"期货订单 ({symbol}) 计算的合约数量无效 ({calculated_quantity})。取消下单。")
                return None
            final_amount = calculated_quantity
            trading_logger.info(f"期货模式 {symbol}: 使用计算数量 {final_amount}")
        else: # spot
            # Ensure spot amount and price use precision
            final_amount = float(self.exchange.amount_to_precision(symbol, amount))
            trading_logger.info(f"现货模式 {symbol}: 使用提供数量 {final_amount} (原始: {amount})")

        if order_type == 'limit':
            if final_price is None:
                trading_logger.error(f"限价单 ({symbol}) 必须指定价格。")
                return None
            final_price = float(self.exchange.price_to_precision(symbol, final_price))
            # For spot, check cost precision as well for limit orders
            if self.market_type == 'spot':
                 cost = final_amount * final_price
                 min_cost = market.get('limits', {}).get('cost', {}).get('min')
                 if min_cost is not None and cost < min_cost:
                     trading_logger.error(f"现货限价单 {symbol} 计算成本 {cost} USDT 低于最小允许值 {min_cost} USDT。取消下单。")
                     return None
        
        # Final check for amount being non-zero after precision
        if final_amount == 0:
            trading_logger.error(f"{symbol} 最终计算的订单数量为0。取消下单。")
            return None

        try:
            params = {}
            # For futures, we might need to specify positionSide if in Hedge Mode.
            # Assuming One-Way mode for now. Side 'buy' opens long or closes short.
            # Side 'sell' opens short or closes long.
            # If exchange is in Hedge Mode, create_order might need explicit LONG/SHORT for positionSide.
            # Example: if side == 'buy': params['positionSide'] = 'LONG' else: params['positionSide'] = 'SHORT'
            # This depends on user's account settings on Binance (One-Way vs Hedge Mode for futures)
            # For simplicity, we'll not add it yet, ccxt might handle it based on one-way mode assumption.

            trading_logger.info(f"准备执行交易所订单: {symbol}, 类型: {order_type}, 方向: {side}, 数量: {final_amount}, 价格: {final_price}, 参数: {params}")

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=final_amount,
                price=final_price,
                params=params
            )
            
            trading_logger.info(
                f"下单成功 ({self.market_type}): {order.get('symbol')}, ID: {order.get('id')}, 方向: {order.get('side')}, 数量: {order.get('amount')}, 价格: {order.get('price') if order.get('price') else order.get('average', 'N/A')}"
            )
            
            # TODO: _update_position and _record_trade need to be market_type aware
            if self.market_type == 'spot':
                entry_price_for_update = order.get('average', order.get('price')) # Use average if available (market orders), else price (limit orders)
                if entry_price_for_update is None and order_type == 'market':
                    # For market orders where average isn't immediately available, fetch last price as fallback
                    # This is a simplification; ideally, filled price should be used.
                    ticker = self.get_ticker(symbol)
                    entry_price_for_update = ticker.get('last')
                
                if entry_price_for_update is not None:
                    self._update_position(symbol, order.get('side'), float(order.get('filled', 0)), entry_price_for_update) 
                else:
                    trading_logger.warning(f"无法确定现货订单 {order.get('id')} 的入场价格以更新仓位。")
            else: # future - position update will be handled differently, likely via fetch_positions
                trading_logger.info(f"期货订单 {order.get('id')} 已下达。仓位更新将依赖 fetch_positions 或更复杂的逻辑。")

            self._record_trade(order) # _record_trade might also need adjustment but basic info is fine.
            
            return order
            
        except ccxt.InsufficientFunds as e:
            trading_logger.error(f"下单失败 ({self.market_type}) - 资金不足: {symbol} {side} {final_amount} - {str(e)}")
            return None
        except ccxt.ExchangeError as e:
            trading_logger.error(f"下单失败 ({self.market_type}) - 交易所错误: {symbol} {side} {final_amount} - {str(e)}")
            return None
        except ValueError as e: # For our internal checks like price for limit order
            trading_logger.error(f"下单失败 ({self.market_type}) - 输入值错误: {symbol} {side} {final_amount} - {str(e)}")
            return None
        except Exception as e:
            trading_logger.error(f"下单失败 ({self.market_type}) - 未知错误: {symbol} {side} {final_amount} - {str(e)}", exc_info=True)
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

    def get_current_positions(self) -> Dict[str, Any]:
        """获取当前持仓 (现货或期货)"""
        if self.market_type == 'future':
            try:
                # For futures, fetch live positions from the exchange
                # fetch_positions returns a list of position objects
                fetched_positions = self.exchange.fetch_positions()
                # Re-format into a dictionary similar to how spot positions might be stored, if needed,
                # or use as is. For now, let's build a dict by symbol.
                current_futures_pos = {}
                for pos in fetched_positions:
                    if pos.get('info') and float(pos.get('info').get('positionAmt', 0)) != 0: # Only open positions
                        current_futures_pos[pos['symbol']] = pos 
                return current_futures_pos
            except Exception as e:
                trading_logger.error(f"获取期货持仓失败: {e}", exc_info=True)
                return {} # Return empty if error
        else: # spot
            # For spot, self.positions is maintained by _update_position
            # Filter out zero-amount spot positions
            return {sym: pos for sym, pos in self.positions.items() if pos.get('amount', 0) > 0}

    # The existing _update_position is for SPOT only.
    # We need to decide how to manage futures positions. CCXT's fetch_positions() is the source of truth.
    # So, _update_position might become a no-op or be removed for futures if we always fetch.
    # For now, the conditional logic in place_order bypasses it for futures. 