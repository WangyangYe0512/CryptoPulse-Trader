#!/usr/bin/env python3
"""
启动时持仓恢复模块
处理程序重启时的持仓状态和订单管理
"""

import os
import sys
from typing import Dict, List

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from executor.binance_executor import BinanceExecutor
from utils.logger import trading_logger

class StartupRecovery:
    """启动时持仓恢复管理器"""
    
    def __init__(self, config: ConfigManager, executor: BinanceExecutor):
        self.config = config
        self.executor = executor
        
    async def check_and_recover_positions(self) -> Dict:
        """检查并恢复持仓状态"""
        recovery_info = {
            'active_positions': [],
            'open_orders': [],
            'recommendations': [],
            'warnings': []
        }
        
        try:
            trading_logger.info("🔍 正在检查启动时的持仓和订单状态...")
            
            # 1. 检查活跃持仓
            positions = await self._get_active_positions()
            recovery_info['active_positions'] = positions
            
            # 2. 检查开放订单
            orders = await self._get_open_orders()
            recovery_info['open_orders'] = orders
            
            # 3. 分析状态并生成建议
            recommendations = self._analyze_and_recommend(positions, orders)
            recovery_info['recommendations'] = recommendations
            
            # 4. 生成警告
            warnings = self._generate_warnings(positions, orders)
            recovery_info['warnings'] = warnings
            
            # 5. 打印恢复报告
            self._print_recovery_report(recovery_info)
            
            return recovery_info
            
        except Exception as e:
            trading_logger.error(f"持仓恢复检查失败: {e}", exc_info=True)
            recovery_info['warnings'].append(f"恢复检查失败: {e}")
            return recovery_info
    
    async def _get_active_positions(self) -> List[Dict]:
        """获取活跃持仓"""
        positions = []
        try:
            raw_positions = await self.executor.exchange.fetch_positions()
            
            for pos in raw_positions:
                contracts = float(pos.get('contracts', 0))
                if contracts != 0:
                    position_info = {
                        'symbol': pos['symbol'],
                        'side': pos['side'],
                        'size': contracts,
                        'entry_price': pos.get('entryPrice'),
                        'mark_price': pos.get('markPrice'),
                        'unrealized_pnl': pos.get('unrealizedPnl'),
                        'percentage': pos.get('percentage')
                    }
                    positions.append(position_info)
                    
        except Exception as e:
            trading_logger.error(f"获取持仓失败: {e}")
            
        return positions
    
    async def _get_open_orders(self) -> List[Dict]:
        """获取开放订单"""
        orders = []
        try:
            raw_orders = await self.executor.exchange.fetch_open_orders()
            
            for order in raw_orders:
                order_info = {
                    'id': order['id'],
                    'symbol': order['symbol'],
                    'type': order['type'],
                    'side': order['side'],
                    'amount': order['amount'],
                    'price': order.get('price'),
                    'stop_price': order.get('stopPrice'),
                    'status': order['status'],
                    'datetime': order['datetime']
                }
                orders.append(order_info)
                
        except Exception as e:
            trading_logger.error(f"获取订单失败: {e}")
            
        return orders
    
    def _analyze_and_recommend(self, positions: List[Dict], orders: List[Dict]) -> List[str]:
        """分析状态并生成建议"""
        recommendations = []
        
        if not positions and not orders:
            recommendations.append("✅ 账户状态干净，可以正常启动交易")
            return recommendations
        
        # 分析持仓
        if positions:
            recommendations.append(f"📊 发现 {len(positions)} 个活跃持仓")
            
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                pnl = pos.get('unrealized_pnl', 0)
                pnl_pct = pos.get('percentage', 0)
                
                if pnl_pct and abs(pnl_pct) > 5:  # 盈亏超过5%
                    if pnl_pct > 0:
                        recommendations.append(f"💰 {symbol} {side}仓位盈利 {pnl_pct:+.2f}%，建议监控")
                    else:
                        recommendations.append(f"⚠️ {symbol} {side}仓位亏损 {pnl_pct:+.2f}%，建议检查止损")
        
        # 分析订单
        if orders:
            stop_orders = [o for o in orders if 'STOP' in o['type'].upper() or 'TAKE_PROFIT' in o['type'].upper()]
            other_orders = [o for o in orders if o not in stop_orders]
            
            if stop_orders:
                recommendations.append(f"🛡️ 发现 {len(stop_orders)} 个止损/止盈订单")
                
            if other_orders:
                recommendations.append(f"📋 发现 {len(other_orders)} 个其他挂单")
        
        # 检查匹配情况
        position_symbols = {pos['symbol'] for pos in positions}
        order_symbols = {order['symbol'] for order in orders}
        
        # 有持仓但无订单的币种
        no_orders_symbols = position_symbols - order_symbols
        if no_orders_symbols:
            recommendations.append(f"⚠️ 以下币种有持仓但无保护订单: {list(no_orders_symbols)}")
        
        # 有订单但无持仓的币种
        orphaned_orders = order_symbols - position_symbols
        if orphaned_orders:
            recommendations.append(f"🧹 以下币种有孤立订单: {list(orphaned_orders)}")
        
        return recommendations
    
    def _generate_warnings(self, positions: List[Dict], orders: List[Dict]) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        # 检查高风险持仓
        for pos in positions:
            pnl_pct = pos.get('percentage', 0)
            if pnl_pct and pnl_pct < -10:  # 亏损超过10%
                warnings.append(f"🚨 {pos['symbol']} {pos['side']}仓位严重亏损 {pnl_pct:+.2f}%")
        
        # 检查订单数量
        if len(orders) > 100:
            warnings.append(f"⚠️ 发现大量挂单 ({len(orders)} 个)，可能接近订单限制")
        
        # 检查策略状态不一致
        if positions:
            warnings.append("⚠️ 程序重启会导致策略状态丢失，请注意以下影响:")
            warnings.append("   • 趋势状态将重置")
            warnings.append("   • 基线价格需要重新建立")
            warnings.append("   • 可能在已有持仓的币种再次交易")
        
        return warnings
    
    def _print_recovery_report(self, recovery_info: Dict):
        """打印恢复报告"""
        print("\n" + "="*60)
        print("🔄 启动时持仓恢复报告")
        print("="*60)
        
        # 持仓信息
        positions = recovery_info['active_positions']
        if positions:
            print(f"\n📊 活跃持仓 ({len(positions)} 个):")
            print("-" * 80)
            print(f"{'币种':<15} {'方向':<6} {'数量':<12} {'入场价':<10} {'标记价':<10} {'盈亏%':<8} {'盈亏$'}")
            print("-" * 80)
            
            for pos in positions:
                symbol = pos['symbol'][:14]
                side = pos['side']
                size = f"{pos['size']:.4f}"
                entry = f"{pos.get('entry_price', 0):.6f}"
                mark = f"{pos.get('mark_price', 0):.6f}"
                pnl_pct = f"{pos.get('percentage', 0):+.2f}%"
                pnl_usd = f"{pos.get('unrealized_pnl', 0):+.2f}"
                
                print(f"{symbol:<15} {side:<6} {size:<12} {entry:<10} {mark:<10} {pnl_pct:<8} {pnl_usd}")
        else:
            print("\n📊 活跃持仓: 无")
        
        # 订单信息
        orders = recovery_info['open_orders']
        if orders:
            print(f"\n📋 挂单 ({len(orders)} 个):")
            print("-" * 70)
            print(f"{'币种':<15} {'类型':<15} {'方向':<6} {'数量':<10} {'价格':<10}")
            print("-" * 70)
            
            for order in orders[:10]:  # 只显示前10个
                symbol = order['symbol'][:14]
                order_type = order['type'][:14]
                side = order['side']
                amount = f"{order['amount']:.4f}"
                price = f"{order.get('price') or order.get('stop_price', 0):.6f}"
                
                print(f"{symbol:<15} {order_type:<15} {side:<6} {amount:<10} {price:<10}")
            
            if len(orders) > 10:
                print(f"... 还有 {len(orders) - 10} 个订单未显示")
        else:
            print("\n📋 挂单: 无")
        
        # 建议
        recommendations = recovery_info['recommendations']
        if recommendations:
            print("\n💡 建议:")
            for rec in recommendations:
                print(f"   {rec}")
        
        # 警告
        warnings = recovery_info['warnings']
        if warnings:
            print("\n⚠️ 警告:")
            for warning in warnings:
                print(f"   {warning}")
        
        print("\n" + "="*60) 