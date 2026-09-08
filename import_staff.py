#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入 Excel 数据到 staff.json
"""

import json
import os
from datetime import datetime

# 尝试导入 openpyxl，如果失败则尝试 xlrd
try:
    import openpyxl
    USE_OPENPYXL = True
except ImportError:
    try:
        import xlrd
        USE_OPENPYXL = False
    except ImportError:
        print("请安装 openpyxl 或 xlrd: pip install openpyxl 或 pip install xlrd")
        exit(1)

# 文件路径（含空格）
EXCEL_FILE = "/Users/alston/Documents/LuxAI/station-camera-dri/在职离职信息-HWTE 5678.xlsx"
OUTPUT_FILE = "/Users/alston/Documents/LuxAI/station-camera-dri/data/staff.json"
TARGET_MONTH = "2024-08"

def read_excel_data():
    """读取 Excel 文件"""
    print(f"正在读取: {EXCEL_FILE}")
    
    if USE_OPENPYXL:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
        
        data = []
        for row in ws.iter_rows(min_row=2, values_only=True):  # 跳过表头
            if row[0] is None:  # 跳过空行
                continue
            data.append(row)
        wb.close()
    else:
        wb = xlrd.open_workbook(EXCEL_FILE)
        ws = wb.sheet_by_index(0)
        
        data = []
        for row_idx in range(1, ws.nrows):  # 跳过表头
            row = [ws.cell_value(row_idx, col_idx) for col_idx in range(ws.ncols)]
            if row[0] is None or row[0] == "":
                continue
            data.append(row)
        wb.release_resources()
    
    print(f"共读取 {len(data)} 条记录")
    return data

def validate_and_transform(data):
    """验证并转换数据"""
    staff_list = []
    validation_results = []
    
    for idx, row in enumerate(data):
        # 列顺序：工号(0)、姓名(1)、部门(2)、级别(3)、智能机/电话(4)、邮箱(5)
        employee_id = str(row[0]).strip() if row[0] else ""
        name = str(row[1]).strip() if row[1] else ""
        level = row[3] if len(row) > 3 else ""
        phone = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        email = str(row[5]).strip() if len(row) > 5 and row[5] else ""
        
        # 转换 level 为数字（保留原值用于显示）
        level_value = level
        if isinstance(level, (int, float)):
            level_value = int(level)
        elif isinstance(level, str) and level.strip():
            try:
                level_value = int(float(level))
            except ValueError:
                pass
        
        staff = {
            "employee_id": employee_id,
            "name": name,
            "level": level_value,
            "phone": phone,
            "email": email
        }
        staff_list.append(staff)
        
        # 验证前3条
        if idx < 3:
            is_level_number = isinstance(level_value, int)
            is_phone_11digits = len(phone) == 11 and phone.isdigit()
            is_email_with_at = "@" in email and "." in email.split("@")[-1] if email else False
            
            validation_results.append({
                "index": idx,
                "employee_id": employee_id,
                "name": name,
                "level": level_value,
                "is_level_number": is_level_number,
                "phone": phone,
                "is_phone_11digits": is_phone_11digits,
                "email": email,
                "is_email_with_at": is_email_with_at
            })
    
    return staff_list, validation_results

def save_to_json(staff_list):
    """保存到 JSON 文件"""
    # 构建最终数据结构
    output_data = {
        TARGET_MONTH: staff_list
    }
    
    # 确保目录存在
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"数据已保存到: {OUTPUT_FILE}")

def print_validation_results(results):
    """打印验证结果"""
    print("\n" + "="*60)
    print("验证结果（前3条）")
    print("="*60)
    
    for r in results:
        print(f"\n【第 {r['index']+1} 条】")
        print(f"  工号: {r['employee_id']}")
        print(f"  姓名: {r['name']}")
        print(f"  级别: {r['level']} → 是数字: {'✓' if r['is_level_number'] else '✗'}")
        print(f"  电话: {r['phone']} → 11位手机号: {'✓' if r['is_phone_11digits'] else '✗'}")
        print(f"  邮箱: {r['email']} → 带@符号: {'✓' if r['is_email_with_at'] else '✗'}")
    
    # 汇总
    all_level_ok = all(r['is_level_number'] for r in results)
    all_phone_ok = all(r['is_phone_11digits'] for r in results)
    all_email_ok = all(r['is_email_with_at'] for r in results)
    
    print("\n" + "="*60)
    print("汇总验证")
    print("="*60)
    print(f"  level 是否都是数字: {'✓ 全部通过' if all_level_ok else '✗ 有问题'}")
    print(f"  phone 是否都是11位: {'✓ 全部通过' if all_phone_ok else '✗ 有问题'}")
    print(f"  email 是否都带@:   {'✓ 全部通过' if all_email_ok else '✗ 有问题'}")

def main():
    print(f"开始导入数据到月份: {TARGET_MONTH}")
    print("-"*40)
    
    # 1. 读取 Excel
    raw_data = read_excel_data()
    
    # 2. 验证并转换
    staff_list, validation_results = validate_and_transform(raw_data)
    
    # 3. 保存
    save_to_json(staff_list)
    
    # 4. 打印验证结果
    print_validation_results(validation_results)
    
    print(f"\n✅ 完成！共导入 {len(staff_list)} 条记录")

if __name__ == "__main__":
    main()