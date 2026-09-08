"""
数据管理器 - 处理 JSON 文件的读写操作
"""
import io
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import openpyxl
except ImportError:
    openpyxl = None

# 获取项目根目录 (scripts -> 项目根目录)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')

# 部门简称与全称的映射
DEPT_SHORT_NAMES = ['五部', '六部', '七部', '八部']
DEPT_FULL_NAMES = {
    '五部': '硬件测试开发五部',
    '六部': '硬件测试开发六部',
    '七部': '硬件测试开发七部',
    '八部': '硬件测试开发八部'
}

def short_to_full(short_name: str) -> str:
    """将部门简称转换为全称"""
    return DEPT_FULL_NAMES.get(short_name, short_name)

def full_to_short(full_name: str) -> str:
    """将部门全称转换为简称"""
    # 从后往前匹配，更精确
    for short, full in DEPT_FULL_NAMES.items():
        if full_name == full:
            return short
    return full_name  # 如果没找到，返回原值


def get_data_path(filename: str) -> str:
    """获取数据文件路径"""
    return os.path.join(DATA_DIR, filename)


def load_json(filename: str) -> Dict[str, Any]:
    """加载 JSON 文件"""
    filepath = get_data_path(filename)
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filename: str, data: Dict[str, Any]) -> bool:
    """保存 JSON 文件"""
    filepath = get_data_path(filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True


# ===== 人员信息 =====
def get_all_staff() -> Dict[str, Any]:
    """获取所有人员信息（按部门存储）"""
    return load_json('staff.json')


def get_department_staff(dept: str = None) -> List[Dict]:
    """获取指定部门的人员信息
    Args:
        dept: 部门名称（全体/五部/六部/七部/八部），如果为 None 或 '全体'，返回所有部门人员
    Returns:
        人员列表
    """
    data = get_all_staff()
    
    if dept is None or dept == '全体':
        # 返回所有部门的人员
        all_staff = []
        for d in DEPT_SHORT_NAMES:
            all_staff.extend(data.get(d, []))
        return all_staff
    else:
        return data.get(dept, [])


def get_department_summary() -> Dict[str, Dict]:
    """获取各部门人员汇总"""
    data = get_all_staff()
    summary = {}
    all_left = data.get('left', [])
    
    for dept in DEPT_SHORT_NAMES:
        members = data.get(dept, [])
        summary[dept] = {
            "current": len(members),
            "joined_count": 0,
            "left_count": len([r for r in all_left if r.get('department') == dept])
        }
    
    return summary


def get_department_detail(dept: str) -> Dict[str, Any]:
    """获取部门详细信息
    Args:
        dept: 部门名称（五部/六部/七部/八部）
    Returns:
        包含 current, joined, left 的字典
    """
    if dept not in DEPT_SHORT_NAMES:
        return {'current': [], 'joined': [], 'left': []}
    
    data = get_all_staff()
    members = data.get(dept, [])
    # 为每个成员添加部门字段
    current = []
    for m in members:
        member_copy = m.copy()
        member_copy['department'] = dept
        current.append(member_copy)
    
    return {
        'current': current,
        'joined': [],
        'left': [r for r in data.get('left', []) if r.get('department') == dept]
    }


def get_department_all() -> Dict[str, Any]:
    """获取所有部门人员汇总"""
    data = get_all_staff()
    all_current = []
    total_count = 0
    all_left = data.get('left', [])
    
    for d in DEPT_SHORT_NAMES:
        members = data.get(d, [])
        total_count += len(members)
        for member in members:
            member_copy = member.copy()
            member_copy['department'] = d
            all_current.append(member_copy)
    
    return {
        'current': all_current,
        'total_count': total_count,
        'departments': {d: len(data.get(d, [])) for d in DEPT_SHORT_NAMES},
        'joined': [],  # 全体视图不显示入职记录，按需要可添加
        'left': all_left
    }


def add_staff_to_department(dept: str, member: Dict, operator: str = 'System',
                            employee_id: str = '', ip_address: str = '') -> bool:
    """添加人员到指定部门
    Args:
        dept: 部门名称
        member: 人员信息 {'employee_id', 'name', 'level', 'phone', 'email'}
        operator: 操作人
        employee_id: 操作人工号
        ip_address: IP 地址
    Returns:
        是否添加成功
    """
    if dept not in DEPT_SHORT_NAMES:
        return False
    
    data = get_all_staff()
    
    # 检查是否已存在（通过工号判断）
    existing = data.get(dept, [])
    if any(m.get('employee_id') == member.get('employee_id') for m in existing):
        return False
    
    existing.append(member)
    data[dept] = existing
    save_json('staff.json', data)
    add_history(f"添加人员: {member.get('name', 'Unknown')} 到 {dept}", operator, employee_id, ip_address)
    return True


def update_department_members(dept: str, members: List[Dict], operator: str = 'System',
                              employee_id: str = '', ip_address: str = '') -> None:
    """更新部门成员列表
    Args:
        dept: 部门名称
        members: 新的人员列表
        operator: 操作人
    """
    data = get_all_staff()
    data[dept] = members
    save_json('staff.json', data)
    add_history(f"更新 {dept} 成员列表 ({len(members)} 人)", operator, employee_id, ip_address)


def remove_staff_from_department(dept: str, staff_employee_id: str, operator: str = 'System',
                                 op_employee_id: str = '', ip_address: str = '') -> bool:
    """从部门移除人员
    Args:
        dept: 部门名称
        staff_employee_id: 员工工号
        operator: 操作人
        op_employee_id: 操作人工号
        ip_address: IP 地址
    Returns:
        是否移除成功
    """
    data = get_all_staff()
    members = data.get(dept, [])
    
    for i, m in enumerate(members):
        if m.get('employee_id') == staff_employee_id:
            name = m.get('name', 'Unknown')
            members.pop(i)
            data[dept] = members
            save_json('staff.json', data)
            add_history(f"移除人员: {name} 从 {dept}", operator, op_employee_id, ip_address)
            return True
    
    return False


def add_left_record(record: Dict, operator: str = 'System', 
                    op_employee_id: str = '', ip_address: str = '') -> None:
    """添加离职记录
    Args:
        record: {'name', 'department', 'reason', 'date'}
        operator: 操作人
        op_employee_id: 操作人工号
        ip_address: IP 地址
    """
    data = get_all_staff()
    
    if 'left' not in data:
        data['left'] = []
    
    record['operator'] = operator
    data['left'].append(record)
    save_json('staff.json', data)
    add_history(f"{record.get('name', 'Unknown')} 离职 ({record.get('department', '')})", operator, op_employee_id, ip_address)


# ===== Action Items =====
def get_all_action_items() -> List[Dict]:
    """获取所有 Action Items"""
    data = load_json('action_items.json')
    return data.get('items', [])


def add_action_item(item: Dict, ip_address: str = '') -> None:
    """添加 Action Item"""
    data = load_json('action_items.json')
    if 'items' not in data:
        data['items'] = []
    
    item['id'] = len(data['items']) + 1
    item['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    data['items'].append(item)
    save_json('action_items.json', data)
    add_history(f"添加 Action Item: {item.get('title', '')}", item.get('operator', 'System'), 
                item.get('employee_id', ''), ip_address)


def update_action_item(item_id: int, updates: Dict, ip_address: str = '') -> None:
    """更新 Action Item"""
    data = load_json('action_items.json')
    for item in data.get('items', []):
        if item.get('id') == item_id:
            item.update(updates)
            item['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            break
    save_json('action_items.json', data)
    add_history(f"更新 Action Item #{item_id}", updates.get('operator', 'System'), 
                updates.get('employee_id', ''), ip_address)


def delete_action_item(item_id: int, operator: str = 'System', 
                       op_employee_id: str = '', ip_address: str = '') -> None:
    """删除 Action Item"""
    data = load_json('action_items.json')
    data['items'] = [item for item in data.get('items', []) if item.get('id') != item_id]
    save_json('action_items.json', data)
    add_history(f"删除 Action Item #{item_id}", operator, op_employee_id, ip_address)


# ===== 信息列表（多表结构）=====
def get_all_info_list() -> List[Dict]:
    """获取所有信息表"""
    data = load_json('info_list.json')
    return data.get('tables', [])

def create_info_table(name: str, headers: List[str] = None, operator: str = 'System',
                      op_employee_id: str = '', ip_address: str = '') -> int:
    """创建新的信息表"""
    data = load_json('info_list.json')
    if 'tables' not in data:
        data['tables'] = []
    
    # 默认表头
    if not headers:
        headers = ['Key', 'Value']
    
    table_id = len(data['tables']) + 1
    table = {
        'id': table_id,
        'name': name,
        'headers': headers,
        'rows': [],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    data['tables'].append(table)
    save_json('info_list.json', data)
    add_history(f"创建信息表: {name}", operator, op_employee_id, ip_address)
    return table_id

def add_info_row(table_id: int, row: Dict, operator: str = 'System',
                 op_employee_id: str = '', ip_address: str = '') -> None:
    """向信息表添加行"""
    data = load_json('info_list.json')
    for table in data.get('tables', []):
        if table.get('id') == table_id:
            if 'rows' not in table:
                table['rows'] = []
            table['rows'].append(row)
            break
    save_json('info_list.json', data)
    add_history(f"信息表 #{table_id} 添加数据", operator, op_employee_id, ip_address)

def update_info_row(table_id: int, row_index: int, row: Dict, operator: str = 'System',
                    op_employee_id: str = '', ip_address: str = '') -> None:
    """更新信息表的某一行"""
    data = load_json('info_list.json')
    for table in data.get('tables', []):
        if table.get('id') == table_id:
            if 'rows' in table and 0 <= row_index < len(table['rows']):
                table['rows'][row_index] = row
            break
    save_json('info_list.json', data)
    add_history(f"信息表 #{table_id} 更新第 {row_index + 1} 行", operator, op_employee_id, ip_address)

def delete_info_table(table_id: int, operator: str = 'System',
                      op_employee_id: str = '', ip_address: str = '') -> None:
    """删除信息表"""
    data = load_json('info_list.json')
    data['tables'] = [t for t in data.get('tables', []) if t.get('id') != table_id]
    save_json('info_list.json', data)
    add_history(f"删除信息表 #{table_id}", operator, op_employee_id, ip_address)

def delete_info_row(table_id: int, row_index: int, operator: str = 'System',
                    op_employee_id: str = '', ip_address: str = '') -> None:
    """删除信息表的某一行"""
    data = load_json('info_list.json')
    for table in data.get('tables', []):
        if table.get('id') == table_id:
            if 'rows' in table and 0 <= row_index < len(table['rows']):
                table['rows'].pop(row_index)
            break
    save_json('info_list.json', data)
    add_history(f"信息表 #{table_id} 删除第 {row_index + 1} 行", operator, op_employee_id, ip_address)


# ===== 数据收集表格 =====
def get_collector_sheets() -> List[Dict]:
    """获取所有收集表格"""
    data = load_json('collector.json')
    return data.get('sheets', [])


def create_collector_sheet(sheet: Dict, ip_address: str = '') -> None:
    """创建收集表格"""
    data = load_json('collector.json')
    if 'sheets' not in data:
        data['sheets'] = []
    
    sheet['id'] = len(data['sheets']) + 1
    sheet['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    data['sheets'].append(sheet)
    save_json('collector.json', data)
    add_history(f"创建收集表格: {sheet.get('name', '')}", sheet.get('operator', 'System'),
                sheet.get('employee_id', ''), ip_address)


def add_collector_row(sheet_id: int, row: Dict, ip_address: str = '') -> None:
    """添加收集表格行"""
    data = load_json('collector.json')
    for sheet in data.get('sheets', []):
        if sheet.get('id') == sheet_id:
            if 'rows' not in sheet:
                sheet['rows'] = []
            row['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            sheet['rows'].append(row)
            break
    save_json('collector.json', data)
    add_history(f"收集表格 #{sheet_id} 添加数据", row.get('operator', 'System'),
                row.get('employee_id', ''), ip_address)


def get_collector_sheet(sheet_id: int) -> Optional[Dict]:
    """获取单个收集表格"""
    data = load_json('collector.json')
    for sheet in data.get('sheets', []):
        if sheet.get('id') == sheet_id:
            return sheet
    return None


def update_collector_row(sheet_id: int, row_index: int, row_data: Dict, ip_address: str = '') -> None:
    """更新收集表格行"""
    data = load_json('collector.json')
    for sheet in data.get('sheets', []):
        if sheet.get('id') == sheet_id:
            if 0 <= row_index < len(sheet.get('rows', [])):
                sheet['rows'][row_index].update(row_data)
                sheet['rows'][row_index]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            break
    save_json('collector.json', data)
    add_history(f"收集表格 #{sheet_id} 更新第 {row_index + 1} 行", row_data.get('operator', 'System'),
                row_data.get('employee_id', ''), ip_address)


def delete_collector_row(sheet_id: int, row_index: int, operator: str = 'System',
                         op_employee_id: str = '', ip_address: str = '') -> None:
    """删除收集表格行"""
    data = load_json('collector.json')
    for sheet in data.get('sheets', []):
        if sheet.get('id') == sheet_id:
            if 0 <= row_index < len(sheet.get('rows', [])):
                sheet['rows'].pop(row_index)
            break
    save_json('collector.json', data)
    add_history(f"收集表格 #{sheet_id} 删除第 {row_index + 1} 行", operator, op_employee_id, ip_address)


def delete_collector_sheet(sheet_id: int, operator: str = 'System',
                           op_employee_id: str = '', ip_address: str = '') -> None:
    """删除收集表格"""
    data = load_json('collector.json')
    sheet_name = None
    for sheet in data.get('sheets', []):
        if sheet.get('id') == sheet_id:
            sheet_name = sheet.get('name', '')
            break
    data['sheets'] = [s for s in data.get('sheets', []) if s.get('id') != sheet_id]
    save_json('collector.json', data)
    if sheet_name:
        add_history(f"删除收集表格: {sheet_name}", operator, op_employee_id, ip_address)


# ===== 历史记录 =====
def add_history(action: str, operator: str, employee_id: str = '', ip_address: str = '') -> None:
    """添加历史记录
    Args:
        action: 操作描述
        operator: 操作人名字
        employee_id: 操作人工号
        ip_address: IP 地址
    """
    data = load_json('history.json')
    if 'records' not in data:
        data['records'] = []
    
    record = {
        'id': len(data['records']) + 1,
        'action': action,
        'operator': operator,
        'employee_id': employee_id,
        'ip_address': ip_address,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    data['records'].insert(0, record)
    
    # 只保留最近 500 条记录
    data['records'] = data['records'][:500]
    save_json('history.json', data)


def get_history(limit: int = 100) -> List[Dict]:
    """获取历史记录"""
    data = load_json('history.json')
    return data.get('records', [])[:limit]


def init_all_data() -> None:
    """初始化所有数据文件"""
    initial = load_json('initial_data.json')
    
    for key in ['staff.json', 'action_items.json', 'info_list.json', 'collector.json', 'history.json']:
        filepath = get_data_path(key)
        if not os.path.exists(filepath):
            if key == 'staff.json':
                save_json(key, initial)
            elif key == 'action_items.json':
                save_json(key, {'items': []})
            elif key == 'info_list.json':
                save_json(key, {'items': []})
            elif key == 'collector.json':
                save_json(key, {'sheets': []})
            elif key == 'history.json':
                save_json(key, {'records': []})


# ===== Excel 导入导出 =====

def export_staff_to_excel(dept: str = None) -> bytes:
    """导出人员信息为 Excel 格式
    Args:
        dept: 部门名称（全体/五部/六部/七部/八部），为 None 时默认全体
    Returns:
        Excel 文件的字节数据
    """
    if openpyxl is None:
        raise Exception("openpyxl 库未安装，无法导出 Excel")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # 标题行
    headers = ['工号', '姓名', '部门', '级别', '智能机', '邮箱']
    ws.append(headers)

    # 获取数据
    data = get_all_staff()
    
    # 收集在职员工
    current_staff = []
    if dept is None or dept == '全体':
        # 导出所有部门
        for d in DEPT_SHORT_NAMES:
            for member in data.get(d, []):
                current_staff.append({
                    'employee_id': member.get('employee_id', ''),
                    'name': member.get('name', ''),
                    'department': d,
                    'level': member.get('level', ''),
                    'phone': member.get('phone', ''),
                    'email': member.get('email', '')
                })
    else:
        # 导出指定部门
        for member in data.get(dept, []):
            current_staff.append({
                'employee_id': member.get('employee_id', ''),
                'name': member.get('name', ''),
                'department': dept,
                'level': member.get('level', ''),
                'phone': member.get('phone', ''),
                'email': member.get('email', '')
            })

    # 按工号排序
    current_staff.sort(key=lambda x: x['employee_id'])

    # 写入数据
    for s in current_staff:
        ws.append([s['employee_id'], s['name'], s['department'], s['level'], s['phone'], s['email']])

    # 保存到内存
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def import_staff_from_excel(file_content: bytes, dept: str = None, operator: str = 'System',
                            op_employee_id: str = '', ip_address: str = '') -> Dict[str, Any]:
    """从 Excel 导入人员信息
    Args:
        file_content: Excel 文件内容（字节）
        dept: 部门名称，为 None 时根据 Excel 中的部门列自动分配
        operator: 操作人
        op_employee_id: 操作人工号
        ip_address: IP 地址
    Returns:
        导入结果 {'current_imported': int, 'errors': list}
    """
    if openpyxl is None:
        raise Exception("openpyxl 库未安装，无法导入 Excel")

    wb = openpyxl.load_workbook(io.BytesIO(file_content))
    ws = wb.active

    result = {
        'current_imported': 0,
        'errors': []
    }

    # 获取现有数据
    data = get_all_staff()

    # 从第二行开始读取（跳过标题）
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        emp_id = row[0] if row[0] else ''
        name = row[1] if row[1] else ''
        dept_name = row[2] if len(row) > 2 and row[2] else ''
        level = row[3] if len(row) > 3 and row[3] else ''
        phone = row[4] if len(row) > 4 and row[4] else ''
        email = row[5] if len(row) > 5 and row[5] else ''

        if not emp_id or not name:
            continue

        # 确定目标部门
        target_dept = dept
        if target_dept is None:
            # 根据 Excel 中的部门列自动分配
            if dept_name in DEPT_SHORT_NAMES:
                target_dept = dept_name
            else:
                # 尝试转换全称为简称
                target_dept = full_to_short(dept_name)
        
        if target_dept not in DEPT_SHORT_NAMES:
            result['errors'].append(f"第 {row_idx} 行: 未知部门 '{dept_name}'")
            continue

        # 构建人员记录
        member = {
            'employee_id': str(emp_id),
            'name': str(name),
            'level': str(level) if level else '',
            'phone': str(phone) if phone else '',
            'email': str(email) if email else ''
        }

        # 检查是否已存在（通过工号）
        existing = data.get(target_dept, [])
        if any(m.get('employee_id') == member['employee_id'] for m in existing):
            continue

        existing.append(member)
        data[target_dept] = existing
        result['current_imported'] += 1

    save_json('staff.json', data)
    add_history(f"导入人员数据: {result['current_imported']} 人" + (f" 到 {dept}" if dept else ""), 
                operator, op_employee_id, ip_address)

    return result