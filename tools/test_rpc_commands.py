#!/usr/bin/env python3
"""
测试RPC命令的脚本
用于验证balance和profit命令是否正常工作
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from utils.enhanced_telegram_integration import EnhancedTelegramIntegration

def test_rpc_commands():
    """测试RPC命令"""
    try:
        # 初始化配置管理器
        config_manager = ConfigManager()
        
        # 创建增强Telegram集成
        telegram_integration = EnhancedTelegramIntegration(config_manager)
        
        # 获取RPC实例
        rpc = telegram_integration.rpc
        
        print("🧪 开始测试RPC命令...")
        
        # 测试balance命令
        print("\n📊 测试 /balance 命令...")
        try:
            balance_result = rpc._rpc_balance("USDT", "USD")
            print("✅ Balance命令成功:")
            print(f"   - 总余额: {balance_result.get('total', 0):.2f} USDT")
            print(f"   - 交易数量: {balance_result.get('trade_count', 0)}")
            if 'error' in balance_result:
                print(f"   ⚠️  错误: {balance_result['error']}")
        except Exception as e:
            print(f"❌ Balance命令失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 测试profit命令
        print("\n💰 测试 /profit 命令...")
        try:
            profit_result = rpc._rpc_profit("USDT", "USD")
            print("✅ Profit命令成功:")
            print(f"   - 总盈亏: {profit_result.get('profit_all_coin', 0):.2f} USDT")
            print(f"   - 已实现盈亏: {profit_result.get('profit_closed_coin', 0):.2f} USDT")
            print(f"   - 未实现盈亏: {profit_result.get('unrealized_pnl', 0):.2f} USDT")
            print(f"   - 交易数量: {profit_result.get('trade_count', 0)}")
            if 'error' in profit_result:
                print(f"   ⚠️  错误: {profit_result['error']}")
        except Exception as e:
            print(f"❌ Profit命令失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 测试status命令
        print("\n📈 测试 /status 命令...")
        try:
            status_result = rpc._rpc_trade_status()
            print("✅ Status命令成功:")
            print(f"   - 开仓交易数量: {len(status_result)}")
            for trade in status_result:
                print(f"   - 交易 {trade.get('trade_id')}: {trade.get('pair')} - 盈亏: {trade.get('profit_abs', 0):.2f} USDT")
        except Exception as e:
            print(f"❌ Status命令失败: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n🎉 RPC命令测试完成!")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_rpc_commands()
