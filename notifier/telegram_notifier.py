import asyncio
from typing import Optional, Dict, Tuple, Coroutine, Any
from datetime import datetime
import threading
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackContext, CallbackQueryHandler,
    filters, MessageHandler
)

from utils.logger import trading_logger
from utils.config_manager import ConfigManager

class TelegramNotifier:
    """Telegram通知系统"""
    
    def __init__(self, config_manager: ConfigManager = None):
        """
        初始化Telegram通知系统
        
        Args:
            config_manager: 配置管理器
        """
        self.config_manager = config_manager or ConfigManager()
        
        # 读取配置
        telegram_config = self.config_manager.get('notification.telegram', {})
        self.token = telegram_config.get('bot_token', '')
        self.chat_id = telegram_config.get('chat_id', '')
        self.enabled = telegram_config.get('enabled', False)
        
        trading_logger.info(f"Telegram配置: enabled={self.enabled}, token={self.token[:10]}..., chat_id={self.chat_id}")
        
        # 消息队列
        self.msg_queue = []
        self.msg_lock = threading.Lock()
        
        # 状态变量
        self.application: Optional[Application] = None
        self.polling_thread: Optional[threading.Thread] = None
        self.polling_loop: Optional[asyncio.AbstractEventLoop] = None
        self.polling_loop_ready = threading.Event() # Event to signal loop readiness
        self.running = False
        self.authorized_chats = set()
        
        # 交易引擎和风险管理器引用
        self.trading_engine = None
        self.risk_manager = None
        self.main_bot_instance: Optional[Any] = None # Added to store CPT instance
        
        # 如果启用，则初始化机器人
        if self.enabled and self.token:
            trading_logger.info("正在初始化Telegram机器人...")
            self._init_bot()
            # 加载授权的聊天ID
            self._load_authorized_chats()
        else:
            trading_logger.warning(f"Telegram通知未启用或缺少配置: enabled={self.enabled}, token_exists={bool(self.token)}")
    
    def set_trading_engine(self, trading_engine):
        """设置交易引擎引用"""
        self.trading_engine = trading_engine
    
    def set_risk_manager(self, risk_manager):
        """设置风险管理器引用"""
        self.risk_manager = risk_manager
    
    def set_main_bot_instance(self, main_bot_instance: Any): # Setter method
        """Sets the reference to the main CryptoPulseTrader instance."""
        self.main_bot_instance = main_bot_instance
    
    def _init_bot(self):
        """初始化Telegram机器人"""
        try:
            trading_logger.info("开始构建Telegram应用...")
            self.application = Application.builder().token(self.token).build()
            
            # 注册命令处理器
            trading_logger.info("注册命令处理器...")
            self.application.add_handler(CommandHandler('start', self._start_cmd))
            self.application.add_handler(CommandHandler('help', self._help_cmd))
            self.application.add_handler(CommandHandler('status', self._status_cmd))
            self.application.add_handler(CommandHandler('balance', self._balance_cmd))
            self.application.add_handler(CommandHandler('trades', self._trades_cmd))
            self.application.add_handler(CommandHandler('performance', self._performance_cmd))
            self.application.add_handler(CommandHandler('daily', self._daily_cmd))
            self.application.add_handler(CommandHandler('stop', self._stop_cmd))
            self.application.add_handler(CommandHandler(['forceexit', 'fx'], self._forceexit_cmd))
            self.application.add_handler(CommandHandler('reload', self._reload_cmd))
            
            # 注册回调查询处理器
            self.application.add_handler(CallbackQueryHandler(self._button_callback))
            
            # 未知命令处理器
            self.application.add_handler(MessageHandler(filters.COMMAND, self._unknown_cmd))
            
            # 启动机器人
            trading_logger.info("启动Telegram机器人轮询线程...")
            self.polling_thread = threading.Thread(target=self._run_polling_thread, daemon=True)
            self.polling_thread.start()
            
            trading_logger.info("Telegram机器人启动成功.")
            self.running = True
            
        except Exception as e:
            trading_logger.error(f"初始化Telegram机器人失败: {str(e)}", exc_info=True)
            self.running = False
    
    def _run_polling_thread(self):
        """Target for the polling thread."""
        thread_id = threading.get_ident()
        if self.application:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.polling_loop = loop
            self.polling_loop_ready.set()
            
            try:
                self.application.run_polling(stop_signals=None, drop_pending_updates=True) 
            except Exception as e:
                trading_logger.error(f"Telegram polling thread异常终止: {e}", exc_info=True)
            finally:
                self.running = False 
                trading_logger.info("Telegram polling thread已停止.")
        else:
            self.polling_loop_ready.set()
    
    def _load_authorized_chats(self):
        """加载授权的聊天ID"""
        # 如果有指定的chat_id，添加到授权列表
        if self.chat_id:
            chat_ids = [i.strip() for i in self.chat_id.split(',')]
            self.authorized_chats = set(chat_ids)
            trading_logger.info(f"已加载{len(self.authorized_chats)}个授权的聊天ID")
    
    def _is_authorized(self, chat_id) -> bool:
        """
        检查聊天ID是否已授权
        
        Args:
            chat_id: Telegram聊天ID
            
        Returns:
            是否已授权
        """
        # 如果授权列表为空，则接受所有聊天
        if not self.authorized_chats:
            return True
        
        return str(chat_id) in self.authorized_chats
    
    async def _send_msg(self, msg: str, callback_path: Optional[str] = None,
                  query: Optional[Update] = None) -> bool:
        if not self.enabled or not self.application or not self.application.bot:
            return False
        
        keyboard = []
        if callback_path:
            keyboard = [[
                InlineKeyboardButton("查看详情", callback_data=callback_path)
            ]]
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        try:
            if query and query.message:
                await query.edit_message_text(
                    text=msg,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            return True
            
        except Exception as e:
            trading_logger.error(f"发送Telegram消息失败: {str(e)}", exc_info=True)
            return False
    
    def _run_async_from_sync(self, coro: Coroutine[Any, Any, Any], wait_for_result: bool = True) -> Any:
        """Helper to run async methods from synchronous code into the polling thread's event loop."""
        main_thread_id = threading.get_ident()
        coro_name = coro.__name__ if hasattr(coro, '__name__') else str(coro)
        
        if not self.polling_loop_ready.wait(timeout=10): 
            trading_logger.error(f"Main thread ({main_thread_id}): Timeout waiting for polling loop to become ready. Cannot send for {coro_name}.")
            return False if wait_for_result else None # Return None if not waiting, False if error expected

        if not self.polling_loop: 
            trading_logger.error(f"Main thread ({main_thread_id}): Polling loop object not found. Cannot send for {coro_name}.")
            return False if wait_for_result else None
        
        if not self.polling_loop.is_running(): # Added a check here before scheduling
             trading_logger.error(f"Main thread ({main_thread_id}): Polling loop is not running. Cannot send for {coro_name}. Loop state: {self.polling_loop}")
             return False if wait_for_result else None

        future = asyncio.run_coroutine_threadsafe(coro, self.polling_loop)
        
        if not wait_for_result:
            trading_logger.debug(f"Main thread ({main_thread_id}): Fire-and-forget for {coro_name}.")
            # Optional: add a callback to log if the future had an exception, without blocking
            def _log_future_exception(f):
                try:
                    f.result(timeout=0) # Check for immediate exception without blocking
                except Exception as e_future:
                    trading_logger.error(f"Main thread ({main_thread_id}): Fire-and-forget task {coro_name} resulted in exception: {e_future}", exc_info=False) # Set exc_info=False to avoid long trace for this non-blocking log
            future.add_done_callback(_log_future_exception)
            return None # For fire-and-forget, we don't return the success/failure of the send

        try:
            return future.result(timeout=10)
        except TimeoutError:
            trading_logger.error(f"Main thread ({main_thread_id}): Timeout running {coro_name} in polling loop.")
            return False
        except Exception as e:
            if isinstance(e, RuntimeError) and "Event loop is closed" in str(e):
                trading_logger.error(f"Main thread ({main_thread_id}): Polling loop was closed when trying to run {coro_name}. {e}")
            else:
                trading_logger.error(f"Main thread ({main_thread_id}): Error running {coro_name} in polling loop: {e}", exc_info=True)
            return False

    async def _send_trade_notification_async(self, trade_type: str, symbol: str, direction: str, 
                                         price: float, amount: float, stop_loss: Optional[float] = None, 
                                         take_profit: Optional[float] = None) -> bool:
        direction_text = "多" if direction == "long" else "空"
        
        if trade_type == "open":
            msg = f"🚀 *开仓通知*\n\n" \
                  f"*币种*: `{symbol}`\n" \
                  f"*方向*: {direction_text}\n" \
                  f"*价格*: `{price:.8f}`\n" \
                  f"*数量*: `{amount} USDT`\n"
            
            if stop_loss:
                msg += f"*止损*: `{stop_loss:.8f}`\n"
            if take_profit:
                msg += f"*止盈*: `{take_profit:.8f}`\n"
                
            msg += f"\n*时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            
        elif trade_type == "add":
            msg = f"➕ *加仓通知*\n\n" \
                  f"*币种*: `{symbol}`\n" \
                  f"*方向*: {direction_text}\n" \
                  f"*价格*: `{price:.8f}`\n" \
                  f"*数量*: `{amount} USDT`\n" \
                  f"\n*时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            
        else:  # close or other types like sl, tp
            if trade_type == "close":
                title_emoji = "🎯 *平仓通知*"
            elif trade_type == "sl":
                title_emoji = "🛑 *止损平仓*"
            elif trade_type == "tp":
                title_emoji = "✅ *止盈平仓*"
            elif trade_type == "timeout":
                title_emoji = "⏱️ *超时平仓*"
            else: 
                title_emoji = "🏁 *订单关闭*"

            msg = f"{title_emoji}\n\n" \
                  f"*币种*: `{symbol}`\n" \
                  f"*方向*: {direction_text}\n" \
                  f"*价格*: `{price:.8f}`\n" \
                  f"*数量*: `{amount} USDT`\n"
            msg += f"\n*时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        
        return await self._send_msg(msg)

    def send_trade_notification(self, trade_type: str, symbol: str, direction: str, 
                                price: float, amount: float, stop_loss: Optional[float] = None, 
                                take_profit: Optional[float] = None, wait_for_result: bool = True) -> bool:
        coro = self._send_trade_notification_async(trade_type, symbol, direction, price, amount, stop_loss, take_profit)
        result = self._run_async_from_sync(coro, wait_for_result=wait_for_result)
        return result if wait_for_result else True # Assume success for fire-and-forget for simplicity of return type
    
    async def _send_error_notification_async(self, error_type: str, error_msg: str) -> bool:
        msg = f"⚠️ *错误警报*\n\n" \
              f"*类型*: `{error_type}`\n" \
              f"*消息*: `{error_msg}`\n" \
              f"\n*时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        
        return await self._send_msg(msg)

    def send_error_notification(self, error_type: str, error_msg: str, wait_for_result: bool = True) -> bool:
        coro = self._send_error_notification_async(error_type, error_msg)
        result = self._run_async_from_sync(coro, wait_for_result=wait_for_result)
        return result if wait_for_result else True # Assume success for fire-and-forget
    
    async def _start_cmd(self, update: Update, context: CallbackContext):
        """处理/start命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        msg = (
            "🤖 *欢迎使用 CryptoPulse Trader*\n\n"
            "使用 /help 查看可用命令列表"
        )
        if context.bot:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode='Markdown'
            )
    
    async def _help_cmd(self, update: Update, context: CallbackContext):
        """处理/help命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        msg = (
            "🔍 可用命令\n\n" 
            "/status \\- 显示当前持仓状态\n" 
            "/balance \\- 显示账户余额\n" 
            "/trades \\- 显示最近交易\n" 
            "/performance \\- 显示性能统计\n" 
            "/daily \\- 显示每日收益\n" 
            "/stop \\- 停止系统\n" 
            "/forceexit \\[交易对符号 \\| 订单ID\\] \\- 强制平仓\n" 
            "/reload \\- 重新加载配置\n"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN_V2
        )
    
    async def _status_cmd(self, update: Update, context: CallbackContext):
        """处理/status命令，显示每个交易对下的所有独立订单"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        status_message_parts = ["📊 *当前系统状态*\n"]
        
        if self.risk_manager and self.risk_manager.positions:
            for symbol, orders_list in self.risk_manager.positions.items():
                if not orders_list: 
                    continue
                
                status_message_parts.append(f"\nSymbol: `{symbol}` ({len(orders_list)} 个独立订单)")
                
                for i, order_details in enumerate(orders_list):
                    order_id = order_details['id']
                    direction = "多" if order_details['direction'] == 'long' else "空"
                    entry_price = order_details['entry_price']
                    size_usdt = order_details['size']
                    stop_loss = order_details['stop_loss']
                    take_profit = order_details['take_profit']
                    entry_time = order_details['entry_time']
                    
                    current_price_for_pnl = "N/A"
                    pnl_percentage_str = "N/A"
                    pnl_amount_usdt_str = "N/A"
                    
                    if self.trading_engine:
                        try:
                            ticker = await asyncio.to_thread(self.trading_engine.get_ticker, symbol)
                            current_price = ticker['last']
                            current_price_for_pnl = f"{current_price:.8f}"
                            
                            if entry_price > 0:
                                if order_details['direction'] == 'long':
                                    pnl_pct = (current_price - entry_price) / entry_price * 100
                                else:
                                    pnl_pct = (entry_price - current_price) / entry_price * 100
                                pnl_percentage_str = f"{pnl_pct:.2f}%"
                                pnl_amount_usdt_str = f"{(pnl_pct/100 * size_usdt):.2f} USDT"
                        except Exception as e:
                            trading_logger.warning(f"获取 {symbol} ticker 计算 PNL 失败: {e}")
                    
                    holding_duration_minutes = int((datetime.now() - entry_time).total_seconds() / 60)
                    
                    status_message_parts.append(
                        f"  订单 #{i+1} (ID: `{order_id}`):\n" 
                        f"    方向: {direction}, 大小: {size_usdt:.2f} USDT\n"
                        f"    入场价: {entry_price:.8f}, 当前价: {current_price_for_pnl}\n"
                        f"    此单盈亏: {pnl_amount_usdt_str} ({pnl_percentage_str})\n"
                        f"    止损: {stop_loss:.8f}, 止盈: {take_profit:.8f}\n"
                        f"    持仓: {holding_duration_minutes} 分钟"
                    )
                status_message_parts.append("---") 
        else:
            status_message_parts.append("当前无持仓订单")
        
        status_message_parts.append(f"\n*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
        final_message = "\n".join(status_message_parts)
        
        if len(final_message) > 4096:
            trading_logger.warning("Status message too long, sending summary instead.")
            summary_msg = f"📊 *持仓摘要*\n\n总计 {len(self.risk_manager.positions)} 个交易对有持仓。"
            active_orders_count = sum(len(orders) for orders in self.risk_manager.positions.values())
            summary_msg += f"总计 {active_orders_count} 个独立订单。\n详情请查看日志。"
            summary_msg += f"\n*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            final_message = summary_msg

        await context.bot.send_message(
            chat_id=chat_id,
            text=final_message,
            parse_mode='Markdown'
        )
    
    async def _balance_cmd(self, update: Update, context: CallbackContext):
        """处理/balance命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        balance_msg = "USDT: 未知"
        daily_pnl_str = "0.0%" 
        
        if self.trading_engine:
            try:
                balance = await asyncio.to_thread(self.trading_engine.get_balance, 'USDT')
                balance_msg = f"USDT: {balance:.2f}"
            except Exception as e:
                balance_msg = f"获取余额失败: {str(e)}"
        
        if self.risk_manager: 
             daily_pnl_str = f"{self.risk_manager.daily_pnl:.2f}%"

        msg = (
            "💰 *账户余额*\n\n"
            f"{balance_msg}\n日盈亏: {daily_pnl_str}\n\n"
            f"*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
    
    async def _trades_cmd(self, update: Update, context: CallbackContext):
        """处理/trades命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        trades_msg = "暂无交易记录"
        
        if self.risk_manager:
            trades = self.risk_manager.trades
            if trades:
                recent_trades = trades[-10:]
                trades_msg = ""
                
                for trade in recent_trades:
                    symbol = trade['symbol']
                    direction = "多" if trade['direction'] == 'long' else "空"
                    entry_price = trade['entry_price']
                    exit_price = trade['exit_price']
                    pnl = trade['pnl']
                    reason = trade['reason']
                    
                    reason_texts = {
                        'stop_loss': '止损触发',
                        'take_profit': '止盈触发',
                        'timeout': '持仓超时',
                        'trend_reversal': '趋势反转',
                        'forced': '手动平仓',
                        'shutdown': '系统关闭'
                    }
                    reason_text = reason_texts.get(reason, reason)
                    
                    holding_time = int((trade['exit_time'] - trade['entry_time']).total_seconds() / 60)
                    
                    trades_msg += (
                        f"*{symbol}* ({direction}): {pnl:.2f}%\n"
                        f"入场: {entry_price:.8f}, 出场: {exit_price:.8f}\n"
                        f"原因: {reason_text}, 时间: {holding_time}分钟\n\n"
                    )
        
        msg = (
            "📝 *最近交易记录*\n\n"
            f"{trades_msg}\n\n"
            f"*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
    
    async def _performance_cmd(self, update: Update, context: CallbackContext):
        """处理/performance命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        performance_msg = "暂无性能数据"
        
        msg = (
            "📈 *性能统计*\n\n"
            f"{performance_msg}\n\n"
            f"*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
    
    async def _daily_cmd(self, update: Update, context: CallbackContext):
        """处理/daily命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        daily_msg = "暂无每日收益数据"
        
        msg = (
            "📅 *每日收益*\n\n"
            f"{daily_msg}\n\n"
            f"*更新时间*: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
    
    async def _forceexit_cmd(self, update: Update, context: CallbackContext):
        """处理/forceexit (/fx) 命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        if not context.args or len(context.args) != 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ 使用方法: `/forceexit [交易对符号 | 订单ID]`\n例如: `/forceexit BTC/USDT` 或 `/fx BTC/USDT_timestamp_0`",
                parse_mode='Markdown'
            )
            return

        target_arg = context.args[0].upper()
        is_order_id_format = "_" in target_arg 

        closed_any_order = False
        messages_to_user = []

        if not self.risk_manager or not self.trading_engine:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ 系统组件未完全初始化，无法执行平仓。", parse_mode='Markdown')
            return

        if is_order_id_format:
            target_symbol = None
            target_order_details = None
            for sym, orders_list in self.risk_manager.positions.items():
                for order in orders_list:
                    if order['id'] == target_arg:
                        target_symbol = sym
                        target_order_details = order
                        break
                if target_symbol:
                    break
            
            if target_symbol and target_order_details:
                messages_to_user.append(f"处理订单ID: `{target_arg}` (属于 `{target_symbol}`)... ")
                success, msg = await self._execute_close_order(target_symbol, target_order_details)
                messages_to_user.append(msg)
                if success: closed_any_order = True
            else:
                messages_to_user.append(f"❌ 未找到订单ID: `{target_arg}` 或该订单不处于可平仓状态。")
        
        else:
            target_symbol = target_arg
            if target_symbol in self.risk_manager.positions and self.risk_manager.positions[target_symbol]:
                messages_to_user.append(f"处理交易对: `{target_symbol}`...准备平掉其下所有订单。")
                orders_to_close = list(self.risk_manager.positions[target_symbol]) 
                if not orders_to_close:
                    messages_to_user.append(f"ℹ️ 交易对 `{target_symbol}` 当前没有活动的独立订单。")
                else:
                    for order_details in orders_to_close:
                        success, msg = await self._execute_close_order(target_symbol, order_details)
                        messages_to_user.append(msg)
                        if success: closed_any_order = True
            else:
                messages_to_user.append(f"❌ 未找到交易对: `{target_symbol}` 的持仓，或其下没有订单。")

        final_user_message = "\n".join(messages_to_user)
        if not final_user_message: 
             final_user_message = "ℹ️ 未执行任何操作。请检查参数。"

        await context.bot.send_message(chat_id=chat_id, text=final_user_message, parse_mode='Markdown')

    async def _execute_close_order(self, symbol: str, order_details: Dict) -> Tuple[bool, str]:
        """执行单个订单的平仓逻辑 (异步) - 注意: 交易引擎的平仓方法也需要是异步的"""
        if not self.trading_engine:
            return False, "交易引擎未初始化"
        try:
            result = await asyncio.to_thread(
                self.trading_engine.close_order, 
                symbol, 
                order_id=order_details['id'], 
                market_order=True
            )
            
            if result and result.get('id'):
                await self._send_trade_notification_async(
                    trade_type="forceclose", 
                    symbol=symbol, 
                    direction=result.get('side', 'unknown'),
                    price=float(result.get('price', 0)), 
                    amount=float(result.get('filled', 0)) * float(result.get('price', 0))
                )
                return True, f"订单 {symbol} (ID: {order_details['id']}) 已强制平仓。"
            else:
                return False, f"强制平仓订单 {symbol} (ID: {order_details['id']}) 失败: {result.get('error', '未知错误') if isinstance(result, dict) else '未知错误'}"
        except Exception as e:
            trading_logger.error(f"强制平仓订单 {symbol} (ID: {order_details['id']}) 时发生异常: {e}", exc_info=True)
            return False, f"强制平仓订单 {symbol} (ID: {order_details['id']}) 时发生异常: {e}"
    
    async def _stop_cmd(self, update: Update, context: CallbackContext):
        """处理/stop命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        msg = (
            "🛑 *停止系统*\n\n"
            "系统停止请求已收到，正在安全停止..."
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
        
        trading_logger.info(f"收到停止系统命令 from chat {chat_id}")
        if hasattr(self, 'main_bot_instance') and self.main_bot_instance:
            self.main_bot_instance.stop()
        else:
            trading_logger.warning("No main_bot_instance reference to stop the main application.")
    
    async def _reload_cmd(self, update: Update, context: CallbackContext):
        """处理/reload命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        msg = (
            "🔄 *重新加载配置*\n\n"
            "正在重新加载配置..."
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
        
        try:
            if self.config_manager:
                self.config_manager.reload()
                
                telegram_config = self.config_manager.get('notification.telegram', {})
                self.token = telegram_config.get('bot_token', '')
                self.chat_id = telegram_config.get('chat_id', '')
                self.enabled = telegram_config.get('enabled', False)
                
                self._load_authorized_chats()
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="✅ 配置已重新加载",
                    parse_mode='Markdown'
                )
        except Exception as e:
            trading_logger.error(f"重新加载配置失败: {str(e)}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 重新加载配置失败: {str(e)}",
                parse_mode='Markdown'
            )
    
    async def _unknown_cmd(self, update: Update, context: CallbackContext):
        """处理未知命令"""
        if not update.effective_chat: return
        chat_id = update.effective_chat.id
        if not self._is_authorized(chat_id):
            await self._send_unauthorized_msg(update)
            return
        
        msg = (
            "❓ *未知命令*\n\n"
            "使用 /help 查看可用命令列表"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode='Markdown'
        )
    
    async def _button_callback(self, update: Update, context: CallbackContext):
        """处理按钮回调"""
        query = update.callback_query
        if not query: return
        await query.answer()
        
        callback_data = query.data
        
        await query.edit_message_text(
            text=f"处理回调: {callback_data}",
            parse_mode='Markdown'
        )
    
    async def _send_unauthorized_msg(self, update: Update):
        """发送未授权消息"""
        trading_logger.warning(f"Unauthorized access attempt by chat {update.effective_chat.id if update.effective_chat else 'N/A'}.")
        if update.effective_chat and update.effective_chat.id:
            await update.effective_chat.send_message(
                "❌ 您未被授权使用此机器人。请联系管理员添加授权。"
            )

    def stop(self):
        """停止Telegram通知系统 (尝试优雅停止 polling thread)"""
        main_thread_id = threading.get_ident()
        trading_logger.info(f"Main thread ({main_thread_id}): 正在停止Telegram通知系统...")
        
        try:
            if self.application and self.running: # self.running is our flag
                if self.application._is_running: # PTB's internal flag for whether its main loop is running
                    trading_logger.info(f"Main thread ({main_thread_id}): Application is running, attempting to stop it.")
                    loop = self.application.loop # Get the loop run_polling is using
                    
                    if loop and loop.is_running():
                        trading_logger.info(f"Main thread ({main_thread_id}): Scheduling application.stop() in loop {id(loop)}.")
                        future = None
                        try:
                            future = asyncio.run_coroutine_threadsafe(self.application.stop(), loop)
                        except RuntimeError as e:
                            trading_logger.error(f"Main thread ({main_thread_id}): RuntimeError scheduling application.stop(): {e}. Loop might be closing.", exc_info=True)
                        
                        if future:
                            try:
                                future.result(timeout=5) # Wait for application.stop() to complete
                                trading_logger.info(f"Main thread ({main_thread_id}): application.stop() call completed or timed out waiting for result.")
                            except TimeoutError:
                                trading_logger.warning(f"Main thread ({main_thread_id}): Timeout waiting for application.stop() future to return result.")
                            except asyncio.CancelledError:
                                trading_logger.warning(f"Main thread ({main_thread_id}): application.stop() future was cancelled.")
                            except Exception as e: 
                                trading_logger.error(f"Main thread ({main_thread_id}): Exception waiting for application.stop() future: {e}", exc_info=True)
                        
                        # After application.stop() is called, run_polling should ideally exit.
                        # Then we wait for the polling thread to terminate.
                        if self.polling_thread and self.polling_thread.is_alive():
                            trading_logger.info(f"Main thread ({main_thread_id}): Joining polling thread ({self.polling_thread.ident})...")
                            self.polling_thread.join(timeout=10) 
                            if self.polling_thread.is_alive():
                                trading_logger.warning(f"Main thread ({main_thread_id}): Polling thread ({self.polling_thread.ident}) did not exit after join with timeout.")
                            else:
                                trading_logger.info(f"Main thread ({main_thread_id}): Polling thread ({self.polling_thread.ident}) has exited.")
                        elif self.polling_thread:
                             trading_logger.info(f"Main thread ({main_thread_id}): Polling thread ({self.polling_thread.ident}) was not alive before join.")
                        else:
                            trading_logger.info(f"Main thread ({main_thread_id}): No polling thread to join.")
                    else:
                         trading_logger.warning(f"Main thread ({main_thread_id}): Telegram application loop not found or not running during stop sequence.")
                else:
                    trading_logger.info(f"Main thread ({main_thread_id}): Telegram application was not marked as _is_running by PTB, or self.running flag was false.")
        except Exception as e:
            trading_logger.error(f"Main thread ({main_thread_id}): Unexpected error during TelegramNotifier stop sequence: {e}", exc_info=True)
        finally:
            self.running = False # Ensure our flag is set
            current_polling_thread_status = "not found or already stopped prior to this final check."
            if self.polling_thread:
                if self.polling_thread.is_alive():
                    current_polling_thread_status = f"({self.polling_thread.ident}) is still alive. It is a daemon and should exit with the main program."
                else:
                    current_polling_thread_status = f"({self.polling_thread.ident}) has stopped."
            
            trading_logger.info(f"Main thread ({main_thread_id}): TelegramNotifier stop sequence finished. Polling thread status: {current_polling_thread_status}")

# 单例实例
_telegram_notifier = None

def get_telegram_notifier(config_manager: ConfigManager = None) -> TelegramNotifier:
    """
    获取Telegram通知器单例
    
    Args:
        config_manager: 配置管理器
        
    Returns:
        Telegram通知器实例
    """
    global _telegram_notifier
    if _telegram_notifier is None:
        _telegram_notifier = TelegramNotifier(config_manager)
    return _telegram_notifier 