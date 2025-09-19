# 兼容 freqtrade 异常类


class OperationalException(Exception):
    """运营异常"""
    pass


class RPCException(Exception):
    """RPC异常"""
    pass