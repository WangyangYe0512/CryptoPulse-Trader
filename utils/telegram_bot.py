"""
Telegram Bot for CryptoPulse Trader
基于freqtrade telegram模块的实现，提供通知和控制功能
具备完整的错误处理和故障隔离机制
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from telegram import Update, Bot, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import NetworkError, BadRequest

from utils.logger import trading_logger
from utils.config_manager import ConfigManager


class TelegramCircuitBreaker:
    """熔断器模式，防止持续的Telegram错误影响系统"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        """
        初始化熔断器
        
        Args:
            failure_threshold: 失败阈值，连续失败次数超过此值时开启熔断
            recovery_timeout: 恢复超时时间（秒），熔断后等待多久尝试恢复
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED(正常), OPEN(熔断), HALF_OPEN(半开)
        
    def record_success(self):
        """记录成功操作"""
        self.failure_count = 0
        self.state = "CLOSED"
        
    def record_failure(self):
        """记录失败操作"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            trading_logger.warning(f"Telegram熔断器开启：连续失败{self.failure_count}次")
            
    def can_execute(self) -> bool:
        """判断是否可以执行操作"""
        if self.state == "CLOSED":
            return True
            
        if self.state == "OPEN":
            # 检查是否到了尝试恢复的时间
            if (datetime.now() - self.last_failure_time).seconds >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                trading_logger.info("Telegram熔断器进入半开状态，尝试恢复")
                return True
            return False
            
        if self.state == "HALF_OPEN":
            return True
            
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "next_retry_time": (
                self.last_failure_time + timedelta(seconds=self.recovery_timeout)
                if self.last_failure_time else None
            )
        }


class TelegramBot:
    """
    Telegram机器人类，提供交易通知和状态查询功能
    具备完整的错误处理和故障隔离机制
    """
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化Telegram机器人
        
        Args:
            config_manager: 配置管理器实例
        """
        self.config_manager = config_manager
        self.config = config_manager.config
        
        # Telegram配置
        telegram_config = self.config.get('notification', {}).get('telegram', {})
        self.enabled = telegram_config.get('enabled', False)
        self.bot_token = telegram_config.get('bot_token', '')
        self.chat_id = telegram_config.get('chat_id', '')
        self.trade_notifications = telegram_config.get('trade_notifications', True)
        self.error_notifications = telegram_config.get('error_notifications', True)
        self.status_notifications = telegram_config.get('status_notifications', True)
        self.commands_enabled = telegram_config.get('commands_enabled', True)
        
        # 群组和话题配置
        self.group_mode = telegram_config.get('group_mode', False)
        self.topic_id = telegram_config.get('topic_id', None)
        
        # 话题路由配置
        topic_routing = telegram_config.get('topic_routing', {})
        self.topic_routing_enabled = topic_routing.get('enabled', False)
        self.topic_routes = topic_routing.get('topics', {})
        
        # Bot实例
        self.application: Optional[Application] = None
        self.bot: Optional[Bot] = None
        
        # 鲁棒性控制
        self.circuit_breaker = TelegramCircuitBreaker(failure_threshold=5, recovery_timeout=300)
        self.max_retry_attempts = 3
        self.operation_timeout = 10.0  # 操作超时时间（秒）
        self.is_healthy = True
        
        # 状态数据 - 这些通常来自交易系统
        self.trading_data = {
            'positions': [],
            'balance': {},
            'profit_loss': {},
            'recent_trades': [],
            'system_status': 'running'
        }
        
        # 错误统计
        self.error_stats = {
            'total_errors': 0,
            'network_errors': 0,
            'api_errors': 0,
            'timeout_errors': 0,
            'last_error_time': None,
            'last_error_message': None
        }
        
        # 验证配置并初始化
        if self._validate_config():
            self._setup_bot()
        else:
            trading_logger.warning("Telegram配置无效或不完整，已禁用")
            self.enabled = False
    
    def _validate_config(self) -> bool:
        """验证Telegram配置"""
        if not self.enabled:
            trading_logger.info("Telegram功能已禁用")
            return False
        
        if not self.bot_token:
            trading_logger.warning("Telegram bot token为空")
            return False
        
        if not self.chat_id:
            trading_logger.warning("Telegram chat ID为空")
            return False
        
        # 验证token格式（基本检查）
        if not self.bot_token.count(':') == 1:
            trading_logger.warning("Telegram bot token格式无效")
            return False
        
        # 验证chat_id格式（群组ID通常是负数，私聊是正数）
        if not (self.chat_id.lstrip('-').isdigit()):
            trading_logger.warning("Telegram chat ID格式无效")
            return False
        
        # 群组模式验证
        if self.group_mode:
            chat_id_num = int(self.chat_id)
            if chat_id_num > 0:
                trading_logger.warning("群组模式下chat_id应该是负数（群组ID）")
                return False
            
            # 验证话题ID格式
            if self.topic_id is not None and not isinstance(self.topic_id, int):
                trading_logger.warning("话题ID应该是整数或null")
                return False
                
            if self.topic_routing_enabled:
                for topic_type, topic_id in self.topic_routes.items():
                    if topic_id is not None and not isinstance(topic_id, int):
                        trading_logger.warning(f"话题路由配置错误: {topic_type} 的话题ID应该是整数或null")
                        return False

        return True
    
    def _setup_bot(self):
        """设置Telegram机器人"""
        try:
            # 创建Application
            self.application = Application.builder().token(self.bot_token).build()
            self.bot = self.application.bot
            
            # 注册命令处理器
            if self.commands_enabled:
                self._register_handlers()
                
            trading_logger.info("Telegram机器人初始化成功")
            
        except Exception as e:
            trading_logger.error(f"Telegram机器人初始化失败: {e}", exc_info=True)
            self.enabled = False
            self.is_healthy = False
    
    def _register_handlers(self):
        """注册命令处理器"""
        handlers = [
            CommandHandler("start", self._start_command),
            CommandHandler("help", self._help_command),
            CommandHandler("status", self._status_command),
            CommandHandler("balance", self._balance_command),
            CommandHandler("profit", self._profit_command),
            CommandHandler("trades", self._trades_command),
            CommandHandler("positions", self._positions_command),
            CommandHandler("daily", self._daily_command),
            CommandHandler("weekly", self._weekly_command),
            CommandHandler("monthly", self._monthly_command),
            CommandHandler("version", self._version_command),
            CommandHandler("config", self._config_command),
            CommandHandler("stop_notifications", self._stop_notifications_command),
            CommandHandler("start_notifications", self._start_notifications_command),
            CommandHandler("health", self._health_command),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            
        # 添加错误处理器
        self.application.add_error_handler(self._error_handler)
        
        trading_logger.info("Telegram命令处理器注册完成")
    
    async def start_bot(self):
        """启动Telegram机器人"""
        if not self.enabled or not self.application:
            return
            
        try:
            # 使用超时控制
            await asyncio.wait_for(self._start_bot_internal(), timeout=30.0)
            
        except asyncio.TimeoutError:
            trading_logger.error("Telegram机器人启动超时")
            self.is_healthy = False
        except Exception as e:
            trading_logger.error(f"启动Telegram机器人失败: {e}", exc_info=True)
            self.is_healthy = False
    
    async def _start_bot_internal(self):
        """内部启动逻辑"""
        try:
            await self.application.initialize()
            await self.application.start()
            await self._set_bot_commands()
            
            # 可选：测试连接
            bot_info = await self.bot.get_me()
            trading_logger.info(f"Telegram机器人已启动: @{bot_info.username}")
            
        except Exception as e:
            trading_logger.error(f"Telegram机器人内部启动失败: {e}", exc_info=True)
            raise
    
    async def _stop_bot_internal(self):
        """内部停止方法"""
        try:
            if self.application and self.application.is_running:
                # 先停止接收更新
                await self.application.stop()
                # 等待所有更新处理完成
                await self.application.shutdown()
                trading_logger.info("Telegram机器人已停止")
        except Exception as e:
            trading_logger.error(f"Telegram机器人内部停止失败: {e}", exc_info=True)
            raise

    def stop_bot(self):
        """停止Telegram机器人"""
        try:
            if self.application and self.application.is_running:
                # 使用新的事件循环来执行停止操作
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._stop_bot_internal())
                finally:
                    loop.close()
        except Exception as e:
            trading_logger.error(f"停止Telegram机器人失败: {e}", exc_info=True)
            raise
    
    async def _set_bot_commands(self):
        """设置机器人命令菜单"""
        commands = [
            BotCommand("start", "启动机器人"),
            BotCommand("help", "显示帮助信息"),
            BotCommand("status", "显示系统状态"),
            BotCommand("balance", "显示账户余额"),
            BotCommand("profit", "显示盈亏统计"),
            BotCommand("trades", "显示最近交易"),
            BotCommand("positions", "显示当前持仓"),
            BotCommand("health", "显示机器人健康状态"),
            BotCommand("version", "显示版本信息"),
        ]
        
        try:
            await asyncio.wait_for(self.bot.set_my_commands(commands), timeout=10.0)
        except Exception as e:
            trading_logger.error(f"设置机器人命令失败: {e}")
    
    # =================== 安全的消息发送方法 ===================
    
    def _get_topic_id(self, notification_type: str = None) -> Optional[int]:
        """获取消息应该发送到的话题ID"""
        if not self.group_mode:
            return None
            
        # 如果启用了话题路由
        if self.topic_routing_enabled and notification_type:
            topic_id = self.topic_routes.get(notification_type)
            if topic_id is not None:
                return topic_id
        
        # 返回默认话题ID
        return self.topic_id

    async def _safe_send_message(self, text: str, parse_mode: str = None, notification_type: str = None) -> bool:
        """
        安全发送消息，包含完整的错误处理和重试机制
        
        Args:
            text: 消息文本
            parse_mode: 解析模式 ('HTML', 'Markdown' 或 None)
            notification_type: 通知类型，用于话题路由
        """
        if not self.enabled or not self.bot:
            return False
            
        # 检查熔断器状态
        if not self.circuit_breaker.can_execute():
            trading_logger.debug("消息发送被熔断器阻止")
            return False
        
        # 获取话题ID
        message_thread_id = self._get_topic_id(notification_type)
        
        for attempt in range(self.max_retry_attempts):
            try:
                await asyncio.wait_for(
                    self.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        parse_mode=parse_mode,
                        message_thread_id=message_thread_id  # 支持话题
                    ),
                    timeout=self.operation_timeout
                )
                
                self.circuit_breaker.record_success()
                return True
                
            except TimeoutError:
                self.error_stats['timeout_errors'] += 1
                trading_logger.warning(f"Telegram消息发送超时 (尝试 {attempt + 1}/{self.max_retry_attempts})")
                
            except BadRequest as e:
                self.error_stats['api_errors'] += 1
                # 对于API错误，不重试
                trading_logger.error(f"Telegram API错误: {e}")
                break
                
            except NetworkError as e:
                self.error_stats['network_errors'] += 1
                trading_logger.warning(f"Telegram网络错误: {e} (尝试 {attempt + 1}/{self.max_retry_attempts})")
                
            except Exception as e:
                self.error_stats['total_errors'] += 1
                trading_logger.error(f"Telegram未知错误: {e} (尝试 {attempt + 1}/{self.max_retry_attempts})")
            
            # 记录错误统计
            self.error_stats['last_error_time'] = datetime.now()
            self.circuit_breaker.record_failure()
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retry_attempts - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避
        
        # 所有重试都失败
        self.error_stats['total_errors'] += 1
        return False

    async def send_message(self, text: str, parse_mode: str = None, notification_type: str = None) -> bool:
        """
        发送消息的公共接口
        
        Args:
            text: 消息文本  
            parse_mode: 解析模式
            notification_type: 通知类型，用于话题路由
        """
        return await self._safe_send_message(text, parse_mode, notification_type)
    
    async def send_trade_notification(self, trade_data: Dict[str, Any]):
        """
        发送交易通知
        """
        if not self.trade_notifications:
            return
            
        try:
            # 直接执行，等待结果
            await self._send_trade_notification_internal(trade_data)
            
        except Exception as e:
            trading_logger.error(f"发送交易通知失败: {e}", exc_info=True)
    
    async def _send_trade_notification_internal(self, trade_data: Dict[str, Any]):
        """内部交易通知逻辑"""
        try:
            if trade_data.get('action') == 'open':
                message = self._format_open_trade_message(trade_data)
            elif trade_data.get('action') == 'close':
                message = self._format_close_trade_message(trade_data)
            else:
                message = self._format_general_trade_message(trade_data)
                
            await self._safe_send_message(message, 'HTML', 'trade')
            
        except Exception as e:
            trading_logger.error(f"发送交易通知失败: {e}", exc_info=True)
    
    async def send_error_notification(self, error_data: Dict[str, Any]):
        """
        发送错误通知
        """
        if not self.error_notifications:
            return
            
        try:
            # 直接执行，等待结果
            await self._send_error_notification_internal(error_data)
            
        except Exception as e:
            trading_logger.error(f"发送错误通知失败: {e}", exc_info=True)
    
    async def _send_error_notification_internal(self, error_data: Dict[str, Any]):
        """内部错误通知逻辑"""
        try:
            message = self._format_error_message(error_data)
            await self._safe_send_message(message, 'HTML', 'error')
            
        except Exception as e:
            trading_logger.error(f"发送错误通知失败: {e}", exc_info=True)
    
    async def send_status_notification(self, status_data: Dict[str, Any]):
        """
        发送状态通知
        """
        if not self.status_notifications:
            return
            
        try:
            # 直接执行，等待结果
            await self._send_status_notification_internal(status_data)
            
        except Exception as e:
            trading_logger.error(f"发送状态通知失败: {e}", exc_info=True)
    
    async def _send_status_notification_internal(self, status_data: Dict[str, Any]):
        """内部状态通知逻辑"""
        try:
            message = self._format_status_message(status_data)
            await self._safe_send_message(message, 'HTML', 'status')
            
        except Exception as e:
            trading_logger.error(f"发送状态通知失败: {e}", exc_info=True)

    # =================== 消息格式化方法 ===================
    
    def _format_open_trade_message(self, trade_data: Dict[str, Any]) -> str:
        """格式化开仓通知消息"""
        symbol = trade_data.get('symbol', 'N/A')
        side = trade_data.get('side', 'N/A')
        price = trade_data.get('price', 0)
        amount = trade_data.get('amount', 0)
        stop_loss = trade_data.get('stop_loss', 0)
        take_profit = trade_data.get('take_profit', 0)
        timestamp = trade_data.get('timestamp', datetime.now())
        
        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        
        message = f"""
{side_emoji} <b>开仓通知</b>

<b>交易对:</b> <code>{symbol}</code>
<b>方向:</b> <code>{side.upper()}</code>
<b>开仓价:</b> <code>${price:.6f}</code>
<b>数量:</b> <code>{amount:.6f}</code>
<b>止损:</b> <code>${stop_loss:.6f}</code>
<b>止盈:</b> <code>${take_profit:.6f}</code>
<b>时间:</b> <code>{timestamp.strftime('%H:%M:%S')}</code>
"""
        return message.strip()
    
    def _format_close_trade_message(self, trade_data: Dict[str, Any]) -> str:
        """格式化平仓通知消息"""
        symbol = trade_data.get('symbol', 'N/A')
        side = trade_data.get('side', 'N/A')
        close_price = trade_data.get('close_price', 0)
        pnl = trade_data.get('pnl', 0)
        pnl_pct = trade_data.get('pnl_pct', 0)
        duration = trade_data.get('duration', 0)
        reason = trade_data.get('reason', 'Manual')
        timestamp = trade_data.get('timestamp', datetime.now())
        
        pnl_emoji = "💚" if pnl >= 0 else "❤️"
        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        
        message = f"""
{side_emoji} <b>平仓通知</b>

<b>交易对:</b> <code>{symbol}</code>
<b>方向:</b> <code>{side.upper()}</code>
<b>平仓价:</b> <code>${close_price:.6f}</code>
{pnl_emoji} <b>盈亏:</b> <code>${pnl:.2f}</code> (<code>{pnl_pct:+.2f}%</code>)
<b>持仓时间:</b> <code>{duration} 分钟</code>
<b>平仓原因:</b> <code>{reason}</code>
<b>时间:</b> <code>{timestamp.strftime('%H:%M:%S')}</code>
"""
        return message.strip()
    
    def _format_error_message(self, error_data: Dict[str, Any]) -> str:
        """格式化错误通知消息"""
        error_type = error_data.get('type', 'Unknown')
        error_message = error_data.get('message', 'N/A')
        timestamp = error_data.get('timestamp', datetime.now())
        
        message = f"""
⚠️ <b>系统错误</b>

<b>错误类型:</b> <code>{error_type}</code>
<b>错误信息:</b> <code>{error_message}</code>
<b>时间:</b> <code>{timestamp.strftime('%H:%M:%S')}</code>
"""
        return message.strip()
    
    def _format_status_message(self, status_data: Dict[str, Any]) -> str:
        """格式化状态通知消息"""
        status = status_data.get('status', 'Unknown')
        message_text = status_data.get('message', '')
        timestamp = status_data.get('timestamp', datetime.now())
        
        status_emoji = {
            'running': '🟢',
            'stopped': '🔴',
            'paused': '🟡',
            'error': '⚠️',
            'healthy': '✅',
            'testing': '🧪'
        }.get(status.lower(), '🔵')
        
        message = f"""
{status_emoji} <b>系统状态</b>

<b>状态:</b> <code>{status.upper()}</code>
<b>信息:</b> <code>{message_text}</code>
<b>时间:</b> <code>{timestamp.strftime('%H:%M:%S')}</code>
"""
        return message.strip()
    
    def _format_general_trade_message(self, trade_data: Dict[str, Any]) -> str:
        """格式化通用交易消息"""
        return f"📊 交易更新: {trade_data}"
    
    # =================== 命令处理器（带错误保护） ===================
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        try:
            welcome_message = """
🚀 <b>欢迎使用 CryptoPulse Trader</b>

这是一个加密货币量化交易机器人，专注于捕捉短期市场波动机会。

<b>可用命令:</b>
• <code>/help</code> - 显示帮助信息
• <code>/status</code> - 显示系统状态
• <code>/balance</code> - 显示账户余额
• <code>/profit</code> - 显示盈亏统计
• <code>/trades</code> - 显示最近交易
• <code>/positions</code> - 显示当前持仓
• <code>/health</code> - 显示机器人健康状态

使用 <code>/help</code> 查看详细命令说明。
"""
            await update.message.reply_text(welcome_message, parse_mode='HTML')
        except Exception as e:
            trading_logger.error(f"处理/start命令失败: {e}", exc_info=True)
            await self._send_error_reply(update, "处理命令时发生错误")
    
    async def _health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/health命令"""
        try:
            circuit_status = self.circuit_breaker.get_status()
            
            health_emoji = "🟢" if self.is_healthy else "🔴"
            circuit_emoji = {
                "CLOSED": "🟢",
                "OPEN": "🔴", 
                "HALF_OPEN": "🟡"
            }.get(circuit_status["state"], "⚪")
            
            message = f"""
{health_emoji} <b>Telegram Bot 健康状态</b>

