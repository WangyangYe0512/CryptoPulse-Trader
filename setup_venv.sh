#!/bin/bash

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级pip
pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt

# 创建必要的目录
mkdir -p logs
mkdir -p data
mkdir -p reports
mkdir -p config

echo "虚拟环境设置完成！"
echo "使用 'source venv/bin/activate' 来激活虚拟环境" 