"""
CryptoPulse Trader - 趋势跟踪策略 原始版本备份
==============================================

此文件备份了基于区块(chunk)的趋势判断方法的原始实现
备份日期: 2025-06-04
备份原因: 准备进行大改前的存档

核心方法:
1. _calculate_custom_trend() - 区块趋势计算的核心逻辑
2. analyze_market() - 市场分析和信号生成
3. 相关的数据结构和参数定义

原始设计思路:
- 将时间分割为固定的时间块(chunk)，默认30秒
- 在每个时间块内收集价格点，计算开盘价到收盘价的变化百分比
- 需要连续N个时间块(默认2个)都朝同一方向变化才确认趋势
- 使用状态机管理趋势转换和交易信号生成
"""

from typing import Dict, Optional
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

class OriginalTrendFollowingStrategy:
    """
    原始的趋势跟踪策略 - 基于时间块(chunk)的趋势判断
    
    核心参数说明:
    - price_point_window_seconds: 价格点保留窗口(默认300秒=5分钟)
    - trend_chunk_seconds: 趋势分析时间块长度(默认30秒)
    - min_chunk_price_change_pct: 时间块内最小价格变化百分比(默认0.05%=5个基点)
    - min_trend_confirm_chunks: 确认趋势需要的连续时间块数量(默认2个)
    """
    
    def __init__(self,
                 # Old parameters (will be reviewed/phased out)
                 min_price_change: float = 0.15,     
                 min_volume_increase: float = 1.1,   
                 stop_loss_pct: float = 0.01,        
                 take_profit_pct: float = 0.02,      
                 position_size: float = 10.0,         
                 min_kline_history: int = 3,          
                 breakout_period: int = 2,           
                 
                 # New parameters for custom interval trend
                 price_point_window_seconds: int = 300, # Keep 5 mins of price points
                 trend_chunk_seconds: int = 30,         # Analysis chunk duration
                 min_chunk_price_change_pct: float = 0.05, # Min change in a chunk
                 min_trend_confirm_chunks: int = 2):     # Consecutive chunks to confirm trend
        
        # 核心时间块参数
        self.price_point_window_seconds = price_point_window_seconds
        if trend_chunk_seconds <= 0:
            trading_logger.warning(f"trend_chunk_seconds was <=0 ({trend_chunk_seconds}), setting to 1.")
            self.trend_chunk_seconds = 1 
        else:
            self.trend_chunk_seconds = trend_chunk_seconds
        self.min_chunk_price_change_pct = min_chunk_price_change_pct
        self.min_trend_confirm_chunks = min_trend_confirm_chunks

        # 交易参数
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.position_size = position_size

        # 数据结构
        self.price_points = {} # 存储原始价格点: {symbol: [(timestamp, price), ...]}
        
        # 状态管理
        self.last_confirmed_trend_state = {} # {symbol: TREND_STATE_UP/DOWN/FLAT}
        self.trend_first_confirmation_chunk_id = {} # {symbol: chunk_id}
        self.last_action_chunk_id = {} # {action_key: chunk_id}

    def _calculate_custom_trend(self, symbol: str, current_ts: float, current_price: float) -> Optional[str]:
        """
        【核心方法】基于价格点在定义时间块内的变化计算趋势
        
        算法逻辑:
        1. 确保有足够的历史数据跨度 (需要 min_trend_confirm_chunks * trend_chunk_seconds)
        2. 从最近完成的时间块开始，向历史回溯分析指定数量的时间块
        3. 计算每个时间块内第一个价格点到最后一个价格点的变化百分比
        4. 只有当所有必需的时间块都朝同一方向变化且幅度超过阈值时，才确认趋势
        
        Args:
            symbol: 交易对符号
            current_ts: 当前时间戳
            current_price: 当前价格
            
        Returns:
            TREND_STATE_UP: 上升趋势
            TREND_STATE_DOWN: 下降趋势  
            None: 无明确趋势
        """
        points = self.price_points.get(symbol, [])
        if not points:
            trading_logger.info(f"[{symbol}] No price points for trend calculation.")
            return None

        # 确保有足够的总时间跨度来形成所需数量的时间块
        min_total_span_needed = self.trend_chunk_seconds * self.min_trend_confirm_chunks
        
        if (points[-1][0] - points[0][0]) < min_total_span_needed:
            trading_logger.info(f"[{symbol}] Insufficient data span for trend. Have {points[-1][0] - points[0][0]:.2f}s, need {min_total_span_needed:.2f}s for {self.min_trend_confirm_chunks} chunks.")
            return None

        chunk_changes_pct = []
        
        # 计算最近完成的时间块结束时间
        # current_ts是"现在"，当前时间块是 current_ts // trend_chunk_seconds
        # 最近完成的时间块结束于 (current_chunk_id * trend_chunk_seconds)
        most_recent_chunk_end_ts = (current_ts // self.trend_chunk_seconds) * self.trend_chunk_seconds
        
        # 分析需要的连续历史时间块
        for i in range(self.min_trend_confirm_chunks):
            # i=0 是最近完成的时间块, i=1 是前一个时间块, 等等
            chunk_end_ts = most_recent_chunk_end_ts - (i * self.trend_chunk_seconds)
            chunk_start_ts = chunk_end_ts - self.trend_chunk_seconds

            # 筛选严格落在此历史时间块内的价格点 [chunk_start_ts, chunk_end_ts)
            chunk_points = [pp for pp in points if chunk_start_ts <= pp[0] < chunk_end_ts]

            if len(chunk_points) < 2:
                trading_logger.info(f"[{symbol}] Not enough points in chunk {i+1} ({len(chunk_points)} points) for trend calc. Range: {chunk_start_ts}-{chunk_end_ts}")
                return None  # 某个必需的历史时间块中数据不足

            # 计算时间块内的价格变化百分比
            chunk_open_price = chunk_points[0][1]   # 时间块内第一个价格
            chunk_close_price = chunk_points[-1][1] # 时间块内最后一个价格
            
            if chunk_open_price == 0: # 避免除零错误
                change_pct = 0.0
            else:
                change_pct = ((chunk_close_price - chunk_open_price) / chunk_open_price) * 100
            
            chunk_changes_pct.append(change_pct)
        
        # chunk_changes_pct 现在包含从最新到最旧的变化
        # 例如，如果 min_trend_confirm_chunks = 2: [最近完成块的变化, 前一个块的变化]
        
        if len(chunk_changes_pct) < self.min_trend_confirm_chunks:
             trading_logger.info(f"[{symbol}] Not enough historical chunks with sufficient data. Got {len(chunk_changes_pct)}, need {self.min_trend_confirm_chunks}")
             return None

        # 统计上涨和下跌的确认时间块数量
        confirmed_up_chunks = 0
        confirmed_down_chunks = 0

        for change in chunk_changes_pct: # 从最近完成块的变化到更早的块
            if change > self.min_chunk_price_change_pct:
                confirmed_up_chunks += 1
            elif change < -self.min_chunk_price_change_pct:
                confirmed_down_chunks += 1
            # 如果变化在 -min_chunk_price_change_pct 到 +min_chunk_price_change_pct 之间，该块为中性
            # 要确认趋势，所有 min_trend_confirm_chunks 都必须朝同一强方向变化

        trading_logger.info(f"[{symbol}] CustomTrend: prices={[(p[0]-current_ts, p[1]) for p in points[-5:]]}, changes={chunk_changes_pct}, up={confirmed_up_chunks}, down={confirmed_down_chunks}, required={self.min_trend_confirm_chunks}")

        # 趋势确认逻辑
        if confirmed_up_chunks >= self.min_trend_confirm_chunks and confirmed_down_chunks == 0 : # 所有块都是上涨
            return TREND_STATE_UP
        elif confirmed_down_chunks >= self.min_trend_confirm_chunks and confirmed_up_chunks == 0: # 所有块都是下跌
            return TREND_STATE_DOWN
        
        return None # 无确认趋势 / 混合信号 / 弱信号

    def analyze_market_original(self, market_data: Dict) -> Optional[Dict]:
        """
        【核心方法】分析市场数据并生成交易信号 - 原始完整版本
        
        状态机逻辑:
        1. 更新价格点历史
        2. 计算当前趋势
        3. 根据前一状态和当前趋势决定动作:
           - 趋势延续: 继续开仓 (但每个时间块只开一次)
           - 趋势反转: 先平仓反向头寸
           - 趋势结束: 平仓所有头寸
           - 新趋势: 观察等待确认
        
        Args:
            market_data: 市场数据字典，包含价格、成交量等信息
            
        Returns:
            Optional[Dict]: 交易信号，如果没有信号则返回None
        """
        try:
            symbol = market_data['symbol']
            current_price = market_data['close'] 
            current_volume = market_data['volume'] 
            current_timestamp = time.time()
            current_chunk_id = int(current_timestamp // self.trend_chunk_seconds)

            trading_logger.info(f"[{symbol}] Analyzing market data: price={current_price}, volume={current_volume}, is_closed={market_data.get('is_closed', 'unknown')}")

            # 更新价格点
            if symbol not in self.price_points:
                self.price_points[symbol] = []
            self.price_points[symbol].append((current_timestamp, current_price))
            cutoff_timestamp = current_timestamp - self.price_point_window_seconds
            self.price_points[symbol] = [pp for pp in self.price_points[symbol] if pp[0] >= cutoff_timestamp]

            # 计算当前趋势
            current_calculated_trend = self._calculate_custom_trend(symbol, current_timestamp, current_price)
            trading_logger.info(f"[{symbol}] Calculated trend: {current_calculated_trend}, price_points_count: {len(self.price_points.get(symbol, []))}")
            
            # 获取历史状态
            previous_trend_state = self.last_confirmed_trend_state.get(symbol, TREND_STATE_FLAT)
            first_confirmation_chunk_id_for_symbol: Optional[int] = self.trend_first_confirmation_chunk_id.get(symbol)

            # 动作键定义
            action_key_open_long = f"{symbol}_{SIGNAL_TYPE_OPEN_LONG}"
            action_key_open_short = f"{symbol}_{SIGNAL_TYPE_OPEN_SHORT}"
            action_key_close = f"{symbol}_CLOSE_POSITIONS" 

            signal_to_generate = None

            # 状态机逻辑 - 上升趋势
            if current_calculated_trend == TREND_STATE_UP:
                if previous_trend_state == TREND_STATE_UP:
                    # 趋势延续 - 继续开多仓
                    if first_confirmation_chunk_id_for_symbol is not None and current_chunk_id > first_confirmation_chunk_id_for_symbol:
                        if self.last_action_chunk_id.get(action_key_open_long) != current_chunk_id:
                            trading_logger.info(f"[{symbol}] TREND_CONTINUES_UP: Generating OPEN_LONG. Prev state: UP. Current Chunk: {current_chunk_id}. First Confirm Chunk: {first_confirmation_chunk_id_for_symbol}")
                            self.last_action_chunk_id[action_key_open_long] = current_chunk_id
                            signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_LONG, current_price, current_volume, market_data)
                        else:
                            trading_logger.debug(f"[{symbol}] TREND_CONTINUES_UP: Already acted (OPEN_LONG) in Current Chunk {current_chunk_id}. Prev state: UP.")
                    else:
                        trading_logger.info(f"[{symbol}] TREND_STILL_UP (or first confirm): Observing. Prev state: UP. Current Chunk: {current_chunk_id}. First Confirm Chunk: {first_confirmation_chunk_id_for_symbol}")
                        if first_confirmation_chunk_id_for_symbol is None:
                             self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_UP
                elif previous_trend_state == TREND_STATE_DOWN:
                    # 趋势反转 - 先平空仓
                    if self.last_action_chunk_id.get(action_key_close) != current_chunk_id:
                        trading_logger.info(f"[{symbol}] TREND_REVERSAL_TO_UP: Closing SHORT positions. Prev state: DOWN. Current Chunk: {current_chunk_id}")
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_UP
                        self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                        self.last_action_chunk_id[action_key_close] = current_chunk_id
                        self.last_action_chunk_id[action_key_open_long] = current_chunk_id 
                        signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_SHORT_POSITIONS, current_price, current_volume, market_data)
                    else:
                        trading_logger.debug(f"[{symbol}] TREND_REVERSAL_TO_UP: Already closed in Current Chunk {current_chunk_id}. Prev state: DOWN.")
                else: 
                    # 新上升趋势检测
                    trading_logger.info(f"[{symbol}] NEW_TREND_DETECTED_UP: Observing. Prev state: {previous_trend_state}. Current Chunk: {current_chunk_id}")
                    self.last_confirmed_trend_state[symbol] = TREND_STATE_UP
                    self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                    
            # 状态机逻辑 - 下降趋势
            elif current_calculated_trend == TREND_STATE_DOWN:
                if previous_trend_state == TREND_STATE_DOWN:
                    # 趋势延续 - 继续开空仓
                    if first_confirmation_chunk_id_for_symbol is not None and current_chunk_id > first_confirmation_chunk_id_for_symbol:
                        if self.last_action_chunk_id.get(action_key_open_short) != current_chunk_id:
                            trading_logger.info(f"[{symbol}] TREND_CONTINUES_DOWN: Generating OPEN_SHORT. Prev state: DOWN. Current Chunk: {current_chunk_id}. First Confirm Chunk: {first_confirmation_chunk_id_for_symbol}")
                            self.last_action_chunk_id[action_key_open_short] = current_chunk_id
                            signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_OPEN_SHORT, current_price, current_volume, market_data)
                        else:
                            trading_logger.debug(f"[{symbol}] TREND_CONTINUES_DOWN: Already acted (OPEN_SHORT) in Current Chunk {current_chunk_id}. Prev state: DOWN.")
                    else:
                        trading_logger.info(f"[{symbol}] TREND_STILL_DOWN (or first confirm): Observing. Prev state: DOWN. Current Chunk: {current_chunk_id}. First Confirm Chunk: {first_confirmation_chunk_id_for_symbol}")
                        if first_confirmation_chunk_id_for_symbol is None:
                            self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_DOWN
                elif previous_trend_state == TREND_STATE_UP:
                    # 趋势反转 - 先平多仓
                    if self.last_action_chunk_id.get(action_key_close) != current_chunk_id:
                        trading_logger.info(f"[{symbol}] TREND_REVERSAL_TO_DOWN: Closing LONG positions. Prev state: UP. Current Chunk: {current_chunk_id}")
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_DOWN
                        self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                        self.last_action_chunk_id[action_key_close] = current_chunk_id
                        self.last_action_chunk_id[action_key_open_short] = current_chunk_id
                        signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_LONG_POSITIONS, current_price, current_volume, market_data)
                    else:
                        trading_logger.debug(f"[{symbol}] TREND_REVERSAL_TO_DOWN: Already closed in Current Chunk {current_chunk_id}. Prev state: UP.")
                else: 
                    # 新下降趋势检测
                    trading_logger.info(f"[{symbol}] NEW_TREND_DETECTED_DOWN: Observing. Prev state: {previous_trend_state}. Current Chunk: {current_chunk_id}")
                    self.last_confirmed_trend_state[symbol] = TREND_STATE_DOWN
                    self.trend_first_confirmation_chunk_id[symbol] = current_chunk_id
                    
            # 状态机逻辑 - 趋势结束(平盘)
            elif current_calculated_trend is None: 
                if previous_trend_state == TREND_STATE_UP:
                    # 上升趋势结束 - 平多仓
                    if self.last_action_chunk_id.get(action_key_close) != current_chunk_id:
                        trading_logger.info(f"[{symbol}] TREND_ENDED_UP_TO_FLAT: Closing LONG positions. Prev state: UP. Current Chunk: {current_chunk_id}")
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_FLAT
                        self.trend_first_confirmation_chunk_id.pop(symbol, None) 
                        self.last_action_chunk_id[action_key_close] = current_chunk_id
                        signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_LONG_POSITIONS, current_price, current_volume, market_data)
                    else:
                        trading_logger.debug(f"[{symbol}] TREND_ENDED_UP_TO_FLAT: Already closed in Current Chunk {current_chunk_id}. Prev state: UP.")
                elif previous_trend_state == TREND_STATE_DOWN:
                    # 下降趋势结束 - 平空仓
                    if self.last_action_chunk_id.get(action_key_close) != current_chunk_id:
                        trading_logger.info(f"[{symbol}] TREND_ENDED_DOWN_TO_FLAT: Closing SHORT positions. Prev state: DOWN. Current Chunk: {current_chunk_id}")
                        self.last_confirmed_trend_state[symbol] = TREND_STATE_FLAT
                        self.trend_first_confirmation_chunk_id.pop(symbol, None) 
                        self.last_action_chunk_id[action_key_close] = current_chunk_id
                        signal_to_generate = self._generate_signal_dict(symbol, SIGNAL_TYPE_CLOSE_SHORT_POSITIONS, current_price, current_volume, market_data)
                    else:
                        trading_logger.debug(f"[{symbol}] TREND_ENDED_DOWN_TO_FLAT: Already closed in Current Chunk {current_chunk_id}. Prev state: DOWN.")
            
            return signal_to_generate

        except Exception as e:
            trading_logger.error(f"Error in analyze_market for data {market_data}: {e}", exc_info=True)
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
        
        return {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'type': signal_type,
            'price': current_price,
            'volume': current_volume, 
            'stop_loss': sl if signal_type in [SIGNAL_TYPE_OPEN_LONG, SIGNAL_TYPE_OPEN_SHORT] else 0.0,
            'take_profit': tp if signal_type in [SIGNAL_TYPE_OPEN_LONG, SIGNAL_TYPE_OPEN_SHORT] else 0.0,
            'strategy': 'TrendFollowingCustomIntervalV2_Original', 
            'kline_interval': market_data.get('kline_interval', 'custom_trend'), 
            'position_size_usdt': signal_position_size
        }

"""
================================================================================
原始算法总结:

核心思想:
- 时间分片: 将连续时间划分为固定长度的时间块(chunk)
- 价格采样: 在每个时间块内收集所有价格点
- 变化计算: 计算每个时间块内第一个价格到最后一个价格的变化百分比
- 趋势确认: 需要连续N个时间块都朝同一方向变化且超过阈值才确认趋势
- 状态管理: 使用状态机管理不同趋势状态间的转换和对应的交易动作

优点:
- 对噪音有一定的抗性(需要连续多个时间块确认)
- 能够捕捉较短期的趋势变化
- 状态机逻辑清晰，便于调试和理解

缺点:
- 在低波动环境下容易误判(如Testnet)
- 固定时间块可能错过重要的价格变化时机
- 需要较多参数调优
- 对时间同步要求较高

参数建议:
主网环境:
- trend_chunk_seconds: 30-60
- min_chunk_price_change_pct: 0.05-0.1 (5-10个基点)
- min_trend_confirm_chunks: 2-3

测试网环境:
- trend_chunk_seconds: 15-30  
- min_chunk_price_change_pct: 0.01-0.05 (1-5个基点)
- min_trend_confirm_chunks: 2
================================================================================
""" 