<b>整体状态:</b> <code>{'健康' if self.is_healthy else '异常'}</code>
{circuit_emoji} <b>熔断器状态:</b> <code>{circuit_status['state']}</code>
<b>失败次数:</b> <code>{circuit_status['failure_count']}</code>

<b>错误统计:</b>
• 总错误: <code>{self.error_stats['total_errors']}</code>
• 网络错误: <code>{self.error_stats['network_errors']}</code>
• API错误: <code>{self.error_stats['api_errors']}</code>
• 超时错误: <code>{self.error_stats['timeout_errors']}</code>

<b>最后错误:</b> <code>{self.error_stats['last_error_time'].strftime('%H:%M:%S') if self.error_stats['last_error_time'] else 'None'}</code>
"""
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            trading_logger.error(f"处理/health命令失败: {e}", exc_info=True)
            await self._send_error_reply(update, "获取健康状态失败")
    
    async def _send_error_reply(self, update: Update, error_msg: str):
        """发送错误回复"""
        try:
            await update.message.reply_text(f"❌ {error_msg}")
        except Exception as e:
            trading_logger.error(f"发送错误回复失败: {e}")
    
    # =================== 其他命令处理器（简化版，实际应用中需要完整实现） ===================
    
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/help命令"""
        try:
            help_message = """
📚 <b>CryptoPulse Trader 命令帮助</b>

<b>查询命令:</b>
• <code>/status</code> - 显示系统运行状态
• <code>/balance</code> - 显示账户余额信息
• <code>/profit [天数]</code> - 显示盈亏统计
• <code>/trades [数量]</code> - 显示最近交易记录
• <code>/positions</code> - 显示当前持仓情况
• <code>/health</code> - 显示机器人健康状态

<b>统计命令:</b>
• <code>/daily [天数]</code> - 显示每日盈亏
• <code>/weekly</code> - 显示每周统计
• <code>/monthly</code> - 显示每月统计

<b>设置命令:</b>
• <code>/config</code> - 显示当前配置
• <code>/version</code> - 显示版本信息
• <code>/stop_notifications</code> - 停止通知
• <code>/start_notifications</code> - 开启通知

❓ 如有问题，请查看日志或联系开发者。
"""
            await update.message.reply_text(help_message, parse_mode='HTML')
        except Exception as e:
            trading_logger.error(f"处理/help命令失败: {e}", exc_info=True)
            await self._send_error_reply(update, "显示帮助失败")
    
    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/status命令"""
        try:
            status_data = await self._get_system_status()
            
            message = f"""
