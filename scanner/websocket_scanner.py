import asyncio
import json
import aiohttp
from typing import List, Set, Tuple
import websockets
from datetime import datetime, timedelta
from utils.logger import trading_logger
from strategy.trend_following import TrendFollowingStrategy
import os
from dotenv import load_dotenv
import threading
import time

# 加载 .env 文件
load_dotenv()

class WebSocketMarketScanner:
    """基于WebSocket的市场扫描器，专注于趋势追踪"""
    
    def __init__(self, 
                 exchange: str = 'binance',
                 min_volume_usdt: float = 1000000,  # 最小24小时交易量(USDT)
                 top_n: int = 15,                   # 每个榜单取前N个
                 kline_interval: str = '1m',       # 1分钟K线
                 data_queue = None,
                 testnet: bool = True): 
        """
        初始化WebSocket市场扫描器
        
        Args:
            exchange: 交易所名称
            min_volume_usdt: 最小24小时交易量(USDT)
            top_n: 每个榜单取前N个
            kline_interval: K线间隔
            data_queue: Queue for passing kline data to main thread
            testnet: Flag indicating whether to use testnet URLs
        """
        self.exchange = exchange
        self.min_volume_usdt = min_volume_usdt
        self.top_n = top_n
        self.kline_interval = kline_interval
        self.data_queue = data_queue
        self.testnet = testnet
        
        # API配置
        self.coingecko_url = "https://pro-api.coingecko.com/api/v3"
        
        if self.testnet:
            self.binance_rest_url = "https://testnet.binancefuture.com/fapi" # Futures Testnet REST URL
            self._ws_url = "wss://stream.binancefuture.com/ws" # Futures Testnet WS URL
            trading_logger.info(f"WebSocketMarketScanner configured for Futures Testnet (REST: {self.binance_rest_url}, WS: {self._ws_url})")
        else:
            self.binance_rest_url = "https://fapi.binance.com" # Live Futures REST URL
            self._ws_url = "wss://fstream.binance.com/ws" # Live Futures WS URL
            trading_logger.info(f"WebSocketMarketScanner configured for Live Futures (REST: {self.binance_rest_url}, WS: {self._ws_url})")

        self.ws = None
        
        # 验证 CoinGecko API key
        self.coingecko_api_key = os.getenv('COINGECKO_API_KEY')
        if not self.coingecko_api_key:
            trading_logger.warning("未找到 COINGECKO_API_KEY，将使用币安数据作为备用")
        
        # 数据存储
        self.watchlist = set()      # 正在跟踪的交易对
        self.kline_cache = {}       # 存储K线数据 {symbol: [kline1, kline2, ...]}
        self.max_kline_cache = 15   # 每个交易对保存的K线数量（15分钟）
        self.last_update = datetime.now()
        
        # 状态标志
        self.is_running = False
        self.reconnect_delay = 5    # 重连延迟(秒)
        self.max_reconnect_attempts = 5
        self.stop_event = threading.Event()
        
        # 初始化策略
        self.strategy = TrendFollowingStrategy(
            min_price_change=0.3,     # 最小价格变化百分比
            min_volume_increase=1.2,  # 最小成交量增加倍数
            stop_loss_pct=0.01,       # 止损百分比 1%
            take_profit_pct=0.02,     # 止盈百分比 2%
            position_size=100.0       # 固定仓位100U
        )
        
        # 交易执行器
        self.executor = None
        
        trading_logger.info(f"WebSocketMarketScanner initialized values. Watchlist: {self.watchlist}, Kline Interval: {self.kline_interval}, Testnet: {self.testnet}")

    def set_executor(self, executor):
        """设置交易执行器"""
        self.executor = executor
        
    async def fetch_coingecko_movers(self) -> Tuple[List[str], List[str]]:
        """获取CoinGecko的涨跌幅榜"""
        try:
            if not self.coingecko_api_key:
                trading_logger.warning("未设置 COINGECKO_API_KEY，跳过 CoinGecko 数据获取")
                return [], []
                
            headers = {
                'X-Cg-Pro-Api-Key': self.coingecko_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.coingecko_url}/coins/top_gainers_losers",
                    params={
                        'vs_currency': 'usd',
                        'duration': '1h',
                        'top_coins': 1000 
                    },
                    headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        gainers = []
                        losers = []
                        
                        for coin in data.get('top_gainers', []):
                            try:
                                symbol = coin.get('symbol', '').replace('$', '').upper()
                                if symbol: gainers.append(symbol)
                            except Exception as e:
                                trading_logger.error(f"处理涨幅榜币种时出错: {coin}, 错误: {str(e)}")
                                continue
                                
                        for coin in data.get('top_losers', []):
                            try:
                                symbol = coin.get('symbol', '').replace('$', '').upper()
                                if symbol: losers.append(symbol)
                            except Exception as e:
                                trading_logger.error(f"处理跌幅榜币种时出错: {coin}, 错误: {str(e)}")
                                continue
                        
                        trading_logger.info(f"从CoinGecko获取到 {len(gainers)} 个涨幅币种和 {len(losers)} 个跌幅币种")
                        return gainers, losers
                    else:
                        trading_logger.error(f"获取CoinGecko数据失败: {response.status} {await response.text()}")
                        if response.status == 401:
                            trading_logger.error("CoinGecko API key 无效或未设置")
                        return [], []
        except Exception as e:
            trading_logger.error(f"获取CoinGecko数据时发生错误: {str(e)}", exc_info=True)
            return [], []
            
    async def fetch_binance_symbols(self) -> Set[str]:
        """获取币安合约交易对列表"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.binance_rest_url}/v1/exchangeInfo") as response:
                    if response.status == 200:
                        data = await response.json()
                        symbols = {item['symbol'] for item in data['symbols'] if item['symbol'].endswith('USDT')}
                        trading_logger.info(f"从币安获取到 {len(symbols)} 个USDT合约交易对")
                        return symbols
                    else:
                        trading_logger.error(f"获取币安交易对失败: {response.status} {await response.text()}")
                        return set()
        except Exception as e:
            trading_logger.error(f"获取币安交易对时发生错误: {str(e)}", exc_info=True)
            return set()
            
    async def update_watchlist(self):
        """更新watchlist，考虑现有持仓状态"""
        try:
            trading_logger.info(f"开始更新watchlist，top_n值: {self.top_n}")
            gainers, losers = await self.fetch_coingecko_movers()
            
            if not gainers and not losers:
                trading_logger.warning("无法从CoinGecko获取数据，尝试使用币安24h行情作为备用...")
                gainers, losers = await self.fetch_binance_24h_movers()
                if not gainers and not losers:
                    trading_logger.error("备用方案(币安24h行情)也失败，无法更新watchlist")
                    return False # Indicate failure to update
            
            binance_symbols = await self.fetch_binance_symbols()
            if not binance_symbols:
                trading_logger.error("无法获取币安交易对列表，无法验证watchlist")
                return False

            valid_gainers = [s for s in gainers if isinstance(s, str) and f"{s.upper()}USDT" in binance_symbols]
            valid_losers = [s for s in losers if isinstance(s, str) and f"{s.upper()}USDT" in binance_symbols]
            
            top_gainers = valid_gainers[:min(self.top_n, len(valid_gainers))]
            top_losers = valid_losers[:min(self.top_n, len(valid_losers))]
            
            new_watchlist_symbols_only = {symbol for symbol in top_gainers + top_losers}
            new_watchlist = {f"{symbol}USDT" for symbol in new_watchlist_symbols_only}
            
            active_positions = set()
            if self.executor:
                try:
                    # Assuming get_account() returns info that includes positions for futures
                    # Call the synchronous get_account method in a separate thread
                    account_info = await asyncio.to_thread(self.executor.get_account)
                    trading_logger.debug(f"Account info from executor: {account_info}")

                    if account_info and isinstance(account_info.get('positions'), list):
                        # For Binance Futures, positions usually have 'symbol' and 'positionAmt'
                        # Filter for positions with a non-zero position amount.
                        active_positions = {
                            pos['symbol'] for pos in account_info['positions']
                            if pos.get('symbol') and float(pos.get('positionAmt', '0')) != 0
                        }
                        trading_logger.info(f"当前持仓交易对 (from get_account): {active_positions}")
                    elif account_info and isinstance(account_info.get('balances'), list): # Fallback for spot-like balance structure
                        active_positions = { 
                            bal['asset'] + 'USDT' for bal in account_info['balances'] 
                            if (float(bal.get('free','0')) > 0 or float(bal.get('locked','0')) > 0) and bal.get('asset')
                        } # This might need adjustment if assets are not base of USDT pairs
                        trading_logger.info(f"当前活跃资产 (from get_account balances, assuming USDT pairs): {active_positions}")
                    else:
                        trading_logger.warning("未能从 executor.get_account() 获取有效的持仓列表 (positions or balances key not found or not a list).")
                except Exception as e:
                    trading_logger.error(f"获取持仓信息时出错: {str(e)}", exc_info=True)
            
            # Symbols to remove: in old watchlist, not in new, and no active position
            to_remove = {s for s in self.watchlist if s not in new_watchlist and s not in active_positions}
            # Symbols to add: in new watchlist, not in old
            to_add = {s for s in new_watchlist if s not in self.watchlist}

            if to_remove:
                trading_logger.info(f"将从 watchlist 移除: {to_remove}")
                if self.ws and self.is_running: # Check if WebSocket is active
                    await self._send_subscription_update(unsubscribe=list(to_remove))
            if to_add:
                trading_logger.info(f"将向 watchlist 添加: {to_add}")
                if self.ws and self.is_running: # Check if WebSocket is active
                    await self._send_subscription_update(subscribe=list(to_add))
            
            self.watchlist.update(to_add)
            self.watchlist.difference_update(to_remove) # More efficient way to remove
            
            # Clean kline_cache for removed symbols
            for symbol_to_remove in to_remove:
                if symbol_to_remove in self.kline_cache:
                    del self.kline_cache[symbol_to_remove]
                    trading_logger.info(f"从kline_cache中移除 {symbol_to_remove}")

            trading_logger.info(f"更新后的 watchlist: {self.watchlist}")
            self.last_update = datetime.now()
            return True # Indicate success
        except Exception as e:
            trading_logger.error(f"更新watchlist时发生严重错误: {str(e)}", exc_info=True)
            return False

    async def fetch_binance_24h_movers(self) -> Tuple[List[str], List[str]]:
        """备用方案：获取币安24小时涨跌幅数据 (简化版，只获取交易量和价格变动)"""
        trading_logger.info("正在使用备用方案: 获取币安24小时行情数据...")
        all_tickers = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.binance_rest_url}/v1/ticker/24hr") as response:
                    if response.status == 200:
                        all_tickers = await response.json()
                    else:
                        trading_logger.error(f"获取币安24h行情失败: {response.status} {await response.text()}")
                        return [], []
        except Exception as e:
            trading_logger.error(f"请求币安24h行情时出错: {str(e)}", exc_info=True)
            return [], []

        usdt_tickers = [
            ticker for ticker in all_tickers 
            if isinstance(ticker, dict) and \
               ticker.get('symbol', '').endswith('USDT') and \
               float(ticker.get('quoteVolume', 0)) >= self.min_volume_usdt
        ]

        if not usdt_tickers:
            trading_logger.warning("未能从币安24h行情中筛选出符合条件的USDT交易对。")
            return [],[]

        # Sort by price change percent
        usdt_tickers.sort(key=lambda x: float(x.get('priceChangePercent', 0)), reverse=True)
        
        gainers = [ticker['symbol'].replace('USDT','') for ticker in usdt_tickers[:self.top_n] if float(ticker.get('priceChangePercent',0)) > 0]
        losers = [ticker['symbol'].replace('USDT','') for ticker in reversed(usdt_tickers[-self.top_n:]) if float(ticker.get('priceChangePercent',0)) < 0]
        
        trading_logger.info(f"备用方案: 获取到 {len(gainers)} 个涨幅币种, {len(losers)} 个跌幅币种 (基于币安24h行情)")
        return gainers, losers

    async def _send_subscription_update(self, subscribe: List[str] = None, unsubscribe: List[str] = None):
        """发送(取消)订阅消息到WebSocket"""
        if not self.ws or not self.is_running:
            trading_logger.warning("WebSocket未连接，无法更新订阅。")
            return

        if subscribe:
            streams_to_sub = [f"{symbol.lower()}@kline_{self.kline_interval}" for symbol in subscribe]
            if streams_to_sub:
                sub_payload = {
                    "method": "SUBSCRIBE",
                    "params": streams_to_sub,
                    "id": int(time.time()) # Unique ID for subscription
                }
                trading_logger.info(f"发送订阅消息: {json.dumps(sub_payload)}")
                await self.ws.send(json.dumps(sub_payload))
        
        if unsubscribe:
            streams_to_unsub = [f"{symbol.lower()}@kline_{self.kline_interval}" for symbol in unsubscribe]
            if streams_to_unsub:
                unsub_payload = {
                    "method": "UNSUBSCRIBE",
                    "params": streams_to_unsub,
                    "id": int(time.time()) # Unique ID for unsubscription
                }
                trading_logger.info(f"发送取消订阅消息: {json.dumps(unsub_payload)}")
                await self.ws.send(json.dumps(unsub_payload))

    async def connect(self):
        """连接到WebSocket并处理消息"""
        if not self.watchlist:
            trading_logger.warning("Watchlist为空，不启动WebSocket连接。")
            # Schedule next update attempt if needed by the calling logic in scan_market
            return

        streams = [f"{symbol.lower()}@kline_{self.kline_interval}" for symbol in self.watchlist]
        if not streams:
            trading_logger.warning("没有有效的streams来订阅，不启动WebSocket连接。")
            return

        # Using self._ws_url which is wss://fstream.binance.com/ws
        # The /stream endpoint is for combined streams, /ws is for individual raw streams
        # For individual subscriptions, the URL is typically just /ws
        # And streams are specified in the subscribe message.
        
        connection_attempts = 0
        while connection_attempts < self.max_reconnect_attempts and not self.stop_event.is_set():
            try:
                trading_logger.info(f"尝试连接到WebSocket: {self._ws_url} (尝试 {connection_attempts + 1}/{self.max_reconnect_attempts})")
                async with websockets.connect(self._ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self.ws = ws
                    self.is_running = True
                    connection_attempts = 0 # Reset on successful connection
                    trading_logger.info("WebSocket连接成功。")

                    # Subscribe to initial streams
                    await self._send_subscription_update(subscribe=list(self.watchlist))
                    
                    async for message in ws:
                        if self.stop_event.is_set():
                            trading_logger.info("Stop event received during message loop, breaking.")
                            break
                        await self.process_message(message)
                        
            except websockets.exceptions.ConnectionClosed as e:
                trading_logger.error(f"WebSocket连接关闭: {e}. Status: {e.code}, Reason: {e.reason}", exc_info=True)
            except ConnectionRefusedError:
                trading_logger.error("WebSocket连接被拒绝。", exc_info=True)
            except asyncio.TimeoutError:
                trading_logger.error("WebSocket连接超时。", exc_info=True)
            except Exception as e:
                trading_logger.error(f"WebSocket连接或处理时发生未知错误: {e}", exc_info=True)
            finally:
                self.is_running = False
                self.ws = None
                if self.stop_event.is_set():
                    trading_logger.info("停止事件已设置，WebSocket将不会重连。")
                    break 
                
                connection_attempts += 1
                if connection_attempts < self.max_reconnect_attempts:
                    trading_logger.info(f"WebSocket断开，将在 {self.reconnect_delay} 秒后重试...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    trading_logger.error(f"已达到最大重连次数 ({self.max_reconnect_attempts})，停止尝试。")
                    self.stop_event.set() # Signal main thread to stop if scanner fails permanently
                    break
        
        if not self.stop_event.is_set(): # If loop exited due to max retries
             trading_logger.warning("WebSocket连接循环意外退出，且stop_event未设置。")
        # No explicit self.stop_event.set() here unless max retries are hit.
        # The stop is usually controlled externally or by error thresholds.
        trading_logger.info("WebSocket连接处理循环结束。")


    async def process_message(self, message: str):
        """处理从WebSocket接收到的消息"""
        try:
            data = json.loads(message)
            # trading_logger.debug(f"原始WebSocket消息: {data}") # Can be very verbose

            if 'e' in data and data['e'] == 'kline':
                kline_data = data['k']
                symbol = kline_data['s']
                
                # Ensure symbol is in our current watchlist before processing
                if symbol not in self.watchlist:
                    # trading_logger.debug(f"收到非监控列表 {symbol} 的K线数据，已忽略。")
                    return

                processed_kline = {
                    'symbol': symbol,
                    'open_time': kline_data['t'],
                    'open': float(kline_data['o']),
                    'high': float(kline_data['h']),
                    'low': float(kline_data['l']),
                    'close': float(kline_data['c']),
                    'volume': float(kline_data['v']),
                    'close_time': kline_data['T'],
                    'is_closed': kline_data['x'] 
                }
                # trading_logger.info(f"处理后K线 for {symbol}: C={processed_kline['close']}, V={processed_kline['volume']}, IsClosed={processed_kline['is_closed']}")
                
                if self.data_queue:
                    await self.data_queue.put(processed_kline)
                else:
                    trading_logger.warning("Data queue not available in WebSocketMarketScanner to send kline data.")

                # 更新K线缓存 (optional, if TrendTracker uses its own cache from queue)
                if symbol not in self.kline_cache:
                    self.kline_cache[symbol] = []
                self.kline_cache[symbol].append(processed_kline)
                if len(self.kline_cache[symbol]) > self.max_kline_cache:
                    self.kline_cache[symbol].pop(0) # 保持缓存大小

            elif 'result' in data and data.get('result') is None and 'id' in data:
                # This is likely a subscription confirmation
                trading_logger.info(f"收到订阅确认/结果: {data}")
            elif 'error' in data:
                trading_logger.error(f"收到WebSocket错误消息: {data}")
                # Potentially set stop_event or handle specific errors if critical
                # Example: if error code indicates auth failure.
                # if data.get('code') == SOME_CRITICAL_ERROR_CODE:
                #    self.stop_event.set()
            else:
                # trading_logger.debug(f"收到其他类型的WebSocket消息: {data}")
                pass

        except json.JSONDecodeError:
            trading_logger.error(f"无法解码WebSocket消息的JSON: {message}")
        except Exception as e:
            trading_logger.error(f"处理WebSocket消息时出错: {e}", exc_info=True)

    async def scan_market(self, stop_event: threading.Event):
        """
        主扫描循环，定期更新watchlist并运行WebSocket连接。
        Accepts a stop_event from the main thread.
        """
        self.stop_event = stop_event # Use the event passed from main.py
        trading_logger.info("启动WebSocket市场扫描器主循环...")
        
        initial_update_done = False
        while not self.stop_event.is_set():
            now = datetime.now()
            # Initial update or if 60 minutes passed since last update
            if not initial_update_done or (now - self.last_update) > timedelta(minutes=55): # Update slightly before 60min
                trading_logger.info("需要更新watchlist...")
                # Ensure update_watchlist is awaited
                update_success = await self.update_watchlist()
                if update_success:
                    initial_update_done = True
                    self.last_update = now 
                    trading_logger.info("Watchlist更新成功。")
                    # If watchlist is not empty and WS is not running, start it
                    if self.watchlist and (not self.ws or not self.is_running):
                        trading_logger.info("Watchlist非空且WebSocket未运行，尝试启动连接。")
                        # Run connect in a separate task so scan_market can continue checking stop_event
                        # and potentially other periodic tasks if any were added here.
                        asyncio.create_task(self.connect())
                    elif not self.watchlist:
                         trading_logger.info("Watchlist为空，WebSocket将不会启动/会停止（如果当前正在运行）。")
                         if self.ws and self.is_running:
                             await self.stop_ws_connection() # Ensure graceful shutdown if watchlist becomes empty
                else:
                    trading_logger.error("Watchlist更新失败。将在下一个周期重试。")
                    # If update fails, maybe wait longer before retry to avoid API rate limits
                    await asyncio.sleep(60) # Wait 1 minute before retrying watchlist update
                    continue # Retry watchlist update sooner

            # Check WebSocket status and data queue (if used for monitoring connection health)
            if self.watchlist and self.is_running:
                # trading_logger.debug(f"WebSocket运行中，监控 {len(self.watchlist)} 个交易对。")
                pass # Main work is done by self.connect() and self.process_message() in their own loop

            # Short sleep to allow other asyncio tasks to run and to check stop_event frequently
            try:
                await asyncio.sleep(1) 
            except asyncio.CancelledError:
                trading_logger.info("scan_market task被取消。")
                break
        
        trading_logger.info("scan_market主循环检测到停止信号。正在关闭...")
        await self.stop_ws_connection() # Ensure WS is closed when scan_market stops
        trading_logger.info("WebSocket市场扫描器主循环已停止。")

    async def stop_ws_connection(self):
        """Stops the WebSocket connection gracefully."""
        trading_logger.info("正在尝试停止WebSocket连接...")
        # self.stop_event.set() # Already set by the caller or error condition
        if self.ws and self.is_running:
            try:
                trading_logger.info("显式关闭WebSocket...")
                await self.ws.close()
                # Wait for the connection task to finish if it was run via create_task
                # This is tricky as self.connect() runs its own loop.
                # The closing of self.ws should cause the loop in self.connect() to exit.
            except Exception as e:
                trading_logger.error(f"关闭WebSocket时出错: {e}", exc_info=True)
        else:
            trading_logger.info("WebSocket连接未激活或已关闭。")
        self.is_running = False
        self.ws = None # Clear the ws object

    # Stopping is handled by setting self.stop_event and allowing async tasks to complete.
    # def stop(self):
    #     trading_logger.info("Attempting to stop WebSocketMarketScanner (sync stop)...")
    #     if not self.stop_event.is_set():
    #         self.stop_event.set()
    #         trading_logger.info("Stop event set for WebSocketMarketScanner.")
        # No thread.join for async tasks here. This would be handled by main thread awaiting the task.

# Removed the __main__ block as it was for a different class structure and sync execution

# Stopping is handled by setting self.stop_event and allowing async tasks to complete.
# def stop(self):
#     trading_logger.info("Attempting to stop WebSocketMarketScanner (sync stop)...")
#     if not self.stop_event.is_set():
#         self.stop_event.set()
#         trading_logger.info("Stop event set for WebSocketMarketScanner.")
    # No thread.join for async tasks here. This would be handled by main thread awaiting the task.