from typing import Tuple, Optional
import pandas as pd
from scipy import stats
from utils.logger import trading_logger

class TrendAnalyzer:
    """趋势分析器"""
    
    def __init__(self, 
                 min_slope_percent: float = 0.5,
                 lookback_periods: int = 5, 
                 confirmation_periods: int = 3):
        """
        初始化趋势分析器
        
        Args:
            min_slope_percent: 最小趋势斜率（百分比）
            lookback_periods: 进行趋势分析时回溯的K线数量
            confirmation_periods: 趋势持续性确认所需的K线数量 (e.g., 最近N根K线同向)
        """
        self.min_slope_percent = min_slope_percent 
        self.lookback_periods = lookback_periods
        self.confirmation_periods = confirmation_periods
        
        # Basic validation for periods
        if self.lookback_periods < 2:
            trading_logger.warning(f"TrendAnalyzer: lookback_periods ({self.lookback_periods}) is too small. Setting to 2.")
            self.lookback_periods = 2

        if self.confirmation_periods <= 0:
            trading_logger.info(f"TrendAnalyzer: confirmation_periods ({self.confirmation_periods}) is zero or negative. Persistence check will be skipped.")
            self.confirmation_periods = 0 # Explicitly set to 0 to signify skipping
        elif self.confirmation_periods >= self.lookback_periods:
            trading_logger.warning(
                f"TrendAnalyzer: confirmation_periods ({self.confirmation_periods}) "
                f"should be less than lookback_periods ({self.lookback_periods}). "
                f"Adjusting confirmation_periods to {max(1, self.lookback_periods - 1)}."
            )
            self.confirmation_periods = max(1, self.lookback_periods - 1)
        
    def analyze_trend(self, data: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        """
        分析趋势
        
        Args:
            data: K线数据 (DataFrame应包含至少 self.lookback_periods 条数据)
            
        Returns:
            (是否确认趋势, 趋势方向 'long'/'short' 或 None)
        """
        try:
            if data is None or len(data) < self.lookback_periods:
                trading_logger.debug(
                    f"TrendAnalyzer: Data insufficient for trend analysis. "
                    f"Need {self.lookback_periods} periods, got {len(data) if data is not None else 0}."
                )
                return False, None
            
            analysis_data = data.tail(self.lookback_periods).copy() # Use .copy() to avoid SettingWithCopyWarning
            analysis_data.reset_index(drop=True, inplace=True) # Ensure index is 0 to N-1 for linregress

            x = analysis_data.index.values # Use the new 0-based index
            y = analysis_data['close'].values
            
            if len(y) < 2: 
                return False, None

            slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
            
            # Calculate slope_percent based on the average price in the window or first price.
            # Using the first price of the *analysis window* for consistency.
            first_price_in_window = y[0]
            if first_price_in_window == 0:
                trading_logger.warning("TrendAnalyzer: First price in analysis window is 0, cannot calculate slope percent.")
                return False, None
            # Slope is per-period. To get overall change over the window, it's slope * (num_periods -1)
            # Then, percentage change = (total_change / first_price) * 100
            # A simpler way: if slope is change per period, then slope_percent = (slope / first_price_in_window) * 100
            slope_percent = (slope / first_price_in_window) * 100 
            
            if abs(slope_percent) < self.min_slope_percent:
                # trading_logger.debug(f"TrendAnalyzer: Slope {slope_percent:.2f}% below threshold {self.min_slope_percent}%")
                return False, None
            
            # Persistence check (if confirmation_periods > 0)
            if self.confirmation_periods > 0:
                # Need at least `confirmation_periods` changes, which means `confirmation_periods + 1` data points
                if len(analysis_data) < self.confirmation_periods + 1:
                    trading_logger.debug(
                        f"TrendAnalyzer: Data insufficient for persistence check. "
                        f"Need {self.confirmation_periods + 1} in analysis window, got {len(analysis_data)}."
                    )
                    # If not enough for persistence, but slope is good, decide if we still consider it a trend
                    # For now, if persistence is configured, we require enough data for it.
                    return False, None # Be strict: if configured, must be met

                # Get the last `confirmation_periods + 1` closes from the analysis_data
                recent_closes_for_persistence = analysis_data['close'].tail(self.confirmation_periods + 1)
                price_changes = recent_closes_for_persistence.diff().dropna() # This will give `confirmation_periods` changes

                if len(price_changes) < self.confirmation_periods:
                    trading_logger.debug("TrendAnalyzer: Not enough price changes for persistence check after diff.")
                    return False, None

                if slope_percent > 0:  # Uptrend, expect positive or zero changes
                    if not all(price_changes >= 0):
                        # trading_logger.debug(f"TrendAnalyzer: Uptrend persistence failed. Changes: {price_changes.tolist()}")
                        return False, None
                    return True, 'long'
                else:  # Downtrend, expect negative or zero changes
                    if not all(price_changes <= 0):
                        # trading_logger.debug(f"TrendAnalyzer: Downtrend persistence failed. Changes: {price_changes.tolist()}")
                        return False, None
                    return True, 'short'
            else:
                # Persistence check is skipped (confirmation_periods is 0)
                return True, 'long' if slope_percent > 0 else 'short'
                
        except Exception as e:
            trading_logger.error(f"趋势分析失败: {str(e)}", exc_info=True)
            return False, None
    
    def get_recent_momentum_direction(self, data: pd.DataFrame) -> Optional[str]:
        """
        检查最近几根K线的收盘价动量方向。
        如果最近两根K线的价格变化同为上涨，则返回 'long'。
        如果最近两根K线的价格变化同为下跌，则返回 'short'。
        否则返回 None。
        
        Args:
            data: K线数据 (至少需要包含3根K线以计算2个价格变化)
            
        Returns:
            动量方向 ('long', 'short') 或 None
        """
        try:
            if len(data) < 3: # Need at least 3 bars for 2 price changes
                return None
                
            # 获取最近3根K线的收盘价
            last_3_closes = data['close'].tail(3)
            
            # 计算价格变化 (diff() 会产生NaN，所以至少需要3个收盘价才有2个有效变化)
            price_changes = last_3_closes.diff().dropna()
            
            if len(price_changes) < 2: # Need two consecutive changes
                return None
                
            # 检查最近2个价格变化是否同向
            change1 = price_changes.iloc[-2] # Second to last change
            change2 = price_changes.iloc[-1] # Last change
            
            if change1 > 0 and change2 > 0:
                return 'long'  # 连续上涨势头
            elif change1 < 0 and change2 < 0:
                return 'short' # 连续下跌势头
                
            return None # 方向不一致或无明显势头
            
        except Exception as e:
            trading_logger.error(f"检查近期动量方向失败: {str(e)}")
            return None
    
    def calculate_stop_loss(self, entry_price: float, direction: str, stop_loss_pct: float = 1.0) -> float:
        """
        计算止损价格
        
        Args:
            entry_price: 入场价格
            direction: 交易方向 ('long' or 'short')
            stop_loss_pct: 止损百分比
            
        Returns:
            止损价格
        """
        if direction == 'long':
            return entry_price * (1 - stop_loss_pct / 100)
        else:
            return entry_price * (1 + stop_loss_pct / 100)
    
    def calculate_take_profit(self, entry_price: float, direction: str, take_profit_pct: float = 2.0) -> float:
        """
        计算止盈价格
        
        Args:
            entry_price: 入场价格
            direction: 交易方向 ('long' or 'short')
            take_profit_pct: 止盈百分比
            
        Returns:
            止盈价格
        """
        if direction == 'long':
            return entry_price * (1 + take_profit_pct / 100)
        else:
            return entry_price * (1 - take_profit_pct / 100) 