#!/usr/bin/env python3
"""
清理币安期货账户中的止损订单
解决 "Reach max stop order limit" 错误
"""

import os
import asyncio
import ccxt.async_support as ccxt
from typing import List, Dict

class OrderCleanup:
    def __init__(self):
        # 从环境变量获取API密钥
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        testnet = os.getenv('BINANCE_TESTNET', 'True').lower() == 'true'
        
        if not api_key or not api_secret:
            raise ValueError("请设置环境变量: BINANCE_API_KEY, BINANCE_API_SECRET")
        
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # 确保使用期货API
            }
        })
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
            print("✅ 使用测试网环境")
        else:
            print("⚠️  使用实盘环境 - 请谨慎操作！")
    
    async def get_all_open_orders(self) -> List[Dict]:
        """获取所有未成交订单"""
        try:
            await self.exchange.load_markets()
            print("📊 正在获取所有未成交订单...")
            
            # 获取所有symbols的开放订单
            all_orders = await self.exchange.fetch_open_orders()
            
            print(f"📋 找到 {len(all_orders)} 个未成交订单")
            return all_orders
        except Exception as e:
            print(f"❌ 获取订单失败: {e}")
            return []
    
    async def cancel_stop_orders(self, dry_run: bool = True) -> Dict:
        """取消止损订单"""
        results = {
            'total_orders': 0,
            'stop_orders': 0,
            'cancelled': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            orders = await self.get_all_open_orders()
            results['total_orders'] = len(orders)
            
            # 统计止损订单
            stop_orders = []
            for order in orders:
                order_type = order.get('type', '').upper()
                if order_type in ['STOP', 'STOP_MARKET', 'TAKE_PROFIT', 'TAKE_PROFIT_MARKET']:
                    stop_orders.append(order)
            
            results['stop_orders'] = len(stop_orders)
            print(f"🎯 找到 {len(stop_orders)} 个止损/止盈订单")
            
            if not stop_orders:
                print("✅ 没有需要清理的止损订单")
                return results
            
            # 显示订单详情
            print("\n📊 止损/止盈订单详情:")
            print("-" * 80)
            for i, order in enumerate(stop_orders, 1):
                symbol = order['symbol']
                order_type = order['type']
                side = order['side']
                amount = order['amount']
                price = order.get('stopPrice') or order.get('price', 'N/A')
                
                print(f"{i:2d}. {symbol:15s} | {order_type:15s} | {side:4s} | {amount:8.4f} | 价格: {price}")
            
            print("-" * 80)
            
            if dry_run:
                print("🔍 这是预览模式，不会实际取消订单")
                print("💡 要实际执行，请运行: python cleanup_orders.py --execute")
                return results
            
            # 实际取消订单
            print(f"\n🗑️  开始取消 {len(stop_orders)} 个止损订单...")
            
            for i, order in enumerate(stop_orders, 1):
                try:
                    order_id = order['id']
                    symbol = order['symbol']
                    
                    print(f"📦 [{i}/{len(stop_orders)}] 取消订单 {order_id} ({symbol})")
                    
                    await self.exchange.cancel_order(order_id, symbol)
                    results['cancelled'] += 1
                    print(f"✅ 订单 {order_id} 已取消")
                    
                    # 避免频率限制
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    results['failed'] += 1
                    error_msg = f"取消订单 {order.get('id', 'unknown')} 失败: {e}"
                    results['errors'].append(error_msg)
                    print(f"❌ {error_msg}")
            
        except Exception as e:
            error_msg = f"清理过程出错: {e}"
            results['errors'].append(error_msg)
            print(f"❌ {error_msg}")
        
        return results
    
    async def show_account_summary(self):
        """显示账户摘要"""
        try:
            print("📈 账户摘要:")
            print("-" * 50)
            
            # 获取余额
            balance = await self.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            print(f"💰 USDT 余额: {usdt_balance.get('free', 0):.2f}")
            
            # 获取持仓
            positions = await self.exchange.fetch_positions()
            active_positions = [p for p in positions if float(p.get('contracts', 0)) != 0]
            print(f"📊 活跃持仓: {len(active_positions)} 个")
            
            if active_positions:
                print("\n🎯 当前持仓:")
                for pos in active_positions:
                    symbol = pos['symbol']
                    side = pos['side']
                    size = pos['contracts']
                    pnl = pos.get('unrealizedPnl', 0)
                    print(f"   {symbol:15s} | {side:5s} | {size:8.4f} | PNL: {pnl:+8.2f}")
            
            print("-" * 50)
            
        except Exception as e:
            print(f"❌ 获取账户信息失败: {e}")

async def main():
    import sys
    
    print("🔧 币安期货订单清理工具")
    print("=" * 50)
    
    try:
        cleanup = OrderCleanup()
        
        # 显示账户摘要
        await cleanup.show_account_summary()
        
        # 检查是否为执行模式
        execute_mode = '--execute' in sys.argv or '-x' in sys.argv
        
        if not execute_mode:
            print("\n⚠️  预览模式 - 不会实际取消订单")
        else:
            print("\n🚨 执行模式 - 将实际取消止损订单！")
            
            # 二次确认
            if input("确认要继续吗？(输入 'YES' 确认): ") != 'YES':
                print("❌ 操作已取消")
                return
        
        # 执行清理
        results = await cleanup.cancel_stop_orders(dry_run=not execute_mode)
        
        # 显示结果摘要
        print("\n📊 清理结果摘要:")
        print("-" * 40)
        print(f"📋 总订单数: {results['total_orders']}")
        print(f"🎯 止损订单数: {results['stop_orders']}")
        print(f"✅ 成功取消: {results['cancelled']}")
        print(f"❌ 取消失败: {results['failed']}")
        
        if results['errors']:
            print("\n❌ 错误详情:")
            for error in results['errors']:
                print(f"   • {error}")
        
        if execute_mode and results['cancelled'] > 0:
            print(f"\n🎉 成功清理了 {results['cancelled']} 个止损订单！")
            print("💡 现在可以重新启动交易机器人了")
    
    except KeyboardInterrupt:
        print("\n⚠️  用户中断操作")
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 