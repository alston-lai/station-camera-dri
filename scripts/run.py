#!/usr/bin/env python3
"""
Station & Camera DRI Management - 启动脚本
"""
import os
import sys

# 添加脚本目录到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
sys.path.insert(0, script_dir)

if __name__ == '__main__':
    from app import app
    print("=" * 50)
    print("Station & Camera DRI Management")
    print("部门信息管理与数据收集平台")
    print("=" * 50)
    print("访问地址: http://localhost:5001")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=True)