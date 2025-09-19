# 兼容 freqtrade 工具函数
from datetime import datetime, timezone
from typing import Any, List


def chunks(lst: List[Any], n: int) -> List[List[Any]]:
    """将列表分成 n 个元素的块"""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def plural(count: int, singular: str, plural_form: str = None) -> str:
    """返回单数或复数形式"""
    if plural_form is None:
        plural_form = singular + 's'
    return singular if count == 1 else plural_form


def dt_from_ts(timestamp: float) -> datetime:
    """从时间戳创建 datetime"""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def dt_humanize_delta(dt: datetime) -> str:
    """人性化时间差显示"""
    now = datetime.now(timezone.utc)
    delta = now - dt
    
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"


def fmt_coin(amount: float, coin: str, show_coin_name: bool = True) -> str:
    """格式化币种数量"""
    if show_coin_name:
        return f"{amount:.8f} {coin}"
    return f"{amount:.8f}"


def fmt_coin2(amount: float, coin: str) -> str:
    """格式化币种数量 (备用格式)"""
    return fmt_coin(amount, coin)


def format_date(date: datetime) -> str:
    """格式化日期"""
    return date.strftime('%Y-%m-%d %H:%M:%S')


def round_value(value: float, decimals: int = 8) -> float:
    """四舍五入数值"""
    return round(value, decimals)