#!/usr/bin/env python3
"""
消息格式演示 - 展示新的freqtrade风格消息模板
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from utils.telegram_bot import TelegramBot

def demo_message_formats():
    """演示各种消息格式"""
    
    print("🎨 CryptoPulse Trader 消息格式演示")
    print("=" * 50)
    
    # 初始化配置管理器和Telegram Bot
    config_manager = ConfigManager()
    telegram_bot = TelegramBot(config_manager)
    
    # 演示开仓消息
    print("\n📈 开仓通知消息:")
    print("-" * 30)
    trade_open_data = {
        'action': 'open',
        'symbol': 'BTC/USDT',
        'side': 'BUY',
        'price': 45678.123456,
        'amount': 0.001234,
        'stop_loss': 44000.00,
        'take_profit': 47000.00,
        'timestamp': datetime.now()
    }
    open_message = telegram_bot._format_open_trade_message(trade_open_data)
    print(open_message)
    
    # 演示平仓消息
    print("\n📉 平仓通知消息:")
    print("-" * 30)
    trade_close_data = {
        'action': 'close',
        'symbol': 'ETH/USDT',
        'side': 'SELL',
        'close_price': 3234.567890,
        'pnl': 125.50,
        'pnl_pct': 5.23,
        'duration': 45,
        'reason': '止盈触发',
        'timestamp': datetime.now()
    }
    close_message = telegram_bot._format_close_trade_message(trade_close_data)
    print(close_message)
    
    # 演示错误消息
    print("\n⚠️ 错误通知消息:")
    print("-" * 30)
    error_data = {
        'type': 'API Error',
        'message': '交易所连接超时，请检查网络连接',
        'timestamp': datetime.now()
    }
    error_message = telegram_bot._format_error_message(error_data)
    print(error_message)
    
    # 演示状态消息
    print("\n📊 状态通知消息:")
    print("-" * 30)
    status_data = {
        'status': 'running',
        'message': '系统运行正常，监控市场中',
        'timestamp': datetime.now()
    }
    status_message = telegram_bot._format_status_message(status_data)
    print(status_message)
    
    print("\n✨ 新格式特点:")
    print("• 使用 **粗体** 标签突出显示字段名")
    print("• 使用 `反引号` 高亮显示数值")  
    print("• 移除了繁重的分隔线")
    print("• 采用简洁清晰的布局")
    print("• 参考freqtrade的专业风格")
    
if __name__ == "__main__":
    demo_message_formats() 