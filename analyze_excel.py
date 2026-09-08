#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel 文件结构分析脚本"""

import pandas as pd
import os

# 文件路径
file_path = "/Users/alston/Documents/LuxAI/station-camera-dri/在职离职信息-HWTE.xlsx"

# 读取 Excel 文件
df = pd.read_excel(file_path, sheet_name='Sheet1')

print("=" * 60)
print("Excel 文件结构分析报告")
print("=" * 60)

print(f"\n文件: 在职离职信息-HWTE.xlsx")
print(f"Sheet: Sheet1")
print(f"数据行数: {len(df)}")
print(f"列数: {len(df.columns)}")

# 显示所有列标题
print("\n" + "-" * 60)
print("【列标题】")
print("-" * 60)
for i, col in enumerate(df.columns, 1):
    print(f"  {i}. {col}")

# 显示前几行数据
print("\n" + "-" * 60)
print("【示例数据（前10行）】")
print("-" * 60)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', 30)
print(df.head(10).to_string())

# 数据类型
print("\n" + "-" * 60)
print("【数据类型】")
print("-" * 60)
for col in df.columns:
    print(f"  {col}: {df[col].dtype}")

# 缺失值统计
print("\n" + "-" * 60)
print("【缺失值统计】")
print("-" * 60)
missing = df.isnull().sum()
has_missing = False
for col in df.columns:
    if missing[col] > 0:
        print(f"  {col}: {missing[col]} 个空值")
        has_missing = True
if not has_missing:
    print("  无缺失值")

# 部门列分析
print("\n" + "-" * 60)
print("【部门列分析】")
print("-" * 60)

# 找到可能的部门列
dept_keywords = ['部门', 'BU', 'Unit', 'unit']
dept_cols = [col for col in df.columns if any(kw in str(col).upper() for kw in [k.upper() for k in dept_keywords])]

if dept_cols:
    for dept_col in dept_cols:
        print(f"\n部门列: {dept_col}")
        print(f"  唯一值数量: {df[dept_col].nunique()}")
        print(f"  所有部门列表:")
        for dept in df[dept_col].dropna().unique():
            count = len(df[df[dept_col] == dept])
            print(f"    - {dept} ({count}人)")
else:
    print("  未找到明显的部门列，尝试显示所有列的唯一值分布")
    for col in df.columns[:5]:  # 显示前5列的分布
        if df[col].dtype == 'object':
            print(f"\n  列 '{col}' 的值分布:")
            value_counts = df[col].value_counts().head(10)
            for val, count in value_counts.items():
                print(f"    - {val}: {count}")