import logging
import os
from datetime import datetime

# 创建日志目录
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 获取一个日志记录器实例
trading_logger = logging.getLogger('trading')

def setup_logging(level_name_str: str = "INFO", 
                  log_to_console: bool = True, 
                  log_to_file: bool = True,
                  third_party_level_str: str = "WARNING"):
    """
    配置 trading_logger 以及可选的第三方库日志级别。
    
    Args:
        level_name_str: trading_logger 的目标日志级别 (例如 "INFO", "DEBUG", "WARNING").
        log_to_console: 是否输出日志到控制台.
        log_to_file: 是否输出日志到文件.
        third_party_level_str: 其他库 (如 websockets, asyncio) 的日志级别.
    """
    try:
        # 将字符串级别转换为 logging 模块的常量
        numeric_level = getattr(logging, level_name_str.upper(), None)
        if not isinstance(numeric_level, int):
            print(f"Warning: Invalid log level string: {level_name_str}. Defaulting to INFO.")
            numeric_level = logging.INFO
        
        third_party_numeric_level = getattr(logging, third_party_level_str.upper(), None)
        if not isinstance(third_party_numeric_level, int):
            print(f"Warning: Invalid third_party_level string: {third_party_level_str}. Defaulting to WARNING.")
            third_party_numeric_level = logging.WARNING

        # 设置 trading_logger 的级别
        trading_logger.setLevel(numeric_level)
        
        # 清除旧的 handlers，以防重复添加 (如果此函数可能被多次调用)
        # for handler in trading_logger.handlers[:]:
        #     trading_logger.removeHandler(handler)

        # 设置日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)' # 更详细的格式
        )

        if log_to_file:
            # 创建文件处理器
            log_file_path = os.path.join(log_dir, f'trading_{datetime.now().strftime("%Y%m%d")}.log')
            file_handler = logging.FileHandler(log_file_path)
            file_handler.setLevel(numeric_level) # 文件处理器也使用配置的级别
            file_handler.setFormatter(formatter)
            if not any(isinstance(h, logging.FileHandler) for h in trading_logger.handlers): # 避免重复添加
                 trading_logger.addHandler(file_handler)

        if log_to_console:
            # 创建控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(numeric_level) # 控制台处理器也使用配置的级别
            console_handler.setFormatter(formatter)
            if not any(isinstance(h, logging.StreamHandler) for h in trading_logger.handlers): # 避免重复添加
                trading_logger.addHandler(console_handler)
        
        # 如果没有启用任何 handler，至少添加一个 NullHandler 以避免 "No handlers could be found" 警告
        if not trading_logger.handlers:
            trading_logger.addHandler(logging.NullHandler())
            print("Warning: No log handlers (console or file) were configured for trading_logger.")

        # 设置其他常用库的日志记录器的级别
        logging.getLogger('websockets').setLevel(third_party_numeric_level)
        logging.getLogger('asyncio').setLevel(third_party_numeric_level)
        
        trading_logger.info(f"Trading logger initialized with level: {level_name_str.upper()}")
        trading_logger.info(f"Third-party loggers (e.g., websockets, asyncio) set to level: {third_party_level_str.upper()}")

    except Exception as e:
        print(f"Error during logging setup: {e}")
        # Fallback to basic config if setup fails catastrophically
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logging.error("Fell back to basicConfig due to logging setup error.", exc_info=True)

# 默认情况下，不进行配置，等待 setup_logging 被调用
# 这可以防止在导入时就固定了 DEBUG 级别

# 如果希望在没有显式调用 setup_logging 时有一个非常基础的回退 (不推荐，最好由主程序控制初始化)
# if not trading_logger.handlers:
#    setup_logging() # 调用一次默认设置，确保至少有 handler

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