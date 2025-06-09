from utils.config_manager import ConfigManager
from utils.contract_pairs_manager import ContractPairsManager
from scanner.websocket_scanner import WebSocketMarketScanner
from executor.binance_executor import BinanceExecutor
from risk.risk_manager import RiskManager
from utils.logger import trading_logger, setup_logging
# Import signal type constants
import asyncio
import os
import signal
import threading

class CryptoPulseTrader:
    """加密货币脉冲交易系统"""
    
    def __init__(self):
        """初始化交易系统"""
        # 加载配置
        self.config = ConfigManager()
        
        # **** 初始化日志系统 ****
        # 从配置中获取日志级别，默认为 "INFO"
        log_level_from_config = self.config.get('logging.level', "INFO")
        console_enabled = self.config.get('logging.console_enabled', True)
        file_enabled = self.config.get('logging.file_enabled', True)
        third_party_log_level = self.config.get('logging.third_party_level', "WARNING")

        # 配置日志系统
        setup_logging(
            level_name_str=log_level_from_config,
            log_to_console=console_enabled,
            log_to_file=file_enabled,
            third_party_level_str=third_party_log_level
        )
        # **************************
        
        trading_logger.info("CryptoPulseTrader initialized after logging setup.") # First log after setup

        # 初始化合约交易对管理器
        self.contract_pairs_manager = ContractPairsManager()
        
        # 初始化风险管理器
        self.risk_manager = RiskManager(self.config)
        
        # 初始化交易执行器
        self.executor = BinanceExecutor(self.config)
        
        # 创建停止事件
        self.stop_event = threading.Event()
        
        # Create data queue for communication between scanner and other components (e.g., TrendTracker)
        self.data_queue = asyncio.Queue()

        # Determine testnet status from config
        testnet_active = self.config.get('api.binance.testnet', True) 
        trading_logger.info(f"DEBUG: Config value for 'api.binance.testnet': {self.config.get('api.binance.testnet')}")
        trading_logger.info(f"DEBUG: Environment BINANCE_TESTNET: {os.getenv('BINANCE_TESTNET')}")
        trading_logger.info(f"Configuring components for Testnet: {testnet_active}")

        # 初始化市场扫描器
        self.scanner = WebSocketMarketScanner(
            config=self.config,
            exchange='binance',
            min_volume_usdt=self.config.get('scanner.min_volume_usdt', 1000000),
            top_n=self.config.get('scanner.max_candidates', 15),
            kline_interval=self.config.get('scanner.kline_interval', '1m'),
            data_queue=self.data_queue,
            testnet=testnet_active
        )
        
        # 设置交易执行器
        self.scanner.set_executor(self.executor)
        
        # 设置策略实例到扫描器，启用动态watchlist管理
        # 策略已在scanner内部初始化，我们只需要设置回自身以启用动态管理
        self.scanner.set_strategy(self.scanner.strategy)
        
        # 设置信号处理
        self.setup_signal_handlers()
        
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            trading_logger.info("Signal received, setting stop_event...")
            self.stop_event.set()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
    async def process_data_queue(self):
        """Processes kline data from the data_queue and generates trading signals."""
        trading_logger.info("Starting data queue processor...")
        while not self.stop_event.is_set():
            try:
                kline_data = await asyncio.wait_for(self.data_queue.get(), timeout=1.0)
                if kline_data:
                    symbol = kline_data.get('symbol')
                    current_price = kline_data.get('close')
                    
                    # 确保为新策略设置初始价格
                    if symbol and current_price and hasattr(self.scanner.strategy, 'set_initial_price'):
                        self.scanner.strategy.set_initial_price(symbol, current_price)
                    
                    # The strategy analyze_market method now directly returns the signal dictionary
                    # or None if no signal is generated.
                    signal_details = self.scanner.strategy.analyze_market(kline_data)
                    
                    if signal_details: # signal_details is the dictionary from TrendFollowingStrategy
                        trading_logger.info(f"策略生成信号: {signal_details['type']} {signal_details['symbol']} @{signal_details['price']}")
                        symbol_from_signal = signal_details.get('symbol')
                        
                        # Ensure the signal_details dictionary is passed to the executor
                        # The executor's execute_signal method expects this dictionary which contains
                        # 'signal_type', 'symbol', 'position_size_usdt', etc.
                        if self.executor:
                            trading_logger.debug(f"Sending signal to executor: {signal_details}")
                            execution_result = await self.executor.execute_signal(signal_details)
                            trading_logger.info(f"执行结果 [{signal_details.get('type')} {symbol_from_signal}]: {execution_result.get('status', 'unknown') if execution_result else 'no_result'}")
                            
                            # TODO: Add notification logic here based on execution_result status
                            if execution_result and execution_result.get('status') == 'error':
                                trading_logger.error(f"Order execution failed for {symbol_from_signal}: {execution_result.get('message')}")
                            elif execution_result and execution_result.get('status') == 'success':
                                trading_logger.info(f"Order execution successful for {symbol_from_signal}.")
                            elif execution_result and 'partial_success' in execution_result.get('status',''):
                                trading_logger.warning(f"Order execution partially successful for {symbol_from_signal}: {execution_result}")

                        else:
                            trading_logger.warning("Executor not available, cannot process signal.")

                        # After attempting to process the signal (successfully or not),
                        # reset the strategy state for this symbol to allow new evaluations.
                        if symbol_from_signal:
                            # The signal type used here is just for logging in remove_signal, it can be any of the details.
                            self.scanner.strategy.remove_signal(symbol_from_signal, signal_details.get('type')) 
                            trading_logger.debug(f"Called remove_signal for {symbol_from_signal} after processing signal type {signal_details.get('type')}.")
                    
                    self.data_queue.task_done()
            except asyncio.TimeoutError:
                continue # No data in queue, continue loop
            except asyncio.CancelledError:
                trading_logger.info("Data queue processor task cancelled.")
                break
            except Exception as e:
                trading_logger.error(f"Error in data queue processor: {e}", exc_info=True)
                # Avoid busy-looping on persistent errors
                await asyncio.sleep(1) 
                trading_logger.info("Data queue processor stopped.")

    async def run(self):
        scanner_task = None
        queue_processor_task = None # Declare queue_processor_task
        try:
            trading_logger.info("Starting CryptoPulseTrader...")
            
            # 启动时持仓恢复检查
            trading_logger.info("执行启动时持仓恢复检查...")
            try:
                from tools import startup_recovery
                recovery = startup_recovery.StartupRecovery(self.config, self.executor)
                recovery_info = await recovery.check_and_recover_positions()
                
                # 如果有活跃持仓或订单，显示警告
                if recovery_info['active_positions'] or recovery_info['open_orders']:
                    trading_logger.warning("⚠️ 检测到已有持仓或挂单，请检查上述报告")
                    trading_logger.warning("程序将继续运行，但策略状态已重置")
                else:
                    trading_logger.info("✅ 启动状态检查完成，账户状态干净")
                    
            except Exception as e:
                trading_logger.error(f"启动时持仓检查失败: {e}")
                trading_logger.warning("程序将继续运行，但建议手动检查持仓状态")
            
            # Check account balance before starting trading (temporarily disabled)
            # trading_logger.info("检查合约账户余额...")
            # balance = await self.executor.get_futures_account_balance()
            # if balance is None:
            #     trading_logger.error("无法获取账户余额，程序将继续运行但可能会有交易问题")
            
            # Create and start the scanner task, passing the stop_event
            scanner_task = asyncio.create_task(self.scanner.scan_market(self.stop_event))
            trading_logger.info("WebSocketMarketScanner.scan_market task created.")

            # Create and start the data queue processor task
            queue_processor_task = asyncio.create_task(self.process_data_queue())
            trading_logger.info("Data queue processor task created.")
            
            # Main loop: keep alive while stop_event is not set and tasks are running
            tasks = [task for task in [scanner_task, queue_processor_task] if task is not None]
            while not self.stop_event.is_set() and any(not task.done() for task in tasks):
                done, pending = await asyncio.wait([task for task in tasks if task and not task.done()], 
                                                   return_when=asyncio.FIRST_COMPLETED, 
                                                   timeout=0.1)
                for task in done:
                    if task.exception():
                        trading_logger.error(f"Task {task.get_name()} completed with exception: {task.exception()}")
                        self.stop_event.set() # Signal other tasks to stop
                    else:
                        trading_logger.info(f"Task {task.get_name()} completed normally.")
                # await asyncio.sleep(0.1) # Replaced by timeout in asyncio.wait

            # If loop exited due to stop_event or task completion
            trading_logger.info("Main loop exited. Initiating shutdown sequence.")
            if not self.stop_event.is_set(): # If exited because all tasks finished
                self.stop_event.set()

            # Wait for tasks to complete with a timeout
            all_tasks = [scanner_task, queue_processor_task]
            for i, task in enumerate(all_tasks):
                if task and not task.done():
                    task_name = task.get_name() if hasattr(task, 'get_name') else f"Task-{i}"
                    trading_logger.info(f"Waiting for {task_name} to complete...")
                    try:
                        await asyncio.wait_for(task, timeout=15.0)
                        trading_logger.info(f"{task_name} completed after stop event.")
                    except asyncio.TimeoutError:
                        trading_logger.warning(f"{task_name} did not complete in 15s. Cancelling.")
                        task.cancel()
                        try: await task
                        except asyncio.CancelledError: trading_logger.info(f"{task_name} cancelled due to timeout.")
                        except Exception as e: trading_logger.error(f"Error cancelling {task_name} after timeout: {e}", exc_info=True)
                    except Exception as e:
                        trading_logger.error(f"Error awaiting {task_name} after stop event: {e}", exc_info=True)

        except asyncio.CancelledError:
            trading_logger.info("CryptoPulseTrader.run() task was cancelled.")
            # Cancel all sub-tasks if main task is cancelled
            for task in [scanner_task, queue_processor_task]:
                if task and not task.done():
                    task.cancel()
                    try: await task
                    except asyncio.CancelledError: pass # Expected
                    except Exception as e: trading_logger.error(f"Error during sub-task cancellation: {e}", exc_info=True)
        except Exception as e:
            trading_logger.error(f"Error in CryptoPulseTrader.run(): {e}", exc_info=True)
            if not self.stop_event.is_set():
                self.stop_event.set()
        finally:
            trading_logger.info("CryptoPulseTrader.run() finally block.")
            if not self.stop_event.is_set():
                trading_logger.info("Ensuring stop_event is set in finally.")
                self.stop_event.set()

            # Final cleanup of tasks
            final_tasks_to_check = [scanner_task, queue_processor_task]
            for task in final_tasks_to_check:
                if task:
                    if not task.done():
                        trading_logger.info(f"Attempting to ensure task {task.get_name()} is completed/cancelled in finally...")
                        if not task.cancelled(): task.cancel()
                        try: 
                            await asyncio.wait_for(task, timeout=10.0)
                            trading_logger.info(f"Task {task.get_name()} completed or cancelled in finally.")
                        except asyncio.TimeoutError: trading_logger.warning(f"Task {task.get_name()} did not finish within timeout in finally.")
                        except asyncio.CancelledError: trading_logger.info(f"Task {task.get_name()} was cancelled in finally.")
                        except Exception as e: trading_logger.error(f"Exception awaiting task {task.get_name()} in finally: {e}", exc_info=True)
                    else:
                        try: 
                            await task # Retrieve result or raise exception if already done
                            trading_logger.info(f"Task {task.get_name()} result retrieved in finally (or no exception). ")
                        except asyncio.CancelledError: trading_logger.info(f"Task {task.get_name()} was already cancelled (checked in finally).")
                        except Exception as e: trading_logger.error(f"Task {task.get_name()} had an exception (checked in finally): {e}", exc_info=True)

            # *** 关闭CCXT连接 ***
            trading_logger.info("Closing CCXT exchange connections...")
            try:
                # 关闭执行器的exchange连接
                if hasattr(self, 'executor') and self.executor and hasattr(self.executor, 'exchange'):
                    await self.executor.exchange.close()
                    trading_logger.info("Executor exchange connection closed.")
                
                # 关闭扫描器中的exchange连接
                if hasattr(self, 'scanner') and self.scanner and hasattr(self.scanner, 'exchange'):
                    await self.scanner.exchange.close()
                    trading_logger.info("Scanner exchange connection closed.")
                    
            except Exception as e:
                trading_logger.error(f"Error closing exchange connections: {e}", exc_info=True)

            trading_logger.info("CryptoPulseTrader shut down.")


def main():
    """主函数"""
    # 创建交易系统实例
    trader = CryptoPulseTrader()
    
    # 运行交易系统
    try:
        asyncio.run(trader.run())
    except KeyboardInterrupt:
        # The signal handler in CryptoPulseTrader should catch SIGINT (Ctrl+C)
        # and set the stop_event. asyncio.run() should then allow tasks to clean up.
        trading_logger.info("KeyboardInterrupt in main. asyncio.run should be handling shutdown gracefully.")
    except Exception as e:
        trading_logger.error(f"程序运行错误: {str(e)}", exc_info=True)
    finally:
        # Final log, most cleanup should be in trader.run()'s finally block.
        trading_logger.info("程序已退出")

if __name__ == "__main__":
    main() 