from datetime import datetime, timedelta
import pandas as pd
from data.data_fetcher import DataFetcher
from strategies.ma_cross_strategy import MACrossStrategy
from backtest_engine import BacktestEngine

def main():
    # 初始化数据获取器
    data_fetcher = DataFetcher()
    
    # 设置回测参数
    symbol = "AAPL"  # 苹果公司股票
    start_date = datetime.now() - timedelta(days=365)  # 一年前
    end_date = datetime.now()
    
    # 获取历史数据
    data = data_fetcher.get_historical_data(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval='1d'
    )
    
    # 初始化策略
    strategy = MACrossStrategy(short_window=20, long_window=50)
    
    # 初始化回测引擎
    backtest = BacktestEngine(
        strategy=strategy,
        initial_capital=100000.0,
        commission=0.001
    )
    
    # 运行回测
    results = backtest.run(data)
    
    # 打印结果
    print("\n=== 回测结果 ===")
    print(f"初始资金: ${results['initial_capital']:,.2f}")
    print(f"最终资金: ${results['final_capital']:,.2f}")
    print(f"总收益率: {results['total_return']*100:.2f}%")
    print(f"夏普比率: {results['sharpe_ratio']:.2f}")
    print(f"最大回撤: {results['max_drawdown']*100:.2f}%")
    print(f"总交易次数: {results['total_trades']}")
    print(f"胜率: {results['win_rate']*100:.2f}%")

if __name__ == "__main__":
    main() 