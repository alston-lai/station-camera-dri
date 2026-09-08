#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导入脚本 - 从 Excel 导入人员数据到指定月份
"""
import sys
import os

# 添加 scripts 目录到路径
sys.path.insert(0, '/Users/alston/Documents/LuxAI/station-camera-dri/scripts')

# 切换到 scripts 目录（因为 data_manager.py 依赖相对路径）
os.chdir('/Users/alston/Documents/LuxAI/station-camera-dri/scripts')

from data_manager import import_staff_from_excel

# Excel 文件路径（包含空格）
excel_path = '/Users/alston/Documents/LuxAI/station-camera-dri/在职离职信息-HWTE 5678.xlsx'

# 读取文件内容
with open(excel_path, 'rb') as f:
    file_content = f.read()

print(f'成功读取文件: {excel_path}')
print(f'文件大小: {len(file_content)} bytes')

# 导入数据到 2024 年 8 月
result = import_staff_from_excel(file_content, year=2024, month=8)

# 打印导入结果
print()
print('='*50)
print('导入结果')
print('='*50)
print(f'在职人数 (current_imported): {result["current_imported"]}')
print(f'离职人数 (left_imported): {result["left_imported"]}')

if result['errors']:
    print()
    print('错误信息:')
    for error in result['errors']:
        print(f'  - {error}')
else:
    print()
    print('无错误')

print('='*50)
print('数据导入完成!')