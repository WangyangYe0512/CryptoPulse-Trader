import os
import asyncio
import ccxt.async_support as ccxt
from typing import Dict, Optional, Set, List
from utils.logger import trading_logger
from utils.config_manager import ConfigManager

class BinanceExecutor:
    """币安交易执行器 (Refactored for CCXT)"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.testnet = config.get('api.binance.testnet', True)
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            raise ValueError("Binance API Key or Secret not found in environment variables (BINANCE_API_KEY, BINANCE_API_SECRET)")

        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True, 
            'timeout': 30000,  # 设置30秒超时（默认10秒可能不够）
            'rateLimit': 1200,  # 每分钟最多50次请求
            'options': {
                'defaultType': 'future',  # 修复：必须设置为合约模式才能访问合约账户
                'recvWindow': 10000,  # 10秒接收窗口
            }
        })

        if self.testnet:
            self.exchange.set_sandbox_mode(True) 
            trading_logger.info("BinanceExecutor (CCXT) configured for Futures Testnet.")
        else:
            trading_logger.info("BinanceExecutor (CCXT) configured for Futures Live.")
        
        self.markets_loaded = False
        trading_logger.info("BinanceExecutor (CCXT) initialized with 30s timeout and enhanced stability settings.")
        
    async def ensure_markets_loaded(self, reload_if_needed=False):
        if not self.markets_loaded or reload_if_needed:
            try:
                trading_logger.info(f"Attempting to load CCXT markets (Reload: {reload_if_needed})...")
                await self.exchange.load_markets(reload=reload_if_needed)
                self.markets_loaded = True
                trading_logger.info(f"CCXT markets loaded successfully (Reloaded: {reload_if_needed}).")
            except Exception as e:
                self.markets_loaded = False 
                trading_logger.error(f"Failed to load CCXT markets: {e}", exc_info=True)
                raise 

    async def check_connection(self):
        try:
            await self.ensure_markets_loaded()
            balance = await self.exchange.fetch_balance(params={}) 
            usdt_balance = balance.get('USDT', {})
            free_usdt = usdt_balance.get('free', 'N/A')
            trading_logger.info(f"Successfully connected to Binance (CCXT). USDT Available: {free_usdt}")
        except Exception as e:
            trading_logger.error(f"Failed to connect or fetch balance via CCXT: {e}", exc_info=True)

    async def get_current_price(self, symbol: str) -> Optional[float]:
        try:
            await self.ensure_markets_loaded()
            # Ensure symbol is in CCXT format (e.g., BTC/USDT)
            # self.exchange.market_id(symbol) can convert from 'BTCUSDT' to 'BTC/USDT' if markets are loaded
            # but it might throw an error if symbol is already BTC/USDT. CCXT often handles both if symbol is unique.
            ccxt_symbol = symbol
            if '/' not in symbol:
                try:
                    market = self.exchange.market(symbol) # Tries to find by ID e.g. BTCUSDT
                    ccxt_symbol = market['symbol'] # Gets the unified symbol e.g. BTC/USDT
                except (ccxt.ExchangeError, ccxt.BadSymbol) as e:
                    trading_logger.warning(f"Could not find market by ID {symbol}, trying as is: {e}")
                    # Fallback to using symbol as is, fetch_ticker might still resolve it
            
            ticker = await self.exchange.fetch_ticker(ccxt_symbol)
            return float(ticker['last'])
        except ccxt.NetworkError as e:
            trading_logger.error(f"CCXT NetworkError fetching price for {symbol} ({ccxt_symbol}): {e}")
            return None
        except ccxt.ExchangeError as e:
            trading_logger.error(f"CCXT ExchangeError fetching price for {symbol} ({ccxt_symbol}): {e}")
            return None
        except Exception as e:
            trading_logger.error(f"Error fetching price for {symbol} ({ccxt_symbol}) via CCXT: {e}", exc_info=True)
            return None

    async def get_symbol_market_info(self, symbol: str) -> Optional[Dict]:
        try:
            await self.ensure_markets_loaded()
            ccxt_symbol = symbol
            if '/' not in symbol:
                try:
                    market_lookup = self.exchange.market(symbol)
                    ccxt_symbol = market_lookup['symbol']
                except (ccxt.ExchangeError, ccxt.BadSymbol) as e:
                    trading_logger.warning(f"Could not find market by ID {symbol} for market_info, trying as is: {e}")

            market = self.exchange.market(ccxt_symbol) # This should now work if ccxt_symbol is unified
            return market
        except ccxt.NetworkError as e:
            trading_logger.error(f"CCXT NetworkError fetching market info for {symbol} ({ccxt_symbol}): {e}")
            return None
        except ccxt.ExchangeError as e:
            trading_logger.error(f"CCXT ExchangeError fetching market info for {symbol} ({ccxt_symbol}): {e}")
            return None
        except Exception as e:
            trading_logger.error(f"Error fetching market info for {symbol} ({ccxt_symbol}) via CCXT: {e}", exc_info=True)
            return None

    def format_quantity(self, symbol: str, quantity_raw: float) -> Optional[float]:
        try:
            if not self.markets_loaded:
                 trading_logger.warning("format_quantity called when markets might not be loaded. Ensure ensure_markets_loaded() was awaited prior.")
            
            ccxt_symbol = symbol
            if '/' not in symbol and self.markets_loaded: # Only try to convert if markets loaded
                try:
                    market = self.exchange.market(symbol)
                    ccxt_symbol = market['symbol']
                except (ccxt.ExchangeError, ccxt.BadSymbol):
                    pass # Use original symbol if market ID lookup fails

            formatted_qty_str = self.exchange.amount_to_precision(ccxt_symbol, quantity_raw)
            return float(formatted_qty_str)
        except Exception as e:
            trading_logger.error(f"Error formatting quantity for {symbol} ({ccxt_symbol}, raw: {quantity_raw}): {e}", exc_info=True)
            return None
            
    def format_price(self, symbol: str, price_raw: float) -> Optional[float]:
        try: 
            if not self.markets_loaded:
                trading_logger.warning("format_price called when markets might not be loaded. Ensure ensure_markets_loaded() was awaited prior.")
            
            ccxt_symbol = symbol
            if '/' not in symbol and self.markets_loaded:
                try:
                    market = self.exchange.market(symbol)
                    ccxt_symbol = market['symbol']
                except (ccxt.ExchangeError, ccxt.BadSymbol):
                    pass
            
            formatted_price_str = self.exchange.price_to_precision(ccxt_symbol, price_raw)
            return float(formatted_price_str)
        except Exception as e:
            trading_logger.error(f"Error formatting price for {symbol} ({ccxt_symbol}, raw: {price_raw}): {e}", exc_info=True)
            return None

    async def set_leverage(self, symbol: str, leverage: int = None) -> bool:
        """设置指定交易对的杠杆倍数，失败时返回是否可以继续交易"""
        try:
            await self.ensure_markets_loaded()
            
            # 确定要设置的杠杆倍数
            if leverage is None:
                # 从配置中获取默认杠杆或币种特定杠杆
                symbol_specific_leverage = self.config.get(f'leverage.symbol_specific.{symbol}')
                leverage = symbol_specific_leverage or self.config.get('leverage.default', 5)
            
            # 检查杠杆倍数限制
            max_allowed = self.config.get('leverage.max_allowed', 20)
            if leverage > max_allowed:
                trading_logger.warning(f"Requested leverage {leverage} exceeds max allowed {max_allowed} for {symbol}. Using max allowed.")
                leverage = max_allowed
            
            trading_logger.info(f"Setting leverage to {leverage}x for {symbol}")
            
            # 使用CCXT设置杠杆
            result = await self.exchange.set_leverage(leverage, symbol)
            trading_logger.info(f"Leverage set successfully for {symbol}: {leverage}x")
            return True
            
        except ccxt.NetworkError as e:
            trading_logger.error(f"Network error setting leverage for {symbol}: {e}")
            return await self._handle_leverage_set_failure(symbol, leverage)
        except ccxt.ExchangeError as e:
            trading_logger.error(f"Exchange error setting leverage for {symbol}: {e}")
            return await self._handle_leverage_set_failure(symbol, leverage)
        except Exception as e:
            trading_logger.error(f"Unexpected error setting leverage for {symbol}: {e}", exc_info=True)
            return await self._handle_leverage_set_failure(symbol, leverage)

    async def _handle_leverage_set_failure(self, symbol: str, target_leverage: int) -> bool:
        """处理杠杆设置失败的情况"""
        try:
            # 获取当前杠杆
            current_leverage = await self.get_current_leverage(symbol)
            
            if current_leverage is not None:
                trading_logger.info(f"Current leverage for {symbol}: {current_leverage}x (target was {target_leverage}x)")
                
                # 检查当前杠杆是否在可接受范围内
                min_acceptable = self.config.get('leverage.min_acceptable', 1)
                max_acceptable = self.config.get('leverage.max_allowed', 20)
                
                if min_acceptable <= current_leverage <= max_acceptable:
                    trading_logger.warning(f"Using current leverage {current_leverage}x for {symbol} (target {target_leverage}x failed)")
                    return True
                else:
                    trading_logger.error(f"Current leverage {current_leverage}x for {symbol} is outside acceptable range {min_acceptable}-{max_acceptable}x")
                    return False
            else:
                trading_logger.warning(f"Could not determine current leverage for {symbol}, assuming safe default")
                # 无法获取当前杠杆，但允许继续（可能是新交易对）
                return True
                
        except Exception as e:
            trading_logger.error(f"Error handling leverage set failure for {symbol}: {e}")
            # 保守处理：如果无法确定状态，允许继续但记录错误
            return True

    async def get_current_leverage(self, symbol: str) -> Optional[int]:
        """获取当前杠杆倍数。在没有持仓时，可能返回None。"""
        try:
            await self.ensure_markets_loaded()
            
            # 先尝试从持仓信息获取杠杆倍数
            positions = await self.exchange.fetch_positions([symbol])
            if positions:
                position = positions[0]
                current_leverage = position.get('leverage')
                if current_leverage:
                    trading_logger.debug(f"Current leverage for {symbol}: {current_leverage}x")
                    return int(float(current_leverage))
            
            # 如果没有持仓，尝试从账户设置获取
            account = await self.exchange.fetch_trading_fees()
            # 有些交易所在账户信息中包含杠杆设置
            return None
            
        except Exception as e:
            trading_logger.error(f"Error fetching current leverage for {symbol}: {e}")
            return None

    async def set_margin_type(self, symbol: str, margin_type: str = 'ISOLATED') -> bool:
        """设置币种的保证金模式（ISOLATED/CROSSED）"""
        try:
            trading_logger.info(f"Setting margin type to {margin_type} for {symbol}")
            
            # 将CCXT符号转换为Binance原始格式
            binance_symbol = symbol
            if '/' in symbol:
                # 从 'TRX/USDT:USDT' 转换为 'TRXUSDT'
                base_quote = symbol.split(':')[0]  # 去掉结算货币部分
                binance_symbol = base_quote.replace('/', '')
            trading_logger.debug(f"Converted symbol {symbol} to Binance format: {binance_symbol}")
            
            # 对于Binance期货，使用特定的API设置保证金模式
            if hasattr(self.exchange, 'fapiPrivatePostMarginType'):
                params = {
                    'symbol': binance_symbol,
                    'marginType': margin_type
                }
                result = await self.exchange.fapiPrivatePostMarginType(params)
                trading_logger.info(f"Successfully set margin type to {margin_type} for {binance_symbol}: {result}")
                return True
            else:
                # 使用CCXT标准方法（如果支持）
                try:
                    result = await self.exchange.set_margin_mode(margin_type.lower(), symbol)
                    trading_logger.info(f"Successfully set margin type to {margin_type} for {symbol} via CCXT: {result}")
                    return True
                except AttributeError:
                    trading_logger.warning(f"Exchange {self.exchange.id} does not support margin type setting via CCXT")
                    return False
                    
        except Exception as e:
            error_msg = str(e).lower()
            
            # 检查是否是因为已经是正确的保证金模式
            if 'no need to change margin type' in error_msg or 'margin type is already' in error_msg:
                trading_logger.info(f"Margin type for {symbol} is already {margin_type}")
                return True
            
            # 检查是否是因为有持仓无法更改
            if 'position exists' in error_msg or 'cannot change margin type' in error_msg:
                trading_logger.warning(f"Cannot change margin type for {symbol} due to existing position: {e}")
                # 在有持仓的情况下，我们假设当前模式是可接受的
                return True
                
            trading_logger.error(f"Failed to set margin type to {margin_type} for {symbol}: {e}")
            return False

    # <<< Placeholder for NEW CCXT-based order methods >>>
    async def execute_signal(self, signal: Dict) -> Optional[Dict]:
        """Executes a trading signal using CCXT."""
        signal_type = signal.get('type')  # 修复：策略生成的信号字典使用'type'而不是'signal_type'
        symbol_from_signal = signal.get('symbol') 
        
        if not symbol_from_signal:
            trading_logger.error("Signal missing symbol.")
            return {"status": "error", "message": "Signal missing symbol"}

        ccxt_symbol = symbol_from_signal
        if '/' not in symbol_from_signal:
            try:
                await self.ensure_markets_loaded() 
                market_details = self.exchange.market(symbol_from_signal) 
                ccxt_symbol = market_details['symbol'] 
                trading_logger.debug(f"Normalized symbol {symbol_from_signal} to {ccxt_symbol}")
            except (ccxt.ExchangeError, ccxt.BadSymbol) as e:
                trading_logger.error(f"Could not normalize symbol {symbol_from_signal} to CCXT format: {e}. Using as is.")
        
        amount_usdt = signal.get('position_size_usdt', self.config.get('strategy.trend_following.position_size_usdt', 10.0))
        trading_logger.info(f"Executor received signal: {signal_type} for {ccxt_symbol} (original: {symbol_from_signal}) with amount {amount_usdt} USDT")

        try:
            if signal_type == 'OPEN_LONG':
                return await self.create_long_order_with_sl_tp(ccxt_symbol, amount_usdt)
            elif signal_type == 'OPEN_SHORT':
                return await self.create_short_order_with_sl_tp(ccxt_symbol, amount_usdt)
            elif signal_type == 'CLOSE_LONG_POSITIONS': 
                closed = await self.close_all_long_positions_for_symbol(ccxt_symbol)
                return {"status": "success", "message": f"Attempted to close long for {ccxt_symbol}", "closed_operation_result": closed} 
            elif signal_type == 'CLOSE_SHORT_POSITIONS': 
                closed = await self.close_all_short_positions_for_symbol(ccxt_symbol)
                return {"status": "success", "message": f"Attempted to close short for {ccxt_symbol}", "closed_operation_result": closed}
            elif signal_type == 'SIGNAL_TYPE_CLOSE_LONG_POSITIONS': 
                closed = await self.close_all_long_positions_for_symbol(ccxt_symbol)
                return {"status": "success", "message": f"Attempted to close long for {ccxt_symbol}", "closed_operation_result": closed} 
            elif signal_type == 'SIGNAL_TYPE_CLOSE_SHORT_POSITIONS': 
                closed = await self.close_all_short_positions_for_symbol(ccxt_symbol)
                return {"status": "success", "message": f"Attempted to close short for {ccxt_symbol}", "closed_operation_result": closed}
            else:
                trading_logger.warning(f"Unsupported signal_type: {signal_type}")
                return {"status": "error", "message": f"Unsupported signal_type: {signal_type}"}
        except Exception as e:
            trading_logger.error(f"Error executing signal {signal_type} for {ccxt_symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def create_long_order_with_sl_tp(self, symbol: str, amount_usdt: float) -> Optional[Dict]:
        trading_logger.info(f"Attempting to create LONG order for {symbol}, amount: {amount_usdt} USDT")
        try:
            await self.ensure_markets_loaded()
            # symbol is assumed to be in CCXT format (e.g., BTC/USDT) due to execute_signal normalization
            ccxt_symbol = symbol
            
            # 设置逐仓模式（在开仓前）
            use_isolated = self.config.get('trading.order.use_isolated_margin', True)
            if use_isolated:
                margin_ok = await self.set_margin_type(ccxt_symbol, 'ISOLATED')
                if not margin_ok:
                    trading_logger.warning(f"Failed to set isolated margin for {ccxt_symbol}, continuing with current margin mode")
            
            # 设置杠杆倍数（在开仓前）
            leverage_ok = await self.set_leverage(ccxt_symbol)
            if not leverage_ok:
                trading_logger.error(f"Leverage setting failed for {ccxt_symbol} and current leverage is unacceptable. Aborting LONG trade.")
                return {"status": "error", "message": f"Unacceptable leverage for {ccxt_symbol}", "code": "leverage_error"}
            
            # 清理该币种的所有旧订单（单向模式下防止孤儿订单）
            trading_logger.info(f"Cleaning up existing orders for {ccxt_symbol} before opening LONG position")
            try:
                await self.exchange.cancel_all_orders(ccxt_symbol)
                trading_logger.info(f"Successfully cancelled existing orders for {ccxt_symbol}")
            except Exception as cleanup_error:
                trading_logger.warning(f"Failed to cleanup orders for {ccxt_symbol}: {cleanup_error}") 

            current_price = await self.get_current_price(ccxt_symbol)
            if not current_price:
                trading_logger.error(f"Could not fetch current price for {ccxt_symbol} to create LONG order.")
                return {"status": "error", "message": f"No price for {ccxt_symbol}", "code": "price_fetch_failed"}

            quantity = amount_usdt / current_price
            formatted_quantity = self.format_quantity(ccxt_symbol, quantity)
            
            if not formatted_quantity or formatted_quantity <= 0:
                trading_logger.error(f"Invalid or zero quantity ({formatted_quantity}) for {ccxt_symbol} with amount {amount_usdt} USDT at price {current_price}.")
                min_qty = self.exchange.markets[ccxt_symbol].get('limits', {}).get('amount', {}).get('min')
                return {"status": "error", "message": f"Invalid quantity {formatted_quantity}. Min Qty: {min_qty}", "code": "invalid_quantity"}

            sl_percentage = self.config.get('trading.order.stop_loss_percentage', 1.0)  
            tp_percentage = self.config.get('trading.order.take_profit_percentage', 2.0) 

            trading_logger.info(f"Placing MARKET LONG order for {formatted_quantity} {ccxt_symbol} at ~{current_price}")
            
            # 创建订单（逐仓模式已在前面设置）
            entry_order = await self.exchange.create_order(ccxt_symbol, 'market', 'buy', formatted_quantity)
            trading_logger.info(f"LONG Entry order attempt: ID {entry_order.get('id')}, Status {entry_order.get('status')}, Avg Price {entry_order.get('average')}, Filled {entry_order.get('filled')}")
            
            actual_entry_price = current_price # Default to pre-fetched price
            # CCXT unified order structure: 'average' is the filled price, 'status' is 'closed' when fully filled for market orders.
            if entry_order.get('average') is not None and entry_order.get('status') == 'closed':
                actual_entry_price = entry_order['average']
            elif entry_order.get('price') is not None and entry_order.get('status') == 'closed': # Some exchanges might use 'price' for filled market orders
                actual_entry_price = entry_order['price']
            elif entry_order.get('filled', 0) > 0: # If partially filled, try to use average if available
                 if entry_order.get('average') is not None:
                    actual_entry_price = entry_order['average']
                 trading_logger.warning(f"Entry order {entry_order.get('id')} for {ccxt_symbol} may be partially filled ({entry_order.get('filled')}/{entry_order.get('amount')}). Using fill price {actual_entry_price} for SL/TP.")
            else:
                trading_logger.warning(f"Entry order {entry_order.get('id')} for {ccxt_symbol} not confirmed filled or average price missing. Order status: {entry_order.get('status')}. Using estimated entry price {actual_entry_price} for SL/TP calcs.")

            sl_price = actual_entry_price * (1 - sl_percentage / 100)
            tp_price = actual_entry_price * (1 + tp_percentage / 100)

            formatted_sl_price = self.format_price(ccxt_symbol, sl_price)
            formatted_tp_price = self.format_price(ccxt_symbol, tp_price)

            if not formatted_sl_price or not formatted_tp_price:
                trading_logger.error(f"Could not format SL/TP prices for {ccxt_symbol}. SL raw: {sl_price}, TP raw: {tp_price}. Entry order {entry_order.get('id')} placed.")
                return {"entry_order": entry_order, "sl_tp_error": "Formatting SL/TP price failed", "status": "partial_success", "code": "sl_tp_format_error"}
            
            sl_order_response = None
            tp_order_response = None
            sl_tp_errors = []

            # Use the amount from the filled entry order for SL/TP if available and > 0
            sl_tp_quantity = formatted_quantity # Default to original formatted quantity
            if entry_order.get('filled') and entry_order['filled'] > 0:
                sl_tp_quantity = entry_order['filled']
                trading_logger.info(f"Using filled quantity {sl_tp_quantity} from entry order for SL/TP.")
            elif entry_order.get('status') != 'closed':
                 trading_logger.warning(f"Entry order {entry_order.get('id')} not 'closed' (status: {entry_order.get('status')}). SL/TP will use originally calculated quantity {sl_tp_quantity}. This might lead to issues if entry was partially filled or failed.")

            if sl_tp_quantity <=0:
                trading_logger.error(f"SL/TP quantity is {sl_tp_quantity} for {ccxt_symbol} after entry order {entry_order.get('id')}. Cannot place SL/TP.")
                return {"entry_order": entry_order, "sl_tp_error": "SL/TP quantity is zero or negative", "status": "partial_success", "code": "sl_tp_zero_quantity"}

            try:
                trading_logger.info(f"Placing SL order for LONG {sl_tp_quantity} {ccxt_symbol} at {formatted_sl_price}")
                sl_params = {'stopPrice': formatted_sl_price, 'reduceOnly': True}  # 单向模式不需要positionSide
                sl_order_response = await self.exchange.create_order(ccxt_symbol, 'STOP_MARKET', 'sell', sl_tp_quantity, params=sl_params)
                trading_logger.info(f"SL order placed: ID {sl_order_response.get('id')}, Status {sl_order_response.get('status')}")
            except Exception as e_sl:
                error_msg = f"Failed to place SL order for {ccxt_symbol} (entry {entry_order.get('id')}): {e_sl}"
                trading_logger.error(error_msg, exc_info=True)
                sl_tp_errors.append({"type": "SL", "error": str(e_sl)})

            try:
                trading_logger.info(f"Placing TP order for LONG {sl_tp_quantity} {ccxt_symbol} at {formatted_tp_price}")
                tp_params = {'stopPrice': formatted_tp_price, 'reduceOnly': True}  # 单向模式不需要positionSide
                tp_order_response = await self.exchange.create_order(ccxt_symbol, 'TAKE_PROFIT_MARKET', 'sell', sl_tp_quantity, params=tp_params)
                trading_logger.info(f"TP order placed: ID {tp_order_response.get('id')}, Status {tp_order_response.get('status')}")
            except Exception as e_tp:
                error_msg = f"Failed to place TP order for {ccxt_symbol} (entry {entry_order.get('id')}): {e_tp}"
                trading_logger.error(error_msg, exc_info=True)
                sl_tp_errors.append({"type": "TP", "error": str(e_tp)})

            final_status = "success"
            if sl_tp_errors:
                final_status = "partial_success"
                # Provide more detail on which one failed
                if not sl_order_response and not tp_order_response:
                    final_status = "partial_success_sl_and_tp_failed"
                elif not sl_order_response:
                    final_status = "partial_success_sl_failed"
                elif not tp_order_response:
                    final_status = "partial_success_tp_failed"
            
            # Ensure entry_order is serializable (it usually is from CCXT)
            return {
                "entry_order": entry_order, 
                "sl_order": sl_order_response, 
                "tp_order": tp_order_response, 
                "status": final_status,
                "sl_tp_errors": sl_tp_errors if sl_tp_errors else None,
                "code": "long_order_processed"
            }

        except ccxt.InsufficientFunds as e:
            trading_logger.error(f"Insufficient funds for LONG order {symbol} ({amount_usdt} USDT): {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "insufficient_funds"}
        except ccxt.InvalidOrder as e: # More specific error for issues like min notional, min quantity
            trading_logger.error(f"Invalid LONG order for {symbol} ({amount_usdt} USDT): {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "invalid_order"}
        except ccxt.NetworkError as e:
            trading_logger.error(f"Network error creating LONG order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "network_error"}
        except ccxt.ExchangeError as e:
            trading_logger.error(f"Exchange error creating LONG order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "exchange_error"}
        except Exception as e:
            trading_logger.error(f"Unexpected error creating LONG order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "unexpected_error"}

    async def create_short_order_with_sl_tp(self, symbol: str, amount_usdt: float) -> Optional[Dict]:
        trading_logger.info(f"Attempting to create SHORT order for {symbol}, amount: {amount_usdt} USDT")
        try:
            await self.ensure_markets_loaded()
            ccxt_symbol = symbol # Assumed to be normalized by execute_signal
            
            # 设置逐仓模式（在开仓前）
            use_isolated = self.config.get('trading.order.use_isolated_margin', True)
            if use_isolated:
                margin_ok = await self.set_margin_type(ccxt_symbol, 'ISOLATED')
                if not margin_ok:
                    trading_logger.warning(f"Failed to set isolated margin for {ccxt_symbol}, continuing with current margin mode")
            
            # 设置杠杆倍数（在开仓前）
            leverage_ok = await self.set_leverage(ccxt_symbol)
            if not leverage_ok:
                trading_logger.error(f"Leverage setting failed for {ccxt_symbol} and current leverage is unacceptable. Aborting SHORT trade.")
                return {"status": "error", "message": f"Unacceptable leverage for {ccxt_symbol}", "code": "leverage_error"}
            
            # 清理该币种的所有旧订单（单向模式下防止孤儿订单）
            trading_logger.info(f"Cleaning up existing orders for {ccxt_symbol} before opening SHORT position")
            try:
                await self.exchange.cancel_all_orders(ccxt_symbol)
                trading_logger.info(f"Successfully cancelled existing orders for {ccxt_symbol}")
            except Exception as cleanup_error:
                trading_logger.warning(f"Failed to cleanup orders for {ccxt_symbol}: {cleanup_error}")

            current_price = await self.get_current_price(ccxt_symbol)
            if not current_price:
                trading_logger.error(f"Could not fetch current price for {ccxt_symbol} to create SHORT order.")
                return {"status": "error", "message": f"No price for {ccxt_symbol}", "code": "price_fetch_failed"}

            quantity = amount_usdt / current_price
            formatted_quantity = self.format_quantity(ccxt_symbol, quantity)
            
            if not formatted_quantity or formatted_quantity <= 0:
                trading_logger.error(f"Invalid or zero quantity ({formatted_quantity}) for {ccxt_symbol} with amount {amount_usdt} USDT at price {current_price}.")
                min_qty = self.exchange.markets[ccxt_symbol].get('limits', {}).get('amount', {}).get('min')
                return {"status": "error", "message": f"Invalid quantity {formatted_quantity}. Min Qty: {min_qty}", "code": "invalid_quantity"}

            sl_percentage = self.config.get('trading.order.stop_loss_percentage', 1.0)
            tp_percentage = self.config.get('trading.order.take_profit_percentage', 2.0)

            trading_logger.info(f"Placing MARKET SHORT order for {formatted_quantity} {ccxt_symbol} at ~{current_price}")
            
            # 创建订单（逐仓模式已在前面设置）
            entry_order = await self.exchange.create_order(ccxt_symbol, 'market', 'sell', formatted_quantity)
            trading_logger.info(f"SHORT Entry order attempt: ID {entry_order.get('id')}, Status {entry_order.get('status')}, Avg Price {entry_order.get('average')}, Filled {entry_order.get('filled')}")

            actual_entry_price = current_price
            if entry_order.get('average') is not None and entry_order.get('status') == 'closed':
                actual_entry_price = entry_order['average']
            elif entry_order.get('price') is not None and entry_order.get('status') == 'closed':
                actual_entry_price = entry_order['price']
            elif entry_order.get('filled', 0) > 0:
                 if entry_order.get('average') is not None:
                    actual_entry_price = entry_order['average']
                 trading_logger.warning(f"Entry order {entry_order.get('id')} for {ccxt_symbol} may be partially filled ({entry_order.get('filled')}/{entry_order.get('amount')}). Using fill price {actual_entry_price} for SL/TP.")
            else:
                trading_logger.warning(f"Entry order {entry_order.get('id')} for {ccxt_symbol} not confirmed filled or average price missing. Order status: {entry_order.get('status')}. Using estimated entry price {actual_entry_price} for SL/TP calcs.")

            # SL/TP calculation for SHORT position
            sl_price = actual_entry_price * (1 + sl_percentage / 100)
            tp_price = actual_entry_price * (1 - tp_percentage / 100)

            formatted_sl_price = self.format_price(ccxt_symbol, sl_price)
            formatted_tp_price = self.format_price(ccxt_symbol, tp_price)

            if not formatted_sl_price or not formatted_tp_price:
                trading_logger.error(f"Could not format SL/TP prices for SHORT {ccxt_symbol}. SL raw: {sl_price}, TP raw: {tp_price}. Entry order {entry_order.get('id')} placed.")
                return {"entry_order": entry_order, "sl_tp_error": "Formatting SL/TP price failed", "status": "partial_success", "code": "sl_tp_format_error"}

            sl_order_response = None
            tp_order_response = None
            sl_tp_errors = []

            sl_tp_quantity = formatted_quantity
            if entry_order.get('filled') and entry_order['filled'] > 0:
                sl_tp_quantity = entry_order['filled']
                trading_logger.info(f"Using filled quantity {sl_tp_quantity} from SHORT entry order for SL/TP.")
            elif entry_order.get('status') != 'closed':
                 trading_logger.warning(f"SHORT Entry order {entry_order.get('id')} not 'closed' (status: {entry_order.get('status')}). SL/TP will use originally calculated quantity {sl_tp_quantity}.")

            if sl_tp_quantity <= 0:
                trading_logger.error(f"SL/TP quantity is {sl_tp_quantity} for SHORT {ccxt_symbol} after entry order {entry_order.get('id')}. Cannot place SL/TP.")
                return {"entry_order": entry_order, "sl_tp_error": "SL/TP quantity is zero or negative", "status": "partial_success", "code": "sl_tp_zero_quantity"}

            try:
                trading_logger.info(f"Placing SL order for SHORT {sl_tp_quantity} {ccxt_symbol} at {formatted_sl_price}")
                sl_params = {'stopPrice': formatted_sl_price, 'reduceOnly': True}  # 单向模式不需要positionSide
                sl_order_response = await self.exchange.create_order(ccxt_symbol, 'STOP_MARKET', 'buy', sl_tp_quantity, params=sl_params)
                trading_logger.info(f"SL order (for short) placed: ID {sl_order_response.get('id')}, Status {sl_order_response.get('status')}")
            except Exception as e_sl:
                error_msg = f"Failed to place SL order for SHORT {ccxt_symbol} (entry {entry_order.get('id')}): {e_sl}"
                trading_logger.error(error_msg, exc_info=True)
                sl_tp_errors.append({"type": "SL", "error": str(e_sl)})

            try:
                trading_logger.info(f"Placing TP order for SHORT {sl_tp_quantity} {ccxt_symbol} at {formatted_tp_price}")
                tp_params = {'stopPrice': formatted_tp_price, 'reduceOnly': True}  # 单向模式不需要positionSide
                tp_order_response = await self.exchange.create_order(ccxt_symbol, 'TAKE_PROFIT_MARKET', 'buy', sl_tp_quantity, params=tp_params)
                trading_logger.info(f"TP order (for short) placed: ID {tp_order_response.get('id')}, Status {tp_order_response.get('status')}")
            except Exception as e_tp:
                error_msg = f"Failed to place TP order for SHORT {ccxt_symbol} (entry {entry_order.get('id')}): {e_tp}"
                trading_logger.error(error_msg, exc_info=True)
                sl_tp_errors.append({"type": "TP", "error": str(e_tp)})

            final_status = "success"
            if sl_tp_errors:
                final_status = "partial_success"
                if not sl_order_response and not tp_order_response:
                    final_status = "partial_success_sl_and_tp_failed"
                elif not sl_order_response:
                    final_status = "partial_success_sl_failed"
                elif not tp_order_response:
                    final_status = "partial_success_tp_failed"

            return {
                "entry_order": entry_order,
                "sl_order": sl_order_response,
                "tp_order": tp_order_response,
                "status": final_status,
                "sl_tp_errors": sl_tp_errors if sl_tp_errors else None,
                "code": "short_order_processed"
            }

        except ccxt.InsufficientFunds as e:
            trading_logger.error(f"Insufficient funds for SHORT order {symbol} ({amount_usdt} USDT): {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "insufficient_funds"}
        except ccxt.InvalidOrder as e:
            trading_logger.error(f"Invalid SHORT order for {symbol} ({amount_usdt} USDT): {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "invalid_order"}
        except ccxt.NetworkError as e:
            trading_logger.error(f"Network error creating SHORT order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "network_error"}
        except ccxt.ExchangeError as e:
            trading_logger.error(f"Exchange error creating SHORT order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "exchange_error"}
        except Exception as e:
            trading_logger.error(f"Unexpected error creating SHORT order for {symbol}: {e}", exc_info=True)
            return {"status": "error", "message": str(e), "code": "unexpected_error"}

    async def close_all_positions_for_symbol_side(self, symbol: str, position_side: str) -> bool:
        """Closes all positions for a given symbol and side (LONG/SHORT) and cancels related orders."""
        # position_side is expected to be 'LONG' or 'SHORT'
        trading_logger.info(f"Attempting to close all {position_side} positions for {symbol}")
        try:
            await self.ensure_markets_loaded()
            ccxt_symbol = symbol # Assumed to be normalized by execute_signal

            # Fetch all positions for the specific symbol. 
            # Some exchanges allow filtering by symbol in fetch_positions, some return all and require client-side filtering.
            # CCXT aims to standardize: fetch_positions([ccxt_symbol]) should work for exchanges supporting it.
            # If not, fetch_positions() and then filter.
            
            positions = []
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Attempt to fetch for a single symbol first
                    positions = await self.exchange.fetch_positions([ccxt_symbol])
                    break  # 成功获取，跳出重试循环
                except ccxt.NetworkError as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 递增等待时间：2s, 4s, 6s
                        trading_logger.warning(f"Network error fetching positions for {ccxt_symbol} (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # 最后一次尝试失败，回退到获取所有持仓
                        trading_logger.warning(f"Could not fetch positions for single symbol {ccxt_symbol} after {max_retries} attempts, fetching all positions and filtering.")
                        try:
                            all_positions = await self.exchange.fetch_positions()
                            positions = [p for p in all_positions if p['symbol'] == ccxt_symbol]
                            break
                        except Exception as e2:
                            trading_logger.error(f"Failed to fetch all positions as fallback: {e2}")
                            raise e2
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        trading_logger.warning(f"Error fetching positions for {ccxt_symbol} (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # 最后一次尝试失败，回退到获取所有持仓
                        trading_logger.warning(f"Could not fetch positions for single symbol {ccxt_symbol} after {max_retries} attempts, fetching all positions and filtering.")
                        try:
                            all_positions = await self.exchange.fetch_positions()
                            positions = [p for p in all_positions if p['symbol'] == ccxt_symbol]
                            break
                        except Exception as e2:
                            trading_logger.error(f"Failed to fetch all positions as fallback: {e2}")
                            raise e2

            target_position = None
            for pos in positions:
                # CCXT position objects have `pos['side']` which is 'long' or 'short' (lowercase).
                # For Binance hedge mode, `pos['info']['positionSide']` is 'LONG', 'SHORT'.
                # We need to match our uppercase `position_side` input.
                
                # Check basic side match (long/short) and if there are contracts
                if pos['symbol'] == ccxt_symbol and pos.get('side', '').lower() == position_side.lower() and float(pos.get('contracts', 0)) != 0:
                    # For Binance Hedge Mode, an additional check on pos['info']['positionSide'] is more robust
                    if self.exchange.id == 'binance' and 'info' in pos and 'positionSide' in pos['info']:
                        if pos['info']['positionSide'] == position_side.upper():
                            target_position = pos
                            break
                    elif self.exchange.id != 'binance': # For other exchanges, rely on pos['side']
                        target_position = pos
                        break
            
            closed_position_successfully = False
            if target_position:
                amount_to_close = float(target_position['contracts'])
                # Ensure amount is positive, as some exchanges might return negative for shorts in non-hedge mode context
                if amount_to_close == 0 : # Should have been caught by previous check, but double check
                    trading_logger.info(f"Position {position_side} for {ccxt_symbol} found but has zero contracts. No close needed.")
                    closed_position_successfully = True # effectively
                else:
                    # For CCXT, amount should always be positive for create_order
                    actual_amount_to_close = abs(amount_to_close) 
                    side_to_close_order = 'sell' if position_side.upper() == 'LONG' else 'buy'
                    
                    trading_logger.info(f"Found {position_side} position for {ccxt_symbol} of size {actual_amount_to_close} (raw: {amount_to_close}). Closing with MARKET {side_to_close_order} order.")
                    close_params = {
                        'reduceOnly': True,
                        'positionSide': position_side.upper() # Crucial for Hedge Mode
                    }
                    try:
                        close_order = await self.exchange.create_order(ccxt_symbol, 'market', side_to_close_order, actual_amount_to_close, params=close_params)
                        trading_logger.info(f"Market close order for {position_side} {ccxt_symbol} placed: ID {close_order.get('id')}, Status {close_order.get('status')}")
                        # Assuming market orders fill quickly; for critical apps, might need to check status
                        closed_position_successfully = True 
                    except Exception as e_close_order:
                        trading_logger.error(f"Error placing market close order for {position_side} {ccxt_symbol}: {e_close_order}", exc_info=True)
                        # Position might still be open or partially closed. Cancellation of SL/TP is still important.
                        closed_position_successfully = False # Explicitly mark as failed if order placement fails
            else:
                trading_logger.info(f"No active {position_side} position found for {ccxt_symbol} to close.")
                closed_position_successfully = True # No position to close is a form of success for this operation

            # Regardless of position found/closed, always attempt to cancel all open orders for this symbol
            # This cleans up any orphaned SL/TP orders, especially important in cyclical strategy.
            trading_logger.info(f"Attempting to cancel all open orders for {ccxt_symbol} after position close attempt.")
            try:
                # Some exchanges might throw error if no orders to cancel. Check `exchange.has['cancelAllOrders']` if needed.
                # Binance does not error if no orders exist.
                cancel_response = await self.exchange.cancel_all_orders(ccxt_symbol)
                trading_logger.info(f"Successfully sent cancel_all_orders for {ccxt_symbol}. Response: {cancel_response}")
                # `closed_position_successfully` remains based on the actual position closing part.
                # The overall function success depends on both parts if we want to be strict.
                # For now, returning `closed_position_successfully` primarily indicates if the position part was okay.
                # The cancel_all_orders is best-effort cleanup.
                return closed_position_successfully # Return true if position close attempt was okay and cancel sent
            except Exception as e_cancel:
                trading_logger.error(f"Error cancelling orders for {ccxt_symbol}: {e_cancel}", exc_info=True)
                # If closing position was successful but cancelling orders failed, this is a partial failure.
                return False # Indicate overall failure if cancel_all_orders fails critically.

        except ccxt.NetworkError as e:
            trading_logger.error(f"Network error during close_all_positions_for_symbol_side ({position_side} for {symbol}): {e}", exc_info=True)
            return False
        except ccxt.ExchangeError as e:
            trading_logger.error(f"Exchange error during close_all_positions_for_symbol_side ({position_side} for {symbol}): {e}", exc_info=True)
            return False
        except Exception as e:
            trading_logger.error(f"Unexpected error during close_all_positions_for_symbol_side ({position_side} for {symbol}): {e}", exc_info=True)
            return False

    async def close_all_long_positions_for_symbol(self, symbol: str) -> bool:
        # trading_logger.info(f"(Skeleton) Attempting to close all LONG positions for {symbol}") # Covered by main func
        return await self.close_all_positions_for_symbol_side(symbol, "LONG")

    async def close_all_short_positions_for_symbol(self, symbol: str) -> bool:
        # trading_logger.info(f"(Skeleton) Attempting to close all SHORT positions for {symbol}") # Covered by main func
        return await self.close_all_positions_for_symbol_side(symbol, "SHORT")

    async def get_active_positions_symbols(self) -> Set[str]:
        """Fetches all active positions and returns a set of their symbols in CCXT format (e.g., 'BTC/USDT')."""
        active_symbols = set()
        trading_logger.debug("Fetching active positions...")
        try:
            await self.ensure_markets_loaded()
            positions = await self.exchange.fetch_positions()
            if not positions:
                trading_logger.info("No active positions found.")
                return active_symbols

            for pos in positions:
                # CCXT `contracts` or `unrealizedPnl` are good indicators of an actual position.
                # `pos['contracts']` should be non-zero for an open position.
                # Some exchanges might use `pos['info']['positionAmt']` (like older Binance parsing)
                # but `pos['contracts']` is more standard in CCXT unified structure.
                contracts = float(pos.get('contracts', 0))
                symbol = pos.get('symbol') # Should be in CCXT format e.g. BTC/USDT

                if symbol and contracts != 0:
                    # For Binance Hedge Mode, ensure we are considering a specific side or sum them up if needed.
                    # For just knowing *if* a symbol has *any* position (long or short), this is fine.
                    # If scanner needs to differentiate, this method might need `position_side` param.
                    # For now, any non-zero contract amount means the symbol is active.
                    active_symbols.add(symbol)
                    trading_logger.debug(f"Active position found: {symbol}, Contracts: {contracts}, Side: {pos.get('side')}")
            
            trading_logger.info(f"Found active position symbols: {active_symbols}")
            return active_symbols
        except ccxt.NetworkError as e:
            trading_logger.error(f"Network error fetching active positions: {e}", exc_info=True)
        except ccxt.ExchangeError as e:
            trading_logger.error(f"Exchange error fetching active positions: {e}", exc_info=True)
        except Exception as e:
            trading_logger.error(f"Unexpected error fetching active positions: {e}", exc_info=True)
        return active_symbols # Return empty set on error to avoid breaking calling logic 

    async def get_all_binance_futures_symbols(self) -> Set[str]:
        """Fetches all USDT-margined futures symbols from Binance using the configured self.exchange instance (respecting testnet/mainnet mode)."""
        mode = "Testnet" if self.testnet else "Mainnet"
        trading_logger.info(f"Fetching all Binance USDT-M futures symbols (from configured {mode} exchange instance).")
        usdt_futures_symbols = set()
        try:
            # Ensure markets are loaded for the current self.exchange instance.
            # reload_if_needed=True to ensure we try to get fresh data, especially if this is called infrequently.
            await self.ensure_markets_loaded(reload_if_needed=True) 
            markets = self.exchange.markets
            
            if not markets:
                trading_logger.error(f"Markets not loaded from {mode} exchange, cannot fetch symbols.")
                return usdt_futures_symbols

            # ---- BEGIN DEBUG LOGGING ----
            # if self.testnet:  # Debug logging removed as per user request
            #     trading_logger.info(f"--- Raw markets found by CCXT in Testnet mode (total: {len(markets)}) ---")
            #     for i, market_info_debug in enumerate(markets.values()):
            #         trading_logger.info(
            #             f"  Market {i+1}: Symbol: {market_info_debug.get('symbol')}, "
            #             f"ID: {market_info_debug.get('id')}, "
            #             f"Type: {market_info_debug.get('type')}, "
            #             f"Linear: {market_info_debug.get('linear')}, "
            #             f"Contract: {market_info_debug.get('contract')}, "
            #             f"Quote: {market_info_debug.get('quote')}, "
            #             f"Settle: {market_info_debug.get('settle')}, "
            #             f"Active: {market_info_debug.get('active')}"
            #         )
            #     trading_logger.info("--- End of raw markets log ---")
            # ---- END DEBUG LOGGING ----

            for symbol_id, market_info in markets.items():
                market_type = market_info.get('type')
                is_usdt_settled_contract = (
                    market_info.get('contract') == True and \
                    market_info.get('linear') == True and \
                    market_info.get('quote') == 'USDT' and 
                    market_info.get('active') == True # Only consider active markets
                )
                
                # We are interested in both USDT-margined perpetual swaps and traditional futures
                if is_usdt_settled_contract and (market_type == 'future' or market_type == 'swap'):
                    usdt_futures_symbols.add(market_info['symbol']) 
           
            trading_logger.info(f"Fetched {len(usdt_futures_symbols)} USDT-M futures/swaps symbols from {mode} exchange after filtering.")
        except Exception as e:
            trading_logger.error(f"Error fetching Binance futures symbols from {mode} exchange: {e}", exc_info=True)
            # Return empty set on error to prevent breaking calling logic.
        return usdt_futures_symbols

    async def get_binance_24h_tickers(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """Fetches 24h ticker data for specified USDT-margined futures symbols (or all if None) from Binance using CCXT."""
        # `symbols` should be a list of CCXT-formatted symbols e.g. ['BTC/USDT', 'ETH/USDT']
        trading_logger.debug(f"Fetching 24h tickers for symbols: {symbols if symbols else 'All USDT Futures'}")
        all_tickers_data = [] 
        try:
            await self.ensure_markets_loaded() # Markets needed for symbol validation by fetch_tickers
           
            # fetch_tickers can take a list of symbols. If None, it fetches all available on the exchange.
            raw_tickers = await self.exchange.fetch_tickers(symbols=symbols)
           
            if not raw_tickers:
                trading_logger.warning("fetch_tickers returned no data.")
                return all_tickers_data

            # CCXT fetch_tickers returns a dictionary of {symbol: ticker_data}
            for symbol, ticker in raw_tickers.items():
                # We only want USDT-margined futures. 
                # If `symbols` arg was provided, they should already be filtered. 
                # If `symbols` was None, we need to filter here based on market info.
                market_info = self.exchange.markets.get(symbol)
                if market_info and \
                   market_info.get('type') == 'future' and \
                   market_info.get('quote') == 'USDT' and \
                   market_info.get('contract') == True and \
                   market_info.get('linear') == True:
                    all_tickers_data.append(ticker) # ticker is already a dict
                elif not market_info and symbols: # If specific symbols were requested but not found in markets.
                    trading_logger.warning(f"Ticker for {symbol} requested but market info not found after fetch_tickers.")

            trading_logger.info(f"Fetched {len(all_tickers_data)} 24h tickers for USDT-margined futures.")
            return all_tickers_data
        except Exception as e:
            trading_logger.error(f"Error fetching Binance 24h tickers: {e}", exc_info=True)
            return all_tickers_data # Return empty/partial list on error 