📊 <b>系统状态概览</b>

<b>机器人状态:</b> <code>{status_data.get('bot_status', 'Unknown')}</code>
<b>运行时间:</b> <code>{status_data.get('uptime', 'Unknown')}</code>
<b>当前时间:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>

<b>交易统计:</b>
• 开放交易: <code>{status_data.get('open_trades', 0)}</code>
• 今日交易: <code>{status_data.get('trades_today', 0)}</code>
• 总利润: <code>${status_data.get('total_profit', 0):.2f}</code>

<b>系统健康:</b>
• Telegram: <code>{'正常' if self.is_healthy else '异常'}</code>
• 内存使用: <code>{status_data.get('memory_usage', 'Unknown')}</code>
• CPU使用: <code>{status_data.get('cpu_usage', 'Unknown')}</code>
"""
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            trading_logger.error(f"处理/status命令失败: {e}", exc_info=True)
            await self._send_error_reply(update, "获取系统状态失败")

    # 其他命令处理器...（为简洁省略，但都应该有相同的错误处理结构）
    async def _balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _profit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _trades_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _daily_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _weekly_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _monthly_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _version_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _config_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_error_reply(update, "功能开发中...")
    
    async def _stop_notifications_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.trade_notifications = False
        self.error_notifications = False
        self.status_notifications = False
        await update.message.reply_text("🔕 所有通知已关闭")
    
    async def _start_notifications_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.trade_notifications = True
        self.error_notifications = True
        self.status_notifications = True
        await update.message.reply_text("🔔 所有通知已开启")
    
    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """全局错误处理器"""
        try:
            trading_logger.error(f"Telegram bot错误: {context.error}", exc_info=True)
            
            # 记录错误但不影响主程序
            self.error_stats['total_errors'] += 1
            self.error_stats['last_error_time'] = datetime.now()
            self.error_stats['last_error_message'] = str(context.error)
            
        except Exception as e:
            trading_logger.error(f"错误处理器本身出错: {e}", exc_info=True)
    
    # =================== 数据获取方法（模拟数据，需要与实际系统集成） ===================
    
    async def _get_system_status(self) -> Dict[str, Any]:
        """获取系统状态（模拟数据，需要与实际系统集成）"""
        return {
            'bot_status': 'Running',
            'total_balance': 1000.0,
            'open_trades': 2,
            'trades_today': 5,
            'total_profit': 25.50,
            'win_rate': 68.5,
            'uptime': '2天3小时',
            'memory_usage': '156MB',
            'cpu_usage': '15%'
        }
    
    # =================== 状态查询方法 ===================
    
    def get_health_status(self) -> Dict[str, Any]:
        """获取健康状态"""
        return {
            'is_healthy': self.is_healthy,
            'is_enabled': self.enabled,
            'circuit_breaker': self.circuit_breaker.get_status(),
            'error_stats': self.error_stats.copy(),
            'notifications': {
                'trade': self.trade_notifications,
                'error': self.error_notifications,
                'status': self.status_notifications
            }
        }
    
    def update_trading_data(self, data: Dict[str, Any]):
        """更新交易数据（线程安全）"""
        try:
            self.trading_data.update(data)
            trading_logger.debug(f"Telegram bot交易数据已更新: {list(data.keys())}")
        except Exception as e:
            trading_logger.error(f"更新交易数据失败: {e}", exc_info=True) 