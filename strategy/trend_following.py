from typing import Dict, List, Optional
from datetime import datetime
from utils.logger import trading_logger
import time

# Define signal types as constants for clarity and to avoid typos
SIGNAL_TYPE_OPEN_LONG = 'OPEN_LONG'
SIGNAL_TYPE_OPEN_SHORT = 'OPEN_SHORT'
SIGNAL_TYPE_CLOSE_LONG_POSITIONS = 'CLOSE_LONG_POSITIONS'
SIGNAL_TYPE_CLOSE_SHORT_POSITIONS = 'CLOSE_SHORT_POSITIONS'

# Define trend states
TREND_STATE_UP = 'UP'
TREND_STATE_DOWN = 'DOWN'
TREND_STATE_FLAT = 'FLAT'

class TrendFollowingStrategy:
    """
    基于涨跌幅的趋势跟踪策略 - 动态基准价格版本
    
    核心思路:
    - 动态更新基准价格：新趋势开始或加仓时更新基准
    - 实时计算当前价格相对最新基准价格的涨跌幅
    - 当涨跌幅超过指定阈值时触发趋势信号
    - 支持循环开仓和独立止损止盈
    - 添加失败计数和FLAT时间跟踪，支持动态watchlist管理
    """
    
    def __init__(self,
                 # 基础交易参数
                 stop_loss_pct: float = 0.01,        # 止损百分比 1%
                 take_profit_pct: float = 0.02,      # 止盈百分比 2%
                 position_size: float = 10.0,        # 固定仓位大小(USDT)
                 
                 # 新的趋势参数
                 trend_trigger_pct: float = 2.0,     # 触发趋势的涨跌幅阈值(%)
                 trend_reset_pct: float = 0.5,       # 趋势重置阈值(%)，回到此范围内认为趋势结束
                 position_add_threshold_pct: float = 0.5,  # 加仓阈值(%)，价格变化达到此值后加仓
                 min_volume_check: bool = True,       # 是否检查最小交易量
                 
                 # 兼容旧参数 (保持接口兼容性)
                 min_price_change: float = 0.15,     
                 min_volume_increase: float = 1.1,   
                 min_kline_history: int = 3,          
                 breakout_period: int = 2,           
                 price_point_window_seconds: int = 300,
                 trend_chunk_seconds: int = 30,
                 min_chunk_price_change_pct: float = 0.05,
                 min_trend_confirm_chunks: int = 2):
        
        # 核心交易参数
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.position_size = position_size

        # 新的趋势判断参数
        self.trend_trigger_pct = trend_trigger_pct
        self.trend_reset_pct = trend_reset_pct
        self.position_add_threshold_pct = position_add_threshold_pct
        self.min_volume_check = min_volume_check
        
        # 数据存储 - 动态基准价格版本
        self.initial_prices = {}          # {symbol: initial_price} - 仅用于首次设置
        self.current_prices = {}          # {symbol: current_price} - 当前价格
        self.baseline_prices = {}         # {symbol: baseline_price} - 动态基准价格（关键！）
        self.price_change_pct = {}        # {symbol: change_pct} - 相对基准价格的涨跌幅
        
        # 趋势状态管理
        self.last_trend_state = {}        # {symbol: TREND_STATE_UP/DOWN/FLAT}
        self.trend_start_time = {}        # {symbol: timestamp} - 趋势开始时间
        self.last_signal_time = {}        # {symbol: timestamp} - 上次信号时间，防止重复信号
        
        # 开仓记录 (用于循环开仓)
        self.position_count = {}          # {symbol: {UP: count, DOWN: count}} - 各方向开仓数量
        self.last_open_price = {}         # {symbol: {UP: price, DOWN: price}} - 上次开仓价格
        
        # 动态watchlist管理相关数据
        self.flat_start_time = {}         # {symbol: timestamp} - FLAT状态开始时间
        self.failure_count = {}           # {symbol: count} - 失败计数（止损、交易失败等）
        self.last_activity_time = {}      # {symbol: timestamp} - 最后活动时间
        self.symbol_ranking = {}          # {symbol: ranking} - 币种在榜单中的排名
        
        # 兼容性数据结构 (保持向后兼容)
        self.kline_history = {}
        self.max_history_size = 15
        self.active_signals = {}

        trading_logger.info(
            f"TrendFollowingStrategy V3.2 initialized with: "
            f"TrendParams(trigger_pct={trend_trigger_pct}%, reset_pct={trend_reset_pct}%), "
            f"TradeParams(sl_pct={stop_loss_pct*100}%, tp_pct={take_profit_pct*100}%, pos_size_usdt={position_size}), "
            f"DynamicBaseline: True, DynamicWatchlistSupport: True"
        )

    def set_initial_price(self, symbol: str, price: float):
        """
        设置币种的初始价格（仅在首次时调用）
        
        Args:
            symbol: 交易对符号
            price: 初始价格
        """
        if symbol not in self.initial_prices:
            self.initial_prices[symbol] = price
            self.current_prices[symbol] = price
            self.baseline_prices[symbol] = price  # 初始基准价格
            self.price_change_pct[symbol] = 0.0
            self.last_trend_state[symbol] = TREND_STATE_FLAT
            self.position_count[symbol] = {'UP': 0, 'DOWN': 0}
            self.last_open_price[symbol] = {'UP': None, 'DOWN': None}
            
            trading_logger.info(f"[{symbol}] Initial price and baseline set to {price}")
        else:
            trading_logger.debug(f"[{symbol}] Initial price already set: {self.initial_prices[symbol]}")

    def _update_baseline_price(self, symbol: str, new_baseline: float, reason: str):
        """
        更新基准价格（趋势跟踪的核心）
        
        Args:
            symbol: 交易对符号
            new_baseline: 新的基准价格
            reason: 更新原因（用于日志）
        """
        old_baseline = self.baseline_prices.get(symbol, 0.0)
        self.baseline_prices[symbol] = new_baseline
        trading_logger.info(f"[{symbol}] Baseline price updated: {old_baseline:.6f} -> {new_baseline:.6f} ({reason})")

    def _calculate_price_change_pct(self, symbol: str, current_price: float) -> float:
        """
        计算价格相对当前基准价格的变化百分比（关键修改！）
        
        Args:
            symbol: 交易对符号
            current_price: 当前价格
            
        Returns:
            float: 变化百分比 (正数为上涨，负数为下跌)
        """
        if symbol not in self.baseline_prices:
            trading_logger.warning(f"[{symbol}] No baseline price set, using current price as baseline")
            self.set_initial_price(symbol, current_price)
            return 0.0
            
        baseline_price = self.baseline_prices[symbol]  # 使用动态基准价格！
        if baseline_price <= 0:
            return 0.0
            
        change_pct = ((current_price - baseline_price) / baseline_price) * 100
        return change_pct

    def _determine_trend_state(self, symbol: str, change_pct: float) -> str:
        """
        根据价格变化百分比确定趋势状态
        
        Args:
            symbol: 交易对符号
            change_pct: 价格变化百分比
            
        Returns:
            str: 趋势状态 (UP/DOWN/FLAT)
        """
        if change_pct >= self.trend_trigger_pct:
            return TREND_STATE_UP
        elif change_pct <= -self.trend_trigger_pct:
            return TREND_STATE_DOWN
        elif abs(change_pct) <= self.trend_reset_pct:
            return TREND_STATE_FLAT
        else:
            # 在reset和trigger之间，保持原有趋势
            return self.last_trend_state.get(symbol, TREND_STATE_FLAT)

    def _should_open_position(self, symbol: str, trend_state: str, current_price: float) -> bool:
        """
        判断是否应该开仓 (循环开仓逻辑)
        
        Args:
            symbol: 交易对符号
            trend_state: 当前趋势状态
            current_price: 当前价格
            
        Returns:
            bool: 是否应该开仓
        """
        # 如果趋势刚开始，立即开仓
        previous_state = self.last_trend_state.get(symbol, TREND_STATE_FLAT)
        if previous_state == TREND_STATE_FLAT and trend_state != TREND_STATE_FLAT:
            return True
            
        # 趋势延续时的循环开仓逻辑
        if trend_state == previous_state and trend_state != TREND_STATE_FLAT:
            last_price = self.last_open_price[symbol].get(trend_state)
            if last_price is None:
                return True
                
            # 计算价格变化，决定是否加仓
            if trend_state == TREND_STATE_UP:
                price_improvement = ((current_price - last_price) / last_price) * 100
                return price_improvement >= self.position_add_threshold_pct  # 价格再上涨阈值时加仓
            else:  # TREND_STATE_DOWN
                price_improvement = ((last_price - current_price) / last_price) * 100
                return price_improvement >= self.position_add_threshold_pct  # 价格再下跌阈值时加仓
                
        return False

    def analyze_market(self, market_data: Dict) -> Optional[Dict]:
        """
        分析市场数据并生成交易信号 - 基于动态基准价格的趋势跟踪
        支持ticker数据（实时价格）和K线数据
        
        Args:
            market_data: 市场数据字典，包含价格、成交量等信息
            
        Returns:
            Optional[Dict]: 交易信号，如果没有信号则返回None
        """
        try:
            symbol = market_data['symbol']
            current_price = market_data['close']  # ticker和kline都有close字段
            current_volume = market_data['volume']
            current_timestamp = time.time()
            
            # 检测数据源类型
            data_source = market_data.get('data_source', 'unknown')
            is_realtime = market_data.get('is_realtime', False)
            
            trading_logger.debug(f"[{symbol}] 接收到{data_source}数据，实时: {is_realtime}, 价格: {current_price}")
            
            # 确保初始价格已设置
            if symbol not in self.baseline_prices:
                self.set_initial_price(symbol, current_price)
                return None  # 首次设置初始价格，不生成信号
            
            # 更新最后活动时间
            self.last_activity_time[symbol] = current_timestamp
            
            # 更新当前价格和计算涨跌幅（基于动态基准价格）
            self.current_prices[symbol] = current_price
            change_pct = self._calculate_price_change_pct(symbol, current_price)
            self.price_change_pct[symbol] = change_pct
            
            # 确定当前趋势状态
            current_trend = self._determine_trend_state(symbol, change_pct)
            previous_trend = self.last_trend_state.get(symbol, TREND_STATE_FLAT)
            
            # 跟踪FLAT状态开始时间
            if current_trend == TREND_STATE_FLAT and previous_trend != TREND_STATE_FLAT:
                self.flat_start_time[symbol] = current_timestamp
            elif current_trend != TREND_STATE_FLAT:
                # 退出FLAT状态，清除FLAT开始时间
                if symbol in self.flat_start_time:
                    del self.flat_start_time[symbol]
            
            baseline_price = self.baseline_prices[symbol]
            
            # 获取额外信息用于日志
            extra_info = ""
            if data_source == 'ticker_stream':
                price_change_24h = market_data.get('price_change', 0.0)
                trade_count = market_data.get('count', 0)
                extra_info = f", 24h变化: {price_change_24h:+.2f}%, 交易次数: {trade_count}"
            
            # 增强日志输出，显示触发阈值对比
            trigger_threshold = self.trend_trigger_pct
            reset_threshold = self.trend_reset_pct
            abs_change = abs(change_pct)
            
            trading_logger.debug(f"[{symbol}] Price: {current_price}, Baseline: {baseline_price}, "
                              f"Change: {change_pct:+.3f}% (|{abs_change:.3f}%|), "
                              f"Thresholds: trigger={trigger_threshold:.3f}%, reset={reset_threshold:.3f}%, "
                              f"Trend: {previous_trend}→{current_trend}, Volume: {current_volume}{extra_info}")
            
            signal_to_generate = None
            current_time = current_timestamp
            
            # 防止短时间内重复信号 (至少间隔30秒)
            last_signal = self.last_signal_time.get(symbol, 0)
            if current_time - last_signal < 30:
                trading_logger.debug(f"[{symbol}] Signal cooldown active, skipping")
                self.last_trend_state[symbol] = current_trend
                return None
            
            # 趋势状态机逻辑
            if current_trend == TREND_STATE_UP:
                if previous_trend == TREND_STATE_DOWN:
                    # 趋势反转：下跌转上涨，先平空仓，更新基准价格
                    trading_logger.info(f"[{symbol}] TREND_REVERSAL: DOWN→UP at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "REVERSAL_TO_UP")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_SHORT_POSITIONS, current_price, current_volume, market_data)
                    self.trend_start_time[symbol] = current_time
                    self.position_count[symbol]['DOWN'] = 0
                    # 重要：不要立即更新状态，等下一次tick再开多仓
                    self.last_trend_state[symbol] = TREND_STATE_FLAT  # 设为过渡状态
                    if signal_to_generate:
                        self.last_signal_time[symbol] = current_time
                    return signal_to_generate
                elif previous_trend == TREND_STATE_FLAT:
                    # 新上涨趋势开始，更新基准价格
                    trading_logger.info(f"[{symbol}] TREND_START_UP at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "NEW_UPTREND_START")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_LONG, current_price, current_volume, market_data)
                    self.trend_start_time[symbol] = current_time
                    self.position_count[symbol]['UP'] = 1
                    self.last_open_price[symbol]['UP'] = current_price
                elif self._should_open_position(symbol, TREND_STATE_UP, current_price):
                    # 趋势延续：循环加仓，更新基准价格为当前开仓价格
                    trading_logger.info(f"[{symbol}] TREND_CONTINUE_UP: Adding position at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "UPTREND_ADD_POSITION")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_LONG, current_price, current_volume, market_data)
                    self.position_count[symbol]['UP'] += 1
                    self.last_open_price[symbol]['UP'] = current_price
                    
            elif current_trend == TREND_STATE_DOWN:
                if previous_trend == TREND_STATE_UP:
                    # 趋势反转：上涨转下跌，先平多仓，更新基准价格
                    trading_logger.info(f"[{symbol}] TREND_REVERSAL: UP→DOWN at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "REVERSAL_TO_DOWN")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_LONG_POSITIONS, current_price, current_volume, market_data)
                    self.trend_start_time[symbol] = current_time
                    self.position_count[symbol]['UP'] = 0
                    # 重要：不要立即更新状态，等下一次tick再开空仓
                    self.last_trend_state[symbol] = TREND_STATE_FLAT  # 设为过渡状态
                    if signal_to_generate:
                        self.last_signal_time[symbol] = current_time
                    return signal_to_generate
                elif previous_trend == TREND_STATE_FLAT:
                    # 新下跌趋势开始，更新基准价格
                    trading_logger.info(f"[{symbol}] TREND_START_DOWN at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "NEW_DOWNTREND_START")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_SHORT, current_price, current_volume, market_data)
                    self.trend_start_time[symbol] = current_time
                    self.position_count[symbol]['DOWN'] = 1
                    self.last_open_price[symbol]['DOWN'] = current_price
                elif self._should_open_position(symbol, TREND_STATE_DOWN, current_price):
                    # 趋势延续：循环加仓，更新基准价格为当前开仓价格
                    trading_logger.info(f"[{symbol}] TREND_CONTINUE_DOWN: Adding position at {change_pct:+.2f}%")
                    self._update_baseline_price(symbol, current_price, "DOWNTREND_ADD_POSITION")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_SHORT, current_price, current_volume, market_data)
                    self.position_count[symbol]['DOWN'] += 1
                    self.last_open_price[symbol]['DOWN'] = current_price
                    
            elif current_trend == TREND_STATE_FLAT:
                if previous_trend == TREND_STATE_UP:
                    # 上涨趋势结束，平仓，基准价格保持不变（等待新趋势）
                    trading_logger.info(f"[{symbol}] TREND_END_UP at {change_pct:+.2f}%")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_LONG_POSITIONS, current_price, current_volume, market_data)
                    self.position_count[symbol]['UP'] = 0
                elif previous_trend == TREND_STATE_DOWN:
                    # 下跌趋势结束，平仓，基准价格保持不变（等待新趋势）
                    trading_logger.info(f"[{symbol}] TREND_END_DOWN at {change_pct:+.2f}%")
                    signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_SHORT_POSITIONS, current_price, current_volume, market_data)
                    self.position_count[symbol]['DOWN'] = 0
            
            # 更新状态
            self.last_trend_state[symbol] = current_trend
            if signal_to_generate:
                self.last_signal_time[symbol] = current_time
                
            return signal_to_generate
            
        except Exception as e:
            trading_logger.error(f"Error in analyze_market for {symbol}: {e}", exc_info=True)
            return None

    def _generate_signal_dict(self, symbol: str, signal_type: str, current_price: float, current_volume: float, market_data: Dict) -> Dict:
        """生成标准的交易信号字典"""
        sl = 0.0
        tp = 0.0
        signal_position_size = 0.0

        if signal_type == SIGNAL_TYPE_OPEN_LONG:
            sl = current_price * (1 - self.stop_loss_pct)
            tp = current_price * (1 + self.take_profit_pct)
            signal_position_size = self.position_size
        elif signal_type == SIGNAL_TYPE_OPEN_SHORT:
            sl = current_price * (1 + self.stop_loss_pct)
            tp = current_price * (1 - self.take_profit_pct)
            signal_position_size = self.position_size
        
        # 确定数据源和间隔
        data_source = market_data.get('data_source', 'unknown')
        interval = 'realtime' if market_data.get('is_realtime') else market_data.get('kline_interval', '1m')
        
        return {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'type': signal_type,
            'price': current_price,
            'volume': current_volume, 
            'stop_loss': sl if signal_type in [SIGNAL_TYPE_OPEN_LONG, SIGNAL_TYPE_OPEN_SHORT] else 0.0,
            'take_profit': tp if signal_type in [SIGNAL_TYPE_OPEN_LONG, SIGNAL_TYPE_OPEN_SHORT] else 0.0,
            'strategy': 'TrendFollowingV3.2_DynamicBaseline_Realtime', 
            'data_interval': interval, 
            'data_source': data_source,
            'position_size_usdt': signal_position_size,
            'price_change_pct': self.price_change_pct.get(symbol, 0.0),
            'baseline_price': self.baseline_prices.get(symbol, 0.0),
            'initial_price': self.initial_prices.get(symbol, 0.0)
        }

    def reset_symbol_state(self, symbol: str):
        """
        重置指定币种的状态 (可用于强制重新开始)
        
        Args:
            symbol: 交易对符号
        """
        if symbol in self.baseline_prices:
            current_price = self.current_prices.get(symbol, self.baseline_prices[symbol])
            trading_logger.info(f"[{symbol}] Resetting state, new baseline price: {current_price}")
            
            self._update_baseline_price(symbol, current_price, "MANUAL_RESET")
            self.price_change_pct[symbol] = 0.0
            self.last_trend_state[symbol] = TREND_STATE_FLAT
            self.position_count[symbol] = {'UP': 0, 'DOWN': 0}
            self.last_open_price[symbol] = {'UP': None, 'DOWN': None}

    def get_status_summary(self) -> Dict:
        """
        获取策略状态摘要
            
        Returns:
            Dict: 状态摘要信息
        """
        summary = {
            'tracked_symbols': len(self.baseline_prices),
            'trends': {},
            'positions': {},
            'baselines': {},
            'total_positions': 0
        }
        
        for symbol in self.baseline_prices:
            trend = self.last_trend_state.get(symbol, TREND_STATE_FLAT)
            change_pct = self.price_change_pct.get(symbol, 0.0)
            positions = self.position_count.get(symbol, {'UP': 0, 'DOWN': 0})
            baseline = self.baseline_prices.get(symbol, 0.0)
            current = self.current_prices.get(symbol, 0.0)
            
            summary['trends'][symbol] = f"{trend} ({change_pct:+.2f}%)"
            summary['positions'][symbol] = f"Long:{positions['UP']} Short:{positions['DOWN']}"
            summary['baselines'][symbol] = f"Current:{current:.6f} Baseline:{baseline:.6f}"
            summary['total_positions'] += positions['UP'] + positions['DOWN']
            
        return summary

    # 兼容性方法 (保持向后兼容)
    def update_market_data(self, market_data: Dict):
        """更新市场数据 - 兼容性方法"""
        symbol = market_data['symbol']
        if symbol not in self.kline_history:
            self.kline_history[symbol] = []
        self.kline_history[symbol].append(market_data)
        
        if len(self.kline_history[symbol]) > self.max_history_size:
            self.kline_history[symbol] = self.kline_history[symbol][-self.max_history_size:]
            
    def get_active_signals(self) -> List[Dict]:
        """获取活跃信号 - 兼容性方法"""
        return list(self.active_signals.values())
        
    def remove_signal(self, symbol: str, signal_id_to_remove: Optional[str] = None):
        """移除信号 - 兼容性方法"""
        if symbol in self.active_signals:
            del self.active_signals[symbol]
        trading_logger.info(f"Signal removed for {symbol}")

    def record_trade_failure(self, symbol: str, failure_type: str = "stop_loss"):
        """
        记录交易失败（止损、交易错误等）
        
        Args:
            symbol: 交易对符号
            failure_type: 失败类型（stop_loss, error, timeout等）
        """
        if symbol not in self.failure_count:
            self.failure_count[symbol] = 0
        
        self.failure_count[symbol] += 1
        trading_logger.info(f"[{symbol}] Trade failure recorded ({failure_type}), total failures: {self.failure_count[symbol]}")

    def get_symbols_to_remove(self, flat_timeout_minutes: int = 30, max_failure_count: int = 3) -> List[str]:
        """
        获取需要从watchlist中移除的币种
        
        Args:
            flat_timeout_minutes: FLAT状态超时时间（分钟）
            max_failure_count: 最大失败次数
            
        Returns:
            List[str]: 需要移除的币种列表
        """
        current_time = time.time()
        symbols_to_remove = []
        
        for symbol in list(self.baseline_prices.keys()):
            remove_reason = None
            
            # 检查FLAT状态超时
            if symbol in self.flat_start_time:
                flat_duration = (current_time - self.flat_start_time[symbol]) / 60  # 转换为分钟
                if flat_duration > flat_timeout_minutes:
                    remove_reason = f"FLAT_TIMEOUT ({flat_duration:.1f}min)"
            
            # 检查失败次数过多
            if symbol in self.failure_count and self.failure_count[symbol] >= max_failure_count:
                remove_reason = f"MAX_FAILURES ({self.failure_count[symbol]})"
            
            if remove_reason:
                symbols_to_remove.append(symbol)
                trading_logger.info(f"[{symbol}] Marked for removal: {remove_reason}")
        
        return symbols_to_remove

    def remove_symbol(self, symbol: str):
        """
        从策略中移除币种的所有数据
        
        Args:
            symbol: 要移除的交易对符号
        """
        # 移除所有相关数据
        data_fields = [
            'initial_prices', 'current_prices', 'baseline_prices', 'price_change_pct',
            'last_trend_state', 'trend_start_time', 'last_signal_time',
            'position_count', 'last_open_price', 'flat_start_time',
            'failure_count', 'last_activity_time', 'symbol_ranking'
        ]
        
        for field in data_fields:
            if hasattr(self, field):
                field_dict = getattr(self, field)
                if symbol in field_dict:
                    del field_dict[symbol]  # 修复：使用del dict[key]而不是delattr
        
        trading_logger.info(f"[{symbol}] Removed from strategy tracking")

    def update_symbol_ranking(self, symbol: str, ranking: int):
        """
        更新币种在榜单中的排名
        
        Args:
            symbol: 交易对符号
            ranking: 排名（1为最高）
        """
        self.symbol_ranking[symbol] = ranking

    def get_symbols_by_ranking_threshold(self, ranking_threshold: int = 20) -> List[str]:
        """
        获取排名超过阈值的币种
        
        Args:
            ranking_threshold: 排名阈值
            
        Returns:
            List[str]: 排名超过阈值的币种列表
        """
        symbols_to_remove = []
        for symbol, ranking in self.symbol_ranking.items():
            if ranking > ranking_threshold:
                symbols_to_remove.append(symbol)
                trading_logger.info(f"[{symbol}] Low ranking detected: {ranking} > {ranking_threshold}")
        
        return symbols_to_remove
