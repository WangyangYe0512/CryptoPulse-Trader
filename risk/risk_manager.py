from typing import Dict, List, Optional
from datetime import datetime, timedelta
from utils.logger import trading_logger
# We need a reference to TradingEngine to get market_type and fetch live futures positions
# from execution.trading_engine import TradingEngine # Assuming this import path is correct

class RiskManager:
    """风险控制管理器"""
    
    def __init__(
        self,
        config_manager,
        max_position_size: float = None,
        max_daily_loss: float = None,
        max_holding_time_minutes: int = None,
        stop_loss_percent: float = None,
        take_profit_percent: float = None
    ):
        """
        初始化风险控制器
        
        Args:
            config_manager: ConfigManager instance
            max_position_size: 每笔订单的最大仓位大小（USDT），None时从配置读取
            max_daily_loss: 最大日亏损百分比，None时从配置读取
            max_holding_time_minutes: 最大持仓时间（分钟），None时从配置读取
            stop_loss_percent: 止损百分比，None时从配置读取
            take_profit_percent: 止盈百分比，None时从配置读取
        """
        self.config_manager = config_manager
        
        # 从配置中读取参数，如果未提供则使用配置值
        self.per_order_size = max_position_size or config_manager.get('risk.max_position_size', 15.0)
        self.max_daily_loss = max_daily_loss or config_manager.get('risk.max_daily_loss', 100.0)
        self.max_holding_time_minutes = max_holding_time_minutes or config_manager.get('trading.max_holding_time_minutes', 60)
        self.stop_loss_percent = (stop_loss_percent or config_manager.get('risk.stop_loss_pct', 1.0)) / 100
        self.take_profit_percent = (take_profit_percent or config_manager.get('risk.take_profit_pct', 2.0)) / 100
        
        # 从配置中读取市场类型
        self.market_type = config_manager.get('trading.market_type', 'futures')
        
        trading_logger.info(f"RiskManager初始化: 单笔限额={self.per_order_size}USDT, 日亏损限制={self.max_daily_loss}USDT, 市场类型={self.market_type}")
        
        self.positions: Dict[str, List[Dict]] = {}
        self.daily_pnl: float = 0.0
        self.trades: List[Dict] = []
        self.last_reset_time = datetime.now()
        
    def can_open_position(self, symbol: str, direction: str, price: float, existing_orders_count: int, max_orders_per_symbol: int) -> bool:
        """
        检查是否可以为某个符号开立新的独立订单
        
        Args:
            symbol: 交易对符号
            direction: 交易方向
            price: 当前价格
            existing_orders_count: 该交易对已有的独立订单数量
            max_orders_per_symbol: 每个交易对允许的最大独立订单数量 (用于循环开仓限制)
            
        Returns:
            是否可以开仓
        """
        try:
            # 检查该符号下的独立订单数量是否已达上限
            if existing_orders_count >= max_orders_per_symbol:
                trading_logger.info(f"{symbol} 已达到最大独立订单数量 ({max_orders_per_symbol})，无法开新单")
                return False
                
            # 检查日亏损限制 (日亏损是全局的，不是针对单个符号)
            if self.daily_pnl <= -self.max_daily_loss:
                trading_logger.warning(f"达到日亏损限制: {self.daily_pnl}%")
                return False
                
            # 检查最小订单量 (现在是 per_order_size)
            if self.per_order_size < 10: # 更通用的最小限制，交易所通常是10USDT左右
                trading_logger.warning(f"订单量 {self.per_order_size} USDT 小于通用最小要求 10 USDT")
                return False
                
            return True
            
        except Exception as e:
            trading_logger.error(f"开仓检查失败: {str(e)}")
            return False
    
    def add_position(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        size: float,
        stop_loss_price: float,
        take_profit_price: float,
        exchange_order_id: Optional[str] = None
    ):
        """
        添加一个新的独立持仓订单记录
        
        Args:
            symbol: 交易对符号
            direction: 交易方向
            entry_price: 此订单的入场价格
            size: 此订单的仓位大小 (USDT)
            stop_loss_price: 此订单的止损价格
            take_profit_price: 此订单的止盈价格
            exchange_order_id: (可选) 交易所返回的订单ID
        """
        if symbol not in self.positions:
            self.positions[symbol] = []
        
        # 为这个新订单生成一个唯一的内部ID
        # 使用时间戳和列表长度确保大致唯一性，更健壮的可以用uuid
        order_internal_id = f"{symbol}_{datetime.now().timestamp()}_{len(self.positions[symbol])}"

        new_order_data = {
            'id': order_internal_id,
            'exchange_order_id': exchange_order_id,
            'direction': direction,
            'entry_price': entry_price,
            'size': size, 
            'stop_loss': stop_loss_price, 
            'take_profit': take_profit_price,
            'entry_time': datetime.now(),
            'status': 'open' # 标记订单状态
        }
        self.positions[symbol].append(new_order_data)
        
        trading_logger.info(
            f"新增独立订单: {symbol} ({order_internal_id}) {direction} {size} USDT @ {entry_price}, "
            f"止损: {stop_loss_price}, 止盈: {take_profit_price}"
        )
    
    def check_position_risk(self, symbol: str, current_price: float) -> List[Dict]:
        """
        Checks risk for all open orders of a symbol (spot) or the net position (futures).
        Returns a list of orders/positions to be closed.
        """
        to_close = []
        market_type = self.market_type

        if market_type == 'spot':
            if symbol in self.positions:
                for order in list(self.positions[symbol]): # Iterate over a copy if modifying list
                    if order['status'] == 'open':
                        # Check SL/TP
                        if order['direction'] == 'long':
                            if current_price <= order['stop_loss']:
                                trading_logger.info(f"RM SPOT: {symbol} LONG SL hit for order {order['id']}. Price: {current_price} <= SL: {order['stop_loss']}")
                                to_close.append({'order': order, 'reason': 'stop_loss', 'price': current_price})
                                continue # Processed this order
                            if current_price >= order['take_profit']:
                                trading_logger.info(f"RM SPOT: {symbol} LONG TP hit for order {order['id']}. Price: {current_price} >= TP: {order['take_profit']}")
                                to_close.append({'order': order, 'reason': 'take_profit', 'price': current_price})
                                continue
                        else:  # short
                            if current_price >= order['stop_loss']:
                                trading_logger.info(f"RM SPOT: {symbol} SHORT SL hit for order {order['id']}. Price: {current_price} >= SL: {order['stop_loss']}")
                                to_close.append({'order': order, 'reason': 'stop_loss', 'price': current_price})
                                continue
                            if current_price <= order['take_profit']:
                                trading_logger.info(f"RM SPOT: {symbol} SHORT TP hit for order {order['id']}. Price: {current_price} <= TP: {order['take_profit']}")
                                to_close.append({'order': order, 'reason': 'take_profit', 'price': current_price})
                                continue
                        
                        # Check Max Holding Time (based on individual order's entry time)
                        if (datetime.now() - order['entry_time']) > timedelta(minutes=self.max_holding_time_minutes):
                            trading_logger.info(f"RM SPOT: {symbol} order {order['id']} max holding time reached.")
                            to_close.append({'order': order, 'reason': 'timeout', 'price': current_price})
                            continue
        
        elif market_type == 'future':
            # For futures, we check each internally tracked conceptual order
            # against the current market price, similar to spot.
            if symbol in self.positions:
                for order in list(self.positions[symbol]): # Iterate over a copy if modifying list
                    if order['status'] == 'open':
                        # Check SL/TP using pre-calculated values in the order object
                        # These values (order['stop_loss'], order['take_profit']) were calculated 
                        # and stored when self.add_position was called.
                        if order['direction'] == 'long':
                            if current_price <= order['stop_loss']:
                                trading_logger.info(f"RM FUTURES: {symbol} LONG SL hit for order {order['id']}. Price: {current_price} <= SL: {order['stop_loss']}")
                                to_close.append({'order': order, 'reason': 'stop_loss', 'price': current_price})
                                continue 
                            if current_price >= order['take_profit']:
                                trading_logger.info(f"RM FUTURES: {symbol} LONG TP hit for order {order['id']}. Price: {current_price} >= TP: {order['take_profit']}")
                                to_close.append({'order': order, 'reason': 'take_profit', 'price': current_price})
                                continue
                        elif order['direction'] == 'short':  # Assuming direction is 'long' or 'short'
                            if current_price >= order['stop_loss']:
                                trading_logger.info(f"RM FUTURES: {symbol} SHORT SL hit for order {order['id']}. Price: {current_price} >= SL: {order['stop_loss']}")
                                to_close.append({'order': order, 'reason': 'stop_loss', 'price': current_price})
                                continue
                            if current_price <= order['take_profit']:
                                trading_logger.info(f"RM FUTURES: {symbol} SHORT TP hit for order {order['id']}. Price: {current_price} <= TP: {order['take_profit']}")
                                to_close.append({'order': order, 'reason': 'take_profit', 'price': current_price})
                                continue
                        else: # Should not happen if direction is always 'long' or 'short'
                            trading_logger.warning(f"RM FUTURES: Unknown order direction '{order['direction']}' for order {order['id']}")
                            continue
                        
                        # Check Max Holding Time (based on individual order's entry time)
                        if (datetime.now() - order['entry_time']) > timedelta(minutes=self.max_holding_time_minutes):
                            trading_logger.info(f"RM FUTURES: {symbol} order {order['id']} max holding time reached.")
                            to_close.append({'order': order, 'reason': 'timeout', 'price': current_price})
                            continue
        
        return to_close
    
    def close_position(self, symbol: str, order_id_to_close: str, exit_price: float, reason: str) -> Optional[Dict]:
        """
        平掉一个指定的独立订单
        
        Args:
            symbol: 交易对符号
            order_id_to_close: 要关闭的独立订单的内部ID
            exit_price: 平仓价格
            reason: 平仓原因
            
        Returns:
            成功平仓则返回该笔交易的记录字典，否则返回 None
        """
        try:
            if symbol not in self.positions:
                trading_logger.warning(f"尝试平仓失败：交易对 {symbol} 不存在于持仓中")
                return None
            
            order_to_close = None
            order_index = -1
            for i, order_data in enumerate(self.positions[symbol]):
                if order_data['id'] == order_id_to_close:
                    order_to_close = order_data
                    order_index = i
                    break
            
            if not order_to_close:
                trading_logger.warning(f"尝试平仓失败：订单ID {order_id_to_close} 在 {symbol} 持仓中未找到")
                return None

            if order_to_close['status'] == 'closed':
                trading_logger.warning(f"尝试平仓失败：订单ID {order_id_to_close} ({symbol}) 已关闭")
                return None
            
            # 计算此独立订单的盈亏 (基于名义价值的百分比)
            # 假设 order_to_close['size'] 是USDT名义价值
            # PNL = (Exit Price - Entry Price) / Entry Price for long
            # PNL = (Entry Price - Exit Price) / Entry Price for short
            # PNL_amount = PNL_percentage * Size_in_quote_currency (which is order_to_close['size'])

            pnl_percentage = 0.0
            if order_to_close['entry_price'] > 0:
                if order_to_close['direction'] == 'long':
                    pnl_percentage = (exit_price - order_to_close['entry_price']) / order_to_close['entry_price'] * 100
                else: # short
                    pnl_percentage = (order_to_close['entry_price'] - exit_price) / order_to_close['entry_price'] * 100
            
            # 更新日总盈亏 (这里假设 daily_pnl 仍然是总的百分比，需要根据实际需求调整是累加金额还是如何处理)
            # 简单起见，这里累加的是基于该订单名义价值的盈亏百分比，这可能不完全准确反映账户总资金的百分比变动
            # 更准确的做法是计算盈亏金额，然后根据账户总资金计算百分比，但目前没有总资金信息
            self.daily_pnl += pnl_percentage # This might need more thought on how to aggregate PNL percentage from different sized trades
            
            # 记录到已关闭交易列表
            closed_trade_log = {
                'order_id': order_to_close['id'],
                'exchange_order_id': order_to_close.get('exchange_order_id'),
                'symbol': symbol,
                'direction': order_to_close['direction'],
                'entry_price': order_to_close['entry_price'],
                'exit_price': exit_price,
                'size': order_to_close['size'], # USDT value of the trade
                'pnl_percentage': pnl_percentage,
                # 'pnl_amount': pnl_amount, # Would be (pnl_percentage / 100) * order_to_close['size']
                'reason': reason,
                'entry_time': order_to_close['entry_time'],
                'exit_time': datetime.now()
            }
            self.trades.append(closed_trade_log)
            
            # 从当前持仓中移除该订单，或者标记为closed
            # 为了简单，我们直接移除。如果需要保留历史，可以标记状态
            self.positions[symbol].pop(order_index)
            # 如果该symbol下没有更多订单了，可以从self.positions中移除该symbol
            if not self.positions[symbol]:
                del self.positions[symbol]
            
            trading_logger.info(
                f"已平仓独立订单: {order_to_close['id']} ({symbol}) {order_to_close['direction']} {order_to_close['size']} USDT "
                f"@ {exit_price}, 原因: {reason}, 盈亏: {pnl_percentage:.2f}%"
            )
            
            return closed_trade_log
            
        except Exception as e:
            trading_logger.error(f"平仓独立订单失败 ({order_id_to_close}, {symbol}): {str(e)}")
            return None
    
    def get_position_summary(self) -> Dict:
        """
        获取持仓摘要
        
        Returns:
            持仓摘要信息
        """
        return {
            'total_positions': len(self.positions),
            'daily_pnl': self.daily_pnl,
            'positions': self.positions,
            'trades': self.trades
        }
    
    def reset_daily_stats(self):
        """重置每日统计"""
        self.daily_pnl = 0.0
        self.trades = [] 

    def _update_daily_pnl(self, pnl_percentage: float):
        # This needs to be more sophisticated, considering trade size relative to capital.
        # For now, a simple sum of percentages for closed trades.
        # This is also not true portfolio PNL.
        if datetime.now().day != self.last_reset_time.day:
            self.daily_pnl = 0.0
            self.last_reset_time = datetime.now()
        self.daily_pnl += pnl_percentage 

    def get_all_open_orders_details(self) -> Dict[str, List[Dict]]:
        """ 
        Returns details of all orders the bot thinks are open (from its internal tracking).
        For futures, this might not perfectly reflect the single net position on exchange but represents bot's intent.
        """
        open_orders = {}
        for symbol, orders in self.positions.items():
            active_orders_for_symbol = [o for o in orders if o['status'] == 'open']
            if active_orders_for_symbol:
                open_orders[symbol] = active_orders_for_symbol
        return open_orders

    def get_order_details(self, symbol: str, order_id: str) -> Optional[Dict]:
        if symbol in self.positions:
            for order in self.positions[symbol]:
                if order['id'] == order_id:
                    return order
        return None

    def get_total_open_orders_count(self) -> int:
        count = 0
        for symbol_orders in self.positions.values():
            for order in symbol_orders:
                if order['status'] == 'open':
                    count += 1
        return count

    def remove_all_orders_for_symbol(self, symbol: str):
        """Removes all tracked orders for a symbol, e.g., after a full position close for futures."""
        if symbol in self.positions:
            del self.positions[symbol]
            trading_logger.info(f"RM: Removed all tracked orders for symbol {symbol}.") 

    def check_risk(self, signal: Dict) -> bool:
        """
        检查交易信号是否通过风险控制
        
        Args:
            signal: 交易信号字典，包含symbol、type、price等信息
            
        Returns:
            bool: True表示通过风险检查，False表示拒绝
        """
        try:
            symbol = signal.get('symbol', '')
            signal_type = signal.get('type', '')
            price = signal.get('price', 0.0)
            position_size = signal.get('position_size_usdt', self.per_order_size)
            
            # 1. 检查日亏损限制
            if self.daily_pnl <= -self.max_daily_loss:
                trading_logger.warning(f"风险检查失败: 达到日亏损限制 {self.daily_pnl}% >= {self.max_daily_loss}%")
                return False
            
            # 2. 检查仓位大小限制
            if position_size > self.per_order_size:
                trading_logger.warning(f"风险检查失败: 仓位大小 {position_size} USDT 超过限制 {self.per_order_size} USDT")
                return False
                
            # 3. 检查最小仓位限制
            if position_size < 10:  # 通用最小限制
                trading_logger.warning(f"风险检查失败: 仓位大小 {position_size} USDT 小于最小要求 10 USDT")
                return False
            
            # 4. 检查当前持仓数量（如果是开仓信号）
            if signal_type in ['OPEN_LONG', 'OPEN_SHORT']:
                current_orders_count = len(self.positions.get(symbol, []))
                max_orders_per_symbol = 5  # 可以从配置中读取
                
                if current_orders_count >= max_orders_per_symbol:
                    trading_logger.warning(f"风险检查失败: {symbol} 已达到最大订单数量 {max_orders_per_symbol}")
                    return False
            
            # 5. 验证价格数据
            if price <= 0:
                trading_logger.warning(f"风险检查失败: 无效价格 {price}")
                return False
                
            # 6. 检查符号是否有效
            if not symbol or not signal_type:
                trading_logger.warning("风险检查失败: 无效的信号数据")
                return False
            
            trading_logger.info(f"风险检查通过: {symbol} {signal_type} @ {price}")
            return True
            
        except Exception as e:
            trading_logger.error(f"风险检查过程中发生错误: {e}", exc_info=True)
            return False 