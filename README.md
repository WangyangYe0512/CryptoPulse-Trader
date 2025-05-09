# Quantitative Trading System

这是一个基于 Python 的量化交易系统，提供完整的量化交易解决方案。

## 功能特点

- 数据获取和处理
- 策略开发和回测
- 实时交易执行
- 风险控制
- 性能分析

## 项目结构

```
.
├── data/               # 数据存储目录
├── strategies/         # 交易策略
├── backtest/          # 回测系统
├── execution/         # 交易执行
├── risk/             # 风险控制
├── analysis/         # 性能分析
└── utils/            # 工具函数
```

## 安装

1. 克隆仓库
```bash
git clone [repository-url]
cd QuantitativeTrading
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

## 使用说明

1. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的配置信息
```

2. 运行回测
```bash
python backtest/run_backtest.py
```

3. 运行实盘交易
```bash
python execution/run_trading.py
```

## 开发指南

- 遵循 PEP 8 编码规范
- 编写单元测试
- 使用类型注解
- 保持代码文档更新

## 许可证

MIT License 