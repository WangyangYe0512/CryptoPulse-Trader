"""
增强的 Telegram 集成 - 使用 CPT-RPC 桥接器
集成 freqtrade 风格的 Telegram 功能与 CryptoPulse Trader
"""

from typing import Dict, Any, Optional, List
import os
import time
from datetime import datetime, timezone, timedelta

from rpc.simple_rpc import RPC
from rpc.telegram import Telegram
from rpc.cpt_bridge import CPTRPCBridge
from utils.config_manager import ConfigManager
from utils.logger import trading_logger


class EnhancedTelegramIntegration:
    """增强的 Telegram 集成类"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.config = self._prepare_config()
        
        # 创建 CPT-RPC 桥接器
        self.bridge = CPTRPCBridge(config_manager)
        
        # 创建 RPC 实例
        self.rpc = RPC(self.config)
        
        # 创建 Telegram 实例
        self.telegram: Optional[Telegram] = None
        self._setup_telegram()
        
        # 运行状态
        self.is_running = False
        # 共享的 CCXT 客户端（公有/私有），避免每次命令创建造成延迟
        self._pub_exchange = None
        self._priv_exchange = None
        # 短缓存：行情价格缓存，降低 /status table 调用延迟
        self._price_cache: Dict[str, Dict[str, float]] = {}
        self._price_cache_ttl_seconds: float = 2.0
        # 持仓同步缓存，避免频繁调用交易所 API
        self._positions_cache: Dict[str, Any] = {}
        self._positions_cache_ttl_seconds: float = 5.0
        # 账户余额缓存，避免频繁调用余额 API
        self._balance_cache: Dict[str, Any] = {}
        self._balance_cache_ttl_seconds: float = 10.0
        
        trading_logger.info("增强 Telegram 集成已初始化")
    
    def _prepare_config(self) -> Dict[str, Any]:
        """准备 freqtrade 格式的配置"""
        telegram_config = self.config_manager.get_telegram_config()
        
        if not telegram_config.get('enabled', False):
            return {}
            
        return {
            'telegram': {
                'enabled': True,
                'token': telegram_config.get('bot_token', ''),
                'chat_id': telegram_config.get('chat_id', ''),
                'keyboard': [
                    ["/daily", "/profit", "/balance"],
                    ["/status", "/count", "/performance"], 
                    ["/trades", "/stats", "/weekly"],
                    ["/start", "/stop", "/help"]
                ],
                'notification_settings': {
                    'status': 'on',
                    'warning': 'on',
                    'startup': 'on',
                    'entry': 'on',
                    'entry_fill': 'on',
                    'exit': 'on',
                    'exit_fill': 'on',
                    'protection_trigger': 'on',
                    'strategy_msg': 'on',
                }
            },
            'dry_run': self.config_manager.get('api.binance.testnet', False),
            'stake_currency': 'USDT',
            'fiat_display_currency': 'USD',
            'stake_amount': self.config_manager.get('strategy.trend_following.position_size_usdt', 25.0),
            'max_open_trades': self.config_manager.get('risk.max_open_positions', 10),
            'strategy': 'CryptoPulseTrend',
            'exchange': {
                'name': 'binance'
            },
            'trading_mode': 'futures',
            'margin_mode': 'isolated'
        }
    
    def _setup_telegram(self):
        """设置 Telegram"""
        if not self.config.get('telegram', {}).get('enabled'):
            trading_logger.info("Telegram 未启用")
            return
            
        try:
            # 使用 RPC 的方法替换默认实现
            self._patch_rpc_methods()
            
            self.telegram = Telegram(self.rpc, self.config)
            trading_logger.info("增强 Telegram 机器人已初始化")
        except Exception as e:
            trading_logger.error(f"Telegram 初始化失败: {e}", exc_info=True)
    
    # =============== 交易所辅助 ===============
    def _get_public_exchange(self):
        try:
            if self._pub_exchange:
                return self._pub_exchange
            import ccxt
            ex = ccxt.binance({
                'enableRateLimit': True,
                'timeout': 10000,
                'options': {
                    'defaultType': 'future',
                    'recvWindow': 10000,
                }
            })
            if self.config_manager.get('api.binance.testnet', False):
                ex.set_sandbox_mode(True)
            self._pub_exchange = ex
            return ex
        except Exception:
            return None

    def _get_private_exchange(self):
        try:
            if self._priv_exchange:
                return self._priv_exchange
            import ccxt
            api_key = os.getenv('BINANCE_API_KEY')
            # 兼容两种环境变量名
            api_secret = os.getenv('BINANCE_API_SECRET') or os.getenv('BINANCE_SECRET_KEY')
            if not api_key or not api_secret:
                return None
            ex = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'timeout': 15000,
                'options': {
                    'defaultType': 'future',
                    'recvWindow': 10000,
                }
            })
            testnet_mode = self.config_manager.get('api.binance.testnet', False)
            if testnet_mode:
                ex.set_sandbox_mode(True)
            self._priv_exchange = ex
            return ex
        except Exception:
            return None

    def _get_current_prices_for_symbols(self, symbols: List[str]) -> Dict[str, float]:
        """获取一批合约符号的最新价格，带 2 秒短缓存。符号格式示例：'BTC/USDT:USDT'。
        """
        result: Dict[str, float] = {}
        if not symbols:
            return result

        exchange = self._get_public_exchange()
        if not exchange:
            return result

        now = time.time()
        unique_symbols = list({s for s in symbols if isinstance(s, str) and s})

        # 找出需要刷新报价的符号
        to_fetch: List[str] = []
        for sym in unique_symbols:
            ce = self._price_cache.get(sym)
            if not ce or (now - ce.get('ts', 0)) > self._price_cache_ttl_seconds:
                to_fetch.append(sym)

        # 批量获取可用的报价
        if to_fetch:
            try:
                # 优化：限制单次批量查询数量，避免超时
                batch_size = 20  # 单次最多查询20个符号
                for i in range(0, len(to_fetch), batch_size):
                    batch = to_fetch[i:i + batch_size]
                    try:
                        tickers = exchange.fetch_tickers(symbols=batch)
                        for sym, tk in (tickers or {}).items():
                            last = tk.get('last') or (tk.get('info', {}).get('lastPrice') if isinstance(tk.get('info'), dict) else None)
                            if last is not None:
                                self._price_cache[sym] = {'price': float(last), 'ts': now}
                    except Exception:
                        # 批量失败时回退到逐个查询
                        for sym in batch:
                            try:
                                tk = exchange.fetch_ticker(sym)
                                last = tk.get('last') or (tk.get('info', {}).get('lastPrice') if isinstance(tk.get('info'), dict) else None)
                                if last is not None:
                                    self._price_cache[sym] = {'price': float(last), 'ts': now}
                            except Exception:
                                # 单个失败忽略
                                pass
            except Exception:
                # 全部失败的回退
                pass

        # 组装结果（命中缓存 + 刷新后的）
        for sym in unique_symbols:
            ce = self._price_cache.get(sym)
            if ce and 'price' in ce:
                result[sym] = ce['price']

        return result

    def _sync_bridge_with_exchange_positions(self):
        """将交易所当前持仓同步到桥接器，以便 /status table 能显示历史持仓。"""
        # 同步持仓数据
        try:
            # 检查持仓缓存
            now = time.time()
            cache_entry = self._positions_cache.get('positions')
            if cache_entry and (now - cache_entry.get('ts', 0)) <= self._positions_cache_ttl_seconds:
                positions = cache_entry['data']
                # 使用缓存的持仓数据
            else:
                # 缓存过期或不存在，重新获取
                ex = self._get_private_exchange()
                if not ex:
                    # 无法获取交易所客户端
                    return
                
                # 获取交易所持仓
                
                # 获取期货持仓
                try:
                    # 直接调用期货API，避免 fetch_positions() 的问题
                    raw_positions = ex.fapiPrivateV2GetPositionRisk()
                    # 处理原始持仓数据
                    
                    # 转换为标准格式
                    positions = []
                    for pos in raw_positions:
                        if float(pos.get('positionAmt', 0)) != 0:
                                # 记录有效持仓
                            symbol = pos.get('symbol', '')
                            # 转换为 CCXT 格式: BTCUSDT -> BTC/USDT:USDT
                            if symbol and symbol.endswith('USDT'):
                                base = symbol[:-4]  # 移除 USDT
                                ccxt_symbol = f"{base}/USDT:USDT"
                            else:
                                ccxt_symbol = symbol
                            
                            position = {
                                'symbol': ccxt_symbol,
                                'contracts': float(pos.get('positionAmt', 0)),
                                'entryPrice': float(pos.get('entryPrice', 0)),
                                'leverage': float(pos.get('leverage', 1)),
                                'side': 'long' if float(pos.get('positionAmt', 0)) > 0 else 'short',
                                'info': pos
                            }
                            positions.append(position)
                    
                    # 更新缓存
                    self._positions_cache['positions'] = {'data': positions, 'ts': now}
                    
                except Exception:
                    # 使用空列表避免卡住
                    positions = []
                    # 缓存空结果（短时间）
                    self._positions_cache['positions'] = {'data': positions, 'ts': now}
            
            if not positions:
                return
            for p in positions:
                try:
                    contracts = float(p.get('contracts', 0) or p.get('info', {}).get('positionAmt', 0))
                    if contracts == 0:
                        continue
                    symbol = p.get('symbol') or p.get('info', {}).get('symbol')
                    if not symbol:
                        continue
                    # CCXT binance futures symbol usually like 'BTC/USDT:USDT'
                    entry_price = float(p.get('entryPrice') or p.get('info', {}).get('entryPrice') or 0)
                    leverage = float(p.get('leverage') or p.get('info', {}).get('leverage') or 1)
                    side = p.get('side') or p.get('info', {}).get('positionSide') or 'LONG'
                    is_long = (str(side).upper() == 'LONG') or (str(side).lower() == 'long') or (str(side).lower() == 'both' and contracts > 0)
                    amount = abs(contracts)
                    stake_amount = entry_price * amount if entry_price and amount else 0.0

                    # 尝试从交易所数据推断持仓的起始时间（尽量接近入场时间）
                    open_ts = None
                    try:
                        # 优先使用 info.updateTime（毫秒）或 info.time/ timestamp
                        info = p.get('info', {}) or {}
                        open_ts = (
                            info.get('updateTime')
                            or info.get('time')
                            or p.get('timestamp')
                        )
                        if isinstance(open_ts, str) and open_ts.isdigit():
                            open_ts = int(open_ts)
                        if isinstance(open_ts, (int, float)) and open_ts and open_ts > 0:
                            open_ts = int(open_ts)
                        else:
                            open_ts = None
                    except Exception:
                        open_ts = None

                    # 若桥接器中不存在该持仓（按 pair 匹配），则创建新 Trade
                    existing = [t for t in self.bridge.get_open_trades() if t.pair == symbol]
                    if existing:
                        # 简单更新杠杆等（不覆盖盈亏）
                        t0 = existing[0]
                        t0.leverage = leverage
                        if not t0.open_rate and entry_price:
                            t0.open_rate = entry_price
                        continue

                    signal = {
                        'symbol': symbol,
                        'type': 'OPEN_LONG' if is_long else 'OPEN_SHORT',
                        'price': entry_price or 0.0,
                        'position_size_usdt': stake_amount or 0.0,
                        'amount_contracts': amount,
                        'open_timestamp': open_ts,
                    }
                    self.bridge.create_trade_from_signal(signal)
                except Exception:
                    continue
        except Exception:
            # 同步失败不应影响命令执行
            pass

    def _patch_rpc_methods(self):
        """为 RPC 添加 CPT 特定方法"""
        
        # 连接 bridge 到 RPC
        self.rpc._bridge = self.bridge
        
        # 重新实现 _rpc_trade_status 以使用桥接器数据
        def _rpc_trade_status_patched(trade_ids: Optional[list] = None, trade_id: Optional[int] = None):
            # 先同步一次交易所持仓
            self._sync_bridge_with_exchange_positions()
            open_trades = self.bridge.get_open_trades()
            # 支持 trade_ids 列表过滤（freqtrade 接口）
            if trade_ids:
                ids = set()
                try:
                    ids = {int(i) for i in trade_ids}
                except Exception:
                    ids = set()
                open_trades = [t for t in open_trades if t.id in ids]
            # 兼容单个 trade_id 过滤
            elif trade_id is not None:
                open_trades = [t for t in open_trades if t.id == trade_id]
            
            result = []
            for trade in open_trades:
                result.append({
                    'trade_id': trade.id,
                    'pair': trade.pair,
                    'base_currency': trade.base_currency,
                    'quote_currency': trade.quote_currency,
                    'is_open': trade.is_open,
                    'amount': trade.amount,
                    'amount_requested': trade.amount,
                    'stake_amount': trade.stake_amount,
                    'max_stake_amount': trade.stake_amount,  # 单次入场，等同 stake_amount
                    'open_rate': trade.open_rate,
                    'close_rate': trade.close_rate,
                    'current_rate': trade.close_rate or trade.open_rate,
                    'profit_ratio': trade.profit_ratio or 0.0,
                    'profit_pct': (trade.profit_ratio or 0.0) * 100,
                    'profit_abs': trade.profit_abs or 0.0,
                    'realized_profit': 0.0,               # 开仓中，已实现盈亏为0
                    'total_profit_abs': trade.profit_abs or 0.0,
                    'stop_loss_abs': trade.stop_loss,
                    'stop_loss_ratio': 0.0,
                    'stop_loss_pct': 0.0,
                    'stoploss_order_id': None,
                    'stoploss_last_update': None,
                    'initial_stop_loss_abs': trade.initial_stop_loss,
                    'initial_stop_loss_ratio': 0.0,
                    'initial_stop_loss_pct': 0.0,
                    'open_date': trade.open_date,
                    'open_timestamp': int(trade.open_date.timestamp() * 1000),
                    'close_date': trade.close_date,
                    'close_timestamp': int(trade.close_date.timestamp() * 1000) if trade.close_date else None,
                    'open_order_id': None,
                    'close_rate_requested': None,
                    'fee_open': trade.fee_open,
                    'fee_open_cost': None,
                    'fee_open_currency': None,
                    'fee_close': trade.fee_close,
                    'fee_close_cost': None,
                    'fee_close_currency': None,
                    'exchange': trade.exchange,
                    'enter_tag': trade.enter_tag,
                    'timeframe': trade.timeframe,
                    'strategy': trade.strategy,
                    'exit_reason': trade.exit_reason,
                    'min_rate': trade.open_rate,
                    'max_rate': trade.max_rate or trade.open_rate,
                    'has_open_orders': False,
                    'orders': [],
                    'leverage': trade.leverage or 1.0,
                    'trading_mode': trade.trading_mode,
                    'funding_fees': 0.0,
                })
            return result
        
        # 重新实现 _rpc_status 以显示 CPT 状态
        def _rpc_status_patched():
            stats = self.bridge.get_trading_stats()
            return {
                'dry_run': self.config.get('dry_run', True),
                'trading_mode': 'futures',
                'state': 'running' if self.is_running else 'stopped',
                'runmode': 'live' if not self.config.get('dry_run', True) else 'dry_run',
                'strategy_version': '1.0.0',
                'bot_name': 'CryptoPulse Trader',
                'minimal_roi': {},
                'stoploss': -0.01,
                'trailing_stop': False,
                'trailing_stop_positive': None,
                'trailing_stop_positive_offset': None,
                'trailing_only_offset_is_reached': False,
                'open_trades': stats['open_trades_count'],
                'stake_amount': self.config.get('stake_amount', 25.0),
                'stake_currency': self.config.get('stake_currency', 'USDT'),
                'stake_currency_decimals': 2,
                'available_balance': 1000.0,  # 模拟余额
                'total_profit': stats['total_profit'],
                'closed_trade_count': stats['closed_trades_count'],
                'first_trade_date': None,
                'last_trade_date': None,
                'avg_duration': None,
                'best_pair': '',
                'best_rate': 0.0,
                'winning_trades': stats['winning_trades'],
                'losing_trades': stats['losing_trades'],
            }
        
        # 重新实现 _rpc_profit 以显示盈亏统计
        def _rpc_profit_patched(stake_currency: str = None, fiat_display_currency: str = None, 
                               trade_ids: list = None):
            stats = self.bridge.get_trading_stats()
            closed_trades = self.bridge.get_closed_trades(100)
            
            profit_closed_coin = sum(t.profit_abs or 0 for t in closed_trades)
            profit_closed_ratio_sum = sum(t.profit_ratio or 0 for t in closed_trades)
            profit_closed_ratio_mean = profit_closed_ratio_sum / len(closed_trades) if closed_trades else 0
            
            return {
                'profit_closed_coin': profit_closed_coin,
                'profit_closed_percent_mean': profit_closed_ratio_mean * 100,
                'profit_closed_ratio_sum': profit_closed_ratio_sum,
                'profit_closed_percent_sum': profit_closed_ratio_sum * 100,
                'profit_closed_fiat': profit_closed_coin,  # 假设 USDT = fiat
                'profit_all_coin': profit_closed_coin,
                'profit_all_percent_mean': profit_closed_ratio_mean * 100,
                'profit_all_ratio_sum': profit_closed_ratio_sum,
                'profit_all_percent_sum': profit_closed_ratio_sum * 100,
                'profit_all_fiat': profit_closed_coin,
                'trade_count': len(closed_trades),
                'first_trade_date': closed_trades[-1].open_date if closed_trades else None,
                'last_trade_date': closed_trades[0].close_date if closed_trades else None,
                'first_trade_timestamp': int(closed_trades[-1].open_date.timestamp()) if closed_trades else None,
                'last_trade_timestamp': int(closed_trades[0].close_date.timestamp()) if closed_trades and closed_trades[0].close_date else None,
                'avg_duration': '0:30:00',  # 模拟平均持仓时间
                'best_pair': '',
                'best_rate': 0.0,
                'winning_trades': stats['winning_trades'],
                'losing_trades': stats['losing_trades'],
            }

        # 重新实现 /status table 所需数据，匹配 freqtrade 风格
        def _rpc_status_table_patched(stake_currency: str, fiat_display_currency: str):
            
            from rpc.utils import dt_humanize_delta
            
            try:
                # 同步持仓数据
                try:
                    self._sync_bridge_with_exchange_positions()
                except Exception:
                    pass  # 同步失败不影响显示已有数据
                
                open_trades = self.bridge.get_open_trades()
                
                if not open_trades:
                    return [], ["ID L/S", "Pair", "Since", "Profit (USD)"], 0.0, 0.0
                
                rows = []
                fiat_profit_sum = 0.0
                fiat_total_profit_sum = 0.0

                def _ccxt_symbol(pair: str) -> str:
                    # 确保使用 USDT 永续格式，例如 BTC/USDT:USDT
                    if ':USDT' in pair:
                        return pair
                    if '/' in pair:
                        return pair + ':USDT'
                    # 回退：如果是 "BTCUSDT" 形式
                    return pair

                # 批量获取当前价格（无超时机制，避免子线程signal问题）
                symbols: List[str] = [_ccxt_symbol(t.pair) for t in open_trades]
                try:
                    prices = self._get_current_prices_for_symbols(symbols)
                except Exception as e:
                    # 价格查询失败时使用空字典
                    trading_logger.warning(f"获取价格失败: {e}")
                    prices = {}

                # 预计算常用值，减少循环内重复计算
                trades_data = []
                for t in open_trades:
                    side_is_long = bool(t.enter_tag and 'long' in t.enter_tag)
                    open_rate = t.open_rate or 0.0
                    amount = t.amount or 0.0
                    sym = _ccxt_symbol(t.pair)
                    cur = prices.get(sym, 0.0)
                    
                    trades_data.append({
                        'trade': t,
                        'side_is_long': side_is_long,
                        'sym': sym,
                        'current_price': cur,
                        'open_rate': open_rate,
                        'amount': amount
                    })

                # 批量计算盈亏
                for data in trades_data:
                    t = data['trade']
                    side_is_long = data['side_is_long']
                    cur = data['current_price']
                    open_rate = data['open_rate']
                    amount = data['amount']
                    
                    side = 'L' if side_is_long else 'S'
                    lev = f"{t.leverage:.0f}x" if t.leverage and t.leverage != 1.0 else "1x"
                    direction_str = f"{side} {lev}"
                    
                    # 按照freqtrade格式：第一列是 "ID Direction"，第二列是pair
                    id_direction_col = f"{t.id} {direction_str}"
                    pair_col = data['sym']
                    since_col = dt_humanize_delta(t.open_date)

                    # 计算当前未实现盈亏
                    pnl_abs = 0.0
                    pnl_ratio = 0.0
                    if cur and open_rate and amount:
                        if side_is_long:
                            pnl_abs = (cur - open_rate) * amount
                        else:
                            pnl_abs = (open_rate - cur) * amount
                        stake_amt = t.stake_amount or (open_rate * amount)
                        if stake_amt:
                            pnl_ratio = pnl_abs / stake_amt

                    pr = pnl_ratio * 100.0
                    pa = pnl_abs
                    profit_col = f"{pr:.2f}% ({pa:.2f})"
                    fiat_profit_sum += pa
                    fiat_total_profit_sum += pa
                    
                    # 使用freqtrade格式：[ID+Direction, Pair, Since, Profit]
                    rows.append([id_direction_col, pair_col, since_col, profit_col])

                headers = ["ID L/S", "Pair", "Since", "Profit (USD)"]
                return rows, headers, fiat_profit_sum, fiat_total_profit_sum
                
            except Exception as e:
                # 异常时返回空结果，并记录详细错误信息
                import traceback
                error_details = traceback.format_exc()
                trading_logger.error(f"_rpc_status_table 执行失败: {type(e).__name__}: {e}")
                trading_logger.error(f"完整错误堆栈:\n{error_details}")
                return [], ["ID L/S", "Pair", "Since", "Profit (USD)"], 0.0, 0.0

        # 重新实现 /balance 所需数据
        def _rpc_balance_patched(stake_currency: str, fiat_display_currency: str):
            """从交易所获取真实账户余额（带缓存）"""
            try:
                # 检查余额缓存
                now = time.time()
                cache_key = f'balance_{stake_currency}'
                cache_entry = self._balance_cache.get(cache_key)
                if cache_entry and (now - cache_entry.get('ts', 0)) <= self._balance_cache_ttl_seconds:
                    return cache_entry['data']

                ex = self._get_private_exchange()
                if not ex:
                    # 回退到假数据
                    total = 1000.0
                    trade_count = len(self.bridge.trades)
                    currencies = [{
                        'currency': stake_currency,
                        'free': total, 'balance': total, 'used': 0.0,
                        'bot_owned': total, 'stake': stake_currency,
                        'is_position': False, 'is_bot_managed': True,
                        'est_stake': total, 'est_stake_bot': total,
                    }]
                    result = {
                        'currencies': currencies, 'total': total, 'total_bot': total,
                        'symbol': stake_currency, 'value': total, 'value_bot': total,
                        'stake': stake_currency, 'starting_capital': total,
                        'starting_capital_fiat': total, 'starting_capital_ratio': 1.0,
                        'starting_capital_fiat_ratio': 1.0, 'trade_count': trade_count,
                    }
                    # 缓存假数据（短时间）
                    self._balance_cache[cache_key] = {'data': result, 'ts': now}
                    return result

                # 获取真实账户余额
                balance = ex.fetch_balance()
                currencies = []
                total = 0.0
                bot_total = 0.0
                
                # 处理主要币种 (USDT)
                usdt_info = balance.get(stake_currency, {})
                free_usdt = float(usdt_info.get('free', 0.0) or 0.0)
                used_usdt = float(usdt_info.get('used', 0.0) or 0.0)
                total_usdt = float(usdt_info.get('total', 0.0) or 0.0)
                if total_usdt == 0.0:
                    total_usdt = free_usdt + used_usdt
                
                currencies.append({
                    'currency': stake_currency,
                    'free': free_usdt,
                    'balance': total_usdt,
                    'used': used_usdt,
                    'bot_owned': total_usdt,  # 假设机器人管理全部资金
                    'stake': stake_currency,
                    'is_position': False,
                    'is_bot_managed': True,
                    'est_stake': total_usdt,
                    'est_stake_bot': total_usdt,
                })
                
                total += total_usdt
                bot_total += total_usdt
                
                # 处理其他有余额的币种（如 BTC、ETH 等）
                for currency, info in balance.items():
                    if currency == stake_currency or currency in ['free', 'used', 'total', 'info']:
                        continue
                    total_amount = float(info.get('total', 0.0) or 0.0)
                    if total_amount <= 0.001:  # 忽略余额很小的币种
                        continue
                    
                    free_amount = float(info.get('free', 0.0) or 0.0)
                    used_amount = float(info.get('used', 0.0) or 0.0)
                    
                    # 估算 USD 价值（可选：通过价格 API 转换）
                    est_usd_value = total_amount  # 简化处理，后续可加入价格转换
                    
                    currencies.append({
                        'currency': currency,
                        'free': free_amount,
                        'balance': total_amount,
                        'used': used_amount,
                        'bot_owned': 0.0,  # 非 USDT 资产通常不由机器人直接管理
                        'stake': stake_currency,
                        'is_position': False,
                        'is_bot_managed': False,
                        'est_stake': est_usd_value,
                        'est_stake_bot': 0.0,
                    })
                
                trade_count = len(self.bridge.trades)
                
                result = {
                    'currencies': currencies,
                    'total': total,
                    'total_bot': bot_total,
                    'symbol': stake_currency,
                    'value': total,
                    'value_bot': bot_total,
                    'stake': stake_currency,
                    'starting_capital': bot_total,  # 可以从配置或数据库获取初始资金
                    'starting_capital_fiat': bot_total,
                    'starting_capital_ratio': 1.0,
                    'starting_capital_fiat_ratio': 1.0,
                    'trade_count': trade_count,
                }
                
                # 缓存真实数据
                self._balance_cache[cache_key] = {'data': result, 'ts': now}
                return result
                
            except Exception:
                # 出错时回退到假数据
                total = 1000.0
                trade_count = len(self.bridge.trades)
                currencies = [{
                    'currency': stake_currency,
                    'free': total, 'balance': total, 'used': 0.0,
                    'bot_owned': total, 'stake': stake_currency,
                    'is_position': False, 'is_bot_managed': True,
                    'est_stake': total, 'est_stake_bot': total,
                }]
                return {
                    'currencies': currencies, 'total': total, 'total_bot': total,
                    'symbol': stake_currency, 'value': total, 'value_bot': total,
                    'stake': stake_currency, 'starting_capital': total,
                    'starting_capital_fiat': total, 'starting_capital_ratio': 1.0,
                    'starting_capital_fiat_ratio': 1.0, 'trade_count': trade_count,
                }

        # 重新实现 /profit 统计，填充所需字段
        def _rpc_trade_statistics_patched(**kwargs):
            from datetime import datetime
            from rpc.utils import dt_humanize_delta

            closed = self.bridge.get_closed_trades(100)
            all_trades = list(self.bridge.trades.values())

            trade_count = len(all_trades)
            closed_count = len(closed)

            profit_closed_coin = sum((t.profit_abs or 0.0) for t in closed)
            profit_closed_ratio_sum = sum((t.profit_ratio or 0.0) for t in closed)
            profit_closed_ratio_mean = (profit_closed_ratio_sum / closed_count) if closed_count else 0.0
            profit_closed_percent = profit_closed_ratio_sum * 100.0

            profit_all_coin = profit_closed_coin
            profit_all_ratio_mean = profit_closed_ratio_mean
            profit_all_percent = profit_closed_percent

            now = datetime.now(timezone.utc)
            first_trade_dt = (min((t.open_date for t in all_trades)) if all_trades else now)
            latest_trade_dt = (max((t.open_date for t in all_trades)) if all_trades else now)

            first_trade_hum = dt_humanize_delta(first_trade_dt)
            latest_trade_hum = dt_humanize_delta(latest_trade_dt)

            # 胜率与期望
            winning_trades = len([t for t in closed if (t.profit_abs or 0.0) > 0])
            losing_trades = len([t for t in closed if (t.profit_abs or 0.0) <= 0])
            winrate = (winning_trades / closed_count) if closed_count else 0.0
            expectancy = profit_closed_ratio_mean
            expectancy_ratio = expectancy

            # 最佳交易对
            if closed:
                best = max(closed, key=lambda t: (t.profit_abs or 0.0))
                best_pair = best.pair
                best_pair_profit_abs = (best.profit_abs or 0.0)
                best_pair_profit_ratio = (best.profit_ratio or 0.0)
            else:
                best_pair = ""
                best_pair_profit_abs = 0.0
                best_pair_profit_ratio = 0.0

            # 平均持仓时间
            if closed:
                durations = [(t.close_date - t.open_date) for t in closed if t.close_date]
                avg_seconds = sum((d.total_seconds() for d in durations), 0.0) / len(durations)
                avg_duration = str(timedelta(seconds=int(avg_seconds)))
            else:
                avg_duration = "0:00:00"

            # 其它指标占位
            trading_volume = sum((t.stake_amount or 0.0) for t in closed)
            gains = sum(((t.profit_abs or 0.0) for t in closed if (t.profit_abs or 0.0) > 0.0), 0.0)
            losses = -sum(((t.profit_abs or 0.0) for t in closed if (t.profit_abs or 0.0) < 0.0), 0.0)
            profit_factor = (gains / losses) if losses > 0 else 0.0

            return {
                'profit_closed_coin': profit_closed_coin,
                'profit_closed_ratio_mean': profit_closed_ratio_mean,
                'profit_closed_percent': profit_closed_percent,
                'profit_closed_fiat': profit_closed_coin,
                'profit_all_coin': profit_all_coin,
                'profit_all_ratio_mean': profit_all_ratio_mean,
                'profit_all_percent': profit_all_percent,
                'profit_all_fiat': profit_all_coin,
                'trade_count': trade_count,
                'closed_trade_count': closed_count,
                'first_trade_humanized': first_trade_hum,
                'first_trade_date': first_trade_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'latest_trade_humanized': latest_trade_hum,
                'latest_trade_date': latest_trade_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'avg_duration': avg_duration,
                'best_pair': best_pair,
                'best_pair_profit_ratio': best_pair_profit_ratio,
                'best_pair_profit_abs': best_pair_profit_abs,
                'winrate': winrate,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'expectancy': expectancy,
                'expectancy_ratio': expectancy_ratio,
                'bot_start_date': first_trade_dt.strftime('%Y-%m-%d %H:%M:%S'),
                'trading_volume': trading_volume,
                'profit_factor': profit_factor,
                'max_drawdown': 0.0,
                'max_drawdown_abs': 0.0,
                'max_drawdown_start': '',
                'drawdown_high': 0.0,
                'max_drawdown_end': '',
                'drawdown_low': 0.0,
                'current_drawdown': 0.0,
                'current_drawdown_abs': 0.0,
                'current_drawdown_start': '',
                'current_drawdown_high': 0.0,
            }

        # 重新实现 强制平仓（单个/全部），直接作用于桥接器中的交易
        def _rpc_force_exit_patched(trade_id=None, ordertype: str = None):
            # all -> 强制平仓全部
            if trade_id == "all" or (isinstance(trade_id, str) and trade_id.lower() == "all"):
                return _rpc_force_exit_all_patched()

            if trade_id is None:
                return {
                    'status': '错误: 请指定交易ID或使用 "all"',
                    'trade_id': None,
                }

            try:
                trade_id_int = int(trade_id)
            except (TypeError, ValueError):
                return {
                    'status': f"错误: 无效的交易ID '{trade_id}'",
                    'trade_id': trade_id,
                }

            trade = self.bridge.get_trade_by_id(trade_id_int)
            if not trade or not trade.is_open:
                return {
                    'status': f'未找到ID为 {trade_id_int} 的开仓交易',
                    'trade_id': trade_id_int
                }

            # 实际调用交易所API进行平仓
            try:
                # 获取交易所客户端
                ex = self._get_private_exchange()
                if not ex:
                    return {
                        'status': f'交易所连接失败，无法平仓 {trade_id_int}',
                        'trade_id': trade_id_int
                    }

                # 将桥接器格式的symbol转换为CCXT格式
                ccxt_symbol = trade.pair
                # 转换symbol格式
                
                # 更鲁棒的符号转换逻辑
                if '/' not in ccxt_symbol:
                    # BTCUSDT -> BTC/USDT:USDT
                    if 'USDT' in ccxt_symbol:
                        base = ccxt_symbol.replace('USDT', '').replace('usdt', '')
                        ccxt_symbol = f"{base}/USDT:USDT"
                    else:
                        # 如果不包含USDT，可能是其他格式，保持原样或添加默认后缀
                        ccxt_symbol = f"{ccxt_symbol}/USDT:USDT"
                elif '/' in ccxt_symbol and ':' not in ccxt_symbol:
                    # BTC/USDT -> BTC/USDT:USDT
                    ccxt_symbol = f"{ccxt_symbol}:USDT"
                
                # 获取当前持仓信息（不按符号筛选，避免API限制）
                try:
                    positions = ex.fetch_positions()
                except Exception:
                    # 回退：尝试按符号获取
                    try:
                        positions = ex.fetch_positions(symbols=[ccxt_symbol])
                    except Exception:
                        positions = []
                target_position = None
                for pos in positions:
                    if pos['symbol'] == ccxt_symbol and abs(float(pos.get('contracts', 0) or 0)) > 0:
                        target_position = pos
                        break

                if not target_position:
                    # 没有找到对应持仓，可能已经被平仓了
                    # 仍然更新桥接器记录为已关闭
                    close_price = trade.open_rate
                    updated_trade = self.bridge.update_trade_on_close(trade_id_int, close_price, 'position_not_found')
                    return {
                        'status': f'未找到对应持仓 {ccxt_symbol}，可能已被平仓',
                        'trade_id': trade_id_int,
                        'pair': trade.pair,
                        'profit': 0.0,
                    }

                # 执行平仓：发送相反方向的市价单
                contracts = abs(float(target_position.get('contracts', 0)))
                side = 'sell' if float(target_position.get('contracts', 0)) > 0 else 'buy'
                
                # 发送市价平仓单（先尝试带 reduceOnly，失败则不带）
                close_order = None
                try:
                    close_order = ex.create_market_order(
                        symbol=ccxt_symbol,
                        side=side,
                        amount=contracts,
                        params={'reduceOnly': True}  # 仅平仓
                    )
                except Exception:
                    try:
                        # 回退：不使用 reduceOnly
                        close_order = ex.create_market_order(
                            symbol=ccxt_symbol,
                            side=side,
                            amount=contracts
                        )
                    except Exception as e2:
                        raise e2
                
                # 确保订单不为空
                if not close_order:
                    raise Exception("订单创建失败：close_order 为 None")

                # 获取成交价格
                close_price = close_order.get('average') or close_order.get('price') or trade.open_rate
                
                # 更新桥接器记录
                updated_trade = self.bridge.update_trade_on_close(trade_id_int, float(close_price), 'force_exit')

                return {
                    'status': '平仓成功',
                    'trade_id': trade_id_int,
                    'pair': updated_trade.pair,
                    'profit': updated_trade.profit_abs,
                    'close_price': close_price,
                    'order_id': close_order.get('id'),
                }

            except Exception as e:
                # 平仓失败，但仍记录为尝试平仓
                trading_logger.error(f"强制平仓失败 {trade_id_int}: {e}")
                return {
                    'status': f'平仓失败: {str(e)}',
                    'trade_id': trade_id_int,
                    'pair': trade.pair,
                    'error': str(e),
                }

        def _rpc_force_exit_all_patched():
            open_trades = self.bridge.get_open_trades()
            if not open_trades:
                return {
                    'status': '当前没有开仓交易',
                    'closed_trades': 0,
                    'total_profit': 0.0,
                }

            # 逐个调用单个平仓逻辑
            closed = []
            total_profit = 0.0
            failed = []
            
            for t in list(open_trades):
                try:
                    result = _rpc_force_exit_patched(t.id)
                    if 'error' in result or '失败' in result.get('status', ''):
                        failed.append({'trade_id': t.id, 'pair': t.pair, 'error': result.get('status', 'Unknown error')})
                    else:
                        profit = result.get('profit', 0.0) or 0.0
                        total_profit += profit
                        closed.append({'trade_id': t.id, 'pair': t.pair, 'profit': profit})
                except Exception as e:
                    failed.append({'trade_id': t.id, 'pair': t.pair, 'error': str(e)})

            status_msg = f'成功平仓 {len(closed)} 个交易'
            if failed:
                status_msg += f'，失败 {len(failed)} 个'

            return {
                'status': status_msg,
                'closed_trades': len(closed),
                'failed_trades': len(failed),
                'total_profit': total_profit,
                'trades': closed,
                'failures': failed if failed else None,
            }
        
        # 应用补丁
        self.rpc._rpc_trade_status = _rpc_trade_status_patched
        self.rpc._rpc_status = _rpc_status_patched
        self.rpc._rpc_profit = _rpc_profit_patched
        # 覆盖强制平仓到桥接器实现，保证与 /fx 联动
        self.rpc._rpc_force_exit = _rpc_force_exit_patched
        self.rpc._rpc_force_exit_all = _rpc_force_exit_all_patched
        self.rpc._rpc_status_table = _rpc_status_table_patched
        self.rpc._rpc_balance = _rpc_balance_patched
        self.rpc._rpc_trade_statistics = _rpc_trade_statistics_patched
    
    def start(self):
        """启动 Telegram 集成"""
        if self.is_running:
            return
            
        self.is_running = True
        
        if self.telegram:
            trading_logger.info("Telegram 机器人已启动")
    
    def send_system_ready_message(self):
        """发送系统就绪消息"""
        if not self.telegram or not self.is_running:
            return
            
        try:
            # 获取当前持仓统计
            open_trades = self.bridge.get_open_trades()
            trade_count = len(open_trades)
            
            # 计算总浮动盈亏
            total_pnl = 0.0
            try:
                statlist, headers, profit_sum, total_profit = self.rpc._rpc_status_table('USDT', 'USD')
                total_pnl = profit_sum
            except Exception:
                pass
            
            ready_msg = self.bridge.create_rpc_status_msg(
                'ready', 
                f'✅ CryptoPulse Trader 已就绪！\n\n'
                f'📊 当前状态:\n'
                f'• 持仓数量: {trade_count} 个\n'
                f'• 浮动盈亏: {total_pnl:.2f} USDT\n'
                f'• 系统时间: {datetime.now().strftime("%H:%M:%S")}\n\n'
                f'📱 可用命令:\n'
                f'/status table - 查看持仓表格\n'
                f'/balance - 查看账户余额\n'
                f'/profit - 查看盈亏统计\n'
                f'/fx all - 强制平仓所有持仓'
            )
            self.telegram.send_msg(ready_msg)
            trading_logger.info("系统就绪消息已发送")
            
        except Exception as e:
            trading_logger.error(f"发送系统就绪消息失败: {e}")
    
    def stop(self):
        """停止 Telegram 集成"""
        self.is_running = False
        
        if self.telegram:
            try:
                # 获取最终统计信息
                open_trades = self.bridge.get_open_trades()
                trade_count = len(open_trades)
                
                total_pnl = 0.0
                try:
                    statlist, headers, profit_sum, total_profit = self.rpc._rpc_status_table('USDT', 'USD')
                    total_pnl = profit_sum
                except Exception:
                    pass
                
                # 发送停止消息
                stop_msg = self.bridge.create_rpc_status_msg(
                    'stopped', 
                    f'🛑 CryptoPulse Trader 已停止\n\n'
                    f'📊 最终状态:\n'
                    f'• 剩余持仓: {trade_count} 个\n'
                    f'• 浮动盈亏: {total_pnl:.2f} USDT\n'
                    f'• 停止时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n'
                    f'⚠️  请手动管理剩余持仓或重新启动系统'
                )
                self.telegram.send_msg(stop_msg)
                trading_logger.info("系统停止消息已发送")
                
            except Exception as e:
                trading_logger.error(f"发送停止消息失败: {e}")
                
            # 清理 Telegram 线程与资源，避免阻塞进程退出
            try:
                self.telegram.cleanup()
            except Exception:
                pass
            self.telegram = None
    
    def send_startup_message(self):
        """发送启动消息（兼容 NotificationManager 调用）"""
        if not self.telegram or not self.is_running:
            return
            
        try:
            startup_msg = self.bridge.create_rpc_status_msg(
                'starting', 
                f'🚀 CryptoPulse Trader 启动中...\n⚙️ 正在初始化系统组件\n📡 模式: {"测试网" if self.config.get("dry_run") else "主网"}'
            )
            self.telegram.send_msg(startup_msg)
            trading_logger.info("启动消息已发送")
        except Exception as e:
            trading_logger.error(f"发送启动消息失败: {e}")
    
    def send_error_message(self, error_type: str, error_message: str):
        """发送错误消息（兼容 NotificationManager 调用）"""
        if not self.telegram or not self.is_running:
            return
            
        try:
            error_msg = self.bridge.create_rpc_status_msg(
                'error',
                f'⚠️ {error_type}\n{error_message}'
            )
            self.telegram.send_msg(error_msg)
            trading_logger.info(f"错误消息已发送: {error_type}")
        except Exception as e:
            trading_logger.error(f"发送错误消息失败: {e}")
    
    def send_trade_open_message(self, symbol: str, side: str, price: float, amount: float):
        """发送开仓消息"""
        if not self.telegram:
            return
            
        try:
            # 创建模拟信号
            signal = {
                'symbol': symbol,
                'type': 'OPEN_LONG' if side.lower() == 'long' else 'OPEN_SHORT',
                'price': price,
                'position_size_usdt': amount
            }
            
            # 通过桥接器转换为 RPC 消息
            entry_msg = self.bridge.signal_to_rpc_entry_msg(signal)
            
            # 发送消息
            self.telegram.send_msg(entry_msg)
            
        except Exception as e:
            trading_logger.error(f"发送开仓消息失败: {e}", exc_info=True)
    
    def send_trade_close_message(self, symbol: str, side: str, close_price: float, pnl: float, pnl_pct: float):
        """发送平仓消息"""
        if not self.telegram:
            return
            
        try:
            # 查找对应的开仓交易
            open_trades = self.bridge.get_open_trades()
            matching_trade = None
            
            for trade in open_trades:
                if trade.pair == symbol:
                    trade_side = 'long' if 'long' in (trade.enter_tag or '') else 'short'
                    if trade_side == side.lower():
                        matching_trade = trade
                        break
            
            if matching_trade:
                # 创建平仓消息
                exit_msg = self.bridge.create_rpc_exit_msg(
                    matching_trade.id, 
                    close_price, 
                    'manual'
                )
                
                # 发送消息
                self.telegram.send_msg(exit_msg)
            else:
                # 如果找不到对应交易，发送策略消息
                strategy_msg = self.bridge.create_rpc_strategy_msg(
                    f"平仓: {symbol} {side} @{close_price:.4f} "
                    f"盈亏: {pnl:.2f} USDT ({pnl_pct:+.2f}%)"
                )
                self.telegram.send_msg(strategy_msg)
                
        except Exception as e:
            trading_logger.error(f"发送平仓消息失败: {e}", exc_info=True)
    
    
    def send_error_message(self, error_type: str, error_message: str):
        """发送错误消息"""
        if not self.telegram:
            return
            
        try:
            strategy_msg = self.bridge.create_rpc_strategy_msg(
                f"⚠️ {error_type}: {error_message}"
            )
            self.telegram.send_msg(strategy_msg)
            
        except Exception as e:
            trading_logger.error(f"发送错误消息失败: {e}", exc_info=True)
    
    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self.telegram is not None and self.config.get('telegram', {}).get('enabled', False)
    
    def get_bridge(self) -> CPTRPCBridge:
        """获取桥接器实例"""
        return self.bridge
