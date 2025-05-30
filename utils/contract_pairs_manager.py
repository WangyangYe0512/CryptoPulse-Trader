import json
import os
import time
from typing import Set
import ccxt
from utils.logger import trading_logger

class ContractPairsManager:
    """币安合约交易对管理器"""
    
    def __init__(self, cache_file: str = 'data/contract_pairs.json', update_interval: int = 86400):
        """
        初始化合约交易对管理器
        
        Args:
            cache_file: 缓存文件路径
            update_interval: 更新间隔（秒），默认24小时
        """
        self.cache_file = cache_file
        self.update_interval = update_interval
        self.pairs: Set[str] = set()
        self.last_update_time = 0
        
        # 确保缓存目录存在
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        
        # 加载或更新交易对
        self._load_or_update_pairs()
        
    def _load_or_update_pairs(self):
        """加载或更新合约交易对"""
        current_time = time.time()
        
        # 检查是否需要更新
        if (not os.path.exists(self.cache_file) or 
            current_time - self.last_update_time > self.update_interval):
            self._update_pairs()
        else:
            self._load_pairs()
            
    def _update_pairs(self):
        """从币安更新合约交易对"""
        try:
            trading_logger.info("正在从币安更新合约交易对...")
            
            # 初始化币安交易所
            exchange = ccxt.binance({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'
                }
            })
            
            # 获取所有合约交易对
            markets = exchange.fetch_markets()
            usdt_pairs = {
                market['symbol'] for market in markets 
                if market['quote'] == 'USDT' and market['active']
            }
            
            # 保存到缓存
            self.pairs = usdt_pairs
            self._save_pairs()
            
            self.last_update_time = time.time()
            trading_logger.info(f"合约交易对更新完成，共 {len(usdt_pairs)} 个交易对")
            
        except Exception as e:
            trading_logger.error(f"更新合约交易对失败: {str(e)}", exc_info=True)
            # 如果更新失败，尝试加载缓存
            if os.path.exists(self.cache_file):
                self._load_pairs()
            else:
                raise
                
    def _load_pairs(self):
        """从缓存加载合约交易对"""
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                self.pairs = set(data['pairs'])
                self.last_update_time = data['last_update_time']
            trading_logger.info(f"从缓存加载了 {len(self.pairs)} 个合约交易对")
        except Exception as e:
            trading_logger.error(f"加载合约交易对缓存失败: {str(e)}", exc_info=True)
            self._update_pairs()
            
    def _save_pairs(self):
        """保存合约交易对到缓存"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({
                    'pairs': list(self.pairs),
                    'last_update_time': self.last_update_time
                }, f, indent=2)
        except Exception as e:
            trading_logger.error(f"保存合约交易对缓存失败: {str(e)}", exc_info=True)
            
    def get_pairs(self) -> Set[str]:
        """获取所有合约交易对"""
        return self.pairs
        
    def is_valid_pair(self, symbol: str) -> bool:
        """检查交易对是否有效"""
        return symbol in self.pairs
        
    def force_update(self):
        """强制更新合约交易对"""
        self._update_pairs() 