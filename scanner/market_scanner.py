from typing import Dict, List, Set, Optional
import pandas as pd
import ccxt
from utils.logger import trading_logger

class MarketScanner:
    """市场扫描引擎"""
    
    def __init__(self, 
                 exchange: ccxt.Exchange, 
                 volatility_timeframe: str = '1h', 
                 volatility_ohlcv_limit: int = 2,
                 analysis_timeframe: str = '1m', # For get_trend_data
                 stable_coins: Optional[Set[str]] = None,
                 main_coins: Optional[Set[str]] = None):
        """
        初始化市场扫描器
        
        Args:
            exchange: 交易所实例
            volatility_timeframe: 计算波动率所用的K线周期
            volatility_ohlcv_limit: 获取波动率K线条数
            analysis_timeframe: 获取趋势分析数据所用的K线周期
            stable_coins: 稳定币集合，如果为None则使用默认值
            main_coins: 主流币集合，如果为None则使用默认值
        """
        self.exchange = exchange
        self.volatility_timeframe = volatility_timeframe
        self.volatility_ohlcv_limit = volatility_ohlcv_limit
        self.analysis_timeframe = analysis_timeframe
        self.stable_coins = stable_coins if stable_coins is not None else {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD'}
        self.main_coins = main_coins if main_coins is not None else {'BTC', 'ETH'}
        
    def scan_market(self, max_candidates: int = 15) -> List[Dict]:
        """
        扫描全市场加密货币
        
        Args:
            max_candidates: 波动率筛选后的最大候选币种数量

        Returns:
            候选币种列表 (按绝对波动率降序排列，未被流动性筛选)
        """
        try:
            markets = self.exchange.fetch_markets()
            trading_logger.info(f"开始扫描市场，共{len(markets)}个交易对")
            
            usdt_pairs = [
                market for market in markets 
                if market['quote'] == 'USDT' and market['active']
            ]
            
            candidates_data = []
            for market in usdt_pairs:
                symbol = market['symbol']
                base_currency = market['base']
                
                if base_currency in self.stable_coins or base_currency in self.main_coins:
                    continue
                
                try:
                    ohlcv = self.exchange.fetch_ohlcv(
                        symbol,
                        timeframe=self.volatility_timeframe,
                        limit=self.volatility_ohlcv_limit 
                    )
                    
                    if len(ohlcv) < self.volatility_ohlcv_limit: # Ensure enough data
                        trading_logger.debug(f"数据不足 ({len(ohlcv)}条) 用于 {symbol} 在 {self.volatility_timeframe} 周期计算波动率，跳过")
                        continue
                        
                    open_price = ohlcv[0][1]  
                    current_price = ohlcv[-1][4] # Use the last available close price
                    if open_price == 0: # Avoid division by zero
                        trading_logger.warning(f"{symbol} 在 {self.volatility_timeframe} 周期的开盘价为0，无法计算波动率，跳过")
                        continue
                    volatility = (current_price - open_price) / open_price * 100
                    
                    ticker = self.exchange.fetch_ticker(symbol)
                    volume_24h_usdt = ticker['quoteVolume']
                    
                    candidates_data.append({
                        'symbol': symbol,
                        'base_currency': base_currency,
                        'volatility': volatility,
                        'volume_24h_usdt': volume_24h_usdt,
                        'current_price': current_price,
                    })
                    
                except Exception as e:
                    trading_logger.warning(f"处理币种 {symbol} 时在市场扫描中出错: {str(e)}")
                    continue # Skip to next symbol
            
            candidates_data.sort(key=lambda x: abs(x['volatility']), reverse=True)
            
            top_candidates = candidates_data[:max_candidates]
            trading_logger.info(f"波动率扫描完成，选出Top {len(top_candidates)} 个候选币种")
            return top_candidates
            
        except Exception as e:
            trading_logger.error(f"市场扫描核心逻辑失败: {str(e)}", exc_info=True)
            return [] # Return empty list on major failure
    
    def get_liquidity_score(self, candidate: Dict) -> float:
        return abs(candidate.get('volatility', 0)) * candidate.get('volume_24h_usdt', 0)
    
    def filter_by_liquidity(self, 
                            candidates: List[Dict], 
                            min_volume_usdt: float = 1000000, 
                            max_liquidity_candidates: int = 5) -> List[Dict]:
        """
        按流动性筛选候选币种
        
        Args:
            candidates: 经过波动率筛选的候选币种列表
            min_volume_usdt: 最小24小时交易量 (USDT)
            max_liquidity_candidates: 流动性筛选后选取的最大数量
            
        Returns:
            筛选后的候选币种列表 (按流动性评分降序排列)
        """
        if not candidates:
            return []
            
        liquid_candidates = []
        for candidate in candidates:
            if candidate.get('volume_24h_usdt', 0) >= min_volume_usdt:
                candidate['liquidity_score'] = self.get_liquidity_score(candidate)
                liquid_candidates.append(candidate)
            else:
                trading_logger.debug(f"币种 {candidate['symbol']} (交易量: {candidate.get('volume_24h_usdt',0)}) 未达到最小交易量 {min_volume_usdt} USDT，已过滤")
        
        liquid_candidates.sort(key=lambda x: x.get('liquidity_score', 0), reverse=True)
        
        final_candidates = liquid_candidates[:max_liquidity_candidates]
        trading_logger.info(f"流动性筛选完成，选出 {len(final_candidates)} 个币种")
        return final_candidates
    
    def get_trend_data(self, symbol: str, limit: int = 5) -> Optional[pd.DataFrame]:
        """
        获取趋势数据 (用于后续的趋势分析)
        
        Args:
            symbol: 交易对符号
            limit: 获取K线条数 (应与TrendAnalyzer的lookback_periods匹配)
            
        Returns:
            包含K线数据的DataFrame，或在失败时返回None
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol,
                timeframe=self.analysis_timeframe, # Use configured timeframe
                limit=limit 
            )
            
            if not ohlcv or len(ohlcv) < limit:
                trading_logger.warning(f"获取 {symbol} 的趋势数据不足或失败 ({len(ohlcv) if ohlcv else 0}条)，期望 {limit} 条")
                return None

            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df
            
        except Exception as e:
            trading_logger.error(f"获取 {symbol} 的趋势数据失败: {str(e)}", exc_info=True)
            return None 