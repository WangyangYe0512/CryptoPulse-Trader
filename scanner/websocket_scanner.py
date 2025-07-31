import asyncio
import json
import aiohttp
from typing import List, Set, Tuple
import websockets
from datetime import datetime, timedelta
from utils.logger import trading_logger
from utils.symbol_validator import SymbolValidator
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
                 config,
                 exchange: str = 'binance',
                 min_volume_usdt: float = 1000000,  # 最小24小时交易量(USDT)
                 top_n: int = 15,                   # 每个榜单取前N个
                 kline_interval: str = '1m',       # 保留用于配置，但实际使用ticker
                 data_queue = None,
                 testnet: bool = True): 
        """
        初始化WebSocket市场扫描器
        
        Args:
            exchange: 交易所名称
            min_volume_usdt: 最小24小时交易量(USDT)
            top_n: 每个榜单取前N个
            kline_interval: K线间隔（保留兼容性，但使用ticker流）
            data_queue: Queue for passing ticker data to main thread
            testnet: Flag indicating whether to use testnet URLs
        """
        self.exchange = exchange
        self.min_volume_usdt = min_volume_usdt
        self.top_n = top_n
        self.kline_interval = kline_interval
        self.data_queue = data_queue
        self.testnet = testnet
        self.config = config
        
        # Log the strategy part of the config for debugging
        strategy_config_debug = self.config.get('strategy')
        trading_logger.info(f"DEBUG: Strategy config loaded by WebSocketMarketScanner: {strategy_config_debug}")
        
        # API配置
        self.coingecko_url = "https://pro-api.coingecko.com/api/v3"
        
        if self.testnet:
            self.binance_rest_url = "https://testnet.binancefuture.com/fapi" # Futures Testnet REST URL
            self._ws_url = "wss://fstream.binancefuture.com/ws" # 使用最新的Testnet WebSocket URL
            trading_logger.info(f"WebSocketMarketScanner configured for Futures Testnet (REST: {self.binance_rest_url}, WS: {self._ws_url})")
        else:
            self.binance_rest_url = "https://fapi.binance.com/fapi" # Live Futures REST URL
            self._ws_url = "wss://fstream.binance.com/ws" # Live Futures WS URL
            trading_logger.info(f"WebSocketMarketScanner configured for Live Futures (REST: {self.binance_rest_url}, WS: {self._ws_url})")

        self.ws = None
        
        # 验证 CoinGecko API key
        self.coingecko_api_key = os.getenv('COINGECKO_API_KEY')
        if not self.coingecko_api_key:
            trading_logger.warning("未找到 COINGECKO_API_KEY，将使用币安数据作为备用")
        
        # 数据存储
        self.watchlist = set()      # 正在跟踪的交易对
        self.active_subscriptions = set() # Initialize active_subscriptions here
        self.ticker_cache = {}      # 存储Ticker数据 {symbol: latest_ticker}
        self.last_update = datetime.now()
        
        # 动态watchlist管理
        self.candidate_pool = set()    # 候补币种池
        self.ranking_cache = {}        # 币种排名缓存 {symbol: ranking}
        self.last_ranking_update = datetime.now()
        
        # 从配置中读取动态管理参数
        self.max_watchlist_size = self.config.get('scanner.dynamic_management.max_watchlist_size', 10)
        self.flat_timeout_minutes = self.config.get('scanner.dynamic_management.flat_timeout_minutes', 30)
        self.max_failure_count = self.config.get('scanner.dynamic_management.max_failure_count', 3)
        self.replacement_pool_size = self.config.get('scanner.dynamic_management.replacement_pool_size', 20)
        self.ranking_threshold = self.config.get('scanner.dynamic_management.ranking_threshold', 20)
        self.update_interval_minutes = self.config.get('scanner.dynamic_management.update_interval_minutes', 60)
        
        # 状态标志
        self.is_running = False
        self.reconnect_delay = 5    # 重连延迟(秒)
        self.max_reconnect_attempts = 5
        self.stop_event = threading.Event()
        
        # 符号验证器（延迟初始化，等executor设置后再创建）
        self.symbol_validator = None
        
        # --- Robustly initialize TrendFollowingStrategy from config ---
        strat_cfg_path = 'strategy.trend_following'
        custom_interval_cfg_path = f'{strat_cfg_path}.custom_interval'
        risk_cfg_path = 'risk'

        # Get position_size from config, with a default that matches the strategy's default
        cfg_position_size = self.config.get(f'{strat_cfg_path}.position_size_usdt', 10.0)
        trading_logger.info(f"WebSocketMarketScanner: Determined 'position_size' for TrendFollowingStrategy: {cfg_position_size} (from config key '{strat_cfg_path}.position_size_usdt', default 10.0)")

        # Get other parameters for TrendFollowingStrategy from config
        cfg_min_price_change = self.config.get(f'{strat_cfg_path}.min_price_change_pct', 0.15)
        cfg_min_volume_increase = self.config.get(f'{strat_cfg_path}.min_volume_increase_ratio', 1.1)
        
        # stop_loss_pct and take_profit_pct from risk section, converted from % to decimal
        cfg_stop_loss_pct = self.config.get(f'{risk_cfg_path}.stop_loss_pct', 1.0) / 100.0
        cfg_take_profit_pct = self.config.get(f'{risk_cfg_path}.take_profit_pct', 2.0) / 100.0
        
        cfg_min_kline_history = self.config.get(f'{strat_cfg_path}.min_kline_history_count', 3)
        cfg_breakout_period = self.config.get(f'{strat_cfg_path}.breakout_period_count', 2)
        
        # 新的趋势参数
        cfg_trend_trigger_pct = self.config.get(f'{strat_cfg_path}.trend_trigger_pct', 2.0)
        cfg_trend_reset_pct = self.config.get(f'{strat_cfg_path}.trend_reset_pct', 0.5)
        cfg_position_add_threshold_pct = self.config.get(f'{strat_cfg_path}.position_add_threshold_pct', 0.5)
        cfg_min_volume_check = self.config.get(f'{strat_cfg_path}.min_volume_check', True)
        
        # 旧的定制间隔参数 (保持兼容性)
        cfg_price_point_window_seconds = self.config.get(f'{custom_interval_cfg_path}.price_point_window_seconds', 300)
        cfg_trend_chunk_seconds = self.config.get(f'{custom_interval_cfg_path}.trend_chunk_seconds', 30)
        cfg_min_chunk_price_change_pct = self.config.get(f'{custom_interval_cfg_path}.min_chunk_price_change_pct', 0.05)
        cfg_min_trend_confirm_chunks = self.config.get(f'{custom_interval_cfg_path}.min_trend_confirm_chunks_count', 2)

        trading_logger.info("WebSocketMarketScanner: Initializing TrendFollowingStrategy V3.0 with parameters from config:")
        trading_logger.info(f"  === 新趋势参数 === trigger_pct={cfg_trend_trigger_pct}%, reset_pct={cfg_trend_reset_pct}%, add_threshold={cfg_position_add_threshold_pct}%, volume_check={cfg_min_volume_check}")
        trading_logger.info(f"  === 交易参数 === position_size={cfg_position_size}, stop_loss_pct={cfg_stop_loss_pct}%, take_profit_pct={cfg_take_profit_pct}%")
        trading_logger.info(f"  === 兼容参数 === min_price_change={cfg_min_price_change}, min_volume_increase={cfg_min_volume_increase}")
        trading_logger.info(f"  === 旧参数 === chunk_seconds={cfg_trend_chunk_seconds}, min_chunk_change_pct={cfg_min_chunk_price_change_pct}%")

        self.strategy = TrendFollowingStrategy(
            # 新的核心参数
            trend_trigger_pct=cfg_trend_trigger_pct,
            trend_reset_pct=cfg_trend_reset_pct,
            position_add_threshold_pct=cfg_position_add_threshold_pct,
            min_volume_check=cfg_min_volume_check,
            
            # 基础交易参数
            stop_loss_pct=cfg_stop_loss_pct,
            take_profit_pct=cfg_take_profit_pct,
            position_size=cfg_position_size, 
            
            # 兼容性参数
            min_price_change=cfg_min_price_change,
            min_volume_increase=cfg_min_volume_increase,
            min_kline_history=cfg_min_kline_history,
            breakout_period=cfg_breakout_period,
            price_point_window_seconds=cfg_price_point_window_seconds,
            trend_chunk_seconds=cfg_trend_chunk_seconds,
            min_chunk_price_change_pct=cfg_min_chunk_price_change_pct,
            min_trend_confirm_chunks=cfg_min_trend_confirm_chunks
        )
        
        # 交易执行器
        self.executor = None
        
        trading_logger.info(f"WebSocketMarketScanner initialized values. Watchlist: {self.watchlist}, Using: TICKER STREAM (Real-time), Testnet: {self.testnet}")

    def set_executor(self, executor):
        """设置交易执行器"""
        try:
            trading_logger.info(f"Setting executor: {type(executor).__name__}")
            self.executor = executor
            
            # 初始化符号验证器
            try:
                trading_logger.info("Initializing SymbolValidator...")
                self.symbol_validator = SymbolValidator(executor)
                trading_logger.info("Symbol validator initialized with executor - VALIDATION ACTIVE")
            except Exception as e:
                trading_logger.error(f"Failed to initialize SymbolValidator: {e}", exc_info=True)
                self.symbol_validator = None
                
        except Exception as e:
            trading_logger.error(f"Error in set_executor: {e}", exc_info=True)
        
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
        """获取币安合约交易对列表 (via Executor using CCXT)."""
        trading_logger.debug("Attempting to fetch Binance futures symbols via executor...")
        if not self.executor or not hasattr(self.executor, 'get_all_binance_futures_symbols'):
            trading_logger.error("Executor not available or does not support get_all_binance_futures_symbols. Cannot fetch symbols.")
            return set()
        
        try:
            symbols = await self.executor.get_all_binance_futures_symbols()
            # The executor method already logs success/failure and returns a set of CCXT symbols (e.g., 'BTC/USDT')
            # The original method returned symbols like 'BTCUSDT'. We need to ensure consistency or adapt.
            # The new executor method returns symbols in 'BASE/QUOTE' format like 'BTC/USDT'.
            # The current usage in update_watchlist (e.g. f"{s.upper()}USDT" in binance_symbols) expects 'BTCUSDT'.
            # Let's convert them back for compatibility with existing logic for now, or update consuming logic.
            # For now, converting to the 'BTCUSDT' format to minimize changes in update_watchlist.
            normalized_symbols = {s.replace('/','') for s in symbols}
            trading_logger.info(f"从Executor获取到 {len(normalized_symbols)} 个USDT合约交易对 (format: ETHUSDT).")
            return normalized_symbols
        except Exception as e:
            trading_logger.error(f"通过Executor获取币安交易对时发生错误: {str(e)}", exc_info=True)
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
            
            # fetch_binance_symbols now returns symbols like 'BTCUSDT' after modification
            binance_symbols = await self.fetch_binance_symbols()
            if not binance_symbols:
                trading_logger.error("无法获取币安交易对列表 (via executor)，无法验证watchlist")
                return False

            # valid_gainers/losers expect symbols like 'ETH' and check against 'ETHUSDT' in binance_symbols
            valid_gainers = [s for s in gainers if isinstance(s, str) and f"{s.upper()}USDT" in binance_symbols]
            valid_losers = [s for s in losers if isinstance(s, str) and f"{s.upper()}USDT" in binance_symbols]
            
            top_gainers = valid_gainers[:min(self.top_n, len(valid_gainers))]
            top_losers = valid_losers[:min(self.top_n, len(valid_losers))]
            
            # new_watchlist expects symbols like 'ETHUSDT'
            new_watchlist_symbols_only = {symbol for symbol in top_gainers + top_losers} # These are like 'ETH'
            new_watchlist = {f"{symbol.upper()}USDT" for symbol in new_watchlist_symbols_only} # Convert to 'ETHUSDT'
            
            active_positions_raw = set() # Initialize as an empty set
            if self.executor and hasattr(self.executor, 'get_active_positions_symbols'): 
                try:
                    trading_logger.info("Fetching active positions using executor.get_active_positions_symbols()...")
                    active_positions_raw = await self.executor.get_active_positions_symbols()
                    # active_positions_raw is now like {'BTC/USDT', 'ETH/USDT'}
                    trading_logger.info(f"当前持仓交易对 (raw from executor): {active_positions_raw}")
                except Exception as e:
                    trading_logger.error(f"获取持仓符号列表时出错 (get_active_positions_symbols): {str(e)}", exc_info=True)
            elif self.executor:
                trading_logger.warning("Executor is present but does not have 'get_active_positions_symbols' method. Cannot fetch active positions.")
            else:
                trading_logger.info("No executor set in scanner. Cannot fetch active positions.")

            # Normalize active_positions to 'BASEQUOTE' format (e.g., 'BTCUSDT') for consistency
            active_positions = {s.replace('/', '') for s in active_positions_raw}
            if active_positions_raw and not active_positions:
                 trading_logger.warning(f"Active positions raw ({active_positions_raw}) resulted in empty set after normalization. Check symbol formats.")
            elif active_positions:
                trading_logger.info(f"Normalized active positions for watchlist comparison: {active_positions}")
            
            # Symbols to remove: in old watchlist (format 'BTCUSDT'), 
            # not in new_watchlist (format 'BTCUSDT'), 
            # and not in active_positions (now also format 'BTCUSDT')
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
            
            # Clean ticker_cache for removed symbols
            for symbol_to_remove in to_remove:
                if symbol_to_remove in self.ticker_cache:
                    del self.ticker_cache[symbol_to_remove]
                    trading_logger.info(f"从ticker_cache中移除 {symbol_to_remove}")

            trading_logger.info(f"更新后的 watchlist: {self.watchlist}")
            self.last_update = datetime.now()
            return True # Indicate success
        except Exception as e:
            trading_logger.error(f"更新watchlist时发生严重错误: {str(e)}", exc_info=True)
            return False

    async def fetch_binance_24h_movers(self) -> Tuple[List[str], List[str]]:
        """备用方案：获取币安24小时涨跌幅数据 (via Executor using CCXT)."""
        trading_logger.info("正在使用备用方案 (via Executor): 获取币安24小时行情数据...")
        
        if not self.executor or not hasattr(self.executor, 'get_binance_24h_tickers'):
            trading_logger.error("Executor not available or does not support get_binance_24h_tickers. Cannot fetch 24h movers.")
            return [], []

        all_tickers_data = []
        try:
            # Get tickers for all USDT futures symbols known to the executor
            all_tickers_data = await self.executor.get_binance_24h_tickers() # Fetches all USDT linear futures tickers
        except Exception as e:
            trading_logger.error(f"通过Executor请求币安24h行情时出错: {str(e)}", exc_info=True)
            return [], []

        if not all_tickers_data:
            trading_logger.warning("未能从Executor获取到24h行情数据。")
            return [], []

        # Filter by min_volume_usdt. CCXT ticker structure standardly includes 'quoteVolume'.
        # Symbol format from CCXT is 'BASE/QUOTE', e.g., 'BTC/USDT'.
        usdt_tickers_filtered = [
            ticker for ticker in all_tickers_data
            if isinstance(ticker, dict) and \
               ticker.get('symbol', '').endswith('/USDT') and \
               ticker.get('quoteVolume') is not None and \
               float(ticker['quoteVolume']) >= self.min_volume_usdt
        ]

        if not usdt_tickers_filtered:
            trading_logger.warning("未能从币安24h行情中筛选出符合条件的USDT交易对 (min_volume_usdt check).")
            return [], []

        # Sort by price change percent. CCXT standard key is 'percentage'.
        # Note: CCXT's 'percentage' is usually already in percent (e.g., 5.5 for 5.5%), unlike raw data which might be 0.055.
        # We need to ensure this matches the expectation of how top_n is picked.
        # The original code used 'priceChangePercent' from raw Binance API which is already a percentage.
        # CCXT `ticker['percentage']` is also a direct percentage.
        usdt_tickers_filtered.sort(key=lambda x: x.get('percentage', 0.0) if x.get('percentage') is not None else 0.0, reverse=True)
        
        # Extract gainers and losers. Symbol from CCXT ticker is e.g. 'BTC/USDT'.
        # The calling logic in update_watchlist expects base symbols like 'BTC'.
        gainers = [
            ticker['symbol'].replace('/USDT','') 
            for ticker in usdt_tickers_filtered[:self.top_n] 
            if ticker.get('percentage') is not None and ticker['percentage'] > 0
        ]
        losers = [
            ticker['symbol'].replace('/USDT','') 
            for ticker in reversed(usdt_tickers_filtered[-self.top_n:]) 
            if ticker.get('percentage') is not None and ticker['percentage'] < 0
        ]
        
        trading_logger.info(f"备用方案 (via Executor): 获取到 {len(gainers)} 个涨幅币种, {len(losers)} 个跌幅币种")
        return gainers, losers

    async def _send_subscription_update(self, subscribe: List[str] = None, unsubscribe: List[str] = None):
        """发送(取消)订阅消息到WebSocket - 改为使用ticker流"""
        if not self.ws or not self.is_running:
            trading_logger.warning("WebSocket未连接，无法更新订阅。")
            return

        if subscribe:
            # 改为订阅ticker流，获取实时价格
            streams_to_sub = [f"{symbol.lower()}@ticker" for symbol in subscribe]
            if streams_to_sub:
                sub_payload = {
                    "method": "SUBSCRIBE",
                    "params": streams_to_sub,
                    "id": int(time.time()) # Unique ID for subscription
                }
                trading_logger.info(f"发送Ticker订阅消息: {json.dumps(sub_payload)}")
                await self.ws.send(json.dumps(sub_payload))
        
        if unsubscribe:
            # 取消订阅ticker流
            streams_to_unsub = [f"{symbol.lower()}@ticker" for symbol in unsubscribe]
            if streams_to_unsub:
                unsub_payload = {
                    "method": "UNSUBSCRIBE",
                    "params": streams_to_unsub,
                    "id": int(time.time()) # Unique ID for unsubscription
                }
                trading_logger.info(f"发送Ticker取消订阅消息: {json.dumps(unsub_payload)}")
                await self.ws.send(json.dumps(unsub_payload))

    async def connect(self):
        """连接到WebSocket并处理消息"""
        if not self.watchlist:
            trading_logger.warning("Watchlist为空，不启动WebSocket连接。")
            # Schedule next update attempt if needed by the calling logic in scan_market
            return

        streams = [f"{symbol.lower()}@ticker" for symbol in self.watchlist]
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
        """处理从WebSocket接收到的消息 - 改为处理ticker数据"""
        try:
            data = json.loads(message)
            if data.get('e') == '24hrTicker':
                trading_logger.info(f"📊 收到Ticker消息: {data['s']} 价格={data['c']}")
            else:
                trading_logger.debug(f"收到WebSocket消息: {data}")  # 非ticker消息保持debug级别

            # 处理ticker数据（实时价格更新）
            if 'e' in data and data['e'] == '24hrTicker':
                ticker_data = data
                symbol = ticker_data['s']
                trading_logger.info(f"📈 Processing ticker for symbol: {symbol}. Current watchlist size: {len(self.watchlist)}")

                # 🛡️ 验证接收到的ticker符号是否有效
                if self.symbol_validator:
                    try:
                        is_valid = await self.symbol_validator.is_valid_watchlist_symbol(symbol)
                        if not is_valid:
                            trading_logger.warning(f"Received ticker for INVALID symbol {symbol}, rejecting data")
                            return
                    except Exception as e:
                        trading_logger.debug(f"Symbol validation check failed for {symbol}: {e}")
                        # 继续处理，但记录警告
                        pass

                if symbol not in self.watchlist:
                    trading_logger.debug(f"Symbol {symbol} NOT in watchlist, skipping.")
                    return

                trading_logger.debug(f"Symbol {symbol} IS in the watchlist. Proceeding to process ticker.")
                
                # 构造实时价格数据
                processed_ticker = {
                    'symbol': symbol,
                    'timestamp': int(time.time() * 1000),  # 当前时间戳
                    'open': float(ticker_data['o']),       # 24h开盘价
                    'high': float(ticker_data['h']),       # 24h最高价
                    'low': float(ticker_data['l']),        # 24h最低价
                    'close': float(ticker_data['c']),      # 当前价格（最重要！）
                    'volume': float(ticker_data['v']),     # 24h交易量
                    'price_change': float(ticker_data['P']), # 24h价格变化百分比
                    'price_change_abs': float(ticker_data['p']), # 24h价格变化绝对值
                    'weighted_avg_price': float(ticker_data['w']), # 24h加权平均价
                    'count': int(ticker_data['n']),        # 24h交易次数
                    'is_realtime': True,                   # 标记为实时数据
                    'data_source': 'ticker_stream'
                }
                
                trading_logger.info(f"💰 处理后Ticker for {symbol}: Price={processed_ticker['close']}, "
                                  f"24hChange={processed_ticker['price_change']:+.2f}%, "
                                  f"Volume={processed_ticker['volume']}")
                
                if self.data_queue:
                    trading_logger.info(f"📤 Sending ticker data for {symbol} to strategy (queue size: {self.data_queue.qsize()})")
                    await self.data_queue.put(processed_ticker)
                    trading_logger.info(f"✅ Successfully sent {symbol} ticker to strategy")
                else:
                    trading_logger.warning("⚠️ Data queue not available - ticker data cannot reach strategy!")

                # 更新Ticker缓存
                self.ticker_cache[symbol] = processed_ticker

            elif 'result' in data and data.get('result') is None and 'id' in data:
                # This is likely a subscription confirmation
                trading_logger.info(f"收到订阅确认/结果: {data}")
            elif 'error' in data:
                trading_logger.error(f"收到WebSocket错误消息: {data}")
            else:
                trading_logger.debug(f"收到其他类型的WebSocket消息: {data}")

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
                update_success = await self._update_watchlist_and_subscriptions()
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
        # self.stop_event.set() # Usually set by the caller or an error condition leading to stop
        if self.ws and self.is_running:
            try:
                trading_logger.info("显式关闭WebSocket...")
                await self.ws.close()
            except Exception as e:
                trading_logger.error(f"关闭WebSocket时出错: {e}", exc_info=True)
        else:
            trading_logger.info("WebSocket连接未激活或已关闭。")
        self.is_running = False
        self.ws = None # Clear the ws object

    async def _update_watchlist_and_subscriptions(self):
        """
        Fetches volatile symbols, gets tradable symbols from the executor,
        finds the intersection, and manages WebSocket subscriptions.
        This method replaces the original self.update_watchlist() for managing subscriptions.
        """
        trading_logger.info("Attempting to update watchlist and subscriptions...")

        try:
            # 动态watchlist管理 - 清除过时币种
            if hasattr(self, 'strategy') and self.strategy:
                symbols_to_remove = self.strategy.get_symbols_to_remove(
                    flat_timeout_minutes=self.flat_timeout_minutes,
                    max_failure_count=self.max_failure_count
                )
                
                # 检查排名阈值 - 但排除活跃持仓币种
                ranking_based_removals = self.strategy.get_symbols_by_ranking_threshold(
                    ranking_threshold=self.ranking_threshold
                )
                
                # 获取当前活跃持仓币种
                active_positions_symbols = set()
                if self.executor and hasattr(self.executor, 'get_active_positions_symbols'):
                    try:
                        active_positions_raw = await self.executor.get_active_positions_symbols()
                        # 转换为watchlist格式 (BTCUSDT)
                        active_positions_symbols = {s.replace('/', '') for s in active_positions_raw}
                        trading_logger.info(f"活跃持仓币种 (用于保护): {active_positions_symbols}")
                    except Exception as e:
                        trading_logger.error(f"获取活跃持仓时出错: {e}")
                
                # 过滤排名移除列表：保留有活跃持仓的币种
                filtered_ranking_removals = []
                for symbol in ranking_based_removals:
                    if symbol not in active_positions_symbols:
                        filtered_ranking_removals.append(symbol)
                        trading_logger.info(f"[{symbol}] 排名过低，将被移除 (无活跃持仓)")
                    else:
                        trading_logger.info(f"[{symbol}] 排名过低但有活跃持仓，保留在watchlist中")
                
                symbols_to_remove.extend(filtered_ranking_removals)
                
                # 从watchlist和策略中移除
                for symbol in symbols_to_remove:
                    if symbol in self.watchlist:
                        self.watchlist.remove(symbol)
                        trading_logger.info(f"Removed {symbol} from watchlist (dynamic management)")
                    self.strategy.remove_symbol(symbol)
                
                trading_logger.info(f"Dynamic management removed {len(symbols_to_remove)} symbols: {symbols_to_remove}")
                if filtered_ranking_removals:
                    trading_logger.info(f"Ranking-based removals (filtered): {len(filtered_ranking_removals)} symbols")

            # 1. Get volatile symbols (base format like 'BTC', 'ETH')
            gainers, losers = await self.fetch_coingecko_movers()
            if not gainers and not losers:
                trading_logger.warning("CoinGecko did not return any volatile symbols. Trying Binance 24h movers as fallback.")
                gainers, losers = await self.fetch_binance_24h_movers()
            
            if not gainers and not losers:
                trading_logger.error("Both CoinGecko and Binance 24h movers failed. Cannot determine candidate symbols.")
                # If we can't get candidates, we might still want to manage subscriptions for active positions.
                coingecko_derived_base_symbols = set()
            else:
                coingecko_derived_base_symbols = {s.upper() for s in gainers + losers if isinstance(s, str)}

            trading_logger.info(f"DEBUG: CoinGecko/Binance Movers derived base symbols (count {len(coingecko_derived_base_symbols)}): {coingecko_derived_base_symbols if len(coingecko_derived_base_symbols) < 50 else str(list(coingecko_derived_base_symbols)[:50]) + '...'}")

            # 2. Get all tradable USDT-margined futures/swaps from executor
            # Expected format from executor: Set of 'BTC/USDT:USDT' or 'ETH/USDT'
            all_executor_symbols_ccxt_format = await self.executor.get_all_binance_futures_symbols()
            
            executor_tradable_base_symbols = set()
            if not all_executor_symbols_ccxt_format:
                trading_logger.warning("Executor did not return any tradable symbols.")
            else:
                sample_executor_symbols = list(all_executor_symbols_ccxt_format)[:5]
                trading_logger.info(f"DEBUG: Sample of all_executor_symbols_ccxt_format (raw from executor, total {len(all_executor_symbols_ccxt_format)}): {sample_executor_symbols}")
                for sym in all_executor_symbols_ccxt_format:
                    if isinstance(sym, str) and "/USDT" in sym: 
                        base = sym.split("/USDT")[0] # Handles 'BTC/USDT:USDT' -> 'BTC', 'ETH/USDT' -> 'ETH'
                        executor_tradable_base_symbols.add(base.upper())
            
            trading_logger.info(f"DEBUG: Executor_tradable_base_symbols (processed, total {len(executor_tradable_base_symbols)}): {executor_tradable_base_symbols if len(executor_tradable_base_symbols) < 100 else str(list(executor_tradable_base_symbols)[:100]) + '...'}")

            # 3. Filter Coingecko/Binance movers by what's tradable on the exchange
            valid_tradeable_candidate_base_symbols = coingecko_derived_base_symbols.intersection(executor_tradable_base_symbols)
            
            # 更新候补池和排名缓存 - 基于交集结果
            self._update_candidate_pool_and_rankings(valid_tradeable_candidate_base_symbols, gainers, losers)
            trading_logger.info(f"DEBUG: Valid_tradeable_candidate_base_symbols (intersection result, count {len(valid_tradeable_candidate_base_symbols)}): {valid_tradeable_candidate_base_symbols}")

            # 4. Get currently active positions from executor
            active_positions_ccxt_format = await self.executor.get_active_positions_symbols() # Expected: Set of 'BTC/USDT'
            trading_logger.info(f"DEBUG: Active_positions_ccxt_format (raw from executor, count {len(active_positions_ccxt_format)}): {active_positions_ccxt_format}")

            # 🛡️ 正确的符号格式转换逻辑 (修复版本)
            active_positions_watchlist_format = set()
            trading_logger.info(f"🔍 DEBUG: Converting active positions from CCXT format: {active_positions_ccxt_format}")
            
            for s in active_positions_ccxt_format:
                if isinstance(s, str) and 'USDT' in s:
                    original_symbol = s
                    # 处理不同的符号格式
                    if ':USDT' in s:  # 永续合约格式: 'BTC/USDT:USDT'
                        base = s.split('/')[0]  # 提取基础币种
                        watchlist_symbol = f"{base.upper()}USDT"
                        trading_logger.debug(f"  永续合约转换: {original_symbol} -> {watchlist_symbol}")
                    elif '/USDT' in s:  # 现货格式: 'BTC/USDT'
                        base = s.split('/')[0]  # 提取基础币种
                        watchlist_symbol = f"{base.upper()}USDT"
                        trading_logger.debug(f"  现货转换: {original_symbol} -> {watchlist_symbol}")
                    else:  # 已经是正确格式: 'BTCUSDT'
                        watchlist_symbol = s.upper()
                        trading_logger.debug(f"  已正确格式: {original_symbol} -> {watchlist_symbol}")
                    
                    # 🛡️ 额外验证：检查是否出现USDTUSDT错误
                    if watchlist_symbol.endswith('USDTUSDT'):
                        trading_logger.error(f"⚠️ CRITICAL ERROR: Detected USDTUSDT format! Original: {original_symbol} -> Wrong: {watchlist_symbol}")
                        # 立即修复
                        watchlist_symbol = watchlist_symbol[:-4]  # 移除多余的USDT
                        trading_logger.info(f"✅ Auto-fixed to: {watchlist_symbol}")
                    
                    active_positions_watchlist_format.add(watchlist_symbol)
                    
            trading_logger.info(f"🎯 DEBUG: Converted active positions to watchlist format: {active_positions_watchlist_format}")
            
            # 🛡️ 验证活跃持仓符号格式的正确性
            if self.symbol_validator:
                try:
                    trading_logger.info(f"🔍 Running symbol validator on: {list(active_positions_watchlist_format)}")
                    valid_symbols, fixed_symbols, invalid_symbols = await self.symbol_validator.validate_and_fix_symbols(
                        list(active_positions_watchlist_format)
                    )
                    
                    if fixed_symbols:
                        trading_logger.warning(f"🔧 Active positions symbols auto-fixed: {fixed_symbols}")
                        # 更新为修复后的符号
                        active_positions_watchlist_format = set(valid_symbols + fixed_symbols)
                    
                    if invalid_symbols:
                        trading_logger.error(f"❌ Invalid active positions symbols detected and removed: {invalid_symbols}")
                        # 移除无效符号
                        active_positions_watchlist_format = set(valid_symbols + fixed_symbols)
                    
                    trading_logger.info(f"✅ Symbol validation completed. Final symbols: {active_positions_watchlist_format}")
                        
                except Exception as e:
                    trading_logger.error(f"❌ Symbol validation failed, proceeding without validation: {e}", exc_info=True)
            else:
                trading_logger.warning("⚠️ NO SYMBOL VALIDATOR AVAILABLE - This is the problem!")
            
            trading_logger.info(f"DEBUG: Active_positions_watchlist_format (processed 'BTCUSDT' format, count {len(active_positions_watchlist_format)}): {active_positions_watchlist_format}")
            
            # 5. Construct the final target watchlist (symbols like 'BTCUSDT')
            # Start with candidates, convert to 'BTCUSDT' format
            new_candidates = {f"{base}USDT" for base in valid_tradeable_candidate_base_symbols}
            
            # 限制新候选数量并从当前watchlist开始
            current_watchlist_copy = self.watchlist.copy()
            final_target_watchlist_symbols = current_watchlist_copy.copy()
            
            # 添加活跃持仓（必须保留）
            final_target_watchlist_symbols.update(active_positions_watchlist_format)
            
            # 从新候选中添加，但不超过最大watchlist大小
            for symbol in new_candidates:
                if len(final_target_watchlist_symbols) >= self.max_watchlist_size:
                    break
                final_target_watchlist_symbols.add(symbol)
            
            # 如果仍有空位，从候补池中补充
            if len(final_target_watchlist_symbols) < self.max_watchlist_size:
                needed_count = self.max_watchlist_size - len(final_target_watchlist_symbols)
                replacement_candidates = self._get_replacement_candidates(final_target_watchlist_symbols, needed_count)
                final_target_watchlist_symbols.update(replacement_candidates)
            trading_logger.info(f"DEBUG: Final_target_watchlist_symbols ('BTCUSDT' format, count {len(final_target_watchlist_symbols)}): {final_target_watchlist_symbols if len(final_target_watchlist_symbols) < 50 else str(list(final_target_watchlist_symbols)[:50]) + '...'}")
            
            # 6. Manage subscriptions
            # self.watchlist stores symbols like 'BTCUSDT'
            # self._send_subscription_update expects lists of symbols like 'BTCUSDT'
            
            # 🛡️ 最终验证：确保所有准备加入watchlist的符号都是有效的
            if self.symbol_validator:
                try:
                    valid_symbols, fixed_symbols, invalid_symbols = await self.symbol_validator.validate_and_fix_symbols(
                        list(final_target_watchlist_symbols)
                    )
                    
                    if fixed_symbols:
                        trading_logger.warning(f"Final watchlist symbols auto-fixed: {len(fixed_symbols)} symbols")
                    
                    if invalid_symbols:
                        trading_logger.error(f"Invalid symbols removed from final watchlist: {invalid_symbols}")
                    
                    # 更新为验证后的符号集合
                    final_target_watchlist_symbols = set(valid_symbols + fixed_symbols)
                    trading_logger.info(f"✅ Symbol validation complete. Final validated watchlist: {len(final_target_watchlist_symbols)} symbols")
                    
                except Exception as e:
                    trading_logger.warning(f"Final symbol validation failed, proceeding without validation: {e}")
            
            symbols_to_send_for_subscribe = list(final_target_watchlist_symbols - self.watchlist)
            symbols_to_send_for_unsubscribe = list(self.watchlist - final_target_watchlist_symbols)

            if not symbols_to_send_for_subscribe and not symbols_to_send_for_unsubscribe:
                trading_logger.info("Watchlist has not changed. No subscription updates needed.")
            else:
                if symbols_to_send_for_subscribe:
                    trading_logger.info(f"Requesting SUBSCRIBE for symbols: {symbols_to_send_for_subscribe}")
                if symbols_to_send_for_unsubscribe:
                    trading_logger.info(f"Requesting UNSUBSCRIBE for symbols: {symbols_to_send_for_unsubscribe}")
                await self._send_subscription_update(subscribe=symbols_to_send_for_subscribe, unsubscribe=symbols_to_send_for_unsubscribe)

            # 7. Update internal state
            self.watchlist = final_target_watchlist_symbols # Update with 'BTCUSDT' symbols
            self.active_subscriptions = {f"{s.lower()}@ticker" for s in self.watchlist} # Update with ticker stream names

            trading_logger.info(f"Watchlist update complete. Current watchlist symbols ('BTCUSDT' format): {self.watchlist if self.watchlist else 'is empty'}. Active ticker subscriptions ({len(self.active_subscriptions)}): {self.active_subscriptions if len(self.active_subscriptions) < 10 else str(list(self.active_subscriptions)[:10]) + '...'}")
            if not self.watchlist:
                 trading_logger.warning("Watchlist is empty after update. WebSocket will not subscribe to new ticker data.")
            return True # Indicate success of update attempt

        except Exception as e:
            trading_logger.error(f"Error updating watchlist and subscriptions: {e}", exc_info=True)
            # Attempt to gracefully stop subscriptions if an error occurs during update
            # Consider if self.active_subscriptions is reliable here.
            # If error is before self.active_subscriptions is set for the current run, it might be stale.
            # Safest is to try unsubscribing from what we think was active.
            current_subs_to_try_unsub = self.active_subscriptions.copy() # Make a copy
            if self.ws and hasattr(self.ws, 'open') and self.ws.open and current_subs_to_try_unsub:
                trading_logger.info(f"Attempting to unsubscribe from {len(current_subs_to_try_unsub)} streams due to error: {current_subs_to_try_unsub}")
                # _send_subscription_update expects symbols, not stream names.
                # We need to convert stream names back to symbols if possible, or clear all.
                # For simplicity here, if _send_subscription_update requires symbols,
                # and we only have stream names in self.active_subscriptions, this part is tricky.
                # The original _send_subscription_update takes symbols.
                # Let's assume we clear self.watchlist and self.active_subscriptions,
                # and the next successful run will fix subscriptions.
                # Or, _send_subscription_update could be enhanced to take stream names for unsubscribe.
                # For now, just log and reset internal state.
                # await self._send_subscription_update(unsubscribe=list(self.watchlist)) # This would use the PREVIOUS watchlist
                pass # Avoid complex recovery logic for now, focus on resetting state

            self.watchlist = set()
            self.active_subscriptions = set()
            trading_logger.info("Watchlist and active_subscriptions cleared due to error.")
            return False # Indicate failure

    def set_strategy(self, strategy):
        """设置策略实例，用于动态watchlist管理"""
        self.strategy = strategy
        trading_logger.info("Strategy instance set for dynamic watchlist management")
        
    def _update_candidate_pool_and_rankings(self, valid_tradeable_symbols: set, gainers: list, losers: list):
        """
        更新候补池和排名缓存
        
        Args:
            valid_tradeable_symbols: CoinGecko与币安交集后的有效可交易币种
            gainers: CoinGecko涨幅榜币种（用于排名）
            losers: CoinGecko跌幅榜币种（用于排名）
        """
        # 候补池 = 有效可交易币种（这些已经是CoinGecko与币安的交集）
        self.candidate_pool = valid_tradeable_symbols.copy()
        
        # 清除旧的排名缓存
        self.ranking_cache.clear()
        
        # 更新排名（基于CoinGecko原始榜单排名）
        all_ranked_symbols = gainers + losers  # CoinGecko原始榜单
        for idx, symbol in enumerate(all_ranked_symbols, 1):
            symbol_upper = symbol.upper()
            # 只为在有效交易集合中的币种记录排名
            if symbol_upper in valid_tradeable_symbols:
                self.ranking_cache[symbol_upper] = idx
                
                # 更新策略中的排名信息（USDT格式）
                if hasattr(self, 'strategy') and self.strategy:
                    self.strategy.update_symbol_ranking(f"{symbol_upper}USDT", idx)
        
        self.last_ranking_update = datetime.now()
        trading_logger.info(f"Updated candidate pool with {len(self.candidate_pool)} valid tradeable symbols")
        trading_logger.info(f"Recorded rankings for {len(self.ranking_cache)} symbols from CoinGecko榜单")
    
    def _get_replacement_candidates(self, current_watchlist: set, needed_count: int) -> list:
        """
        从候补池中选择替换候选币种
        
        Args:
            current_watchlist: 当前的watchlist
            needed_count: 需要的币种数量
            
        Returns:
            list: 选择的候选币种列表（USDT格式）
        """
        candidates = []
        
        # 将候补池转换为USDT格式并排除已在watchlist中的
        available_candidates = []
        for base_symbol in self.candidate_pool:
            usdt_symbol = f"{base_symbol}USDT"
            if usdt_symbol not in current_watchlist:
                ranking = self.ranking_cache.get(base_symbol, 999)  # 默认低排名
                available_candidates.append((usdt_symbol, ranking))
        
        # 按排名排序（排名越小越好）
        available_candidates.sort(key=lambda x: x[1])
        
        # 选择前N个
        candidates = [symbol for symbol, ranking in available_candidates[:needed_count]]
        
        trading_logger.info(f"Selected {len(candidates)} replacement candidates from pool of {len(available_candidates)}: {candidates}")
        return candidates

# Note: The main way to stop the scanner is by setting the self.stop_event
# from an external controller (e.g., the main application thread).
# The scan_market loop checks this event.