"""
CryptoPulse Trader 主程序
加密货币量化交易机器人，专注于捕捉短期市场波动机会
"""

import signal
import sys
from datetime import datetime
import threading
import asyncio

# 导入核心模块
from utils.config_manager import ConfigManager
from utils.logger import setup_logging, trading_logger
from utils.notification_manager import NotificationManager
from scanner.websocket_scanner import WebSocketMarketScanner as MarketScanner
from executor.binance_executor import BinanceExecutor as Trader
from risk.risk_manager import RiskManager


class CryptoPulseTrader:
    """CryptoPulse Trader 主类"""
    
    def __init__(self):
        """初始化交易机器人"""
        self.is_running = False
        self.start_time = None
        
        # 核心组件（按重要性排序，通知系统故障不影响交易）
        self.config_manager = None
        self.notification_manager = None  # 非关键组件，故障时可以继续运行
        self.market_scanner = None
        self.trend_analyzer = None
        self.executor = None
        self.risk_manager = None
        
        # 系统状态
        self.system_status = {
            'start_time': None,
            'last_scan_time': None,
            'total_scans': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'notifications_sent': 0,
            'notification_failures': 0
        }
        
        # 错误统计
        self.error_stats = {
            'scan_errors': 0,
            'trade_errors': 0,
            'notification_errors': 0,
            'critical_errors': 0,
            'last_error_time': None
        }
        
        # 初始化组件
        self._initialize_components()
    
    def _initialize_components(self):
        """初始化核心组件"""
        try:
            # 1. 初始化配置管理器
            self.config_manager = ConfigManager()
            trading_logger.info("配置管理器初始化成功")
            
            # 2. 初始化通知管理器
            self.notification_manager = NotificationManager(self.config_manager)
            trading_logger.info("通知管理器初始化成功")
            
            # 3. 创建数据队列用于WebSocket数据传递
            import asyncio
            self.data_queue = asyncio.Queue()
            trading_logger.info("数据队列初始化成功")
            
            # 4. 初始化市场扫描器 (传入数据队列)
            self.market_scanner = MarketScanner(
                config=self.config_manager.config,
                testnet=self.config_manager.config.get('exchange', {}).get('testnet', True),
                data_queue=self.data_queue  # 重要：传入数据队列
            )
            
            # 5. 初始化交易执行器
            self.executor = Trader(self.config_manager)
            
            # 6. 设置扫描器的执行器
            self.market_scanner.set_executor(self.executor)
            
            # 7. 初始化风险管理器
            self.risk_manager = RiskManager(self.config_manager)
            
            # 8. 获取扫描器的策略实例，用于实时信号处理
            self.strategy = self.market_scanner.strategy
            trading_logger.info("策略实例获取成功")
            
            trading_logger.info("核心交易组件初始化成功")
            
            # 7. 设置信号处理
            self._setup_signal_handlers()
            
        except Exception as e:
            trading_logger.error(f"组件初始化失败: {e}", exc_info=True)
            raise
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            trading_logger.info(f"接收到信号 {signum}，正在优雅关闭...")
            self.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def start(self):
        """启动交易机器人"""
        if self.is_running:
            trading_logger.warning("交易机器人已在运行")
            return
        
        try:
            self.is_running = True
            self.start_time = datetime.now()
            self.system_status['start_time'] = self.start_time
            
            trading_logger.info("=" * 50)
            trading_logger.info("🚀 CryptoPulse Trader 启动中...")
            trading_logger.info(f"启动时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            trading_logger.info("=" * 50)
            
            # 发送启动通知（非阻塞，失败不影响系统）
            self._safe_notify_system_start()
            
            # 运行主循环
            self._run_main_loop()
            
        except KeyboardInterrupt:
            trading_logger.info("收到中断信号，正在停止...")
        except Exception as e:
            trading_logger.error(f"启动失败: {e}", exc_info=True)
            self.error_stats['critical_errors'] += 1
        finally:
            self.stop()
    
    def _safe_notify_system_start(self):
        """安全发送系统启动通知"""
        try:
            if self.notification_manager:
                self.notification_manager.notify_system_start()
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.warning(f"发送启动通知失败（不影响系统运行）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def _run_main_loop(self):
        """运行主循环 - 支持实时数据处理"""
        scan_interval = self.config_manager.config.get('trading', {}).get('scan_interval', 3600)  # 默认1小时
        
        trading_logger.info(f"主循环已启动，扫描间隔: {scan_interval}秒")
        
        # 🚀 启动异步事件循环来处理实时数据和定时任务
        asyncio.run(self._run_async_main_loop(scan_interval))
    
    async def _run_async_main_loop(self, scan_interval):
        """异步主循环 - 同时处理定时任务和实时数据"""
        trading_logger.info("🚀 启动异步主循环，支持实时数据处理")
        
        # 创建任务
        tasks = []
        
        # 1. 定时交易周期任务
        trading_cycle_task = asyncio.create_task(self._periodic_trading_cycle(scan_interval))
        tasks.append(trading_cycle_task)
        
        # 2. 实时数据处理任务
        data_processing_task = asyncio.create_task(self._process_realtime_data())
        tasks.append(data_processing_task)
        
        try:
            # 等待所有任务完成（或被中断）
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            trading_logger.info("收到中断信号，正在停止异步任务...")
            for task in tasks:
                task.cancel()
        except Exception as e:
            trading_logger.error(f"异步主循环发生错误: {e}", exc_info=True)
        finally:
            trading_logger.info("异步主循环已停止")
    
    async def _periodic_trading_cycle(self, scan_interval):
        """定时交易周期任务"""
        while self.is_running:
            try:
                cycle_start_time = asyncio.get_event_loop().time()
                
                # 执行一个交易周期
                await self._execute_trading_cycle()
                
                # 计算执行时间
                cycle_duration = asyncio.get_event_loop().time() - cycle_start_time
                trading_logger.info(f"交易周期完成，耗时: {cycle_duration:.2f}秒")
                
                # 等待下一个周期
                sleep_time = max(0, scan_interval - cycle_duration)
                if sleep_time > 0:
                    trading_logger.info(f"等待 {sleep_time:.0f} 秒后开始下一个周期")
                    await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                trading_logger.info("定时交易周期任务被取消")
                break
            except Exception as e:
                trading_logger.error(f"定时交易周期发生错误: {e}", exc_info=True)
                self.error_stats['critical_errors'] += 1
                self._safe_notify_error("Trading Cycle Error", str(e))
                await asyncio.sleep(60)  # 短暂休息
    
    async def _process_realtime_data(self):
        """处理来自WebSocket的实时数据"""
        trading_logger.info("🔄 开始处理WebSocket实时数据流...")
        
        while self.is_running:
            try:
                # 从队列中获取ticker数据（1秒超时）
                ticker_data = await asyncio.wait_for(self.data_queue.get(), timeout=1.0)
                
                # 📊 处理ticker数据
                await self._handle_ticker_data(ticker_data)
                
                # 标记任务完成
                self.data_queue.task_done()
                
            except asyncio.TimeoutError:
                # 超时是正常的，继续循环
                continue
            except asyncio.CancelledError:
                trading_logger.info("实时数据处理任务被取消")
                break
            except Exception as e:
                trading_logger.error(f"处理实时数据时发生错误: {e}", exc_info=True)
                self.error_stats['critical_errors'] += 1
                await asyncio.sleep(1)  # 短暂休息
    
    async def _handle_ticker_data(self, ticker_data):
        """处理单个ticker数据并生成交易信号"""
        try:
            symbol = ticker_data['symbol']
            price = ticker_data['close']
            
            # 📈 使用策略分析市场数据
            signal = self.strategy.analyze_market(ticker_data)
            
            if signal:
                # 🎯 生成了交易信号！
                trading_logger.info(f"🎯 策略生成信号: {signal['type']} {signal['symbol']} @{signal['price']}")
                
                # 执行风险检查
                approved_signals = self._execute_risk_check([signal])
                
                if approved_signals:
                    # 执行交易
                    self._execute_trades(approved_signals)
                else:
                    trading_logger.info(f"信号被风险管理器拒绝: {signal['symbol']}")
            
        except Exception as e:
            trading_logger.error(f"处理ticker数据失败 {ticker_data.get('symbol', 'unknown')}: {e}", exc_info=True)
    
    async def _execute_trading_cycle(self):
        """执行一个完整的交易周期"""
        try:
            trading_logger.info("开始新的交易周期")
            self.system_status['total_scans'] += 1
            self.system_status['last_scan_time'] = datetime.now()
            
            # 1. 市场扫描（关键步骤）
            candidates = await self._execute_market_scan()
            if not candidates:
                trading_logger.info("未发现交易候选")
                return
            
            # 2. 趋势分析（关键步骤）
            signals = self._execute_trend_analysis(candidates)
            if not signals:
                trading_logger.info("未产生交易信号")
                return
            
            # 3. 风险检查（关键步骤）
            approved_signals = self._execute_risk_check(signals)
            if not approved_signals:
                trading_logger.info("所有信号被风险管理器拒绝")
                return
            
            # 4. 执行交易（关键步骤）
            self._execute_trades(approved_signals)
            
        except Exception as e:
            trading_logger.error(f"交易周期执行失败: {e}", exc_info=True)
            self.error_stats['critical_errors'] += 1
            self._safe_notify_error("Trading Cycle Error", str(e))
    
    async def _execute_market_scan(self):
        """执行市场扫描"""
        try:
            trading_logger.info("执行市场扫描...")
            
            # 创建停止事件
            stop_event = threading.Event()
            candidates = await self.market_scanner.scan_market(stop_event)
            
            if candidates:
                trading_logger.info(f"市场扫描完成，发现 {len(candidates)} 个候选币种")
                # 记录扫描结果（非阻塞通知）
                self._safe_notify_scan_result(candidates)
            else:
                trading_logger.info("市场扫描完成，未发现候选币种")
            
            return candidates
            
        except Exception as e:
            trading_logger.error(f"市场扫描失败: {e}", exc_info=True)
            self.error_stats['scan_errors'] += 1
            self._safe_notify_error("Market Scan Error", str(e))
            return []
    
    def _execute_trend_analysis(self, candidates):
        """执行趋势分析"""
        try:
            trading_logger.info(f"对 {len(candidates)} 个候选币种执行趋势分析...")
            
            signals = []
            for candidate in candidates:
                try:
                    signal = self.trend_analyzer.analyze_trend(candidate)
                    if signal:
                        signals.append(signal)
                        trading_logger.info(f"生成信号: {signal.get('symbol')} - {signal.get('direction')}")
                except Exception as e:
                    trading_logger.warning(f"分析 {candidate.get('symbol')} 时失败: {e}")
                    continue
            
            trading_logger.info(f"趋势分析完成，生成 {len(signals)} 个交易信号")
            return signals
            
        except Exception as e:
            trading_logger.error(f"趋势分析失败: {e}", exc_info=True)
            self.error_stats['scan_errors'] += 1
            self._safe_notify_error("Trend Analysis Error", str(e))
            return []
    
    def _execute_risk_check(self, signals):
        """执行风险检查"""
        try:
            trading_logger.info(f"对 {len(signals)} 个信号执行风险检查...")
            
            approved_signals = []
            for signal in signals:
                try:
                    if self.risk_manager.check_risk(signal):
                        approved_signals.append(signal)
                        trading_logger.info(f"信号通过风险检查: {signal.get('symbol')}")
                    else:
                        trading_logger.info(f"信号被风险管理器拒绝: {signal.get('symbol')}")
                        
                        # 发送风险警告（非阻塞）
                        risk_msg = f"信号 {signal.get('symbol')} 被风险管理器拒绝"
                        self._safe_notify_risk_warning(risk_msg)
                        
                except Exception as e:
                    trading_logger.warning(f"检查信号 {signal.get('symbol')} 风险时失败: {e}")
                    continue
            
            trading_logger.info(f"风险检查完成，批准 {len(approved_signals)} 个信号")
            return approved_signals
            
        except Exception as e:
            trading_logger.error(f"风险检查失败: {e}", exc_info=True)
            self.error_stats['scan_errors'] += 1
            self._safe_notify_error("Risk Check Error", str(e))
            return []
    
    def _execute_trades(self, signals):
        """执行交易"""
        try:
            trading_logger.info(f"执行 {len(signals)} 个交易...")
            
            trade_results = []
            for signal in signals:
                try:
                    result = self.executor.execute_trade(signal)
                    trade_results.append(result)
                    
                    if result.get('success'):
                        self.system_status['successful_trades'] += 1
                        trading_logger.info(f"交易成功: {result}")
                        
                        # 发送交易成功通知（非阻塞）
                        self._safe_notify_trade_success(result)
                    else:
                        self.system_status['failed_trades'] += 1
                        trading_logger.error(f"交易失败: {result}")
                        
                        # 发送交易失败通知（非阻塞）
                        self._safe_notify_trade_failure(result)
                        
                except Exception as e:
                    self.system_status['failed_trades'] += 1
                    self.error_stats['trade_errors'] += 1
                    trading_logger.error(f"执行交易 {signal.get('symbol')} 时失败: {e}", exc_info=True)
                    
                    # 发送交易错误通知（非阻塞）
                    self._safe_notify_error("Trade Execution Error", f"{signal.get('symbol')}: {str(e)}")
                    continue
            
            trading_logger.info(f"交易执行完成，成功: {len([r for r in trade_results if r.get('success')])}, 失败: {len([r for r in trade_results if not r.get('success')])}")
            
        except Exception as e:
            trading_logger.error(f"交易执行失败: {e}", exc_info=True)
            self.error_stats['trade_errors'] += 1
            self._safe_notify_error("Trade Execution Error", str(e))
    
    # =================== 安全通知方法（所有通知都是非阻塞的） ===================
    
    def _safe_notify_scan_result(self, candidates):
        """安全发送扫描结果通知"""
        try:
            if self.notification_manager:
                # 这里可以根据需要选择发送简要或详细的扫描结果
                pass  # 暂时不发送扫描结果通知，避免过多通知
        except Exception as e:
            trading_logger.debug(f"发送扫描结果通知失败（忽略）: {e}")
            self.error_stats['notification_errors'] += 1
    
    def _safe_notify_trade_success(self, trade_result):
        """安全发送交易成功通知"""
        try:
            if self.notification_manager:
                # 提取交易信息
                symbol = trade_result.get('symbol', 'Unknown')
                side = trade_result.get('side', 'Unknown')
                price = trade_result.get('price', 0)
                amount = trade_result.get('amount', 0)
                
                self.notification_manager.notify_trade_open(
                    symbol=symbol,
                    side=side,
                    price=price,
                    amount=amount
                )
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.debug(f"发送交易成功通知失败（忽略）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def _safe_notify_trade_failure(self, trade_result):
        """安全发送交易失败通知"""
        try:
            if self.notification_manager:
                error_msg = f"交易失败: {trade_result.get('symbol')} - {trade_result.get('error', 'Unknown error')}"
                self.notification_manager.notify_error("Trade Failed", error_msg)
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.debug(f"发送交易失败通知失败（忽略）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def _safe_notify_error(self, error_type, error_message):
        """安全发送错误通知"""
        try:
            if self.notification_manager:
                self.notification_manager.notify_error(error_type, error_message)
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.debug(f"发送错误通知失败（忽略）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def _safe_notify_risk_warning(self, warning_message):
        """安全发送风险警告通知"""
        try:
            if self.notification_manager:
                self.notification_manager.notify_risk_warning(warning_message)
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.debug(f"发送风险警告通知失败（忽略）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def stop(self):
        """停止交易机器人"""
        if not self.is_running:
            return
            
        try:
            trading_logger.info("=" * 50)
            trading_logger.info("🛑 CryptoPulse Trader 正在停止...")
            
            # 1. 停止主循环
            self.is_running = False
            
            # 2. 停止通知管理器
            if self.notification_manager:
                self.notification_manager.stop()
                trading_logger.info("通知管理器已停止")
            
            # 3. 停止市场扫描器
            if self.market_scanner:
                asyncio.run(self.market_scanner.stop_ws_connection())
                trading_logger.info("市场扫描器已停止")
            
            # 4. 停止交易执行器
            if self.executor:
                self.executor.stop()
                trading_logger.info("交易执行器已停止")
            
            # 5. 输出最终统计信息
            self._print_final_stats()
            
            # 6. 发送停止通知（非阻塞）
            self._safe_notify_system_stop()
            
            trading_logger.info("CryptoPulse Trader 已安全停止")
            trading_logger.info("=" * 50)
            
        except Exception as e:
            trading_logger.error(f"停止过程中发生错误: {e}", exc_info=True)
        finally:
            # 确保进程退出
            sys.exit(0)
    
    def _safe_notify_system_stop(self):
        """安全发送系统停止通知"""
        try:
            if self.notification_manager:
                self.notification_manager.notify_system_stop()
                self.system_status['notifications_sent'] += 1
        except Exception as e:
            trading_logger.warning(f"发送停止通知失败（忽略）: {e}")
            self.system_status['notification_failures'] += 1
            self.error_stats['notification_errors'] += 1
    
    def _print_final_stats(self):
        """输出最终统计信息"""
        try:
            if self.start_time:
                runtime = datetime.now() - self.start_time
                
                trading_logger.info(f"运行时长: {runtime}")
                trading_logger.info(f"总扫描次数: {self.system_status['total_scans']}")
                trading_logger.info(f"成功交易: {self.system_status['successful_trades']}")
                trading_logger.info(f"失败交易: {self.system_status['failed_trades']}")
                trading_logger.info(f"通知发送: {self.system_status['notifications_sent']}")
                trading_logger.info(f"通知失败: {self.system_status['notification_failures']}")
                
                # 错误统计
                error_values = [v for v in self.error_stats.values() if isinstance(v, (int, float))]
                total_errors = sum(error_values)
                trading_logger.info(f"总错误数: {total_errors}")
                
                if total_errors > 0:
                    trading_logger.info(f"  - 扫描错误: {self.error_stats['scan_errors']}")
                    trading_logger.info(f"  - 交易错误: {self.error_stats['trade_errors']}")
                    trading_logger.info(f"  - 通知错误: {self.error_stats['notification_errors']}")
                    trading_logger.info(f"  - 关键错误: {self.error_stats['critical_errors']}")
                
        except Exception as e:
            trading_logger.error(f"输出统计信息失败: {e}", exc_info=True)
    
    def get_status(self):
        """获取系统状态"""
        try:
            status = {
                'is_running': self.is_running,
                'start_time': self.start_time,
                'system_status': self.system_status.copy(),
                'error_stats': self.error_stats.copy(),
                'notification_manager_status': None
            }
            
            # 获取通知管理器状态（安全方式）
            try:
                if self.notification_manager:
                    status['notification_manager_status'] = self.notification_manager.get_status()
            except Exception as e:
                trading_logger.warning(f"获取通知管理器状态失败: {e}")
                status['notification_manager_status'] = {'error': str(e)}
            
            return status
            
        except Exception as e:
            trading_logger.error(f"获取系统状态失败: {e}", exc_info=True)
            return {'error': str(e)}


def main():
    """主函数"""
    try:
        # 设置日志
        setup_logging()
        
        # 创建并启动交易机器人
        trader = CryptoPulseTrader()
        trader.start()
        
    except Exception as e:
        trading_logger.error(f"程序启动失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main() 