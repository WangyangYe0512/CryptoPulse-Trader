#!/usr/bin/env python3
"""
Telegram群组ID获取助手

帮助用户获取正确的群组ID和话题ID
"""

import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config_manager import ConfigManager
from utils.logger import setup_logging
from telegram import Bot
from telegram.error import TelegramError


async def get_chat_info():
    """获取聊天信息"""
    
    print("🔍 Telegram群组ID获取助手")
    print("=" * 50)
    
    # 初始化日志
    setup_logging(level_name_str="INFO")
    
    # 获取配置
    config_manager = ConfigManager()
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not bot_token:
        print("❌ 错误: 未设置环境变量 TELEGRAM_BOT_TOKEN")
        return
    
    if not chat_id:
        print("❌ 错误: 未设置环境变量 TELEGRAM_CHAT_ID")
        print("💡 提示: 可以先设置任意值，然后通过机器人获取正确ID")
        return
    
    try:
        # 创建Bot实例
        bot = Bot(token=bot_token)
        
        print(f"🤖 Bot Token: {bot_token[:15]}...")
        print(f"💬 当前Chat ID: {chat_id}")
        
        # 获取聊天信息
        print("\n📡 获取聊天信息...")
        
        try:
            chat = await bot.get_chat(chat_id)
            
            print("✅ 聊天信息获取成功:")
            print(f"   ID: {chat.id}")
            print(f"   类型: {chat.type}")
            print(f"   标题: {chat.title or '私聊'}")
            print(f"   用户名: @{chat.username or 'N/A'}")
            print(f"   描述: {chat.description or 'N/A'}")
            
            if chat.type in ['group', 'supergroup']:
                print(f"   成员数: {chat.approximate_member_count or 'N/A'}")
                
                # 检查是否为超级群组且支持话题
                if hasattr(chat, 'is_forum') and chat.is_forum:
                    print("   支持话题: 是")
                    print("   💡 提示: 这是一个支持话题的超级群组")
                else:
                    print("   支持话题: 否")
            
            # 建议配置
            print("\n📝 建议的配置:")
            
            if chat.type == 'private':
                print("   模式: 私聊模式")
                print(f"   TELEGRAM_CHAT_ID={chat.id}")
                print("   config.yaml:")
                print("     group_mode: false")
                
            elif chat.type in ['group', 'supergroup']:
                print("   模式: 群组模式")
                print(f"   TELEGRAM_CHAT_ID={chat.id}")
                print("   config.yaml:")
                print("     group_mode: true")
                print("     topic_id: null  # 发送到主群组")
                
                if hasattr(chat, 'is_forum') and chat.is_forum:
                    print("\n   📋 话题功能:")
                    print("     topic_id: 话题ID  # 发送到特定话题")
                    print("     topic_routing:")
                    print("       enabled: true")
                    print("       topics:")
                    print("         trade: 话题ID1")
                    print("         error: 话题ID2")
                    print("         status: 话题ID3")
                    print("         system: null")
                    
        except TelegramError as e:
            print(f"❌ 无法获取聊天信息: {e}")
            print("💡 可能原因:")
            print("   1. Chat ID不正确")
            print("   2. 机器人不在此群组中")
            print("   3. 机器人权限不足")
            
        # 获取最近的更新（获取消息示例）
        print("\n📨 获取最近更新...")
        
        try:
            updates = await bot.get_updates(limit=10)
            
            if updates:
                print(f"✅ 找到 {len(updates)} 条最近更新:")
                
                chat_info = {}
                for update in updates[-5:]:  # 显示最近5条
                    if update.message:
                        msg = update.message
                        chat_key = f"{msg.chat.type}_{msg.chat.id}"
                        
                        if chat_key not in chat_info:
                            chat_info[chat_key] = {
                                'id': msg.chat.id,
                                'type': msg.chat.type,
                                'title': msg.chat.title or msg.chat.first_name or 'Unknown',
                                'topics': set()
                            }
                        
                        # 检查是否有话题信息
                        if hasattr(msg, 'message_thread_id') and msg.message_thread_id:
                            chat_info[chat_key]['topics'].add(msg.message_thread_id)
                
                print("\n📋 发现的聊天:")
                for info in chat_info.values():
                    print(f"   {info['type']}: {info['title']} (ID: {info['id']})")
                    if info['topics']:
                        print(f"     话题IDs: {sorted(info['topics'])}")
                        
            else:
                print("❌ 没有找到最近的更新")
                print("💡 提示: 请先在群组中发送一条消息，然后重新运行此脚本")
                
        except TelegramError as e:
            print(f"❌ 无法获取更新: {e}")
            
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


def show_help():
    """显示帮助信息"""
    
    print("""
🆘 获取群组ID的方法:

方法1: 使用@userinfobot
1. 将 @userinfobot 添加到您的群组
2. 在群组中发送任意消息
3. 机器人会回复群组信息，包含群组ID

方法2: 通过Web界面
1. 登录 https://web.telegram.org/
2. 打开您的群组
3. 查看URL中的ID（例如: #-1001234567890）

方法3: 转发消息
1. 从群组转发任意消息到 @userinfobot
2. 查看回复中的群组ID

方法4: 使用Bot API
1. 让机器人发送一条消息到群组
2. 访问: https://api.telegram.org/bot<TOKEN>/getUpdates
3. 查找 "chat":{"id":-1001234567890} 

💡 注意事项:
- 私聊ID通常是正数 (例如: 123456789)
- 群组ID通常是负数 (例如: -1001234567890)
- 超级群组ID通常以 -100 开头
- 话题ID是正整数 (例如: 2, 3, 4)

🔧 获取话题ID:
1. 确保群组启用了话题功能
2. 在想要的话题中发送消息  
3. 运行此脚本查看话题ID
4. 或通过Bot API的getUpdates查看message_thread_id
""")


async def main():
    """主函数"""
    
    if len(sys.argv) > 1 and sys.argv[1] == '--help':
        show_help()
        return
    
    try:
        await get_chat_info()
        
    except KeyboardInterrupt:
        print("\n👋 脚本已中断")
    except Exception as e:
        print(f"❌ 脚本执行失败: {e}")


if __name__ == "__main__":
    print("使用 --help 参数查看获取群组ID的详细方法")
    asyncio.run(main()) 