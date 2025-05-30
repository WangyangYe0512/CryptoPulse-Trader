from utils.config_manager import ConfigManager
from utils.contract_pairs_manager import ContractPairsManager
from scanner.websocket_scanner import WebSocketMarketScanner
from executor.binance_executor import BinanceExecutor
from risk.risk_manager import RiskManager
from utils.logger import trading_logger
import asyncio
import signal
import threading

class CryptoPulseTrader:
    """加密货币脉冲交易系统"""
    
    def __init__(self):
        """初始化交易系统"""
        # 加载配置
        self.config = ConfigManager()
        
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
        trading_logger.info(f"Configuring components for Testnet: {testnet_active}")

        # 初始化市场扫描器
        self.scanner = WebSocketMarketScanner(
            exchange='binance',
            min_volume_usdt=self.config.get('scanner.min_volume_usdt', 1000000),
            top_n=self.config.get('scanner.max_candidates', 15),
            kline_interval=self.config.get('scanner.volatility_timeframe', '1h'),
            data_queue=self.data_queue,
            testnet=testnet_active
        )
        
        # 设置交易执行器
        self.scanner.set_executor(self.executor)
        
        # 设置信号处理
        self.setup_signal_handlers()
        
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            trading_logger.info("Signal received, setting stop_event...")
            self.stop_event.set()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
    async def run(self):
        scanner_task = None
        try:
            trading_logger.info("Starting CryptoPulseTrader...")
            
            # Create and start the scanner task, passing the stop_event
            scanner_task = asyncio.create_task(self.scanner.scan_market(self.stop_event))
            trading_logger.info("WebSocketMarketScanner.scan_market task created.")
            
            # Main loop: keep alive while stop_event is not set and scanner_task is running
            while not self.stop_event.is_set():
                if scanner_task.done():
                    trading_logger.info("Scanner task ended.")
                    try:
                        await scanner_task # Retrieve potential exceptions from the task
                    except asyncio.CancelledError:
                        trading_logger.info("Scanner task was cancelled.")
                    except Exception as e:
                        trading_logger.error(f"Scanner task failed: {e}", exc_info=True)
                    break # Exit main loop if scanner task is done
                await asyncio.sleep(0.1) # Short sleep to yield control

            # If loop exited due to stop_event or scanner_task completion
            if self.stop_event.is_set():
                trading_logger.info("Stop event is set. Initiating shutdown.")

            if scanner_task and not scanner_task.done():
                trading_logger.info("Stop event set, waiting for scanner task to complete...")
                # The scanner_task should see the stop_event and finish
                try:
                    await asyncio.wait_for(scanner_task, timeout=15.0) # Wait with timeout
                    trading_logger.info("Scanner task awaited after stop event.")
                except asyncio.TimeoutError:
                    trading_logger.warning("Scanner task did not complete in 15s after stop event. Cancelling.")
                    scanner_task.cancel()
                    try: await scanner_task
                    except asyncio.CancelledError: trading_logger.info("Scanner task cancelled due to timeout.")
                    except Exception as e: trading_logger.error(f"Error cancelling scanner task after timeout: {e}", exc_info=True)
                except Exception as e:
                     trading_logger.error(f"Error awaiting scanner task after stop event: {e}", exc_info=True)

        except asyncio.CancelledError:
            trading_logger.info("CryptoPulseTrader.run() task was cancelled.")
            if scanner_task and not scanner_task.done():
                trading_logger.info("Cancelling scanner task due to main task cancellation...")
                scanner_task.cancel()
                try:
                    await scanner_task
                except asyncio.CancelledError:
                    trading_logger.info("Scanner task successfully cancelled.")
                except Exception as e:
                    trading_logger.error(f"Exception during scanner task cancellation: {e}", exc_info=True)
        except Exception as e:
            trading_logger.error(f"Error in CryptoPulseTrader.run(): {e}", exc_info=True)
            if not self.stop_event.is_set(): # Ensure stop_event is set on unexpected error
                self.stop_event.set()
        finally:
            trading_logger.info("CryptoPulseTrader.run() finally block.")
            if not self.stop_event.is_set(): # Defensive set
                trading_logger.info("Ensuring stop_event is set in finally.")
                self.stop_event.set()

            if scanner_task: # Ensure scanner_task is handled
                if not scanner_task.done():
                    trading_logger.info("Attempting to ensure scanner task is completed/cancelled in finally...")
                    if not scanner_task.cancelled(): 
                         scanner_task.cancel() 
                    try:
                        await asyncio.wait_for(scanner_task, timeout=10.0)
                        trading_logger.info("Scanner task completed or cancelled in finally.")
                    except asyncio.TimeoutError:
                        trading_logger.warning("Scanner task did not finish within timeout in finally.")
                    except asyncio.CancelledError:
                        trading_logger.info("Scanner task was cancelled in finally.")
                    except Exception as e:
                        trading_logger.error(f"Exception awaiting scanner task in finally: {e}", exc_info=True)
                else: # If task is done, check for exceptions one last time
                    try:
                        # Awaiting a done task retrieves its result or raises its exception
                        await scanner_task 
                        trading_logger.info("Scanner task result retrieved in finally (or no exception). ")
                    except asyncio.CancelledError:
                        trading_logger.info("Scanner task was already cancelled (checked in finally).")
                    except Exception as e:
                         trading_logger.error(f"Scanner task had an exception (checked in finally): {e}", exc_info=True)

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