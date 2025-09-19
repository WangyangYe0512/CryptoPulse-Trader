# 简化的 RPC 类，为 Telegram 提供必要接口
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import datetime

from rpc.constants import __version__, Config
from rpc.enums import State, MarketDirection, TradingMode
from rpc.persistence import Trade
from rpc.exceptions import RPCException

logger = logging.getLogger(__name__)


class RPCHandler(ABC):
    """RPC 处理器基类"""
    
    def __init__(self, rpc: 'RPC', config: Config):
        """初始化 RPC 处理器"""
        self._rpc = rpc
        self._config = config
    
    @abstractmethod
    def send_msg(self, msg: Dict[str, Any]) -> None:
        """发送消息"""
        pass


class MockFreqtrade:
    """模拟 Freqtrade 实例"""
    def __init__(self, config: Config):
        self.config = config
        self.trading_mode = TradingMode.SPOT


class RPC:
    """简化的 RPC 类"""
    
    def __init__(self, config: Config):
        self._config = config
        self._trades: List[Trade] = []
        self._state = State.STOPPED
        self._market_direction = MarketDirection.NONE
        self._freqtrade = MockFreqtrade(config)
        self._fiat_converter = None  # 添加缺失的属性
        
    def _rpc_trade_status(self, trade_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取交易状态"""
        if trade_id is not None:
            trades = [t for t in self._trades if t.id == trade_id and t.is_open]
        else:
            trades = [t for t in self._trades if t.is_open]
            
        result = []
        for trade in trades:
            result.append({
                'trade_id': trade.id,
                'pair': trade.pair,
                'base_currency': trade.base_currency,
                'quote_currency': trade.quote_currency,
                'is_open': trade.is_open,
                'amount': trade.amount,
                'amount_requested': trade.amount,
                'stake_amount': trade.stake_amount,
                'open_rate': trade.open_rate,
                'close_rate': trade.close_rate,
                'current_rate': trade.close_rate or trade.open_rate,
                'profit_ratio': trade.profit_ratio or 0.0,
                'profit_pct': (trade.profit_ratio or 0.0) * 100,
                'profit_abs': trade.profit_abs or 0.0,
                'stop_loss_abs': trade.stop_loss,
                'stop_loss_ratio': 0.0,
                'stop_loss_pct': 0.0,
                'stoploss_order_id': None,
                'stoploss_last_update': None,
                'initial_stop_loss_abs': trade.initial_stop_loss,
                'initial_stop_loss_ratio': 0.0,
                'initial_stop_loss_pct': 0.0,
                'open_date': trade.open_date,
                'open_timestamp': int(trade.open_date.timestamp() * 1000),
                'close_date': trade.close_date,
                'close_timestamp': int(trade.close_date.timestamp() * 1000) if trade.close_date else None,
                'open_order_id': None,
                'close_rate_requested': None,
                'fee_open': trade.fee_open,
                'fee_open_cost': None,
                'fee_open_currency': None,
                'fee_close': trade.fee_close,
                'fee_close_cost': None,
                'fee_close_currency': None,
                'exchange': trade.exchange,
                'enter_tag': trade.enter_tag,
                'timeframe': trade.timeframe,
                'strategy': trade.strategy,
                'exit_reason': trade.exit_reason,
                'min_rate': trade.open_rate,
                'max_rate': trade.max_rate or trade.open_rate,
                'has_open_orders': False,
                'orders': [],
                'leverage': trade.leverage or 1.0,
                'trading_mode': trade.trading_mode,
                'funding_fees': 0.0,
                'is_short': False,
            })
        return result
    
    def _rpc_status_table(self, stake_currency: str, fiat_display_currency: str) -> Dict[str, Any]:
        """获取状态表格"""
        trades = self._rpc_trade_status()
        
        trade_count = len(trades)
        if trade_count == 0:
            raise RPCException('no active trade')
            
        profit_all_coin = sum(t['profit_abs'] for t in trades)
        profit_all_ratio = sum(t['profit_ratio'] for t in trades) / trade_count if trade_count > 0 else 0
        profit_closed_coin = 0.0
        profit_closed_ratio = 0.0
        
        return {
            'trades': trades,
            'trades_count': trade_count,
            'current_stake': sum(t['stake_amount'] for t in trades),
            'profit_all_coin': profit_all_coin,
            'profit_all_percent_mean': profit_all_ratio * 100,
            'profit_closed_coin': profit_closed_coin,
            'profit_closed_percent_mean': profit_closed_ratio * 100,
            'best_pair': '',
            'best_rate': 0.0,
        }
    
    def _rpc_daily_profit(self, timescale: int, stake_currency: str, fiat_display_currency: str) -> Dict[str, Any]:
        """获取每日利润"""
        return {
            'stake_currency': stake_currency,
            'fiat_display_currency': fiat_display_currency,
            'data': []
        }
    
    def _rpc_trade_statistics(self, stake_currency: str, fiat_display_currency: str, start_date=None) -> Dict[str, Any]:
        """获取交易统计"""
        closed_trades = [t for t in self._trades if not t.is_open]
        
        if not closed_trades:
            raise RPCException('no closed trade')
            
        profit_closed_coin = sum(t.profit_abs or 0 for t in closed_trades)
        profit_closed_ratio = sum(t.profit_ratio or 0 for t in closed_trades)
        profit_closed_percent_mean = (profit_closed_ratio / len(closed_trades)) * 100 if closed_trades else 0
        
        return {
            'profit_closed_coin': profit_closed_coin,
            'profit_closed_percent_mean': profit_closed_percent_mean,
            'profit_closed_ratio_mean': profit_closed_ratio / len(closed_trades) if closed_trades else 0,
            'profit_closed_percent_sum': profit_closed_ratio * 100,
            'profit_closed_ratio_sum': profit_closed_ratio,
            'profit_closed_fiat': 0.0,
            'profit_all_coin': profit_closed_coin,
            'profit_all_percent_mean': profit_closed_percent_mean,
            'profit_all_ratio_mean': profit_closed_ratio / len(closed_trades) if closed_trades else 0,
            'profit_all_percent_sum': profit_closed_ratio * 100,
            'profit_all_ratio_sum': profit_closed_ratio,
            'profit_all_fiat': 0.0,
            'trade_count': len(closed_trades),
            'closed_trade_count': len(closed_trades),
            'first_trade_date': closed_trades[0].open_date.strftime('%Y-%m-%d %H:%M:%S') if closed_trades else '',
            'first_trade_timestamp': int(closed_trades[0].open_date.timestamp()) if closed_trades else 0,
            'latest_trade_date': closed_trades[-1].close_date.strftime('%Y-%m-%d %H:%M:%S') if closed_trades and closed_trades[-1].close_date else '',
            'latest_trade_timestamp': int(closed_trades[-1].close_date.timestamp()) if closed_trades and closed_trades[-1].close_date else 0,
            'avg_duration': '0:00:00',
            'best_pair': '',
            'best_rate': 0.0,
            'winning_trades': len([t for t in closed_trades if (t.profit_ratio or 0) > 0]),
            'losing_trades': len([t for t in closed_trades if (t.profit_ratio or 0) <= 0]),
        }
    
    def _rpc_profit(self, stake_currency: str = None, fiat_display_currency: str = None, trade_ids: list = None) -> Dict[str, Any]:
        """获取盈亏统计 - freqtrade profit 命令的实现"""
        return self._rpc_trade_statistics(stake_currency or 'USDT', fiat_display_currency or '')
    
    def _rpc_balance(self, stake_currency: str, fiat_display_currency: str) -> Dict[str, Any]:
        """获取余额"""
        return {
            'currencies': [],
            'total': 1000.0,
            'symbol': stake_currency,
            'value': 1000.0,
            'stake': stake_currency,
            'starting_capital': 1000.0,
            'starting_capital_ratio': 1.0,
            'starting_capital_pct': 100.0,
            'note': 'Simulated balance'
        }
    
    def _rpc_start(self) -> Dict[str, str]:
        """启动交易"""
        self._state = State.RUNNING
        return {'status': 'starting trader ...'}
    
    def _rpc_stop(self) -> Dict[str, str]:
        """停止交易"""
        self._state = State.STOPPED
        return {'status': 'stopping trader ...'}
    
    def _rpc_reload_config(self) -> Dict[str, str]:
        """重载配置"""
        return {'status': 'Reloading config ...'}
    
    def _rpc_get_logs(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """获取日志"""
        return {
            'logs': [],
            'log_count': 0
        }
    
    def _rpc_count(self) -> Dict[str, Any]:
        """获取交易计数"""
        max_open_trades = self._config.get('max_open_trades', 10)
        current_trades = len([t for t in self._trades if t.is_open])
        
        return {
            'current': current_trades,
            'max': max_open_trades,
            'total_stake': sum(t.stake_amount for t in self._trades if t.is_open)
        }
    
    def _rpc_performance(self) -> List[Dict[str, Any]]:
        """获取性能统计"""
        closed_trades = [t for t in self._trades if not t.is_open]
        
        if not closed_trades:
            return []
            
        # 按交易对分组统计
        pair_stats = {}
        for trade in closed_trades:
            if trade.pair not in pair_stats:
                pair_stats[trade.pair] = {
                    'pair': trade.pair,
                    'profit': 0.0,
                    'profit_abs': 0.0,
                    'profit_ratio': 0.0,
                    'count': 0
                }
            
            pair_stats[trade.pair]['profit'] += trade.profit_abs or 0
            pair_stats[trade.pair]['profit_abs'] += trade.profit_abs or 0
            pair_stats[trade.pair]['profit_ratio'] += trade.profit_ratio or 0
            pair_stats[trade.pair]['count'] += 1
        
        # 计算平均值并排序
        performance = []
        for stats in pair_stats.values():
            stats['profit_ratio'] = stats['profit_ratio'] / stats['count']
            performance.append(stats)
        
        return sorted(performance, key=lambda x: x['profit'], reverse=True)
    
    def _rpc_version(self) -> Dict[str, str]:
        """获取版本信息"""
        return {
            'version': __version__
        }
    
    def _rpc_show_config(self, config_mask: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """显示配置"""
        return {
            'dry_run': self._config.get('dry_run', True),
            'stake_currency': self._config.get('stake_currency', 'USDT'),
            'max_open_trades': self._config.get('max_open_trades', 10),
            'strategy': self._config.get('strategy', 'DefaultStrategy'),
        }
    
    def _rpc_get_market_direction(self) -> Dict[str, str]:
        """获取市场方向"""
        return {
            'market_direction': self._market_direction.value
        }
    
    def _rpc_set_market_direction(self, direction: str) -> Dict[str, str]:
        """设置市场方向"""
        try:
            self._market_direction = MarketDirection(direction.lower())
            return {
                'market_direction': self._market_direction.value,
                'status': f'Successfully updated marketdirection from {MarketDirection.NONE.value} to {direction}.'
            }
        except ValueError:
            return {
                'status': f'Invalid market direction: {direction}'
            }
    
    def _rpc_status_table(self, stake_currency: str, fiat_display_currency: str = None):
        """获取状态表格 - 返回 freqtrade 格式的数据"""
        from math import nan, isnan
        
        # 获取开仓交易
        trades = self._rpc_trade_status()
        
        if not trades:
            from rpc.exceptions import RPCException
            raise RPCException("no active trade")
        
        trades_list = []
        fiat_profit_sum = nan
        fiat_total_profit_sum = nan
        
        for trade in trades:
            # 格式化利润
            profit_ratio = trade.get('profit_ratio', 0.0)
            profit = f"{profit_ratio:.2%}"
            
            fiat_profit = trade.get('profit_abs', 0.0)
            if fiat_profit and not isnan(fiat_profit):
                profit += f" ({fiat_profit:.2f})"
                fiat_profit_sum = fiat_profit if isnan(fiat_profit_sum) else fiat_profit_sum + fiat_profit
            
            total_profit = trade.get('profit_abs', 0.0)
            if total_profit and not isnan(total_profit):
                fiat_total_profit_sum = total_profit if isnan(fiat_total_profit_sum) else fiat_total_profit_sum + total_profit
            
            # 方向字符串
            direction_str = ""
            leverage = trade.get('leverage', 1.0)
            direction = trade.get('direction', 'long')
            if leverage and leverage != 1.0:
                direction_str = f"{direction} {leverage:.1f}x"
            else:
                direction_str = direction
            
            trades_list.append([
                trade.get('trade_id', ''),
                trade.get('pair', ''),
                direction_str,
                profit
            ])
        
        columns = ['ID', '交易对', '方向', '盈亏']
        
        return trades_list, columns, fiat_profit_sum, fiat_total_profit_sum
    
    def _rpc_timeunit_profit(self, timescale: int, stake_currency: str, fiat_display_currency: str = None, unit: str = 'days'):
        """获取时间单位盈亏"""
        return []
    
    def _rpc_trade_statistics(self, stake_currency: str = 'USDT', fiat_display_currency: str = '', **kwargs):
        """获取交易统计"""
        return {
            'wins': 0,
            'losses': 0,
            'winning_trades': 0,
            'losing_trades': 0,
        }
    
    def _rpc_stats(self):
        """获取统计信息"""
        return {
            'exit_reasons': {},
            'durations': {}
        }
    
    def _rpc_force_exit(self, trade_id=None, ordertype: str = None):
        """强制平仓 - 支持单个交易或所有交易"""
        from datetime import timezone
        
        # 如果 trade_id 是字符串 "all"，则平仓所有交易
        if trade_id == "all" or (isinstance(trade_id, str) and trade_id.lower() == "all"):
            return self._rpc_force_exit_all()
        
        # 单个交易平仓
        if trade_id is None:
            return {
                'status': '错误: 请指定交易ID或使用 "all"',
                'trade_id': None,
                'result': 'Error: Trade ID required'
            }
        
        # 找到对应的交易并标记为已关闭
        for trade in self._trades:
            if trade.id == trade_id and trade.is_open:
                trade.is_open = False
                trade.close_date = datetime.now(timezone.utc)
                trade.close_rate = trade.open_rate * (1 + (trade.profit_ratio or 0))
                trade.exit_reason = 'force_exit'
                
                # 计算最终盈亏
                if trade.profit_abs is None:
                    trade.profit_abs = (trade.close_rate - trade.open_rate) * trade.amount
                
                return {
                    'status': '平仓成功',
                    'trade_id': trade_id,
                    'pair': trade.pair,
                    'profit': trade.profit_abs,
                    'result': f'Trade {trade_id} force exited',
                    'result_msg': f'Manually exited trade {trade_id}'
                }
        
        return {
            'status': f'未找到ID为 {trade_id} 的开仓交易',
            'trade_id': trade_id,
            'result': f'Trade {trade_id} not found or already closed'
        }
    
    def _rpc_force_exit_all(self):
        """强制平仓所有开仓交易"""
        from datetime import timezone
        
        open_trades = [trade for trade in self._trades if trade.is_open]
        
        if not open_trades:
            return {
                'status': '当前没有开仓交易',
                'closed_trades': 0,
                'total_profit': 0.0,
                'result': 'No open trades to close'
            }
        
        closed_trades = []
        total_profit = 0.0
        
        for trade in open_trades:
            trade.is_open = False
            trade.close_date = datetime.now(timezone.utc)
            trade.close_rate = trade.open_rate * (1 + (trade.profit_ratio or 0))
            trade.exit_reason = 'force_exit_all'
            
            # 计算最终盈亏
            if trade.profit_abs is None:
                trade.profit_abs = (trade.close_rate - trade.open_rate) * trade.amount
            
            total_profit += trade.profit_abs or 0
            
            closed_trades.append({
                'trade_id': trade.id,
                'pair': trade.pair,
                'profit': trade.profit_abs
            })
        
        return {
            'status': f'成功平仓 {len(closed_trades)} 个交易',
            'closed_trades': len(closed_trades),
            'total_profit': total_profit,
            'trades': closed_trades,
            'result': f'Force exited {len(closed_trades)} trades',
            'result_msg': f'Manually exited all {len(closed_trades)} open trades'
        }
    
    def _rpc_force_enter(self, pair: str, side: str, amount: float = None, 
                        price: float = None, ordertype: str = None, 
                        stakeamount: float = None, enter_tag: str = 'force_entry'):
        """强制开仓"""
        
        trade_id = len(self._trades) + 1
        trade = Trade(
            id=trade_id,
            exchange='binance',
            pair=pair,
            is_open=True,
            fee_open=0.001,
            fee_close=None,
            open_rate=price or 1000.0,
            close_rate=None,
            amount=amount or 1.0,
            stake_amount=stakeamount or 100.0,
            strategy='Manual',
            enter_tag=enter_tag,
            timeframe=1,
            open_date=datetime.now(),
            close_date=None,
            profit_ratio=None,
            profit_abs=None,
            exit_reason=None,
            initial_stop_loss=None,
            stop_loss=None,
            max_rate=price or 1000.0,
            leverage=1.0,
            trading_mode='futures'
        )
        
        self._trades.append(trade)
        
        return {
            'result': f'Trade {trade_id} manually entered',
            'trade_id': trade_id,
            'result_msg': f'Manually entered trade for {pair}'
        }