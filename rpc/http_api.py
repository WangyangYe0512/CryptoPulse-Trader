#!/usr/bin/env python3
"""
HTTP API for RPC Commands
提供HTTP接口来调用RPC命令，支持外部系统控制交易状态
"""

import json
from typing import Dict, Any
from datetime import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

from utils.logger import trading_logger

logger = trading_logger


class RPCAPIHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""
    
    def __init__(self, rpc_instance, *args, **kwargs):
        self.rpc = rpc_instance
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """处理GET请求"""
        try:
            # 解析URL路径
            parsed_path = urllib.parse.urlparse(self.path)
            path = parsed_path.path
            query_params = urllib.parse.parse_qs(parsed_path.query)
            
            # 路由处理
            if path == '/api/status':
                self._handle_status()
            elif path == '/api/start':
                self._handle_start()
            elif path == '/api/pause':
                self._handle_pause()
            elif path == '/api/stop':
                self._handle_stop()
            elif path == '/api/health':
                self._handle_health()
            else:
                self._send_error_response(404, "Not Found")
                
        except Exception as e:
            logger.error(f"HTTP API error: {e}", exc_info=True)
            self._send_error_response(500, f"Internal Server Error: {str(e)}")
    
    def do_POST(self):
        """处理POST请求"""
        try:
            # 解析URL路径
            parsed_path = urllib.parse.urlparse(self.path)
            path = parsed_path.path
            
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            # 解析JSON数据
            request_data = {}
            if post_data:
                try:
                    request_data = json.loads(post_data.decode('utf-8'))
                except json.JSONDecodeError:
                    self._send_error_response(400, "Invalid JSON")
                    return
            
            # 路由处理
            if path == '/api/start':
                self._handle_start_post(request_data)
            elif path == '/api/pause':
                self._handle_pause_post(request_data)
            elif path == '/api/stop':
                self._handle_stop_post(request_data)
            else:
                self._send_error_response(404, "Not Found")
                
        except Exception as e:
            logger.error(f"HTTP API POST error: {e}", exc_info=True)
            self._send_error_response(500, f"Internal Server Error: {str(e)}")
    
    def _handle_status(self):
        """处理状态查询"""
        try:
            if hasattr(self.rpc, '_rpc_status'):
                status_data = self.rpc._rpc_status()
            else:
                status_data = {'status': 'unknown', 'state': 'unknown'}
            
            self._send_json_response(200, {
                'success': True,
                'data': status_data,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            self._send_error_response(500, f"Failed to get status: {str(e)}")
    
    def _handle_start(self):
        """处理启动命令（GET）"""
        self._execute_rpc_command('start', 'Starting trader...')
    
    def _handle_start_post(self, request_data: Dict[str, Any]):
        """处理启动命令（POST）"""
        self._execute_rpc_command('start', 'Starting trader...', request_data)
    
    def _handle_pause(self):
        """处理暂停命令（GET）"""
        self._execute_rpc_command('pause', 'Pausing trader...')
    
    def _handle_pause_post(self, request_data: Dict[str, Any]):
        """处理暂停命令（POST）"""
        self._execute_rpc_command('pause', 'Pausing trader...', request_data)
    
    def _handle_stop(self):
        """处理停止命令（GET）"""
        self._execute_rpc_command('stop', 'Stopping trader...')
    
    def _handle_stop_post(self, request_data: Dict[str, Any]):
        """处理停止命令（POST）"""
        self._execute_rpc_command('stop', 'Stopping trader...', request_data)
    
    def _handle_health(self):
        """处理健康检查"""
        self._send_json_response(200, {
            'success': True,
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'CryptoPulse Trader HTTP API'
        })
    
    def _execute_rpc_command(self, command: str, description: str, request_data: Dict[str, Any] = None):
        """执行RPC命令"""
        try:
            # 获取RPC方法
            rpc_method = getattr(self.rpc, f'_rpc_{command}', None)
            if not rpc_method:
                self._send_error_response(404, f"Command '{command}' not found")
                return
            
            # 执行命令
            result = rpc_method()
            
            # 记录操作日志
            logger.info(f"HTTP API: {command} command executed via HTTP")
            
            # 返回结果
            self._send_json_response(200, {
                'success': True,
                'command': command,
                'description': description,
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"HTTP API: Failed to execute {command}: {e}", exc_info=True)
            self._send_error_response(500, f"Failed to execute {command}: {str(e)}")
    
    def _send_json_response(self, status_code: int, data: Dict[str, Any]):
        """发送JSON响应"""
        response_data = json.dumps(data, ensure_ascii=False, indent=2)
        
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
        self.wfile.write(response_data.encode('utf-8'))
    
    def _send_error_response(self, status_code: int, message: str):
        """发送错误响应"""
        self._send_json_response(status_code, {
            'success': False,
            'error': message,
            'timestamp': datetime.now().isoformat()
        })
    
    def log_message(self, format, *args):
        """重写日志方法，使用我们的logger"""
        logger.debug(f"HTTP API: {format % args}")


class RPCAPIServer:
    """RPC HTTP API服务器"""
    
    def __init__(self, rpc_instance, host: str = 'localhost', port: int = 8080):
        self.rpc = rpc_instance
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.is_running = False
        
        logger.info(f"RPC HTTP API server initialized: {host}:{port}")
    
    def start(self):
        """启动HTTP服务器"""
        if self.is_running:
            logger.warning("HTTP API server is already running")
            return
        
        try:
            # 创建自定义处理器
            def handler(*args, **kwargs):
                return RPCAPIHandler(self.rpc, *args, **kwargs)
            
            # 创建HTTP服务器
            self.server = HTTPServer((self.host, self.port), handler)
            
            # 在单独线程中启动服务器
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            self.is_running = True
            logger.info(f"RPC HTTP API server started on http://{self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start HTTP API server: {e}", exc_info=True)
            raise
    
    def _run_server(self):
        """运行服务器（在单独线程中）"""
        try:
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP API server error: {e}", exc_info=True)
        finally:
            self.is_running = False
    
    def stop(self):
        """停止HTTP服务器"""
        if not self.is_running:
            return
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=5)
            
            self.is_running = False
            logger.info("RPC HTTP API server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping HTTP API server: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        return {
            'is_running': self.is_running,
            'host': self.host,
            'port': self.port,
            'endpoints': [
                'GET /api/status - 获取交易状态',
                'GET /api/start - 启动交易',
                'GET /api/pause - 暂停交易',
                'GET /api/stop - 停止交易',
                'GET /api/health - 健康检查',
                'POST /api/start - 启动交易（带参数）',
                'POST /api/pause - 暂停交易（带参数）',
                'POST /api/stop - 停止交易（带参数）'
            ]
        }


def create_rpc_api_server(rpc_instance, host: str = 'localhost', port: int = 8080) -> RPCAPIServer:
    """创建RPC HTTP API服务器实例"""
    return RPCAPIServer(rpc_instance, host, port)
