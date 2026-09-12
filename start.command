#!/bin/bash

# Station & Camera DRI Management - 启动脚本
# 双击此文件即可启动服务（本地直接运行，不使用 Docker）

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/scripts"

# 选择一个可用的 Python 环境：优先项目内 venv，其次旧的工作流 venv，最后系统 python3
VENV_CANDIDATES=(
    "$SCRIPT_DIR/venv"
    "/Users/alston/Documents/Cline/Workflows/venv"
)
PY=""
for V in "${VENV_CANDIDATES[@]}"; do
    if [ -x "$V/bin/python" ] && "$V/bin/python" -c "import flask" >/dev/null 2>&1; then
        PY="$V/bin/python"
        break
    fi
done
if [ -z "$PY" ] && python3 -c "import flask" >/dev/null 2>&1; then
    PY="python3"
fi

if [ -z "$PY" ]; then
    echo "❌ 未找到已安装 Flask 的 Python 环境。"
    echo ""
    echo "请先执行以下命令创建虚拟环境并安装依赖："
    echo "   cd \"$SCRIPT_DIR\""
    echo "   python3 -m venv venv"
    echo "   ./venv/bin/pip install -r requirements.txt"
    echo ""
    echo "按 Enter 键退出..."
    read
    exit 1
fi

# 确保在正确的目录
cd "$APP_DIR" || exit 1

# 显示启动信息
echo "=========================================="
echo "   Station & Camera DRI Management"
echo "   部门信息管理与数据收集平台"
echo "=========================================="
echo "   Python : $PY"
echo "   数据库 : $SCRIPT_DIR/data/app.db"
echo ""
echo "正在启动服务..."
echo ""
echo "服务地址: http://localhost:5001"
echo "按 Ctrl+C 停止服务"
echo "=========================================="
echo ""

# 运行服务
"$PY" run.py

# 按任意键退出
echo ""
echo "按 Enter 键退出..."
read