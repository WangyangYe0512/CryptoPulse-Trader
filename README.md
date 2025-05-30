# CryptoPulse - 加密货币脉冲交易系统

CryptoPulse是一个基于Python的加密货币自动交易系统，专注于捕捉市场短期趋势和价格脉冲。系统通过实时监控市场数据，识别潜在的交易机会，并自动执行交易策略。

## 主要特性

- 实时市场扫描：使用CoinGecko API监控市场数据
- 趋势追踪：通过WebSocket实时追踪30秒K线趋势
- 智能交易执行：基于Binance API的自动化交易执行
- 风险控制：完整的风险管理系统，包括止损、止盈和仓位管理
- 实时通知：通过Telegram发送交易和系统状态通知
- 日志记录：详细的交易和系统日志

## 系统要求

- Python 3.8+
- 网络连接
- Binance账户和API密钥
- CoinGecko API密钥
- Telegram Bot Token

## 安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/cryptopulse.git
cd cryptopulse
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置：
- 复制`.env.example`为`.env`并填写API密钥等敏感信息：
  ```
  BINANCE_API_KEY=your_binance_api_key
  BINANCE_API_SECRET=your_binance_api_secret
  COINGECKO_API_KEY=your_coingecko_api_key
  TELEGRAM_BOT_TOKEN=your_telegram_bot_token
  TELEGRAM_CHAT_ID=your_telegram_chat_id
  ```
- 根据需要修改`config.yaml`中的其他配置项

## 使用方法

1. 启动系统：
```bash
python main.py
```

2. 监控系统：
- 通过Telegram接收实时通知
- 查看`logs/trading.log`获取详细日志

## 配置说明

### 敏感信息配置 (.env)
- `BINANCE_API_KEY`: Binance API密钥
- `BINANCE_API_SECRET`: Binance API密钥
- `COINGECKO_API_KEY`: CoinGecko API密钥
- `TELEGRAM_BOT_TOKEN`: Telegram Bot Token
- `TELEGRAM_CHAT_ID`: Telegram Chat ID

### 交易配置 (config.yaml)
- `trading.pairs`: 交易对筛选条件
- `trading.trend`: 趋势分析参数
- `trading.order`: 订单管理参数

### 风险控制
- `risk.max_position_size`: 最大持仓大小
- `risk.max_daily_loss`: 最大日亏损限制
- `risk.stop_loss`: 止损百分比
- `risk.take_profit`: 止盈百分比

### 通知配置
- `notification.telegram`: Telegram通知设置
- `notification.daily_summary`: 每日总结设置

## 目录结构

```
cryptopulse/
├── main.py              # 主程序入口
├── config.yaml          # 非敏感配置项
├── .env                # 敏感配置信息
├── requirements.txt     # 依赖包列表
├── README.md           # 项目说明
├── scanner/            # 市场扫描模块
├── executor/           # 交易执行模块
├── risk/              # 风险管理模块
├── notifier/          # 通知模块
└── utils/             # 工具模块
```

## 风险提示

加密货币交易具有高风险，请在使用本系统前充分了解相关风险。本系统不构成投资建议，使用本系统进行交易的风险由用户自行承担。

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request来帮助改进项目。

## 联系方式

如有问题或建议，请通过以下方式联系：
- 提交Issue
- 发送邮件至：your.email@example.com 