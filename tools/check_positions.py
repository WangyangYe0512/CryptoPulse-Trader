#!/usr/bin/env python3
"""
快速检查当前持仓和订单状态
"""

import os
import sys
import asyncio

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from executor.binance_executor import BinanceExecutor
from startup_recovery import StartupRecovery
from utils.logger import setup_logging

async def main():
    """检查当前持仓状态"""
    print("🔍 快速持仓检查工具")
    print("=" * 40)
    
    try:
        # 设置简单日志
        setup_logging(level_name_str="WARNING", log_to_console=True, log_to_file=False)
        
        # 初始化组件
        config = ConfigManager()
        executor = BinanceExecutor(config)
        recovery = StartupRecovery(config, executor)
        
        # 执行检查
        recovery_info = await recovery.check_and_recover_positions()
        
        # 简要总结
        positions = recovery_info['active_positions']
        orders = recovery_info['open_orders']
        
        print("\n📊 总结:")
        print(f"   • 活跃持仓: {len(positions)} 个")
        print(f"   • 挂单: {len(orders)} 个")
        
        if positions or orders:
            print("\n⚠️ 检测到活跃交易状态！")
            print("   如果现在重启程序，将会:")
            print("   • 程序不知道上述持仓状态")
            print("   • 策略状态完全重置")
            print("   • 可能在已有持仓的币种再次开仓")
            print("   • 止损/止盈订单会继续有效但程序不监控")
        else:
            print("\n✅ 账户状态干净，重启程序无影响")
            
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 关闭CCXT连接
        try:
            if 'executor' in locals() and executor and hasattr(executor, 'exchange'):
                await executor.exchange.close()
        except Exception as e:
            print(f"Error closing exchange connection: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 