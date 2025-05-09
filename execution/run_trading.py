import time
from datetime import datetime
import pandas as pd
from data.data_fetcher import DataFetcher
from strategies.ma_cross_strategy import MACrossStrategy
from execution.trading_engine import TradingEngine

def main():
    # 初始化组件
    data_fetcher = DataFetcher()
    strategy = MACrossStrategy(short_window=20, long_window=50)
    trading_engine = TradingEngine(use_testnet=True)
    
    # 交易参数
    symbol = "BTC/USDT"
    interval = "1h"
    check_interval = 60  # 检查间隔（秒）
    
    print(f"开始交易 {symbol}...")
    
    while True:
        try:
            # 获取最新数据
            end_date = datetime.now()
            start_date = end_date - pd.Timedelta(days=7)  # 获取最近7天数据
            
            data = data_fetcher.get_historical_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval
            )
            
            # 生成交易信号
            signals = strategy.generate_signals(data)
            latest_signal = signals['signal'].iloc[-1]
            
            # 获取当前持仓
            current_position = trading_engine.positions.get(symbol, 0)
            
            # 获取账户余额
            balance = trading_engine.get_balance()
            ticker = trading_engine.get_ticker(symbol)
            current_price = ticker['last']
            
            print(f"\n=== {datetime.now()} ===")
            print(f"当前价格: {current_price}")
            print(f"账户余额: {balance} USDT")
            print(f"当前持仓: {current_position}")
            print(f"最新信号: {latest_signal}")
            
            # 执行交易
            if latest_signal != 0 and latest_signal != current_position:
                # 计算交易数量
                amount = abs(latest_signal) * (balance * 0.95) / current_price
                
                # 下单
                side = 'buy' if latest_signal > 0 else 'sell'
                order = trading_engine.place_order(
                    symbol=symbol,
                    order_type='market',
                    side=side,
                    amount=amount
                )
                
                print(f"执行{side}单: {amount} {symbol} @ {current_price}")
                print(f"订单ID: {order['id']}")
            
            # 等待下一次检查
            time.sleep(check_interval)
            
        except Exception as e:
            print(f"发生错误: {str(e)}")
            time.sleep(check_interval)

if __name__ == "__main__":
    main() 