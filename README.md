# CryptoPulse Trader

一个基于 Python 的加密货币量化交易机器人，专注于捕捉短期市场波动机会。

## 核心特性

- 自动市场扫描：每小时扫描市场，识别高波动率币种
- 智能流动性筛选：确保充足的交易流动性
- 趋势确认机制：多维度验证交易信号
- 自动风险控制：止损、止盈、最大持仓时间限制
- 实时通知：通过Telegram发送交易和系统状态通知
- 命令控制：通过Telegram命令查询状态和控制系统

## 环境要求

- Python 3.8+
- Binance API Key (支持现货和合约)
- Telegram Bot Token (可选，用于通知和控制)

## 快速开始

### 1. 克隆项目
```bash
git clone <项目地址>
cd QuantitativeTrading
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
复制环境变量模板：
```bash
cp .env-example .env
```

编辑 `.env` 文件，设置必要的配置：
```env
# Binance API 配置
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
BINANCE_TESTNET=false

# Telegram 通知配置（可选）
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### 4. 功能配置
编辑 `config/config.yaml` 文件，调整交易参数和功能开关：

```yaml
# 交易配置
trading:
  order:
    max_order_size: 20        # 单笔最大订单（U）
    
# 风险控制
risk:
  max_position_size: 15       # 单笔最大仓位（U）
  stop_loss_pct: 1.0         # 止损百分比
  take_profit_pct: 2.0       # 止盈百分比

# Telegram 通知
notification:
  telegram:
    enabled: true             # 启用Telegram功能
    trade_notifications: true  # 交易通知
    error_notifications: true  # 错误通知
    commands_enabled: true     # 命令功能
```

### 5. 启动系统
```bash
python main.py
```

## Telegram 功能配置

### 创建 Telegram Bot
1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 创建新机器人
3. 按提示设置机器人名称和用户名
4. 获取 Bot Token 并设置到 `.env` 文件中

### 获取 Chat ID
1. 在 Telegram 中搜索 `@userinfobot`
2. 发送任意消息获取您的 User ID
3. 将 User ID 设置为 `TELEGRAM_CHAT_ID`

### 测试 Telegram 功能
```bash
python tools/telegram_test.py
```

### 群组和话题支持
CryptoPulse Trader现在支持在Telegram群组中运行，包括分话题的超级群组：

**配置群组模式:**
```yaml
notification:
  telegram:
    enabled: true
    group_mode: true              # 启用群组模式
    topic_id: null                # 话题ID（null=主群组）
    
    # 话题路由（可选）
    topic_routing:
      enabled: true               # 启用话题路由
      topics:
        trade: 123                # 交易通知话题ID
        error: 456                # 错误通知话题ID
        status: 789               # 状态通知话题ID
        system: null              # 系统消息（主群组）
```

**环境变量配置:**
```env
# 群组ID（负数）
TELEGRAM_CHAT_ID=-1001234567890
```

### 可用命令
- `/start` - 启动机器人
- `/help` - 显示帮助信息
- `/status` - 系统运行状态
- `/balance` - 账户余额查询
- `/profit [天数]` - 盈亏统计
- `/trades [数量]` - 最近交易记录
- `/positions` - 当前持仓情况
- `/config` - 配置信息

详细配置说明请参考：
- [docs/telegram_setup.md](docs/telegram_setup.md)
- [docs/telegram_group_setup.md](docs/telegram_group_setup.md)

## 配置说明

### 主要配置项

#### 交易参数
- `trading.order.max_order_size`: 单笔最大订单金额
- `trading.order.max_orders_per_symbol`: 单币种最大订单数
- `risk.stop_loss_pct`: 止损百分比
- `risk.take_profit_pct`: 止盈百分比

#### 风险控制
- `risk.max_position_size`: 单笔最大仓位
- `risk.max_daily_loss`: 日最大亏损限制
- `risk.max_open_positions`: 最大同时持仓数

#### 通知配置
- `notification.telegram.enabled`: 启用Telegram功能
- `notification.telegram.trade_notifications`: 交易通知开关
- `notification.telegram.error_notifications`: 错误通知开关

### 环境变量说明

#### 必需配置
- `BINANCE_API_KEY`: Binance API 密钥
- `BINANCE_API_SECRET`: Binance API 私钥

#### Telegram配置（可选）
- `TELEGRAM_BOT_TOKEN`: Telegram Bot Token
- `TELEGRAM_CHAT_ID`: Telegram Chat ID

#### 其他配置
- `BINANCE_TESTNET`: 是否使用测试网（默认false）
- `LOG_LEVEL`: 日志级别（默认INFO）

## 目录结构

```
cryptopulse/
├── main.py                  # 主程序入口
├── config/
│   └── config.yaml         # 主配置文件
├── .env                    # 环境变量配置
├── requirements.txt        # 依赖包列表
├── docs/
│   └── telegram_setup.md   # Telegram配置说明
├── tools/
│   └── telegram_test.py    # Telegram功能测试
├── scanner/                # 市场扫描模块
├── executor/               # 交易执行模块
├── risk/                   # 风险管理模块
├── utils/                  # 工具模块
│   ├── telegram_bot.py     # Telegram机器人
│   └── notification_manager.py  # 通知管理器
└── logs/                   # 日志文件
```

## 功能特色

### 智能扫描
- 每小时自动扫描全市场币种
- 基于波动率和交易量的多维度筛选
- 动态watchlist管理，自动更新候选币种

### 风险控制
- 严格的止损止盈机制
- 最大持仓时间限制
- 日亏损限额保护
- 实时风险监控和预警

### 实时通知
- 开仓/平仓实时通知
- 系统状态和错误警报
- 风险预警和资金提醒
- 支持命令查询和控制

### 高可靠性
- 异步处理架构，高性能低延迟
- 完善的错误处理和恢复机制
- 详细的日志记录和监控
- 优雅的启动和关闭流程

## 使用建议

### 新手用户
1. 建议先在测试网环境熟悉功能
2. 设置较小的仓位和较严格的止损
3. 开启所有通知，密切关注系统运行

### 进阶用户
1. 根据市场条件调整扫描参数
2. 优化风险控制参数提高收益
3. 通过Telegram命令灵活控制系统

### 生产环境
1. 确保网络稳定和服务器可靠性
2. 定期备份配置和日志文件
3. 监控系统资源使用情况

## 风险提示

⚠️ **重要提醒**
- 加密货币交易具有高风险，请在充分了解风险的前提下使用
- 本系统仅供学习和研究使用，不构成投资建议
- 建议先在测试环境或小资金环境下验证策略效果
- 使用前请仔细阅读并理解所有配置参数

## 技术支持

- 查看日志：`tail -f logs/trading.log`
- 测试Telegram：`python tools/telegram_test.py`
- 问题反馈：通过 Issue 或 Pull Request

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request来帮助改进项目。

## 联系方式

如有问题或建议，请通过以下方式联系：
- 提交Issue
- 发送邮件至：your.email@example.com 