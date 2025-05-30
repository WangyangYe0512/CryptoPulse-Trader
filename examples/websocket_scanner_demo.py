import asyncio
import sys
import os
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner.websocket_scanner import WebSocketMarketScanner
from utils.logger import trading_logger

# 设置日志级别为DEBUG以查看详细信息
trading_logger.setLevel(logging.DEBUG)

async def main():
    # 要监控的交易对列表
    symbols = [
        'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOGEUSDT',
        'XRPUSDT', 'DOTUSDT', 'UNIUSDT', 'LTCUSDT', 'LINKUSDT',
        'SOLUSDT', 'MATICUSDT', 'AVAXUSDT', 'ATOMUSDT', 'NEARUSDT',
        'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'THETAUSDT', 'EOSUSDT'
    ]
    
    # 初始化扫描器
    scanner = WebSocketMarketScanner(
        symbols=symbols,
        min_volume_usdt=1000000,  # 最小24小时交易量100万USDT
        top_n=5                    # 显示前5名
    )
    
    try:
        # 启动扫描
        trading_logger.info("启动WebSocket市场扫描...")
        await scanner.scan_market()
        
    except KeyboardInterrupt:
        trading_logger.info("收到停止信号，正在关闭...")
        await scanner.stop()
        
    except Exception as e:
        trading_logger.error(f"发生错误: {str(e)}")
        await scanner.stop()

if __name__ == "__main__":
    asyncio.run(main()) 