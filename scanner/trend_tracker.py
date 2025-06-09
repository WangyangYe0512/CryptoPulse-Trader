import json
import threading
import websocket
from typing import Dict, List, Optional, Callable
from utils.logger import trading_logger

class TrendTracker:
    """WebSocket趋势追踪器"""
    
    def __init__(self, symbols: List[str], on_trend_update: Optional[Callable] = None, 
                 price_weight: float = 2.0, volume_weight: float = 0.5):
        """
        初始化趋势追踪器
        
        Args:
            symbols: 要追踪的交易对列表
            on_trend_update: 趋势更新回调函数
            price_weight: 价格变化权重系数
            volume_weight: 成交量变化权重系数
        """
        self.symbols = symbols
        self.on_trend_update = on_trend_update
        self.price_weight = price_weight
        self.volume_weight = volume_weight
        self.ws = None
        self.running = False
        self.kline_data: Dict[str, List[Dict]] = {}
        
    def start(self):
        """启动趋势追踪"""
        if self.running:
            return
            
        self.running = True
        trading_logger.info("启动趋势追踪...")
        
        # 构建WebSocket URL
        ws_url = "wss://fstream.binance.com/ws"
        
        # 构建订阅消息
        streams = [f"{symbol.lower()}@kline_30s" for symbol in self.symbols]
        subscribe_message = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1
        }
        
        # 创建WebSocket连接
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open
        )
        
        # 保存订阅消息
        self.subscribe_message = subscribe_message
        
        # 启动WebSocket线程
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()
        
    def stop(self):
        """停止趋势追踪"""
        if not self.running:
            return
            
        self.running = False
        if self.ws:
            self.ws.close()
            
    def _run_websocket(self):
        """运行WebSocket连接"""
        try:
            self.ws.run_forever()
        except Exception as e:
            trading_logger.error(f"WebSocket运行异常: {str(e)}", exc_info=True)
            
    def _on_message(self, ws, message):
        """处理WebSocket消息"""
        try:
            data = json.loads(message)
            
            # 处理K线数据
            if 'k' in data:
                kline = data['k']
                symbol = data['s']
                
                # 更新K线数据
                self._update_kline_data(symbol, kline)
                
                # 如果K线已关闭，分析趋势
                if kline['x']:  # K线已关闭
                    trend = self._analyze_trend(symbol)
                    if trend and self.on_trend_update:
                        self.on_trend_update(symbol, trend)
                        
        except Exception as e:
            trading_logger.error(f"处理WebSocket消息异常: {str(e)}", exc_info=True)
            
    def _on_error(self, ws, error):
        """处理WebSocket错误"""
        trading_logger.error(f"WebSocket错误: {str(error)}")
        
    def _on_close(self, ws, close_status_code, close_msg):
        """处理WebSocket关闭"""
        trading_logger.info(f"WebSocket连接关闭: {close_status_code} - {close_msg}")
        
    def _on_open(self, ws):
        """处理WebSocket连接打开"""
        trading_logger.info("WebSocket连接已建立")
        if self.subscribe_message:
            ws.send(json.dumps(self.subscribe_message))
            trading_logger.info(f"已订阅 {len(self.subscribe_message['params'])} 个交易对的K线数据")
            
    def _update_kline_data(self, symbol: str, kline: dict):
        """更新K线数据"""
        try:
            if symbol not in self.kline_data:
                self.kline_data[symbol] = []
                
            # 添加新的K线数据
            self.kline_data[symbol].append({
                'timestamp': kline['t'],
                'open': float(kline['o']),
                'high': float(kline['h']),
                'low': float(kline['l']),
                'close': float(kline['c']),
                'volume': float(kline['v'])
            })
            
            # 保持数据量在合理范围内
            if len(self.kline_data[symbol]) > 100:
                self.kline_data[symbol] = self.kline_data[symbol][-100:]
                
        except Exception as e:
            trading_logger.error(f"更新K线数据异常: {str(e)}", exc_info=True)
            
    def _analyze_trend(self, symbol: str) -> Optional[Dict]:
        """
        分析趋势
        
        Args:
            symbol: 交易对符号
            
        Returns:
            趋势分析结果，包含以下字段：
            - direction: 趋势方向 ('up' 或 'down')
            - strength: 趋势强度 (0-100)
            - price_change: 价格变化百分比
            - volume_change: 成交量变化百分比
        """
        try:
            if symbol not in self.kline_data or len(self.kline_data[symbol]) < 2:
                return None
                
            # 获取最近两根K线
            current_kline = self.kline_data[symbol][-1]
            previous_kline = self.kline_data[symbol][-2]
            
            # 计算价格变化
            price_change = (current_kline['close'] - previous_kline['close']) / previous_kline['close'] * 100
            
            # 计算成交量变化
            volume_change = (current_kline['volume'] - previous_kline['volume']) / previous_kline['volume'] * 100 if previous_kline['volume'] > 0 else 0
            
            # 判断趋势方向
            direction = 'up' if price_change > 0 else 'down'
            
            # 计算趋势强度 (基于价格变化和成交量变化的综合评分)
            strength = min(100, abs(price_change) * self.price_weight + abs(volume_change) * self.volume_weight)
            
            return {
                'direction': direction,
                'strength': strength,
                'price_change': price_change,
                'volume_change': volume_change
            }
            
        except Exception as e:
            trading_logger.error(f"分析趋势异常: {str(e)}", exc_info=True)
            return None 