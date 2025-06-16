"""
通知管理器
统一管理系统通知，支持多种通知渠道（Telegram、邮件等）
具备完整的错误处理和故障隔离机制，确保通知失败不影响主程序
"""

import asyncio
from typing import Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum
import threading
import queue

from utils.logger import trading_logger
from utils.config_manager import ConfigManager
from utils.telegram_bot import TelegramBot


class NotificationPriority(Enum):
    """通知优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class NotificationType(Enum):
    """通知类型"""
    TRADE_OPEN = "trade_open"
    TRADE_CLOSE = "trade_close" 
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    SYSTEM_ERROR = "system_error"
    RISK_WARNING = "risk_warning"
    MARKET_ALERT = "market_alert"
    STATUS_UPDATE = "status_update"


class NotificationFailsafe:
    """通知系统故障保护机制"""
    
    def __init__(self, max_failure_rate: float = 0.8, monitoring_window: int = 60):
        """
        初始化故障保护
        
        Args:
            max_failure_rate: 最大失败率阈值
            monitoring_window: 监控时间窗口（秒）
        """
        self.max_failure_rate = max_failure_rate
        self.monitoring_window = monitoring_window
        
        self.notifications_sent = 0
        self.notifications_failed = 0
        self.is_failsafe_active = False
        self.last_reset_time = datetime.now()
        
        self._lock = threading.Lock()
    
    def record_success(self):
        """记录成功通知"""
        with self._lock:
            self.notifications_sent += 1
            self._check_reset_counters()
    
    def record_failure(self):
        """记录失败通知"""
        with self._lock:
            self.notifications_failed += 1
            self._check_reset_counters()
            self._check_failsafe()
    
    def _check_reset_counters(self):
        """检查是否需要重置计数器"""
        now = datetime.now()
        if (now - self.last_reset_time).seconds >= self.monitoring_window:
            self.notifications_sent = 0
            self.notifications_failed = 0
            self.is_failsafe_active = False
            self.last_reset_time = now
    
    def _check_failsafe(self):
        """检查是否需要启动故障保护"""
        total = self.notifications_sent + self.notifications_failed
        if total >= 5:  # 至少有5次通知才开始检查
            failure_rate = self.notifications_failed / total
            if failure_rate >= self.max_failure_rate:
                self.is_failsafe_active = True
                trading_logger.warning(f"通知系统故障保护启动：失败率{failure_rate:.2%}")
    
    def should_block_notification(self) -> bool:
        """判断是否应该阻止通知"""
        with self._lock:
            return self.is_failsafe_active
    
    def get_status(self) -> Dict[str, Any]:
        """获取故障保护状态"""
        with self._lock:
            total = self.notifications_sent + self.notifications_failed
            failure_rate = (self.notifications_failed / total) if total > 0 else 0
            
            return {
                'is_active': self.is_failsafe_active,
                'sent': self.notifications_sent,
                'failed': self.notifications_failed,
                'failure_rate': failure_rate,
                'monitoring_window': self.monitoring_window,
                'last_reset': self.last_reset_time
            }


class NotificationManager:
    """
    通知管理器
    
    功能：
    1. 统一管理所有系统通知
    2. 支持优先级分级处理
    3. 异步队列处理，不阻塞主程序
    4. 故障自愈机制
    5. 通知去重和限流
    """
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化通知管理器
        
        Args:
            config_manager: 配置管理器实例
        """
        self.config_manager = config_manager
        self.config = config_manager.config
        
        # 通知渠道
        self.telegram_bot: Optional[TelegramBot] = None
        
        # 通知队列和处理
        self.notification_queue = queue.Queue(maxsize=1000)  # 限制队列大小
        self.telegram_queue = queue.Queue(maxsize=1000)  # Telegram专用队列
        self.is_running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.telegram_thread: Optional[threading.Thread] = None
        
        # 故障保护
        self.failsafe = NotificationFailsafe()
        
        # 通知统计
        self.stats = {
            'total_sent': 0,
            'total_failed': 0,
            'by_type': {},
            'by_priority': {},
            'last_notification_time': None,
            'start_time': datetime.now()
        }
        
        # 通知去重（防止短时间内重复通知）
        self.recent_notifications = {}  # hash -> timestamp
        self.dedup_window = 10  # 去重时间窗口（秒）
        
        # 初始化Telegram机器人（如果启用）
        self._init_telegram_bot()
        
        # 启动通知处理线程
        self.start()
    
    def _init_telegram_bot(self):
        """初始化Telegram机器人"""
        try:
            notification_config = self.config.get('notification', {})
            telegram_config = notification_config.get('telegram', {})
            
            if telegram_config.get('enabled', False):
                self.telegram_bot = TelegramBot(self.config_manager)
                trading_logger.info("Telegram通知已启用")
            else:
                trading_logger.info("Telegram通知未启用")
                
        except Exception as e:
            trading_logger.error(f"初始化Telegram机器人失败: {e}", exc_info=True)
            # 不影响主程序继续运行
            self.telegram_bot = None
    
    def start(self):
        """启动通知管理器"""
        if self.is_running:
            return
            
        try:
            self.is_running = True
            
            # 启动处理线程
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            
            # 启动Telegram专用线程
            if self.telegram_bot:
                self.telegram_thread = threading.Thread(target=self._telegram_worker_loop, daemon=True)
                self.telegram_thread.start()
                
                # 启动Telegram机器人（异步，安全方式）
                self._safe_start_telegram_bot()
            
            trading_logger.info("通知管理器已启动")
            
        except Exception as e:
            trading_logger.error(f"启动通知管理器失败: {e}", exc_info=True)
    
    def _telegram_worker_loop(self):
        """Telegram专用工作线程"""
        trading_logger.info("Telegram处理线程已启动")
        
        # 创建异步环境
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            while self.is_running:
                try:
                    # 获取Telegram通知（带超时）
                    try:
                        telegram_item = self.telegram_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    
                    # 处理Telegram通知
                    success = loop.run_until_complete(self._process_telegram_notification(telegram_item))
                    
                    # 更新统计
                    if success:
                        self.stats['total_sent'] += 1
                        self.failsafe.record_success()
                    else:
                        self.stats['total_failed'] += 1
                        self.failsafe.record_failure()
                    
                    # 标记任务完成
                    self.telegram_queue.task_done()
                    
                except Exception as e:
                    trading_logger.error(f"Telegram处理线程错误: {e}", exc_info=True)
                    
        finally:
            # 清理事件循环
            try:
                loop.close()
            except:
                pass
            trading_logger.info("Telegram处理线程已停止")
    
    async def _process_telegram_notification(self, item: Dict[str, Any]) -> bool:
        """处理Telegram通知"""
        try:
            notification_type = item['type']
            data = item['data']
            
            if notification_type in ['trade_open', 'trade_close']:
                await self.telegram_bot.send_trade_notification(data)
            elif notification_type == 'system_error':
                await self.telegram_bot.send_error_notification(data)
            elif notification_type in ['system_start', 'system_stop', 'status_update']:
                await self.telegram_bot.send_status_notification(data)
            elif notification_type == 'risk_warning':
                # 风险警告作为错误通知发送
                warning_data = {
                    'type': 'Risk Warning',
                    'message': data.get('message', ''),
                    'timestamp': datetime.now()
                }
                await self.telegram_bot.send_error_notification(warning_data)
            elif notification_type == 'market_alert':
                # 市场警报作为状态通知发送
                alert_data = {
                    'status': 'market_alert',
                    'message': data.get('message', ''),
                    'timestamp': datetime.now()
                }
                await self.telegram_bot.send_status_notification(alert_data)
            
            return True
            
        except Exception as e:
            trading_logger.error(f"处理Telegram通知失败: {e}", exc_info=True)
            return False
    
    def _worker_loop(self):
        """通知处理工作循环"""
        trading_logger.info("通知处理线程已启动")
        
        while self.is_running:
            try:
                # 获取通知（带超时，避免无限阻塞）
                try:
                    notification = self.notification_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 处理通知
                success = self._process_notification(notification)
                
                # 更新统计
                self._update_stats(notification, success)
                
                # 标记任务完成
                self.notification_queue.task_done()
                
            except Exception as e:
                trading_logger.error(f"通知处理线程错误: {e}", exc_info=True)
                # 继续运行，不因单次错误而停止
                
        trading_logger.info("通知处理线程已停止")
    
    def _process_notification(self, notification: Dict[str, Any]) -> bool:
        """
        处理单个通知
        
        Args:
            notification: 通知对象
            
        Returns:
            bool: 处理是否成功
        """
        try:
            notification_type = notification['type']
            data = notification['data']
            priority = notification['priority']
            
            trading_logger.debug(f"处理通知: {notification_type.value} (优先级: {priority.name})")
            
            # 发送到Telegram队列
            success = True
            if self.telegram_bot:
                try:
                    telegram_item = {
                        'type': notification_type.value,
                        'data': data,
                        'priority': priority.name
                    }
                    self.telegram_queue.put_nowait(telegram_item)
                except queue.Full:
                    trading_logger.warning("Telegram队列已满，丢弃通知")
                    success = False
            
            return success
            
        except Exception as e:
            trading_logger.error(f"处理通知时发生错误: {e}", exc_info=True)
            return False
    
    def _update_stats(self, notification: Dict[str, Any], success: bool):
        """更新通知统计"""
        try:
            if success:
                self.stats['total_sent'] += 1
            else:
                self.stats['total_failed'] += 1
            
            # 按类型统计
            type_name = notification['type'].value
            if type_name not in self.stats['by_type']:
                self.stats['by_type'][type_name] = {'sent': 0, 'failed': 0}
            
            if success:
                self.stats['by_type'][type_name]['sent'] += 1
            else:
                self.stats['by_type'][type_name]['failed'] += 1
            
            # 按优先级统计
            priority_name = notification['priority'].name
            if priority_name not in self.stats['by_priority']:
                self.stats['by_priority'][priority_name] = {'sent': 0, 'failed': 0}
            
            if success:
                self.stats['by_priority'][priority_name]['sent'] += 1
            else:
                self.stats['by_priority'][priority_name]['failed'] += 1
            
            # 更新最后通知时间
            self.stats['last_notification_time'] = datetime.now()
            
        except Exception as e:
            trading_logger.error(f"更新通知统计失败: {e}", exc_info=True)
    
    # =================== 便捷接口方法 ===================
    
    def notify_trade_open(self, symbol: str, side: str, price: float, amount: float, 
                         stop_loss: float = 0, take_profit: float = 0):
        """通知开仓"""
        data = {
            'action': 'open',
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.TRADE_OPEN, data, NotificationPriority.HIGH)
    
    def notify_trade_close(self, symbol: str, side: str, close_price: float, 
                          pnl: float, pnl_pct: float, duration: int, reason: str = 'Manual'):
        """通知平仓"""
        data = {
            'action': 'close',
            'symbol': symbol,
            'side': side,
            'close_price': close_price,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'duration': duration,
            'reason': reason,
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.TRADE_CLOSE, data, NotificationPriority.HIGH)
    
    def notify_system_start(self):
        """通知系统启动"""
        data = {
            'status': 'running',
            'message': 'CryptoPulse Trader 已启动',
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.SYSTEM_START, data, NotificationPriority.NORMAL)
    
    def notify_system_stop(self):
        """通知系统停止"""
        data = {
            'status': 'stopped',
            'message': 'CryptoPulse Trader 已停止',
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.SYSTEM_STOP, data, NotificationPriority.NORMAL)
    
    def notify_error(self, error_type: str, error_message: str, priority: NotificationPriority = NotificationPriority.NORMAL):
        """通知系统错误"""
        data = {
            'type': error_type,
            'message': error_message,
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.SYSTEM_ERROR, data, priority)
    
    def notify_risk_warning(self, message: str):
        """通知风险警告"""
        data = {
            'message': message,
            'timestamp': datetime.now()
        }
        self.send_notification(NotificationType.RISK_WARNING, data, NotificationPriority.HIGH)
    
    # =================== 状态查询方法 ===================
    
    def get_status(self) -> Dict[str, Any]:
        """获取通知管理器状态"""
        telegram_status = {}
        if self.telegram_bot:
            telegram_status = self.telegram_bot.get_health_status()
        
        return {
            'is_running': self.is_running,
            'queue_size': self.notification_queue.qsize(),
            'stats': self.stats.copy(),
            'failsafe': self.failsafe.get_status(),
            'telegram': telegram_status,
            'dedup_cache_size': len(self.recent_notifications)
        }
    
    def get_health_check(self) -> Dict[str, Any]:
        """获取健康检查结果"""
        status = self.get_status()
        
        # 计算健康评分
        health_score = 100
        issues = []
        
        # 检查运行状态
        if not status['is_running']:
            health_score -= 50
            issues.append("通知管理器未运行")
        
        # 检查队列积压
        queue_size = status['queue_size']
        if queue_size > 100:
            health_score -= 20
            issues.append(f"通知队列积压严重：{queue_size}条")
        elif queue_size > 50:
            health_score -= 10
            issues.append(f"通知队列积压：{queue_size}条")
        
        # 检查故障保护状态
        if status['failsafe']['is_active']:
            health_score -= 30
            issues.append("故障保护机制已激活")
        
        # 检查Telegram状态
        telegram_status = status.get('telegram', {})
        if telegram_status.get('is_enabled') and not telegram_status.get('is_healthy'):
            health_score -= 20
            issues.append("Telegram机器人异常")
        
        # 计算成功率
        total_notifications = status['stats']['total_sent'] + status['stats']['total_failed']
        success_rate = (status['stats']['total_sent'] / total_notifications * 100) if total_notifications > 0 else 100
        
        if success_rate < 80:
            health_score -= 20
            issues.append(f"通知成功率过低：{success_rate:.1f}%")
        elif success_rate < 90:
            health_score -= 10
            issues.append(f"通知成功率较低：{success_rate:.1f}%")
        
        # 确保健康评分不为负数
        health_score = max(0, health_score)
        
        return {
            'health_score': health_score,
            'is_healthy': health_score >= 80,
            'issues': issues,
            'success_rate': success_rate,
            'status': status
        }
    
    def _safe_start_telegram_bot(self):
        """安全启动Telegram机器人"""
        try:
            # 检查是否有运行的事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果有运行的事件循环，创建任务
                asyncio.create_task(self._start_telegram_bot())
            except RuntimeError:
                # 没有运行的事件循环，在新线程中启动
                def start_bot_in_thread():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self._start_telegram_bot())
                        loop.close()
                    except Exception as e:
                        trading_logger.error(f"后台启动Telegram机器人失败: {e}")
                
                bot_thread = threading.Thread(target=start_bot_in_thread, daemon=True)
                bot_thread.start()
        except Exception as e:
            trading_logger.error(f"安全启动Telegram机器人失败: {e}")
    
    async def _start_telegram_bot(self):
        """异步启动Telegram机器人"""
        try:
            if self.telegram_bot:
                await self.telegram_bot.start_bot()
        except Exception as e:
            trading_logger.error(f"启动Telegram机器人失败: {e}", exc_info=True)
    
    def stop(self):
        """停止通知管理器"""
        if not self.is_running:
            return
            
        try:
            self.is_running = False
            
            # 停止Telegram机器人（异步，安全方式）
            if self.telegram_bot:
                self._safe_stop_telegram_bot()
                 
            # 等待工作线程结束
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=5.0)
                
            # 等待Telegram线程结束
            if self.telegram_thread and self.telegram_thread.is_alive():
                self.telegram_thread.join(timeout=5.0)
            
            trading_logger.info("通知管理器已停止")
            
        except Exception as e:
            trading_logger.error(f"停止通知管理器失败: {e}", exc_info=True)
    
    def _safe_stop_telegram_bot(self):
        """安全停止Telegram机器人"""
        try:
            # 检查是否有运行的事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果有运行的事件循环，创建任务
                asyncio.create_task(self._stop_telegram_bot())
            except RuntimeError:
                # 没有运行的事件循环，在新线程中停止
                def stop_bot_in_thread():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self._stop_telegram_bot())
                        loop.close()
                    except Exception as e:
                        trading_logger.error(f"后台停止Telegram机器人失败: {e}")
                
                bot_thread = threading.Thread(target=stop_bot_in_thread, daemon=True)
                bot_thread.start()
                # 给停止操作一些时间
                bot_thread.join(timeout=3.0)
        except Exception as e:
            trading_logger.error(f"安全停止Telegram机器人失败: {e}")
    
    async def _stop_telegram_bot(self):
        """异步停止Telegram机器人"""
        try:
            if self.telegram_bot:
                await self.telegram_bot.stop_bot()
        except Exception as e:
            trading_logger.error(f"停止Telegram机器人失败: {e}", exc_info=True)
    
    def send_notification(
        self,
        notification_type: Union[NotificationType, str],
        data: Dict[str, Any],
        priority: NotificationPriority = NotificationPriority.NORMAL
    ) -> bool:
        """
        发送通知（非阻塞）
        
        Args:
            notification_type: 通知类型
            data: 通知数据
            priority: 通知优先级
            
        Returns:
            bool: 是否成功加入队列
        """
        try:
            # 故障保护检查
            if self.failsafe.should_block_notification():
                trading_logger.debug("通知被故障保护机制阻止")
                return False
            
            # 转换类型
            if isinstance(notification_type, str):
                notification_type = NotificationType(notification_type)
            
            # 创建通知对象
            notification = {
                'type': notification_type,
                'data': data,
                'priority': priority,
                'timestamp': datetime.now(),
                'retry_count': 0
            }
            
            # 去重检查
            if self._is_duplicate_notification(notification):
                trading_logger.debug(f"重复通知已忽略: {notification_type}")
                return False
            
            # 加入队列
            try:
                self.notification_queue.put_nowait(notification)
                return True
            except queue.Full:
                trading_logger.warning("通知队列已满，丢弃通知")
                return False
                
        except Exception as e:
            trading_logger.error(f"发送通知失败: {e}", exc_info=True)
            return False
    
    def _is_duplicate_notification(self, notification: Dict[str, Any]) -> bool:
        """检查是否为重复通知"""
        try:
            # 生成通知hash
            notification_hash = self._generate_notification_hash(notification)
            now = datetime.now()
            
            # 清理过期的去重记录
            self._cleanup_dedup_records(now)
            
            # 检查是否重复
            if notification_hash in self.recent_notifications:
                last_time = self.recent_notifications[notification_hash]
                if (now - last_time).seconds < self.dedup_window:
                    return True
            
            # 记录此次通知
            self.recent_notifications[notification_hash] = now
            return False
            
        except Exception as e:
            trading_logger.error(f"去重检查失败: {e}", exc_info=True)
            return False
    
    def _generate_notification_hash(self, notification: Dict[str, Any]) -> str:
        """生成通知hash用于去重"""
        try:
            type_str = notification['type'].value
            data = notification['data']
            
            # 对于交易通知，使用symbol+action
            if type_str in ['trade_open', 'trade_close']:
                symbol = data.get('symbol', '')
                action = data.get('action', '')
                return f"{type_str}_{symbol}_{action}"
            
            # 对于错误通知，使用error_type
            elif type_str == 'system_error':
                error_type = data.get('type', '')
                return f"{type_str}_{error_type}"
            
            # 其他通知只按类型去重
            else:
                return type_str
                
        except Exception:
            return str(notification['type'])
    
    def _cleanup_dedup_records(self, now: datetime):
        """清理过期的去重记录"""
        try:
            expired_keys = []
            for key, timestamp in self.recent_notifications.items():
                if (now - timestamp).seconds > self.dedup_window * 2:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self.recent_notifications[key]
                
        except Exception as e:
            trading_logger.error(f"清理去重记录失败: {e}", exc_info=True) 