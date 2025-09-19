# 兼容 freqtrade 枚举类型
from enum import Enum


class RPCMessageType(Enum):
    STATUS = 'status'
    WARNING = 'warning'
    STARTUP = 'startup'
    ENTRY = 'entry'
    ENTRY_FILL = 'entry_fill'
    ENTRY_CANCEL = 'entry_cancel'
    EXIT = 'exit'
    EXIT_FILL = 'exit_fill'
    EXIT_CANCEL = 'exit_cancel'
    PROTECTION_TRIGGER = 'protection_trigger'
    PROTECTION_TRIGGER_GLOBAL = 'protection_trigger_global'
    STRATEGY_MSG = 'strategy_msg'
    WHITELIST = 'whitelist'
    ANALYZED_DF = 'analyzed_df'
    NEW_CANDLE = 'new_candle'
    EXCEPTION = 'exception'


class MarketDirection(Enum):
    NONE = 'none'
    LONG = 'long'
    SHORT = 'short'
    EVEN = 'even'


class SignalDirection(Enum):
    LONG = 'long'
    SHORT = 'short'


class TradingMode(Enum):
    SPOT = 'spot'
    MARGIN = 'margin'
    FUTURES = 'futures'


class State(Enum):
    RUNNING = 'running'
    STOPPED = 'stopped'
    RELOAD_CONFIG = 'reload_config'