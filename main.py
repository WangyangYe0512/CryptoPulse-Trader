import time
from datetime import datetime
import ccxt
from utils.logger import trading_logger
from utils.config_manager import ConfigManager
from data.data_fetcher import DataFetcher
from scanner.market_scanner import MarketScanner
from analyzer.trend_analyzer import TrendAnalyzer
from risk.risk_manager import RiskManager
from execution.trading_engine import TradingEngine
from analysis.performance_analyzer import PerformanceAnalyzer
from notifier.telegram_notifier import get_telegram_notifier
from typing import Tuple, Optional
import pandas as pd

class CryptoPulseTrader:
    """加密货币脉冲交易系统"""
    
    def __init__(self):
        """初始化交易系统"""
        self.config = ConfigManager()
        
        self.exchange = ccxt.binance({
            'apiKey': self.config.get('api.binance.api_key'),
            'secret': self.config.get('api.binance.api_secret'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'testnet': self.config.get('api.binance.testnet', True)
            }
        })
        
        self.data_fetcher = DataFetcher(exchange=self.exchange)
        self.market_scanner = MarketScanner(
            exchange=self.exchange,
            volatility_timeframe=self.config.get('scanner.volatility_timeframe', '1h'),
            volatility_ohlcv_limit=self.config.get('scanner.volatility_ohlcv_limit', 2),
            analysis_timeframe=self.config.get('trend.analysis_timeframe', '1m')
        )
        self.trend_analyzer = TrendAnalyzer(
            min_slope_percent=self.config.get('trend.min_slope_percent', 0.5),
            lookback_periods=self.config.get('trend.lookback_periods', 5),
            confirmation_periods=self.config.get('trend.confirmation_periods', 3)
        )
        
        self.risk_manager = RiskManager(
            max_position_size=self.config.get('trading.per_order_size_usdt', 100.0),
            max_daily_loss=self.config.get('trading.max_daily_loss_percent', 5.0),
            max_holding_time=self.config.get('trading.max_holding_time_minutes', 60),
            stop_loss_pct=self.config.get('trading.stop_loss_percent', 1.0),
            take_profit_pct=self.config.get('trading.take_profit_percent', 2.0)
        )
        self.trading_engine = TradingEngine(
            api_key=self.config.get('api.binance.api_key'),
            api_secret=self.config.get('api.binance.api_secret'),
            testnet=self.config.get('api.binance.testnet', True)
        )
        self.performance_analyzer = PerformanceAnalyzer()
        
        self.telegram_notifier = get_telegram_notifier(self.config)
        self.telegram_notifier.set_trading_engine(self.trading_engine)
        self.telegram_notifier.set_risk_manager(self.risk_manager)
        
        self.check_interval = self.config.get('trading.check_interval_seconds', 60)
        self.last_scan_time = None
        
        self.max_orders_per_symbol = self.config.get('trading.max_orders_per_symbol', 3) 
        self.max_active_symbols = self.config.get('trading.max_active_symbols', 5) 
        self.scan_interval = self.config.get('scanner.scan_interval', 3600)
        self.add_position_interval = self.config.get('trading.add_position_interval', 30)
        
    def run(self):
        trading_logger.info("启动交易系统...")
        if self.config.get('notification.notify_on_status', True):
            self.telegram_notifier.send_error_notification(
                "系统启动", 
                "CryptoPulse Trader已启动，正在等待扫描时间..."
            )
        
        while True:
            try:
                current_time = datetime.now()
                
                if (self.last_scan_time is None or 
                    (current_time - self.last_scan_time).total_seconds() >= self.scan_interval):
                    self._scan_market()
                    self.last_scan_time = current_time
                
                self._check_positions()
                
                if current_time.hour == 0 and current_time.minute == 0:
                    self._generate_daily_report()
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                trading_logger.error(f"系统运行错误: {str(e)}", exc_info=True)
                if self.config.get('notification.notify_on_error', True):
                    self.telegram_notifier.send_error_notification(
                        "系统错误", 
                        f"运行时错误: {str(e)}"
                    )
                time.sleep(self.check_interval) 
                
    def _scan_market(self):
        """扫描市场机会并可能开立新的独立订单"""
        try:
            trading_logger.info("开始市场扫描...")
            initial_candidates = self.market_scanner.scan_market(
                max_candidates=self.config.get('scanner.max_candidates', 15)
            ) 
            filtered_candidates = self.market_scanner.filter_by_liquidity(
                candidates=initial_candidates, 
                min_volume_usdt=self.config.get('scanner.min_volume_usdt', 1000000),
                max_liquidity_candidates=self.config.get('scanner.max_liquidity_candidates', 5)
            )
            trading_logger.info(f"流动性筛选后剩余 {len(filtered_candidates)} 个候选币种")
            
            opened_new_symbols_count = 0

            for candidate in filtered_candidates:
                symbol = candidate['symbol']
                
                current_active_symbols = len(self.risk_manager.positions)
                if symbol not in self.risk_manager.positions and current_active_symbols >= self.max_active_symbols:
                    trading_logger.info(f"已达到最大活跃交易对数量 ({self.max_active_symbols})，跳过新币种 {symbol}")
                    continue
                
                trend_data = self.market_scanner.get_trend_data(
                    symbol,
                    limit=self.config.get('trend.lookback_periods', 5)
                )
                if trend_data is None or trend_data.empty:
                    trading_logger.warning(f"无法获取 {symbol} 的趋势数据，跳过")
                    continue
                
                trend_confirmed, direction = self.trend_analyzer.analyze_trend(trend_data)
                
                if trend_confirmed:
                    trading_logger.info(f"{symbol} 趋势确认: {direction}")
                    current_price = trend_data['close'].iloc[-1]
                    
                    existing_orders_for_symbol_count = len(self.risk_manager.positions.get(symbol, []))
                    
                    if self.risk_manager.can_open_position(symbol, direction, current_price, existing_orders_for_symbol_count, self.max_orders_per_symbol):
                        order_size_usdt = self.risk_manager.per_order_size
                        
                        stop_loss_price = self.trend_analyzer.calculate_stop_loss(
                            current_price, direction, self.risk_manager.stop_loss_pct
                        )
                        take_profit_price = self.trend_analyzer.calculate_take_profit(
                            current_price, direction, self.risk_manager.take_profit_pct
                        )
                        
                        trading_logger.info(f"准备为 {symbol} 开设独立订单，价格: {current_price}, 方向: {direction}, 大小: {order_size_usdt} USDT")
                        exchange_order = self.trading_engine.place_order(
                            symbol=symbol,
                            side='buy' if direction == 'long' else 'sell',
                            order_type='limit',
                            amount=order_size_usdt / current_price, 
                            price=current_price
                        )
                        
                        if exchange_order:
                            self.risk_manager.add_position(
                                symbol=symbol,
                                direction=direction,
                                entry_price=current_price, 
                                size=order_size_usdt, 
                                stop_loss_price=stop_loss_price,
                                take_profit_price=take_profit_price,
                                exchange_order_id=exchange_order.get('id')
                            )
                            
                            is_new_symbol_position = symbol not in self.risk_manager.positions or len(self.risk_manager.positions[symbol]) == 1
                            if is_new_symbol_position:
                                opened_new_symbols_count +=1 
                            
                            if self.config.get('notification.notify_on_trade', True):
                                self.telegram_notifier.send_trade_notification(
                                    trade_type="open",
                                    symbol=symbol,
                                    direction=direction,
                                    price=current_price,
                                    amount=order_size_usdt,
                                    stop_loss=stop_loss_price,
                                    take_profit=take_profit_price
                                )
                    else:
                        trading_logger.info(f"无法为 {symbol} 开设新订单，原因：不满足开仓条件或已达该币种订单上限。已有订单数: {existing_orders_for_symbol_count}")
                        
            trading_logger.info(f"市场扫描完成，新开仓的交易对数量: {opened_new_symbols_count}")
                            
        except Exception as e:
            trading_logger.error(f"市场扫描错误: {str(e)}", exc_info=True)
            if self.config.get('notification.notify_on_error', True):
                self.telegram_notifier.send_error_notification(
                    "扫描错误", 
                    f"市场扫描失败: {str(e)}"
                )
            
    def _check_positions(self):
        """检查所有活跃交易对下的每个独立订单的风险，并处理循环加仓"""
        try:
            active_symbols = list(self.risk_manager.positions.keys())

            for symbol in active_symbols:
                if symbol not in self.risk_manager.positions or not self.risk_manager.positions[symbol]:
                    continue

                current_price = self.data_fetcher.get_current_price(symbol)
                if current_price is None:
                    trading_logger.warning(f"无法获取 {symbol} 的当前价格，跳过风险检查")
                    continue
                
                close_trigger = self.risk_manager.check_position_risk(symbol, current_price)
                
                if close_trigger:
                    close_reason, order_id_to_close = close_trigger
                    trading_logger.info(f"订单 {order_id_to_close} ({symbol}) 触发平仓，原因: {close_reason}")
                    
                    order_to_close_details = None
                    for order_in_list in self.risk_manager.positions.get(symbol, []):
                        if order_in_list['id'] == order_id_to_close:
                            order_to_close_details = order_in_list
                            break
                    
                    if order_to_close_details:
                        order_size_usdt = order_to_close_details['size']
                        order_direction = order_to_close_details['direction']
                        order_entry_price = order_to_close_details['entry_price'] 
                        
                        amount_to_close_base_currency = order_size_usdt / current_price 
                        
                        exchange_order = self.trading_engine.place_order(
                            symbol=symbol,
                            side='sell' if order_direction == 'long' else 'buy',
                            order_type='limit', 
                            amount=amount_to_close_base_currency,
                            price=current_price
                        )
                        
                        if exchange_order:
                            closed_trade_log = self.risk_manager.close_position(
                                symbol, order_id_to_close, current_price, close_reason
                            )
                            
                            if closed_trade_log and self.config.get('notification.notify_on_trade', True):
                                pnl_percentage = closed_trade_log['pnl_percentage']
                                pnl_amount_usdt = (pnl_percentage / 100) * order_size_usdt
                                
                                reason_text_map = {
                                    'stop_loss': '止损触发',
                                    'take_profit': '止盈触发',
                                    'timeout': '持仓超时',
                                    'trend_reversal': '趋势反转(按当前定义)',
                                    'forced': '手动平仓',
                                    'shutdown': '系统关闭'
                                }
                                reason_display_text = reason_text_map.get(close_reason, close_reason)
                                
                                entry_time = order_to_close_details['entry_time']
                                holding_duration_minutes = int((datetime.now() - entry_time).total_seconds() / 60)

                                msg = f"🔴 单独订单平仓通知\n\n" \
                                      f"*订单ID*: `{order_id_to_close}`\n" \
                                      f"*币种*: `{symbol}`\n" \
                                      f"*方向*: {'多' if order_direction == 'long' else '空'}\n" \
                                      f"*入场价*: `{order_entry_price:.8f}`\n" \
                                      f"*平仓价*: `{current_price:.8f}`\n" \
                                      f"*数量*: `{order_size_usdt:.2f} USDT`\n" \
                                      f"*此单盈亏*: `{pnl_amount_usdt:.2f} USDT ({pnl_percentage:.2f}%)`\n" \
                                      f"*原因*: {reason_display_text}\n" \
                                      f"*持仓时间*: {holding_duration_minutes} 分钟"
                                self.telegram_notifier._send_msg(msg)
                    else:
                        trading_logger.error(f"严重错误：无法在 {symbol} 中找到待平仓的订单ID {order_id_to_close}")

                else: 
                    trend_data = self.market_scanner.get_trend_data(
                        symbol,
                        limit=self.config.get('trend.lookback_periods', 5)
                    ) 
                    if trend_data is None or trend_data.empty:
                        trading_logger.warning(f"无法获取 {symbol} 的趋势数据，跳过循环加仓检查")
                        continue
                    
                    can_add, add_direction = self._can_add_new_order_for_symbol(symbol, trend_data)
                    if can_add:
                        add_price = trend_data['close'].iloc[-1]
                        order_size_usdt = self.risk_manager.per_order_size

                        stop_loss_price = self.trend_analyzer.calculate_stop_loss(
                            add_price, add_direction, self.risk_manager.stop_loss_pct
                        )
                        take_profit_price = self.trend_analyzer.calculate_take_profit(
                            add_price, add_direction, self.risk_manager.take_profit_pct
                        )
                        
                        trading_logger.info(f"准备为 {symbol} 循环加仓，价格: {add_price}, 方向: {add_direction}, 大小: {order_size_usdt} USDT")
                        exchange_order = self.trading_engine.place_order(
                            symbol=symbol,
                            side='buy' if add_direction == 'long' else 'sell',
                            order_type='limit',
                            amount=order_size_usdt / add_price, 
                            price=add_price
                        )

                        if exchange_order:
                            self.risk_manager.add_position(
                                symbol=symbol,
                                direction=add_direction,
                                entry_price=add_price,
                                size=order_size_usdt,
                                stop_loss_price=stop_loss_price,
                                take_profit_price=take_profit_price,
                                exchange_order_id=exchange_order.get('id')
                            )
                            if self.config.get('notification.notify_on_trade', True):
                                self.telegram_notifier.send_trade_notification(
                                    trade_type="add", 
                                    symbol=symbol,
                                    direction=add_direction,
                                    price=add_price,
                                    amount=order_size_usdt,
                                    stop_loss=stop_loss_price,
                                    take_profit=take_profit_price
                                )
                        
        except Exception as e:
            trading_logger.error(f"持仓检查错误: {str(e)}", exc_info=True)
            if self.config.get('notification.notify_on_error', True):
                self.telegram_notifier.send_error_notification(
                    "持仓检查错误", 
                    f"检查持仓失败: {str(e)}"
                )
    
    def _can_add_new_order_for_symbol(self, symbol: str, trend_data: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        """
        检查是否可以为指定交易对进行循环加仓（即开设一个新的独立订单）
        """
        current_orders_for_symbol = self.risk_manager.positions.get(symbol, [])
        if len(current_orders_for_symbol) >= self.max_orders_per_symbol:
            return False, None

        if not current_orders_for_symbol:
            return False, None
        
        assumed_symbol_direction = current_orders_for_symbol[0]['direction']

        trend_confirmed, current_trend_direction = self.trend_analyzer.analyze_trend(trend_data)
        
        if not trend_confirmed or current_trend_direction != assumed_symbol_direction:
            trading_logger.info(f"{symbol} 当前趋势 ({current_trend_direction}, confirmed={trend_confirmed}) 与持仓方向 ({assumed_symbol_direction}) 不符或趋势未确认，不加仓")
            return False, None

        last_order_time = current_orders_for_symbol[-1]['entry_time']
        time_since_last_order_minutes = (datetime.now() - last_order_time).total_seconds() / 60
        
        if time_since_last_order_minutes < self.add_position_interval:
            return False, None
        
        if not self.risk_manager.can_open_position(symbol, current_trend_direction, trend_data['close'].iloc[-1], 
                                                 existing_orders_count=len(current_orders_for_symbol), 
                                                 max_orders_per_symbol=self.max_orders_per_symbol):
            trading_logger.info(f"{symbol} 未通过 RiskManager 的开仓条件检查 (日亏损或订单数已达上限)，不加仓")
            return False, None

        trading_logger.info(f"{symbol} 满足所有循环加仓条件，方向: {current_trend_direction}")
        return True, current_trend_direction
            
    def _generate_daily_report(self):
        """生成每日报告"""
        try:
            trades = self.risk_manager.trades
            self.performance_analyzer.trades = [] 
            for trade in trades:
                self.performance_analyzer.add_trade(trade)
                
            report = self.performance_analyzer.generate_report('reports')
            trading_logger.info(f"生成每日报告:\n{report}")
            
            if self.config.get('notification.notify_on_status', True):
                self.telegram_notifier._send_msg(
                    f"📊 *每日性能报告*\n\n{report}"
                )
            
            self.risk_manager.reset_daily_stats()
            
        except Exception as e:
            trading_logger.error(f"生成报告错误: {str(e)}", exc_info=True)
            if self.config.get('notification.notify_on_error', True):
                self.telegram_notifier.send_error_notification(
                    "报告生成错误", 
                    f"生成每日报告失败: {str(e)}"
                )
    
    def stop(self):
        """停止交易系统，并尝试平掉所有持仓的独立订单"""
        trading_logger.info("正在停止交易系统...")
        if self.config.get('notification.notify_on_status', True):
            self.telegram_notifier.send_error_notification("系统关闭中", "CryptoPulse Trader 正在关闭，将尝试平掉所有持仓订单...")

        if self.telegram_notifier and hasattr(self.telegram_notifier, 'updater') and self.telegram_notifier.updater:
            self.telegram_notifier.updater.stop()
            trading_logger.info("Telegram机器人轮询已停止")
        
        try:
            active_symbols_to_close = list(self.risk_manager.positions.keys())
            trading_logger.info(f"系统关闭：准备平仓 {len(active_symbols_to_close)} 个交易对下的所有独立订单。")

            for symbol in active_symbols_to_close:
                if symbol in self.risk_manager.positions:
                    orders_for_symbol = list(self.risk_manager.positions[symbol]) 
                    trading_logger.info(f"正在处理交易对 {symbol}，有 {len(orders_for_symbol)} 个独立订单待平仓。")
                    
                    for order_details in orders_for_symbol:
                        order_id = order_details['id']
                        order_direction = order_details['direction']
                        order_size_usdt = order_details['size']
                        
                        trading_logger.info(f"准备平仓订单 {order_id} ({symbol})...")
                        current_price = self.data_fetcher.get_current_price(symbol)
                        if current_price is None:
                            trading_logger.error(f"无法获取 {symbol} 的价格以平仓订单 {order_id}，跳过此订单。")
                            if self.config.get('notification.notify_on_error', True):
                                self.telegram_notifier.send_error_notification(
                                    "平仓失败(关机)", 
                                    f"无法获取 {symbol} 价格以平仓订单 {order_id}。"
                                )
                            continue
                        
                        amount_to_close_base = order_size_usdt / current_price
                        
                        exchange_order = self.trading_engine.place_order(
                            symbol=symbol,
                            side='sell' if order_direction == 'long' else 'buy',
                            order_type='market', 
                            amount=amount_to_close_base,
                            price=None 
                        )
                        
                        if exchange_order:
                            closed_log = self.risk_manager.close_position(symbol, order_id, current_price, 'shutdown')
                            if closed_log and self.config.get('notification.notify_on_trade', True):
                                trading_logger.info(f"订单 {order_id} ({symbol}) 已在系统关闭过程中平仓。")
                                self.telegram_notifier.send_error_notification(
                                    "订单已平仓(关机)", 
                                    f"订单 {order_id} ({symbol}) 已于系统关闭时平仓。盈亏: {closed_log.get('pnl_percentage', 0):.2f}%"
                                )
                            else:
                                trading_logger.error(f"尝试记录订单 {order_id} ({symbol}) 平仓失败(RiskManager)。")
                        else:
                            trading_logger.error(f"交易所未能确认订单 {order_id} ({symbol}) 的平仓。")
                            if self.config.get('notification.notify_on_error', True):
                                self.telegram_notifier.send_error_notification(
                                    "交易所平仓失败(关机)", 
                                    f"订单 {order_id} ({symbol}) 在交易所的平仓未能确认。"
                                )
        except Exception as e:
            trading_logger.error(f"停止系统时平仓所有订单失败: {str(e)}", exc_info=True)
            if self.config.get('notification.notify_on_error', True):
                self.telegram_notifier.send_error_notification("关机错误", f"平仓所有订单时发生严重错误: {str(e)}")
            
        if self.telegram_notifier:
             self.telegram_notifier.stop() 

        trading_logger.info("交易系统已停止")

if __name__ == '__main__':
    trader = CryptoPulseTrader()
    try:
        trader.run()
    except KeyboardInterrupt:
        trader.stop()
    except Exception as e:
        trading_logger.critical(f"系统发生致命错误并退出: {str(e)}", exc_info=True) 
        if hasattr(trader, 'telegram_notifier') and trader.telegram_notifier and trader.config.get('notification.notify_on_error', True):
            trader.telegram_notifier.send_error_notification("系统致命错误", f"系统因严重错误而停止: {str(e)}")
        if hasattr(trader, 'stop'):
            trader.stop() 