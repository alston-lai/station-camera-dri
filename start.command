#!/bin/bash

# Station & Camera DRI Management - 启动脚本
# 双击此文件即可启动服务

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/scripts"
VENV_DIR="/Users/alston/Documents/Cline/Workflows/venv"

# 确保在正确的目录
cd "$APP_DIR"

# 激活虚拟环境
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
fi

# 显示启动信息
echo "=========================================="
echo "   Station & Camera DRI Management"
echo "   部门信息管理与数据收集平台"
echo "=========================================="
echo ""
echo "正在启动服务..."
echo ""
echo "服务地址: http://localhost:5001"
echo "按 Ctrl+C 停止服务"
echo "=========================================="
echo ""

# 运行服务
python3 run.py

# 按任意键退出
echo ""
echo "按 Enter 键退出..."
read