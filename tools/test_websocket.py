#!/usr/bin/env python3
"""
WebSocket连接测试脚本
用于诊断Binance WebSocket连接问题
"""

import asyncio
import json
import websockets
import time

async def test_binance_ws():
    """测试Binance WebSocket连接和订阅"""
    
    # 使用Binance Futures WebSocket URL
    ws_url = "wss://fstream.binance.com/ws"
    
    try:
        print(f"正在连接到: {ws_url}")
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
            print("✅ WebSocket连接成功!")
            
            # 订阅一个简单的ticker
            subscribe_message = {
                "method": "SUBSCRIBE",
                "params": ["btcusdt@ticker"],
                "id": int(time.time())
            }
            
            print(f"发送订阅消息: {json.dumps(subscribe_message)}")
            await ws.send(json.dumps(subscribe_message))
            
            # 等待订阅确认和数据
            message_count = 0
            timeout_count = 0
            
            while message_count < 5 and timeout_count < 10:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    data = json.loads(message)
                    message_count += 1
                    
                    if 'result' in data and data.get('result') is None:
                        print(f"✅ 订阅确认: {data}")
                    elif 'e' in data and data['e'] == '24hrTicker':
                        print(f"✅ 收到ticker数据: {data['s']} 价格: {data['c']}")
                    else:
                        print(f"📨 其他消息: {data}")
                        
                except asyncio.TimeoutError:
                    timeout_count += 1
                    print(f"⏰ 等待消息超时 ({timeout_count}/10)")
                    
            if message_count >= 5:
                print("✅ WebSocket测试成功 - 收到预期数据!")
            else:
                print(f"⚠️ WebSocket测试警告 - 只收到 {message_count} 条消息")
                
    except websockets.exceptions.ConnectionClosed as e:
        print(f"❌ WebSocket连接关闭: {e}")
    except Exception as e:
        print(f"❌ WebSocket测试失败: {e}")

if __name__ == "__main__":
    print("开始Binance WebSocket连接测试...")
    asyncio.run(test_binance_ws()) 