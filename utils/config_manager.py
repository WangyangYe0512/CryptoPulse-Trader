import os
from typing import Dict, Any
import yaml
from dotenv import load_dotenv
from utils.logger import trading_logger

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str = 'config/config.yaml'):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = {}
        self.logger = trading_logger  # 添加logger属性
        
        # 加载.env文件
        load_dotenv()
        
        # 加载配置文件
        self._load_config()
        
    def _load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r') as f:
                self.config = yaml.safe_load(f)
                
            # 添加环境变量中的敏感信息
            self.config['api'] = {
                'binance': {
                    'api_key': os.getenv('BINANCE_API_KEY'),
                    'api_secret': os.getenv('BINANCE_API_SECRET')
                },
                'coingecko': {
                    'api_key': os.getenv('COINGECKO_API_KEY')
                }
            }
            
            # 初始化通知配置
            if 'notification' not in self.config:
                self.config['notification'] = {}
            
            # 确保telegram配置存在
            if 'telegram' not in self.config['notification']:
                self.config['notification']['telegram'] = {}
            
            # 设置Telegram配置 - 敏感信息从环境变量读取
            telegram_config = self.config['notification']['telegram']
            telegram_config.update({
                'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
                'chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
            })
            
            # 功能开关从config.yaml读取，如果没有则设置默认值
            if 'enabled' not in telegram_config:
                telegram_config['enabled'] = True
            if 'trade_notifications' not in telegram_config:
                telegram_config['trade_notifications'] = True
            if 'error_notifications' not in telegram_config:
                telegram_config['error_notifications'] = True
            if 'status_notifications' not in telegram_config:
                telegram_config['status_notifications'] = True
            if 'commands_enabled' not in telegram_config:
                telegram_config['commands_enabled'] = True
            
            # 应用环境变量覆盖
            self._override_with_env_vars()
            
            trading_logger.info("配置加载成功")
            
        except Exception as e:
            trading_logger.error(f"加载配置文件失败: {str(e)}", exc_info=True)
            raise
            
    def get(self, key: str, default=None):
        """
        获取配置项
        
        Args:
            key: 配置项键名，支持点号分隔的多级键名
            default: 默认值
            
        Returns:
            配置项值
        """
        try:
            value = self.config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
            
    def set(self, key: str, value):
        """
        设置配置项
        
        Args:
            key: 配置项键名，支持点号分隔的多级键名
            value: 配置项值
        """
        try:
            keys = key.split('.')
            target = self.config
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = value
        except Exception as e:
            trading_logger.error(f"设置配置项失败: {str(e)}", exc_info=True)
            raise
            
    def save(self):
        """保存配置到文件"""
        try:
            # 创建配置的副本，移除敏感信息
            config_copy = self.config.copy()
            if 'api' in config_copy:
                del config_copy['api']
                
            with open(self.config_file, 'w') as f:
                yaml.dump(config_copy, f, default_flow_style=False)
                
            trading_logger.info("配置保存成功")
            
        except Exception as e:
            trading_logger.error(f"保存配置文件失败: {str(e)}", exc_info=True)
            raise
    
    def get_telegram_config(self) -> dict:
        """获取 Telegram 配置"""
        return self.config.get('notification', {}).get('telegram', {})

    def _ensure_path(self, keys: list):
        """Ensures the path exists in the config dict, creating it if necessary."""
        current_level = self.config
        for key in keys[:-1]:
            current_level = current_level.setdefault(key, {})
            if not isinstance(current_level, dict):
                # This case should ideally not happen if config structure is consistent
                # Or if an env var tries to set a sub-key where a non-dict value already exists
                trading_logger.error(f"配置路径冲突: {key} 不是一个字典，无法设置子键。")
                return None # Indicates an issue
        return current_level

    def _set_env_var(self, keys: list, env_var_name: str, default_value: Any, type_converter: type = str):
        """Helper to set config value from environment variable."""
        env_value = os.getenv(env_var_name)
        # trading_logger.debug(f"Checking env var: {env_var_name}, value: {env_value}")
        if env_value is not None:
            try:
                typed_value = type_converter(env_value)
                current_level = self._ensure_path(keys)
                if current_level is not None:
                    current_level[keys[-1]] = typed_value
                    # trading_logger.debug(f"Config overridden by env: {'.'.join(keys)} = {typed_value}")
            except ValueError as e:
                trading_logger.warning(
                    f"无法转换环境变量 {env_var_name} ('{env_value}') 为类型 {type_converter.__name__}: {e}. "
                    f"将使用yaml中定义的值或默认值 (如果未在yaml中定义则为 {default_value})."
                )
        # If env_value is None, the value from yaml (or its default if not in yaml) remains.
        # If not in yaml either, get() method will use its own passed default.

    def _override_with_env_vars(self):
        """用环境变量中的值覆盖从YAML加载的配置。
           环境变量的命名应遵循一定的约定，例如 UPPER_CASE_WITH_UNDERSCORES。
           这里我们将环境变量映射到配置字典中的路径。
        """
        # API config
        self._set_env_var(['api', 'binance', 'api_key'], 'BINANCE_API_KEY', '')
        self._set_env_var(['api', 'binance', 'api_secret'], 'BINANCE_API_SECRET', '')
        self._set_env_var(['api', 'binance', 'testnet'], 'BINANCE_TESTNET', 'true', lambda v: v.lower() == 'true')

        # Telegram config - 只覆盖敏感信息
        self._set_env_var(['notification', 'telegram', 'bot_token'], 'TELEGRAM_BOT_TOKEN', '')
        self._set_env_var(['notification', 'telegram', 'chat_id'], 'TELEGRAM_CHAT_ID', '')

        # Scanner config
        self._set_env_var(['scanner', 'scan_interval'], 'SCAN_INTERVAL_SECONDS', 3600, int)
        self._set_env_var(['scanner', 'volatility_timeframe'], 'VOLATILITY_TIMEFRAME', '1h')
        self._set_env_var(['scanner', 'volatility_ohlcv_limit'], 'VOLATILITY_OHLCV_LIMIT', 2, int)
        self._set_env_var(['scanner', 'max_candidates'], 'MAX_CANDIDATES', 15, int)
        self._set_env_var(['scanner', 'min_volume_usdt'], 'MIN_VOLUME_USDT', 1000000, float)
        self._set_env_var(['scanner', 'max_liquidity_candidates'], 'MAX_LIQUIDITY_CANDIDATES', 5, int)

        # Trend config
        self._set_env_var(['trend', 'analysis_timeframe'], 'TREND_ANALYSIS_TIMEFRAME', '1m')
        self._set_env_var(['trend', 'lookback_periods'], 'TREND_LOOKBACK_PERIODS', 5, int)
        self._set_env_var(['trend', 'confirmation_periods'], 'TREND_CONFIRMATION_PERIODS', 3, int)
        self._set_env_var(['trend', 'min_slope_percent'], 'TREND_MIN_SLOPE_PERCENT', 0.5, float)

        # Trading config
        self._set_env_var(['trading', 'market_type'], 'MARKET_TYPE', 'spot', str)
        self._set_env_var(['trading', 'per_order_size_usdt'], 'PER_ORDER_SIZE_USDT', 100.0, float)
        self._set_env_var(['trading', 'max_orders_per_symbol'], 'MAX_ORDERS_PER_SYMBOL', 3, int)
        self._set_env_var(['trading', 'max_active_symbols'], 'MAX_ACTIVE_SYMBOLS', 5, int)
        self._set_env_var(['trading', 'add_position_interval'], 'ADD_POSITION_INTERVAL_MINUTES', 30, int)
        self._set_env_var(['trading', 'max_daily_loss_percent'], 'MAX_DAILY_LOSS_PERCENT', 5.0, float)
        self._set_env_var(['trading', 'max_holding_time_minutes'], 'MAX_HOLDING_TIME_MINUTES', 60, int)
        self._set_env_var(['trading', 'stop_loss_percent'], 'STOP_LOSS_PERCENT', 1.0, float)
        self._set_env_var(['trading', 'take_profit_percent'], 'TAKE_PROFIT_PERCENT', 2.0, float)
        self._set_env_var(['trading', 'check_interval_seconds'], 'CHECK_INTERVAL_SECONDS', 60, int)

        # Notification config
        self._set_env_var(['notification', 'notify_on_trade'], 'NOTIFY_ON_TRADE', 'true', lambda v: v.lower() == 'true')
        self._set_env_var(['notification', 'notify_on_error'], 'NOTIFY_ON_ERROR', 'true', lambda v: v.lower() == 'true')
        self._set_env_var(['notification', 'notify_on_status'], 'NOTIFY_ON_STATUS', 'true', lambda v: v.lower() == 'true')

        # Logging config
        self._set_env_var(['logging', 'level'], 'LOG_LEVEL', 'INFO')
        self._set_env_var(['logging', 'file'], 'LOG_FILE', 'logs/trading.log')
        
        # Database config (SQLite)
        self._set_env_var(['database', 'enabled'], 'DB_ENABLED', 'false', lambda v: v.lower() == 'true')
        self._set_env_var(['database', 'type'], 'DB_TYPE', 'sqlite')
        self._set_env_var(['database', 'path'], 'DB_PATH', 'data/')
        self._set_env_var(['database', 'filename'], 'DB_FILENAME', 'trading_data.sqlite')
            
    def get_all(self) -> Dict[str, Any]:
        return self.config.copy() 