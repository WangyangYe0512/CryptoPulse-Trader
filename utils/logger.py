import logging
import os
from datetime import datetime

# 创建日志目录
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 设置日志格式
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 创建文件处理器
log_file = os.path.join(log_dir, f'trading_{datetime.now().strftime("%Y%m%d")}.log')
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# 创建日志记录器
trading_logger = logging.getLogger('trading')
trading_logger.setLevel(logging.DEBUG)
trading_logger.addHandler(file_handler)
trading_logger.addHandler(console_handler)

# 设置其他日志记录器的级别
logging.getLogger('websockets').setLevel(logging.DEBUG)
logging.getLogger('asyncio').setLevel(logging.DEBUG) 