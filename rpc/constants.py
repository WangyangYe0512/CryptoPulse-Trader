# 兼容 freqtrade 常量
from typing import Dict, Any

__version__ = "1.0.0"

# 灰尘阈值常量
DUST_PER_COIN = {
    'BTC': 0.0001,
    'ETH': 0.001,
    'BNB': 0.01,
    'USDT': 1.0,
    'USDC': 1.0,
}

# 配置类型
Config = Dict[str, Any]