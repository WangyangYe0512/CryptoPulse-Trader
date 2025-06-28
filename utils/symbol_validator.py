"""
符号验证工具 - 基于币安API的交易对验证
利用现有缓存机制，性能影响极小
"""

from typing import Set, Optional, List, Tuple
from utils.logger import trading_logger
from datetime import datetime, timedelta


class SymbolValidator:
    """
    高效的交易对符号验证器
    
    特点:
    - 利用现有的 BinanceExecutor 缓存机制
    - 无额外API调用开销
    - 内存查找，毫秒级响应
    - 自动修正常见符号格式错误
    """
    
    def __init__(self, executor=None):
        self.executor = executor
        self.valid_symbols_cache: Set[str] = set()  # CCXT格式: {'BTC/USDT:USDT', ...}
        self.valid_symbols_watchlist_format: Set[str] = set()  # Watchlist格式: {'BTCUSDT', ...}
        self.last_cache_update = None
        self.cache_ttl_minutes = 60  # 缓存1小时，与 ContractPairsManager 同步
        
    async def ensure_cache_updated(self) -> bool:
        """确保缓存是最新的，利用executor的现有缓存"""
        try:
            # 检查是否需要更新缓存
            if (self.last_cache_update is None or 
                datetime.now() - self.last_cache_update > timedelta(minutes=self.cache_ttl_minutes)):
                
                if not self.executor:
                    trading_logger.warning("No executor available for symbol validation")
                    return False
                
                # 利用executor的现有方法和缓存
                trading_logger.debug("Updating symbol validator cache from executor...")
                ccxt_symbols = await self.executor.get_all_binance_futures_symbols()
                
                if ccxt_symbols:
                    self.valid_symbols_cache = ccxt_symbols.copy()
                    # 转换为watchlist格式
                    self.valid_symbols_watchlist_format = {
                        self._ccxt_to_watchlist_format(symbol) 
                        for symbol in ccxt_symbols 
                        if symbol and self._ccxt_to_watchlist_format(symbol)
                    }
                    self.last_cache_update = datetime.now()
                    trading_logger.info(f"Symbol validator cache updated: {len(self.valid_symbols_cache)} CCXT symbols, {len(self.valid_symbols_watchlist_format)} watchlist symbols")
                    return True
                else:
                    trading_logger.warning("Failed to get symbols from executor for validation")
                    return False
            return True
        except Exception as e:
            trading_logger.error(f"Error updating symbol validator cache: {e}", exc_info=True)
            return False
    
    def _ccxt_to_watchlist_format(self, ccxt_symbol: str) -> Optional[str]:
        """
        将CCXT格式转换为watchlist格式
        BTC/USDT:USDT -> BTCUSDT
        BTC/USDT -> BTCUSDT
        """
        try:
            if not isinstance(ccxt_symbol, str) or 'USDT' not in ccxt_symbol:
                return None
                
            if ':USDT' in ccxt_symbol:  # 永续合约格式: 'BTC/USDT:USDT'
                base = ccxt_symbol.split('/')[0]
                return f"{base.upper()}USDT"
            elif '/USDT' in ccxt_symbol:  # 现货格式: 'BTC/USDT'
                base = ccxt_symbol.split('/')[0]
                return f"{base.upper()}USDT"
            else:
                return ccxt_symbol.upper()
        except Exception as e:
            trading_logger.debug(f"Error converting symbol {ccxt_symbol}: {e}")
            return None
    
    async def validate_symbols(self, symbols: List[str], format_type: str = "watchlist") -> Tuple[List[str], List[str]]:
        """
        批量验证符号
        
        Args:
            symbols: 要验证的符号列表
            format_type: "watchlist" 或 "ccxt"
            
        Returns:
            (valid_symbols, invalid_symbols)
        """
        await self.ensure_cache_updated()
        
        valid_symbols = []
        invalid_symbols = []
        
        if format_type == "watchlist":
            valid_set = self.valid_symbols_watchlist_format
        else:
            valid_set = self.valid_symbols_cache
        
        for symbol in symbols:
            if symbol in valid_set:
                valid_symbols.append(symbol)
            else:
                invalid_symbols.append(symbol)
                
        return valid_symbols, invalid_symbols
    
    async def validate_and_fix_symbols(self, symbols: List[str]) -> Tuple[List[str], List[str], List[str]]:
        """
        验证并尝试修复符号格式错误
        
        Returns:
            (valid_symbols, fixed_symbols, invalid_symbols)
        """
        await self.ensure_cache_updated()
        
        valid_symbols = []
        fixed_symbols = []
        invalid_symbols = []
        
        for symbol in symbols:
            # 直接验证watchlist格式
            if symbol in self.valid_symbols_watchlist_format:
                valid_symbols.append(symbol)
                continue
            
            # 尝试修复常见错误
            fixed = self._attempt_fix_symbol(symbol)
            if fixed and fixed in self.valid_symbols_watchlist_format:
                fixed_symbols.append(fixed)
                trading_logger.info(f"Symbol auto-fixed: {symbol} -> {fixed}")
            else:
                invalid_symbols.append(symbol)
                
        return valid_symbols, fixed_symbols, invalid_symbols
    
    def _attempt_fix_symbol(self, symbol: str) -> Optional[str]:
        """尝试修复常见的符号格式错误"""
        if not isinstance(symbol, str):
            return None
        
        # 修复双重USDT错误: BTCUSDTUSDT -> BTCUSDT
        if symbol.endswith('USDTUSDT'):
            return symbol[:-4]  # 移除最后的USDT
        
        # 修复缺少USDT: BTC -> BTCUSDT  
        if not symbol.endswith('USDT') and symbol.isalpha():
            return f"{symbol.upper()}USDT"
        
        return symbol.upper()
    
    async def is_valid_watchlist_symbol(self, symbol: str) -> bool:
        """快速检查单个watchlist格式符号是否有效"""
        await self.ensure_cache_updated()
        return symbol in self.valid_symbols_watchlist_format
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计信息"""
        return {
            'ccxt_symbols_count': len(self.valid_symbols_cache),
            'watchlist_symbols_count': len(self.valid_symbols_watchlist_format),
            'last_update': self.last_cache_update,
            'cache_age_minutes': (datetime.now() - self.last_cache_update).total_seconds() / 60 if self.last_cache_update else None
        } 