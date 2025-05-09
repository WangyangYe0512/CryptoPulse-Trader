import os
from typing import Dict, Any, Optional
import yaml
from dotenv import load_dotenv
from utils.logger import trading_logger

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: str = 'config/config.yaml'):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.load_config()
        
    def load_config(self):
        """加载配置文件"""
        try:
            load_dotenv() 
            
            default_config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    default_config = yaml.safe_load(f) or {}
            else:
                trading_logger.warning(f"配置文件不存在: {self.config_path}, 将使用环境变量或硬编码的默认值。")
            
            self.config = default_config
            self._override_with_env_vars() # New method to handle overrides
            
        except Exception as e:
            trading_logger.error(f"加载配置失败: {str(e)}", exc_info=True)
            self.config = {} # Fallback to empty config on error

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
        self._set_env_var(['trading', 'per_order_size_usdt'], 'PER_ORDER_SIZE_USDT', 100.0, float) # New/Renamed
        self._set_env_var(['trading', 'max_orders_per_symbol'], 'MAX_ORDERS_PER_SYMBOL', 3, int)
        self._set_env_var(['trading', 'max_active_symbols'], 'MAX_ACTIVE_SYMBOLS', 5, int)
        self._set_env_var(['trading', 'add_position_interval'], 'ADD_POSITION_INTERVAL_MINUTES', 30, int) # Renamed from ADD_POSITION_INTERVAL
        self._set_env_var(['trading', 'max_daily_loss_percent'], 'MAX_DAILY_LOSS_PERCENT', 5.0, float)
        self._set_env_var(['trading', 'max_holding_time_minutes'], 'MAX_HOLDING_TIME_MINUTES', 60, int)
        self._set_env_var(['trading', 'stop_loss_percent'], 'STOP_LOSS_PERCENT', 1.0, float)
        self._set_env_var(['trading', 'take_profit_percent'], 'TAKE_PROFIT_PERCENT', 2.0, float)
        self._set_env_var(['trading', 'check_interval_seconds'], 'CHECK_INTERVAL_SECONDS', 60, int)

        # Notification config
        self._set_env_var(['notification', 'telegram_enabled'], 'TELEGRAM_ENABLED', 'true', lambda v: v.lower() == 'true')
        self._set_env_var(['notification', 'telegram_token'], 'TELEGRAM_BOT_TOKEN', '')
        self._set_env_var(['notification', 'telegram_chat_id'], 'TELEGRAM_CHAT_ID', '')
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
            
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值 (e.g., 'trading.per_order_size_usdt')
        """
        try:
            keys = key.split('.')
            value = self.config
            for k in keys:
                value = value[k]
            return value
        except KeyError: # More specific exception
            # trading_logger.debug(f"配置键 '{key}' 未找到，返回默认值: {default}")
            return default
        except TypeError: # If a path component is not a dict (e.g. config['api'] is a string but trying to get config['api']['binance'])
            # trading_logger.debug(f"配置路径类型错误，键 '{key}' 的某个父级不是字典，返回默认值: {default}")
            return default
            
    def set(self, key: str, value: Any):
        """
        设置配置值 (主要用于测试或动态修改，不保存到文件)
        """
        try:
            keys = key.split('.')
            current_level = self._ensure_path(keys)
            if current_level is not None:
                 current_level[keys[-1]] = value
        except Exception as e:
            trading_logger.error(f"设置配置失败 ({key}): {str(e)}", exc_info=True)
            
    # save and reload methods are not strictly necessary if we primarily rely on init loading
    # but can be useful for advanced scenarios or if config file is edited at runtime.
    def save_to_yaml(self, path: Optional[str] = None):
        """将当前配置保存到指定的YAML文件 (主要用于调试或生成模板)"""
        save_path = path or self.config_path
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'w') as f:
                yaml.dump(self.config, f, sort_keys=False)
            trading_logger.info(f"配置已保存到 {save_path}")
        except Exception as e:
            trading_logger.error(f"保存配置到 {save_path} 失败: {str(e)}", exc_info=True)
            
    def reload(self):
        """重新加载配置文件和环境变量"""
        trading_logger.info(f"重新加载配置自 {self.config_path} 和环境变量...")
        self.load_config()
        
    def get_all(self) -> Dict[str, Any]:
        return self.config.copy() 