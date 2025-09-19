#!/usr/bin/env python3
"""
CPT RPC Bridge - 连接 CryptoPulse Trader 数据与 freqtrade RPC 系统
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from rpc.persistence import Trade

class CPTRPCBridge:
    """CPT 到 freqtrade RPC 桥接器"""
    
    def __init__(self, config_manager):
        """初始化桥接器"""
        self.config_manager = config_manager
        self.trades: Dict[int, Trade] = {}
        self._trade_id_counter = 1
        
        # 初始化时不创建示例数据，依赖真实交易所数据
        
    def _create_sample_trades(self):
        """创建示例交易数据用于测试"""
        sample_trades = [
            {
                'pair': 'BTC/USDT:USDT',
                'direction': 'long',
                'leverage': 1.0,
                'entry_price': 42000.0,
                'current_price': 45800.0,
                'amount': 0.01,
                'stake_amount': 420.0,
                'hours_ago': 16
            },
            {
                'pair': 'ETH/USDT:USDT', 
                'direction': 'long',
                'leverage': 5.0,
                'entry_price': 2500.0,
                'current_price': 2650.0,
                'amount': 0.2,
                'stake_amount': 500.0,
                'hours_ago': 12
            },
            {
                'pair': 'ADA/USDT:USDT',
                'direction': 'short',
                'leverage': 3.0,
                'entry_price': 0.45,
                'current_price': 0.42,
                'amount': 1000.0,
                'stake_amount': 450.0,
                'hours_ago': 8
            }
        ]
        
        for trade_data in sample_trades:
            self._add_sample_trade(trade_data)
            
    def _add_sample_trade(self, trade_data: Dict[str, Any]) -> Trade:
        """添加示例交易"""
        trade_id = self._trade_id_counter
        self._trade_id_counter += 1
        
        # 计算开仓时间
        open_time = datetime.now(timezone.utc) - timedelta(hours=trade_data['hours_ago'])
        
        # 计算盈亏
        entry_price = trade_data['entry_price']
        current_price = trade_data['current_price']
        amount = trade_data['amount']
        
        if trade_data['direction'] == 'long':
            profit_abs = (current_price - entry_price) * amount
        else:  # short
            profit_abs = (entry_price - current_price) * amount
            
        profit_ratio = profit_abs / trade_data['stake_amount']
        
        # 创建 Trade 对象
        trade = Trade(
            id=trade_id,
            exchange='binance',
            pair=trade_data['pair'],
            is_open=True,
            fee_open=0.001,
            fee_close=0.001,
            open_rate=entry_price,
            close_rate=None,
            amount=amount,
            stake_amount=trade_data['stake_amount'],
            strategy='CPTStrategy',
            enter_tag='cpt_entry',
            timeframe=5,
            open_date=open_time,
            close_date=None,
            profit_ratio=profit_ratio,
            profit_abs=profit_abs,
            exit_reason=None,
            initial_stop_loss=None,
            stop_loss=None,
            max_rate=current_price,
            leverage=trade_data['leverage'],
            trading_mode='futures' if trade_data['leverage'] > 1 else 'spot'
        )
        
        # 设置当前价格和盈亏
        trade.current_rate = current_price
        trade.profit_ratio = profit_ratio
        trade.profit_abs = profit_abs
        
        self.trades[trade_id] = trade
        return trade
        
    def get_open_trades(self) -> List[Trade]:
        """获取开仓交易"""
        return [trade for trade in self.trades.values() if trade.is_open]
        
    def get_closed_trades(self, limit: int = 50) -> List[Trade]:
        """获取已平仓交易"""
        closed = [trade for trade in self.trades.values() if not trade.is_open]
        return closed[-limit:] if limit else closed
        
    def get_trade_by_id(self, trade_id: int) -> Optional[Trade]:
        """根据ID获取交易"""
        return self.trades.get(trade_id)
        
    def close_trade(self, trade_id: int, close_price: float = None) -> bool:
        """平仓交易"""
        trade = self.get_trade_by_id(trade_id)
        if not trade or not trade.is_open:
            return False
            
        if close_price is None:
            close_price = trade.current_rate
            
        trade.close(close_price)
        return True
        
    def get_profit_stats(self) -> Dict[str, float]:
        """获取盈亏统计"""
        open_trades = self.get_open_trades()
        closed_trades = self.get_closed_trades()
        
        total_profit = sum(trade.profit_abs for trade in open_trades if trade.profit_abs)
        closed_profit = sum(trade.close_profit_abs for trade in closed_trades if trade.close_profit_abs)
        
        return {
            'total_profit': total_profit,
            'closed_profit': closed_profit,
            'open_trade_count': len(open_trades),
            'closed_trade_count': len(closed_trades)
        }
    
    def get_trading_stats(self) -> Dict[str, Any]:
        """获取交易统计信息"""
        open_trades = self.get_open_trades()
        closed_trades = self.get_closed_trades()
        
        # 计算胜负统计
        winning_trades = len([t for t in closed_trades if (t.profit_abs or 0) > 0])
        losing_trades = len([t for t in closed_trades if (t.profit_abs or 0) <= 0])
        
        # 计算总盈亏
        total_profit = sum(t.profit_abs or 0 for t in closed_trades)
        
        return {
            'open_trades_count': len(open_trades),
            'closed_trades_count': len(closed_trades),
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'total_profit': total_profit,
            'win_rate': (winning_trades / len(closed_trades)) if closed_trades else 0.0
        }
    def create_trade_from_signal(self, signal: Dict[str, Any]) -> Trade:
        """从交易信号创建真实交易记录"""
        trade_id = self._trade_id_counter
        self._trade_id_counter += 1
        
        # 从信号中提取交易信息
        pair = signal.get('symbol', 'UNKNOWN/USDT:USDT')
        direction = signal.get('type', signal.get('action', 'OPEN_LONG')).upper()
        entry_price = signal.get('price', 0.0)
        amount = signal.get('amount_contracts', signal.get('amount', 0.0))
        leverage = signal.get('leverage', 1.0)
        
        # 处理开仓时间
        open_timestamp = signal.get('open_timestamp')
        if open_timestamp and open_timestamp > 0:
            try:
                # 处理毫秒时间戳
                if open_timestamp > 1000000000000:  # 毫秒时间戳
                    open_timestamp = open_timestamp / 1000
                open_date = datetime.fromtimestamp(open_timestamp, tz=timezone.utc)
            except Exception:
                # 时间戳无效，估算为1小时前
                open_date = datetime.now(timezone.utc) - timedelta(hours=1)
        else:
            # 没有时间戳，估算为30分钟前（合理的持仓时间）
            open_date = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        # 转换方向标识
        is_long = 'LONG' in direction or 'long' in direction.lower()
        enter_tag = 'long_entry' if is_long else 'short_entry'
        
        # 创建真实交易记录
        trade = Trade(
            id=trade_id,
            exchange='binance',
            pair=pair,
            is_open=True,
            fee_open=0.001,
            fee_close=0.001,
            open_rate=entry_price,
            close_rate=None,
            amount=amount,
            stake_amount=entry_price * amount,
            strategy='CPTStrategy',
            enter_tag=enter_tag,
            timeframe=5,
            open_date=open_date,
            close_date=None,
            profit_ratio=0.0,
            profit_abs=0.0,
            exit_reason=None,
            initial_stop_loss=None,
            stop_loss=None,
            max_rate=entry_price,
            leverage=leverage,
            trading_mode='futures' if leverage > 1 else 'spot'
        )
        
        self.trades[trade_id] = trade
        self.config_manager.logger.info(f"创建真实交易记录: {trade_id} - {pair}")
        return trade
            
    def create_rpc_status_msg(self, status: str, message: str) -> Dict[str, Any]:
        """创建RPC状态消息"""
        from rpc.enums import RPCMessageType
        return {
            'type': RPCMessageType.STATUS,
            'status': message,  # 注意：这里应该是消息内容，不是状态
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def create_rpc_strategy_msg(self, message: str) -> Dict[str, Any]:
        """创建策略消息（用于发送一般信息/错误提示）"""
        try:
            from rpc.enums import RPCMessageType
            msg_type = getattr(RPCMessageType, 'STRATEGY', 'strategy')
        except Exception:
            msg_type = 'strategy'
        return {
            'type': msg_type,
            'message': message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
    def signal_to_rpc_entry_msg(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """将交易信号转换为RPC入场消息"""
        try:
            action = signal.get('action', 'UNKNOWN')
            symbol = signal.get('symbol', 'UNKNOWN')
            price = signal.get('price', 0.0)
            amount = signal.get('amount', 0.0)
            
            # 确定消息类型
            if 'OPEN_LONG' in action:
                msg_type = 'entry'
                side = 'long'
            elif 'OPEN_SHORT' in action:
                msg_type = 'entry'
                side = 'short'
            elif 'CLOSE' in action:
                msg_type = 'exit'
                side = 'long' if 'LONG' in action else 'short'
            else:
                msg_type = 'unknown'
                side = 'unknown'
                
            return {
                'type': msg_type,
                'side': side,
                'pair': symbol,
                'price': price,
                'amount': amount,
                'action': action,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            self.config_manager.logger.error(f"转换信号为RPC消息失败: {e}")
            return {
                'type': 'error',
                'message': f'信号转换失败: {str(e)}',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    def update_trade_on_close(self, trade_id: int, close_price: float, exit_reason: str = 'manual') -> Trade:
        """更新交易记录为已关闭状态"""
        if trade_id not in self.trades:
            self.config_manager.logger.warning(f"交易记录 {trade_id} 不存在，无法更新")
            # 创建一个虚拟的已关闭交易记录
            trade = Trade(
                id=trade_id,
                exchange='binance',
                pair='UNKNOWN/USDT:USDT',
                is_open=False,
                fee_open=0.001,
                fee_close=0.001,
                open_rate=close_price,
                close_rate=close_price,
                amount=0.0,
                stake_amount=0.0,
                strategy='CPTStrategy',
                enter_tag='unknown',
                timeframe=5,
                open_date=datetime.now(timezone.utc),
                close_date=datetime.now(timezone.utc),
                profit_ratio=0.0,
                profit_abs=0.0,
                exit_reason=exit_reason,
                initial_stop_loss=None,
                stop_loss=None,
                max_rate=close_price,
                leverage=1.0,
                trading_mode='futures'
            )
            return trade
            
        trade = self.trades[trade_id]
        
        # 更新交易记录为已关闭
        trade.is_open = False
        trade.close_rate = close_price
        trade.close_date = datetime.now(timezone.utc)
        trade.exit_reason = exit_reason
        
        # 计算盈亏
        if trade.open_rate and trade.close_rate:
            # 根据方向计算盈亏
            is_long = 'long' in (trade.enter_tag or '').lower()
            if is_long:
                trade.profit_abs = (trade.close_rate - trade.open_rate) * trade.amount
            else:
                trade.profit_abs = (trade.open_rate - trade.close_rate) * trade.amount
            
            if trade.stake_amount and trade.stake_amount > 0:
                trade.profit_ratio = trade.profit_abs / trade.stake_amount
            else:
                trade.profit_ratio = 0.0
        
        self.config_manager.logger.info(f"交易记录 {trade_id} 已更新为关闭状态，盈亏: {trade.profit_abs:.2f} USDT")
        return trade