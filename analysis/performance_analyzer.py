from typing import List, Dict
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
from utils.logger import trading_logger

class PerformanceAnalyzer:
    """交易性能分析器"""
    
    def __init__(self):
        """初始化性能分析器"""
        self.trades: List[Dict] = []
        self.daily_stats: Dict[str, Dict] = {}
        
    def add_trade(self, trade: Dict):
        """
        添加交易记录
        
        Args:
            trade: 交易记录字典
        """
        self.trades.append(trade)
        
        # 更新日统计
        date = trade['exit_time'].strftime('%Y-%m-%d')
        if date not in self.daily_stats:
            self.daily_stats[date] = {
                'trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'pnl': 0.0,
                'max_drawdown': 0.0
            }
            
        stats = self.daily_stats[date]
        stats['trades'] += 1
        stats['pnl'] += trade['pnl']
        
        if trade['pnl'] > 0:
            stats['winning_trades'] += 1
        else:
            stats['losing_trades'] += 1
            
    def calculate_metrics(self) -> Dict:
        """
        计算性能指标
        
        Returns:
            性能指标字典
        """
        if not self.trades:
            return {}
            
        df = pd.DataFrame(self.trades)
        
        # 基础指标
        total_trades = len(df)
        winning_trades = len(df[df['pnl'] > 0])
        losing_trades = len(df[df['pnl'] <= 0])
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = df[df['pnl'] <= 0]['pnl'].mean() if losing_trades > 0 else 0
        
        # 计算最大回撤
        cumulative_returns = df['pnl'].cumsum()
        rolling_max = cumulative_returns.expanding().max()
        drawdowns = (cumulative_returns - rolling_max) / rolling_max * 100
        max_drawdown = abs(drawdowns.min())
        
        # 计算夏普比率
        daily_returns = df.groupby(df['exit_time'].dt.date)['pnl'].sum()
        sharpe_ratio = np.sqrt(252) * (daily_returns.mean() / daily_returns.std()) if len(daily_returns) > 1 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else float('inf'),
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'total_pnl': df['pnl'].sum(),
            'avg_trade_pnl': df['pnl'].mean(),
            'best_trade': df['pnl'].max(),
            'worst_trade': df['pnl'].min()
        }
        
    def plot_equity_curve(self, save_path: str = None):
        """
        绘制权益曲线
        
        Args:
            save_path: 图表保存路径
        """
        if not self.trades:
            trading_logger.warning("没有交易记录，无法绘制权益曲线")
            return
            
        df = pd.DataFrame(self.trades)
        df['cumulative_pnl'] = df['pnl'].cumsum()
        
        plt.figure(figsize=(12, 6))
        plt.plot(df['exit_time'], df['cumulative_pnl'], label='Cumulative PnL')
        plt.title('Equity Curve')
        plt.xlabel('Date')
        plt.ylabel('Cumulative PnL (%)')
        plt.grid(True)
        plt.legend()
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()
            
    def plot_daily_returns(self, save_path: str = None):
        """
        绘制每日收益分布
        
        Args:
            save_path: 图表保存路径
        """
        if not self.trades:
            trading_logger.warning("没有交易记录，无法绘制每日收益分布")
            return
            
        df = pd.DataFrame(self.trades)
        daily_returns = df.groupby(df['exit_time'].dt.date)['pnl'].sum()
        
        plt.figure(figsize=(12, 6))
        plt.hist(daily_returns, bins=50, alpha=0.75)
        plt.title('Daily Returns Distribution')
        plt.xlabel('Daily Return (%)')
        plt.ylabel('Frequency')
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()
            
    def plot_win_loss_distribution(self, save_path: str = None):
        """
        绘制盈亏分布
        
        Args:
            save_path: 图表保存路径
        """
        if not self.trades:
            trading_logger.warning("没有交易记录，无法绘制盈亏分布")
            return
            
        df = pd.DataFrame(self.trades)
        
        plt.figure(figsize=(12, 6))
        plt.hist(df['pnl'], bins=50, alpha=0.75)
        plt.title('Win/Loss Distribution')
        plt.xlabel('Trade PnL (%)')
        plt.ylabel('Frequency')
        plt.grid(True)
        
        if save_path:
            plt.savefig(save_path)
        else:
            plt.show()
            
    def generate_report(self, save_dir: str = None) -> str:
        """
        生成性能报告
        
        Args:
            save_dir: 报告保存目录
            
        Returns:
            报告内容
        """
        metrics = self.calculate_metrics()
        
        report = "=== Trading Performance Report ===\n\n"
        report += f"Total Trades: {metrics['total_trades']}\n"
        report += f"Winning Trades: {metrics['winning_trades']}\n"
        report += f"Losing Trades: {metrics['losing_trades']}\n"
        report += f"Win Rate: {metrics['win_rate']:.2f}%\n"
        report += f"Average Win: {metrics['avg_win']:.2f}%\n"
        report += f"Average Loss: {metrics['avg_loss']:.2f}%\n"
        report += f"Profit Factor: {metrics['profit_factor']:.2f}\n"
        report += f"Maximum Drawdown: {metrics['max_drawdown']:.2f}%\n"
        report += f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}\n"
        report += f"Total PnL: {metrics['total_pnl']:.2f}%\n"
        report += f"Average Trade PnL: {metrics['avg_trade_pnl']:.2f}%\n"
        report += f"Best Trade: {metrics['best_trade']:.2f}%\n"
        report += f"Worst Trade: {metrics['worst_trade']:.2f}%\n"
        
        if save_dir:
            # 保存报告
            report_path = f"{save_dir}/performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(report_path, 'w') as f:
                f.write(report)
                
            # 保存图表
            self.plot_equity_curve(f"{save_dir}/equity_curve.png")
            self.plot_daily_returns(f"{save_dir}/daily_returns.png")
            self.plot_win_loss_distribution(f"{save_dir}/win_loss_distribution.png")
            
        return report 