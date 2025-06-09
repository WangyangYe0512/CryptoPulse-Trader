# CryptoPulse Trader - 运维工具

本文件夹包含CryptoPulse Trader系统的各种运维和诊断工具。

## 📁 工具清单

### 🔄 `startup_recovery.py`
**启动时持仓恢复工具**
- 功能：检查并报告程序启动时的持仓和订单状态
- 用途：主程序启动时自动调用，检测状态不一致问题
- 运行：集成在主程序中，无需单独运行

### 📊 `check_positions.py`
**快速持仓检查工具**
- 功能：快速查看当前持仓和挂单状态
- 用途：日常运维，快速了解账户状态
- 运行：`python tools/check_positions.py`

### 🧹 `cleanup_orders.py`
**订单清理工具**
- 功能：清理大量止损/止盈订单，解决订单限制问题
- 用途：紧急情况下清理孤立订单
- 运行：
  - 预览模式：`python tools/cleanup_orders.py`
  - 执行模式：`python tools/cleanup_orders.py --execute`

## 🚀 使用方法

### 日常检查
```bash
# 快速检查当前持仓状态
python tools/check_positions.py
```

### 紧急清理
```bash
# 预览需要清理的订单
python tools/cleanup_orders.py

# 实际执行清理（谨慎使用）
python tools/cleanup_orders.py --execute
```

### 程序重启前
```bash
# 检查重启影响
python tools/check_positions.py
```

## ⚠️ 注意事项

1. **环境变量**：确保设置正确的API密钥环境变量
2. **网络连接**：所有工具都需要访问Binance API
3. **权限控制**：cleanup_orders.py有实盘操作风险，使用前请仔细确认
4. **资源清理**：工具运行后会自动关闭网络连接

## 🔧 配置要求

- Python 3.8+
- 有效的Binance API密钥
- 正确的环境变量配置
- 网络连接到Binance API

## 📝 日志

工具运行时的日志信息会显示在控制台，便于实时监控和调试。 