# CryptoPulse Trader 运行指南

## 修正的问题总结

在代码审查过程中，我们发现并修复了以下问题：

1. **移除 `TradingEngine` 中的冗余方法**：
   - 删除了未使用的 `_initialize_exchange` 方法
   - 确保交易所实例完全由 `__init__` 方法通过传入的参数正确配置

2. **改进 `TradingEngine` 中的持仓更新逻辑**：
   - 修改 `_update_position` 方法，使其能够正确处理多次加仓和平仓
   - 添加了更详细的持仓信息，包括平均价格和总成本

3. **优化错误处理**：
   - `get_balance` 方法在发生错误时返回 0.0 而不是抛出异常
   - 改进了 `get_ticker` 方法的错误日志记录

4. **增强类型安全性**：
   - 更新类型提示，使其更准确（如 `Dict[str, Dict]` 而不是 `Dict[str, float]`）

5. **改进日志记录**：
   - 添加了测试网络模式的日志记录
   - 记录每笔交易的详细信息

## 系统概述

CryptoPulse Trader (CPT) 是一个自动化加密货币交易系统，每小时扫描市场，寻找波动最大的币种，并通过多维度筛选和趋势确认后执行交易。

### 核心组件：

1. **MarketScanner**：扫描全市场加密货币，识别高波动性机会
2. **TrendAnalyzer**：分析短期趋势，生成交易信号
3. **RiskManager**：控制风险，管理持仓和交易记录
4. **TradingEngine**：执行交易，与交易所API交互
5. **PerformanceAnalyzer**：分析交易性能，生成报告

## 运行指南

### 前提条件

1. 安装必要的依赖：
```bash
pip install -r requirements.txt
```

2. 创建 `.env` 文件（基于 `.env.example`）：
```
# API配置
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET=true

# 交易配置
MAX_POSITION_SIZE=100.0
MAX_DAILY_LOSS=5.0
MAX_HOLDING_TIME=60
STOP_LOSS_PCT=1.0
TAKE_PROFIT_PCT=2.0

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/trading.log
```

3. 确保以下目录存在：
```bash
mkdir -p logs reports config
```

### 运行系统

启动交易系统：
```bash
python main.py
```

### 系统运行流程

1. 系统启动后，会每小时扫描一次市场
2. 对波动性大的币种应用流动性筛选
3. 对候选币种执行趋势分析
4. 确认趋势后，执行交易
5. 持续监控持仓风险
6. 每日0点生成绩效报告

### 监控与管理

- 交易日志保存在 `logs/trading.log`
- 性能报告保存在 `reports/` 目录
- 图表（权益曲线、每日收益分布等）也保存在 `reports/` 目录

## 测试网络操作

系统默认使用 Binance 测试网络（testnet）。确保您已经：

1. 在 Binance Testnet 创建了 API 密钥
2. 确认 `.env` 文件中 `BINANCE_TESTNET=true`

在测试环境中，您可以：
- 测试交易逻辑而不需要真实资金
- 验证风险控制系统的有效性
- 测试趋势检测的准确性

## 常见问题解决

1. **找不到配置文件**：
   - 确保 `config/config.yaml` 文件存在，或系统将使用环境变量和默认值

2. **API错误**：
   - 检查API密钥和密钥是否正确
   - 确认testnet设置与您的API密钥类型匹配

3. **交易执行失败**：
   - 检查账户余额是否充足
   - 验证交易对的最小交易量要求

## 下一步开发计划

1. 添加更多交易策略
2. 开发回测功能
3. 实现Telegram通知系统
4. 添加Web界面监控
5. 实现数据库持久化存储 