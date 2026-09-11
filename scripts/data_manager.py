"""
数据管理器 - SQLite 存储实现
把主要业务数据（人员 / Action / 信息表 / 数据收集 / 历史 / 用户 / 员工档案）存到 SQLite。
保留与旧 JSON 实现一致的对外函数签名，方便上层 app.py 无缝切换。
旧的 data/*.json 仅用于一次性迁移（已完成），日常运行不再读取。
"""
import csv
import io
import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import openpyxl
except ImportError:
    openpyxl = None

# 项目根目录 (scripts -> 项目根目录)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')

# 可通过环境变量 LUXAI_DB_PATH 指定数据库路径（便于测试/多实例隔离）
DATABASE_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(DATA_DIR, 'app.db')

# 部门简称与全称映射
DEPT_SHORT_NAMES = ['五部', '六部', '七部', '八部']
DEPT_FULL_NAMES = {
    '五部': '硬件测试开发五部',
    '六部': '硬件测试开发六部',
    '七部': '硬件测试开发七部',
    '八部': '硬件测试开发八部'
}


def short_to_full(short_name: str) -> str:
    return DEPT_FULL_NAMES.get(short_name, short_name)


def full_to_short(full_name: str) -> str:
    for short, full in DEPT_FULL_NAMES.items():
        if full_name == full:
            return short
    return full_name


# 数据收集表格里有时用 HWTE5/HWTE6/HWTE7/HWTE8 表示五/六/七/八部
HWTE_DEPT_MAP = {'5': '五部', '6': '六部', '7': '七部', '8': '八部'}


def normalize_dept(value: Any) -> str:
    """把各种部门写法统一成短名（五部/六部/七部/八部）。

    支持：五部、硬件测试开发五部、HWTE5、HWTE-5、HWTE 5、hwte5、HWTE_5 等；
    无法识别时返回去掉首尾空白后的原文。
    """
    s = str(value or '').strip()
    if not s:
        return ''
    if s in DEPT_SHORT_NAMES:
        return s
    short = full_to_short(s)
    if short in DEPT_SHORT_NAMES:
        return short
    compact = s.upper().replace(' ', '').replace('-', '').replace('_', '')
    if compact.startswith('HWTE'):
        digit = compact[4:5]
        if digit in HWTE_DEPT_MAP:
            return HWTE_DEPT_MAP[digit]
    for d in DEPT_SHORT_NAMES:
        if d in s:
            return d
    return s


def get_data_path(filename: str) -> str:
    """返回数据目录下文件的路径（兼容旧调用）"""
    return os.path.join(DATA_DIR, filename)


# ===== 数据库连接管理 =====
# 每个线程一个连接，开启 WAL 提升并发读写，busy_timeout 避免锁冲突直接报错
_local = threading.local()


def _conn() -> sqlite3.Connection:
    c = getattr(_local, 'conn', None)
    if c is None:
        os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
        c = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL;')
        c.execute('PRAGMA busy_timeout=30000;')
        c.execute('PRAGMA foreign_keys=ON;')
        _local.conn = c
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS staff (
    department  TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    name        TEXT DEFAULT '',
    level       TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    email       TEXT DEFAULT '',
    PRIMARY KEY (department, employee_id)
);

CREATE TABLE IF NOT EXISTS staff_left (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT,
    name       TEXT,
    reason     TEXT,
    date       TEXT,
    operator   TEXT
);

CREATE TABLE IF NOT EXISTS staff_joined (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    department TEXT,
    name       TEXT,
    reason     TEXT,
    date       TEXT,
    operator   TEXT
);

CREATE TABLE IF NOT EXISTS personnel_files (
    employee_id       TEXT PRIMARY KEY,
    name              TEXT DEFAULT '',
    department        TEXT DEFAULT '',
    join_date         TEXT DEFAULT '',
    title             TEXT DEFAULT '',
    level             TEXT DEFAULT '',
    salary            TEXT DEFAULT '',
    equity            TEXT DEFAULT '',
    promotion         TEXT DEFAULT '',
    reward_punishment TEXT DEFAULT '',
    updated_at        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users (
    employee_id             TEXT PRIMARY KEY,
    name                    TEXT DEFAULT '',
    can_edit_department     INTEGER DEFAULT 0,
    can_edit_action_items   INTEGER DEFAULT 0,
    can_edit_info_list      INTEGER DEFAULT 0,
    can_edit_personnel_file TEXT DEFAULT 'NO',
    created_at              TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS action_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    dri        TEXT,
    eta        TEXT,
    status     TEXT,
    progress   TEXT,
    operator   TEXT,
    created_at TEXT,
    updated_at TEXT,
    extra_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS info_tables (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    headers_json TEXT,
    rows_json    TEXT,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS collector_sheets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT,
    headers_json TEXT,
    rows_json    TEXT,
    operator     TEXT,
    created_at   TEXT,
    locked       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT,
    operator    TEXT,
    employee_id TEXT,
    ip_address  TEXT,
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS revisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT,
    ref_id       INTEGER,
    payload_json TEXT,
    created_at   TEXT
);
"""


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _now_minute() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _migrated() -> bool:
    c = _conn()
    row = c.execute("SELECT value FROM meta WHERE key='migrated'").fetchone()
    return row is not None


def _mark_migrated():
    c = _conn()
    c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('migrated','1')")
    c.commit()


def _meta_get(key: str):
    row = _conn().execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def _meta_set(key: str, value: str = '1'):
    c = _conn()
    c.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', (key, value))
    c.commit()


def _snapshot_revision(kind: str, ref_id, payload) -> None:
    """在破坏性操作（改表头/删表）前保存一份快照，便于事后找回数据。
    仅保留最近 100 条，失败不影响主流程。"""
    try:
        c = _conn()
        c.execute('INSERT INTO revisions(kind,ref_id,payload_json,created_at) VALUES(?,?,?,?)',
                  (kind, int(ref_id) if str(ref_id).lstrip('-').isdigit() else None,
                   json.dumps(payload, ensure_ascii=False), _now_minute()))
        c.execute('DELETE FROM revisions WHERE id NOT IN '
                  '(SELECT id FROM revisions ORDER BY id DESC LIMIT 100)')
        c.commit()
    except Exception:
        pass


# ===== 用户表（从旧 users.json 一次性迁移）=====
def _migrate_users_from_json():
    """把 data/users.json 一次性导入 users 表（之后不再依赖该文件）"""
    if _meta_get('users_migrated'):
        return
    c = _conn()
    if c.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 0:
        path = os.path.join(DATA_DIR, 'users.json')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for u in data.get('users', []):
                    emp = str(u.get('employee_id', '')).strip()
                    if not emp:
                        continue
                    c.execute(
                        'INSERT OR IGNORE INTO users'
                        '(employee_id,name,can_edit_department,can_edit_action_items,'
                        'can_edit_info_list,can_edit_personnel_file,created_at)'
                        ' VALUES(?,?,?,?,?,?,?)',
                        (emp, u.get('name', ''),
                         1 if u.get('can_edit_department') else 0,
                         1 if u.get('can_edit_action_items') else 0,
                         1 if u.get('can_edit_info_list') else 0,
                         str(u.get('can_edit_personnel_file', 'NO')).strip(), _now_minute()))
                c.commit()
            except Exception:
                c.rollback()
    _meta_set('users_migrated')


# ===== 用户 CRUD =====
def get_all_users() -> List[Dict]:
    c = _conn()
    rows = c.execute('SELECT * FROM users ORDER BY employee_id').fetchall()
    return [dict(r) for r in rows]


def get_user(employee_id: str) -> Optional[Dict]:
    row = _conn().execute('SELECT * FROM users WHERE employee_id=?',
                          (str(employee_id).strip(),)).fetchone()
    return dict(row) if row else None


def upsert_user(record: Dict) -> bool:
    emp = str(record.get('employee_id', '')).strip()
    if not emp:
        return False
    c = _conn()
    exists = c.execute('SELECT 1 FROM users WHERE employee_id=?', (emp,)).fetchone()
    if exists:
        c.execute(
            'UPDATE users SET name=?, can_edit_department=?, can_edit_action_items=?,'
            ' can_edit_info_list=?, can_edit_personnel_file=? WHERE employee_id=?',
            (record.get('name', ''),
             1 if record.get('can_edit_department') else 0,
             1 if record.get('can_edit_action_items') else 0,
             1 if record.get('can_edit_info_list') else 0,
             str(record.get('can_edit_personnel_file', 'NO')).strip(), emp))
    else:
        c.execute(
            'INSERT INTO users(employee_id,name,can_edit_department,can_edit_action_items,'
            'can_edit_info_list,can_edit_personnel_file,created_at) VALUES(?,?,?,?,?,?,?)',
            (emp, record.get('name', ''),
             1 if record.get('can_edit_department') else 0,
             1 if record.get('can_edit_action_items') else 0,
             1 if record.get('can_edit_info_list') else 0,
             str(record.get('can_edit_personnel_file', 'NO')).strip(), _now_minute()))
    c.commit()
    return True


def delete_user(employee_id: str) -> bool:
    c = _conn()
    cur = c.execute('DELETE FROM users WHERE employee_id=?', (str(employee_id).strip(),))
    c.commit()
    return cur.rowcount > 0


def bootstrap_admin_if_empty():
    """user 表为空时，可用环境变量创建一个初始管理员，避免全新部署被锁在外面。
    需设置 ADMIN_EMPLOYEE_ID（可选 ADMIN_NAME）。"""
    c = _conn()
    if c.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] > 0:
        return
    emp = os.environ.get('ADMIN_EMPLOYEE_ID', '').strip()
    if not emp:
        return
    upsert_user({
        'employee_id': emp,
        'name': os.environ.get('ADMIN_NAME', 'Admin'),
        'can_edit_department': True,
        'can_edit_action_items': True,
        'can_edit_info_list': True,
        'can_edit_personnel_file': 'ALL'
    })


# ===== 一次性的 JSON -> SQLite 迁移 =====
def _load_json_file(filename: str):
    path = get_data_path(filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _migrate_all():
    """仅在数据库尚未迁移时，把现有 JSON 业务数据导入 SQLite。"""
    if _migrated():
        return
    c = _conn()
    try:
        # staff
        staff = _load_json_file('staff.json')
        if isinstance(staff, dict):
            for dept in DEPT_SHORT_NAMES:
                for m in staff.get(dept, []):
                    if not m:
                        continue
                    c.execute(
                        'INSERT OR IGNORE INTO staff(department,employee_id,name,level,phone,email) VALUES(?,?,?,?,?,?)',
                        (dept, str(m.get('employee_id', '')), m.get('name', ''),
                         m.get('level', ''), m.get('phone', ''), m.get('email', '')))
            for rec in staff.get('left', []):
                c.execute(
                    'INSERT INTO staff_left(department,name,reason,date,operator) VALUES(?,?,?,?,?)',
                    (rec.get('department', ''), rec.get('name', ''), rec.get('reason', ''),
                     rec.get('date', ''), rec.get('operator', '')))
        # action_items
        ai = _load_json_file('action_items.json')
        if isinstance(ai, dict):
            for it in ai.get('items', []):
                c.execute(
                    'INSERT INTO action_items(title,dri,eta,status,progress,operator,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                    (it.get('title', ''), it.get('dri', ''), it.get('eta', ''), it.get('status', ''),
                     it.get('progress', ''), it.get('operator', ''), it.get('created_at', ''), it.get('updated_at', '')))
        # info_list（records 列表顺序：旧的 history 是“最新在前”，这里无需处理）
        info = _load_json_file('info_list.json')
        if isinstance(info, dict):
            for t in info.get('tables', []):
                c.execute(
                    'INSERT INTO info_tables(name,headers_json,rows_json,created_at) VALUES(?,?,?,?)',
                    (t.get('name', ''), json.dumps(t.get('headers', []), ensure_ascii=False),
                     json.dumps(t.get('rows', []), ensure_ascii=False), t.get('created_at', '')))
        # collector
        col = _load_json_file('collector.json')
        if isinstance(col, dict):
            for s in col.get('sheets', []):
                c.execute(
                    'INSERT INTO collector_sheets(name,headers_json,rows_json,operator,created_at) VALUES(?,?,?,?,?)',
                    (s.get('name', ''), json.dumps(s.get('headers', []), ensure_ascii=False),
                     json.dumps(s.get('rows', []), ensure_ascii=False), s.get('operator', ''), s.get('created_at', '')))
        # history（JSON 里 records 是最新在前；倒序写入，让 SQLite 里 id 大的为最新）
        hist = _load_json_file('history.json')
        if isinstance(hist, dict):
            records = list(reversed(hist.get('records', [])))
            for r in records:
                c.execute(
                    'INSERT INTO history(action,operator,employee_id,ip_address,timestamp) VALUES(?,?,?,?,?)',
                    (r.get('action', ''), r.get('operator', ''), r.get('employee_id', ''),
                     r.get('ip_address', ''), r.get('timestamp', '')))
        c.commit()
        _mark_migrated()
    except Exception:
        c.rollback()
        raise


# ===== 历史记录 =====
def add_history(action: str, operator: str, employee_id: str = '', ip_address: str = '') -> None:
    """新增一条历史记录，并只保留最近 500 条"""
    c = _conn()
    c.execute('INSERT INTO history(action,operator,employee_id,ip_address,timestamp) VALUES(?,?,?,?,?)',
              (action, operator, employee_id, ip_address, _now()))
    # 保留最近 500 条
    c.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 500)')
    c.commit()


def get_history(limit: int = 100) -> List[Dict]:
    """返回历史记录，最新在前"""
    c = _conn()
    rows = c.execute('SELECT * FROM history ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
    return [dict(r) for r in rows]


# ===== 人员信息 =====
def get_all_staff() -> Dict[str, Any]:
    """以旧 JSON 结构返回全部人员（兼容旧调用）：{部门: [成员], 'left': [...]}"""
    c = _conn()
    result = {d: [] for d in DEPT_SHORT_NAMES}
    for row in c.execute('SELECT * FROM staff ORDER BY employee_id'):
        r = dict(row)
        result.setdefault(r['department'], []).append({
            'employee_id': r['employee_id'],
            'name': r['name'],
            'level': r['level'],
            'phone': r['phone'],
            'email': r['email'],
        })
    result['left'] = _all_left_records()
    return result


def _all_left_records() -> List[Dict]:
    c = _conn()
    rows = c.execute('SELECT * FROM staff_left ORDER BY id DESC').fetchall()
    return [dict(r) for r in rows]


def _all_joined_records() -> List[Dict]:
    c = _conn()
    rows = c.execute('SELECT * FROM staff_joined ORDER BY id DESC').fetchall()
    return [dict(r) for r in rows]


def get_department_staff(dept: str = None) -> List[Dict]:
    """获取指定部门人员；dept 为 None 或 '全体' 时返回所有部门（不带 department 字段）"""
    c = _conn()
    if dept is None or dept == '全体':
        rows = c.execute('SELECT * FROM staff ORDER BY employee_id').fetchall()
        return [{k: r[k] for k in ('employee_id', 'name', 'level', 'phone', 'email')} for r in rows]
    rows = c.execute('SELECT * FROM staff WHERE department=? ORDER BY employee_id', (dept,)).fetchall()
    return [{k: r[k] for k in ('employee_id', 'name', 'level', 'phone', 'email')} for r in rows]


def get_department_summary() -> Dict[str, Dict]:
    c = _conn()
    cur_ym = datetime.now().strftime('%Y-%m')
    summary = {}
    for dept in DEPT_SHORT_NAMES:
        cur = c.execute('SELECT COUNT(*) AS n FROM staff WHERE department=?', (dept,)).fetchone()['n']
        left = c.execute('SELECT COUNT(*) AS n FROM staff_left WHERE department=?', (dept,)).fetchone()['n']
        left_month = c.execute(
            "SELECT COUNT(*) AS n FROM staff_left WHERE department=? AND substr(date,1,7)=?",
            (dept, cur_ym)).fetchone()['n']
        summary[dept] = {'current': cur, 'left_total': left, 'left_month': left_month}
    return summary


def get_department_detail(dept: str) -> Dict[str, Any]:
    if dept not in DEPT_SHORT_NAMES:
        return {'current': [], 'joined': [], 'left': []}
    c = _conn()
    current = []
    for row in c.execute('SELECT * FROM staff WHERE department=? ORDER BY employee_id', (dept,)):
        member = {k: row[k] for k in ('employee_id', 'name', 'level', 'phone', 'email')}
        member['department'] = dept
        current.append(member)
    joined = [dict(r) for r in c.execute(
        'SELECT * FROM staff_joined WHERE department=? ORDER BY id DESC', (dept,))]
    left = [dict(r) for r in c.execute(
        'SELECT * FROM staff_left WHERE department=? ORDER BY id DESC', (dept,))]
    return {'current': current, 'joined': joined, 'left': left}


def get_department_all() -> Dict[str, Any]:
    c = _conn()
    all_current = []
    total = 0
    dept_counts = {}
    for dept in DEPT_SHORT_NAMES:
        rows = c.execute('SELECT * FROM staff WHERE department=? ORDER BY employee_id', (dept,)).fetchall()
        dept_counts[dept] = len(rows)
        total += len(rows)
        for r in rows:
            member = {k: r[k] for k in ('employee_id', 'name', 'level', 'phone', 'email')}
            member['department'] = dept
            all_current.append(member)
    return {
        'current': all_current,
        'total_count': total,
        'departments': dept_counts,
        'joined': _all_joined_records(),
        'left': _all_left_records()
    }


def add_staff_to_department(dept: str, member: Dict, operator: str = 'System',
                            employee_id: str = '', ip_address: str = '') -> bool:
    if dept not in DEPT_SHORT_NAMES:
        return False
    emp = str(member.get('employee_id', '')).strip()
    if not emp:
        return False
    c = _conn()
    dup = c.execute('SELECT 1 FROM staff WHERE department=? AND employee_id=?',
                    (dept, emp)).fetchone()
    if dup:
        return False
    c.execute('INSERT INTO staff(department,employee_id,name,level,phone,email) VALUES(?,?,?,?,?,?)',
              (dept, emp, member.get('name', ''), member.get('level', ''),
               member.get('phone', ''), member.get('email', '')))
    c.commit()
    add_history(f"添加人员: {member.get('name', 'Unknown')} 到 {dept}", operator, employee_id, ip_address)
    return True


def update_department_members(dept: str, members: List[Dict], operator: str = 'System',
                              employee_id: str = '', ip_address: str = '') -> None:
    if dept not in DEPT_SHORT_NAMES:
        return
    c = _conn()
    c.execute('DELETE FROM staff WHERE department=?', (dept,))
    for m in members:
        emp = str(m.get('employee_id', '')).strip()
        if not emp:
            continue
        c.execute('INSERT INTO staff(department,employee_id,name,level,phone,email) VALUES(?,?,?,?,?,?)',
                  (dept, emp, m.get('name', ''), m.get('level', ''),
                   m.get('phone', ''), m.get('email', '')))
    c.commit()
    add_history(f"更新 {dept} 成员列表 ({len(members)} 人)", operator, employee_id, ip_address)


def remove_staff_from_department(dept: str, staff_employee_id: str, operator: str = 'System',
                                 op_employee_id: str = '', ip_address: str = '') -> bool:
    c = _conn()
    row = c.execute('SELECT name FROM staff WHERE department=? AND employee_id=?',
                    (dept, staff_employee_id)).fetchone()
    if not row:
        return False
    name = row['name']
    c.execute('DELETE FROM staff WHERE department=? AND employee_id=?', (dept, staff_employee_id))
    c.commit()
    add_history(f"移除人员: {name} 从 {dept}", operator, op_employee_id, ip_address)
    return True


def add_left_record(record: Dict, operator: str = 'System',
                    op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    c.execute('INSERT INTO staff_left(department,name,reason,date,operator) VALUES(?,?,?,?,?)',
              (record.get('department', ''), record.get('name', ''), record.get('reason', ''),
               record.get('date', ''), operator))
    c.commit()
    add_history(f"{record.get('name', 'Unknown')} 离职 ({record.get('department', '')})",
                operator, op_employee_id, ip_address)


def add_joined_record(record: Dict, operator: str = 'System',
                      op_employee_id: str = '', ip_address: str = '') -> None:
    """新增一条入职记录（record: department/name/reason/date）"""
    c = _conn()
    c.execute('INSERT INTO staff_joined(department,name,reason,date,operator) VALUES(?,?,?,?,?)',
              (record.get('department', ''), record.get('name', ''), record.get('reason', ''),
               record.get('date', ''), operator))
    c.commit()
    add_history(f"{record.get('name', 'Unknown')} 入职 ({record.get('department', '')})",
                operator, op_employee_id, ip_address)


def find_staff_id_by_name(dept: str, name: str):
    """在指定部门内按姓名精确查找，返回唯一匹配的 employee_id；无匹配或多个同名返回 None"""
    c = _conn()
    rows = c.execute('SELECT employee_id FROM staff WHERE department=? AND name=?', (dept, name)).fetchall()
    if len(rows) == 1:
        return rows[0]['employee_id']
    return None


def update_staff_member(dept: str, employee_id: str, fields: Dict,
                        operator: str = 'System', op_employee_id: str = '',
                        ip_address: str = '') -> bool:
    """编辑某在职人员的信息（fields: name/level/phone/email），返回是否找到并更新"""
    if dept not in DEPT_SHORT_NAMES:
        return False
    c = _conn()
    emp = str(employee_id).strip()
    if not emp:
        return False
    exists = c.execute('SELECT 1 FROM staff WHERE department=? AND employee_id=?', (dept, emp)).fetchone()
    if not exists:
        return False
    sets, vals = [], []
    for k in ('name', 'level', 'phone', 'email'):
        if k in fields:
            sets.append(f'{k}=?')
            vals.append(str(fields.get(k, '')))
    if sets:
        vals.extend((dept, emp))
        c.execute(f'UPDATE staff SET {", ".join(sets)} WHERE department=? AND employee_id=?', vals)
        c.commit()
        add_history(f"更新人员: {fields.get('name', emp)} ({dept})", operator, op_employee_id, ip_address)
    return True


_RECORD_TABLES = {'joined': 'staff_joined', 'left': 'staff_left'}


def _record_table(rec_type: str):
    return _RECORD_TABLES.get(rec_type)


def update_department_record(rec_type: str, rec_id: int, fields: Dict) -> bool:
    """编辑某条入职/离职记录（可改 name/date/reason），返回是否找到并更新"""
    table = _record_table(rec_type)
    if table is None:
        return False
    c = _conn()
    exists = c.execute(f'SELECT 1 FROM {table} WHERE id=?', (rec_id,)).fetchone()
    if not exists:
        return False
    sets, vals = [], []
    for k in ('name', 'date', 'reason'):
        if k in fields:
            sets.append(f'{k}=?')
            vals.append(str(fields.get(k, '')))
    if not sets:
        return True
    vals.append(rec_id)
    c.execute(f'UPDATE {table} SET {", ".join(sets)} WHERE id=?', vals)
    c.commit()
    return True


def delete_department_record(rec_type: str, rec_id: int) -> bool:
    """删除某条入职/离职记录"""
    table = _record_table(rec_type)
    if table is None:
        return False
    c = _conn()
    cur = c.execute(f'DELETE FROM {table} WHERE id=?', (rec_id,))
    c.commit()
    return cur.rowcount > 0


# ===== 员工档案（人事档案）=====
# 数据来源：项目根目录 "档案信息.xlsx"；首次访问时把该员工档案落库，
# 之后编辑结果保存在 personnel_files 表中（Excel 作为初始/缺省来源）。
PERSONNEL_FILE_PATH = os.path.join(PROJECT_DIR, '档案信息.xlsx')

_personnel_cache = {'mtime': None, 'data': {}}


def _fmt_date_value(value) -> str:
    """把 Excel 里的日期（datetime/字符串）规范成 YYYY-MM-DD"""
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    s = str(value).strip()
    if not s:
        return ''
    for sep in ('-', '/', '.'):
        if sep in s:
            parts = s.split(' ')[0].split(sep)
            if len(parts) == 3:
                try:
                    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                    return f'{y:04d}-{m:02d}-{d:02d}'
                except ValueError:
                    return s
    return s


def _num_to_str(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _calc_seniority(join_date: str) -> str:
    """按入职日期计算司龄（年，保留 2 位小数）"""
    if not join_date:
        return ''
    d = None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            d = datetime.strptime(str(join_date).strip(), fmt)
            break
        except ValueError:
            continue
    if d is None:
        return ''
    years = (datetime.now() - d).days / 365.25
    return f'{years:.2f}'


def _load_personnel_excel() -> Dict[str, Dict]:
    """读取并缓存 档案信息.xlsx，返回 {工号: 档案字段}"""
    if openpyxl is None or not os.path.exists(PERSONNEL_FILE_PATH):
        return {}
    try:
        mtime = os.path.getmtime(PERSONNEL_FILE_PATH)
    except OSError:
        return {}
    if _personnel_cache['mtime'] == mtime and _personnel_cache['data']:
        return _personnel_cache['data']

    try:
        wb = openpyxl.load_workbook(PERSONNEL_FILE_PATH, data_only=True)
    except Exception:
        return {}
    ws = wb.worksheets[0]
    headers = [('' if c.value is None else str(c.value)) for c in ws[1]]

    def find_col(*keywords):
        for i, h in enumerate(headers):
            for kw in keywords:
                if kw in h:
                    return i
        return None

    emp_i = find_col('工号')
    name_i = find_col('姓名')
    dept_i = find_col('部门')
    join_i = find_col('入职日期')
    title_i = find_col('职务')
    level_i = find_col('职级', '级别')
    salary_i = find_col('薪资')
    equity_i = find_col('股权')
    reward_i = find_col('奖惩')
    promo_cols = [i for i, h in enumerate(headers) if '晋升' in h]

    data = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        if emp_i is None or emp_i >= len(r) or r[emp_i] is None:
            continue
        emp = _num_to_str(r[emp_i])
        if not emp:
            continue

        def cell(idx):
            if idx is None or idx >= len(r) or r[idx] is None:
                return ''
            return str(r[idx]).strip()

        promotions = []
        for i in promo_cols:
            val = cell(i)
            if val.upper() in ('Y', 'YES', 'TRUE', '是', '1'):
                label = headers[i].split('是否晋升')[0].replace('\n', ' ').strip()
                promotions.append(f'{label} 晋升')

        dept_full = cell(dept_i)
        data[emp] = {
            'employee_id': emp,
            'name': cell(name_i),
            'department': full_to_short(dept_full) if dept_full else '',
            'join_date': _fmt_date_value(r[join_i]) if (join_i is not None and join_i < len(r)) else '',
            'title': cell(title_i),
            'level': cell(level_i),
            'salary': _num_to_str(r[salary_i]) if (salary_i is not None and salary_i < len(r)) else '',
            'equity': cell(equity_i),
            'promotion': '\n'.join(promotions),
            'reward_punishment': cell(reward_i),
        }
    _personnel_cache['mtime'] = mtime
    _personnel_cache['data'] = data
    return data


def get_personnel_file(employee_id: str) -> Optional[Dict]:
    """获取员工档案：优先取库；没有则从 Excel / 在职人员初始化后落库"""
    emp = str(employee_id or '').strip()
    if not emp:
        return None
    c = _conn()
    row = c.execute('SELECT * FROM personnel_files WHERE employee_id=?', (emp,)).fetchone()
    if row is None:
        # 库中无档案：用当前在职人员信息建一条空白档案（供后续编辑），不再读取 Excel
        s = c.execute('SELECT name, department FROM staff WHERE employee_id=? LIMIT 1',
                      (emp,)).fetchone()
        base = {
            'employee_id': emp,
            'name': s['name'] if s else '',
            'department': s['department'] if s else '',
            'join_date': '', 'title': '', 'level': '', 'salary': '',
            'equity': '', 'promotion': '', 'reward_punishment': ''
        }
        c.execute(
            'INSERT OR IGNORE INTO personnel_files'
            '(employee_id,name,department,join_date,title,level,salary,equity,promotion,reward_punishment,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (emp, base.get('name', ''), base.get('department', ''), base.get('join_date', ''),
             base.get('title', ''), base.get('level', ''), base.get('salary', ''),
             base.get('equity', ''), base.get('promotion', ''), base.get('reward_punishment', ''),
             _now_minute()))
        c.commit()
        row = c.execute('SELECT * FROM personnel_files WHERE employee_id=?', (emp,)).fetchone()
    rec = dict(row) if row else None
    if rec:
        rec['seniority'] = _calc_seniority(rec.get('join_date', ''))
        # 电话取自当前在职人员数据（staff 表），实时读取，便于与部门信息保持一致
        s = c.execute('SELECT phone FROM staff WHERE employee_id=? LIMIT 1', (emp,)).fetchone()
        rec['phone'] = (s['phone'] if s and s['phone'] else '')
    return rec


def update_personnel_file(employee_id: str, fields: Dict) -> bool:
    """更新员工档案（join_date/title/level/salary/equity/promotion/reward_punishment）"""
    emp = str(employee_id or '').strip()
    if not emp:
        return False
    get_personnel_file(emp)  # 确保记录存在
    c = _conn()
    allowed = ('join_date', 'title', 'level', 'salary', 'equity',
               'promotion', 'reward_punishment')
    sets, vals = [], []
    for k in allowed:
        if k in fields:
            sets.append(f'{k}=?')
            vals.append(str(fields.get(k, '')))
    if not sets:
        return True
    sets.append('updated_at=?')
    vals.append(_now_minute())
    vals.append(emp)
    c.execute(f'UPDATE personnel_files SET {", ".join(sets)} WHERE employee_id=?', vals)
    c.commit()
    return True


def import_personnel_files_from_excel_once() -> int:
    """一次性把 档案信息.xlsx 全部导入 personnel_files，并为所有在职人员补齐空白档案。
    完成后写入 meta 标记，之后程序不再读取该 Excel（可安全删除该文件）。"""
    if _meta_get('personnel_files_imported'):
        return 0
    data = _load_personnel_excel()
    c = _conn()
    now = _now_minute()
    for emp, base in data.items():
        c.execute(
            'INSERT OR IGNORE INTO personnel_files'
            '(employee_id,name,department,join_date,title,level,salary,equity,promotion,reward_punishment,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (emp, base.get('name', ''), base.get('department', ''), base.get('join_date', ''),
             base.get('title', ''), base.get('level', ''), base.get('salary', ''),
             base.get('equity', ''), base.get('promotion', ''), base.get('reward_punishment', ''),
             now))
    # 在职人员若不在 Excel 中，也建一条空白档案，保证人人有档案
    for r in c.execute('SELECT employee_id, name, department FROM staff'):
        c.execute('INSERT OR IGNORE INTO personnel_files(employee_id,name,department,updated_at)'
                  ' VALUES(?,?,?,?)',
                  (r['employee_id'], r['name'], r['department'], now))
    c.commit()
    _meta_set('personnel_files_imported')
    return c.execute('SELECT COUNT(*) AS n FROM personnel_files').fetchone()['n']


# ===== Action Items =====
# 列配置：内置列（key 固定、不可删除）+ 自定义列（存储在 extra_json 中）。
ACTION_BASE_COLUMNS = [
    {'key': 'title', 'label': '标题', 'builtin': True},
    {'key': 'progress', 'label': '进度', 'builtin': True},
    {'key': 'eta', 'label': 'ETA', 'builtin': True},
    {'key': 'dri', 'label': 'DRI', 'builtin': True},
    {'key': 'status', 'label': '状态', 'builtin': True},
]


def get_action_columns() -> List[Dict]:
    """获取 Action Items 的列配置（含内置列改名与自定义列）"""
    raw = _meta_get('action_items_columns')
    if not raw:
        return [dict(c) for c in ACTION_BASE_COLUMNS]
    try:
        cols = json.loads(raw)
        if isinstance(cols, list) and cols:
            return cols
    except Exception:
        pass
    return [dict(c) for c in ACTION_BASE_COLUMNS]


def set_action_columns(columns: List[Dict]) -> bool:
    """保存 Action Items 列配置。内置列必须保留（key 不可变），自定义列 key 以 c_ 前缀。"""
    base_keys = {c['key'] for c in ACTION_BASE_COLUMNS}
    clean = []
    seen = set()
    for c in columns or []:
        key = str(c.get('key', '')).strip()
        label = str(c.get('label', '')).strip()
        if not key or not label or key in seen:
            continue
        if key in base_keys:
            clean.append({'key': key, 'label': label, 'builtin': True})
        else:
            if not key.startswith('c_'):
                continue
            clean.append({'key': key, 'label': label, 'builtin': False})
        seen.add(key)
    # 内置列必须齐全
    if not base_keys.issubset(seen):
        return False
    _meta_set('action_items_columns', json.dumps(clean, ensure_ascii=False))
    return True


def _action_row_to_dict(row) -> Dict:
    d = dict(row)
    try:
        d['extra'] = json.loads(d.get('extra_json') or '{}')
    except Exception:
        d['extra'] = {}
    return d


def get_all_action_items() -> List[Dict]:
    c = _conn()
    rows = c.execute('SELECT * FROM action_items ORDER BY id ASC').fetchall()
    return [_action_row_to_dict(r) for r in rows]


def add_action_item(item: Dict, ip_address: str = '', op_employee_id: str = '') -> None:
    c = _conn()
    extra = item.get('extra', {}) or {}
    cur = c.execute(
        'INSERT INTO action_items(title,dri,eta,status,progress,operator,created_at,extra_json)'
        ' VALUES(?,?,?,?,?,?,?,?)',
        (item.get('title', ''), item.get('dri', ''), item.get('eta', ''),
         item.get('status', '进行中'), item.get('progress', ''), item.get('operator', ''),
         _now_minute(), json.dumps(extra, ensure_ascii=False)))
    item['id'] = cur.lastrowid
    item['created_at'] = _now_minute()
    c.commit()
    add_history(f"添加 Action Item: {item.get('title', '')}", item.get('operator', 'System'),
                op_employee_id or item.get('employee_id', ''), ip_address)


def update_action_item(item_id: int, updates: Dict, ip_address: str = '',
                       op_employee_id: str = '') -> None:
    c = _conn()
    cur = c.execute('SELECT title FROM action_items WHERE id=?', (item_id,)).fetchone()
    title = (cur['title'] if cur else '') or ''
    fields = ['title', 'dri', 'eta', 'status', 'progress', 'operator']
    sets = []
    vals = []
    for f in fields:
        if f in updates:
            sets.append(f'{f}=?')
            vals.append(updates[f])
    if 'extra' in updates:
        sets.append('extra_json=?')
        vals.append(json.dumps(updates.get('extra') or {}, ensure_ascii=False))
    if not sets:
        return
    sets.append('updated_at=?')
    vals.append(_now_minute())
    vals.append(item_id)
    set_clause = ', '.join(sets)
    c.execute('UPDATE action_items SET ' + set_clause + ' WHERE id=?', vals)
    c.commit()
    name = updates.get('title') or title
    add_history(f"更新 Action Item「{name}」" if name else "更新 Action Item",
                updates.get('operator', 'System'),
                op_employee_id or updates.get('employee_id', ''), ip_address)


def delete_action_item(item_id: int, operator: str = 'System',
                       op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    cur = c.execute('SELECT title FROM action_items WHERE id=?', (item_id,)).fetchone()
    title = (cur['title'] if cur else '') or ''
    c.execute('DELETE FROM action_items WHERE id=?', (item_id,))
    c.commit()
    add_history(f"删除 Action Item「{title}」" if title else "删除 Action Item",
                operator, op_employee_id, ip_address)


# ===== 信息列表（多表，表结构与行内容自由，rows 以 JSON 存于单行）=====
def get_all_info_list() -> List[Dict]:
    c = _conn()
    rows = c.execute('SELECT * FROM info_tables ORDER BY id ASC').fetchall()
    out = []
    for r in rows:
        out.append({
            'id': r['id'],
            'name': r['name'],
            'headers': json.loads(r['headers_json'] or '[]'),
            'rows': json.loads(r['rows_json'] or '[]'),
            'created_at': r['created_at'],
        })
    return out


def _get_info_table(table_id: int):
    return _conn().execute('SELECT * FROM info_tables WHERE id=?', (table_id,)).fetchone()


def create_info_table(name: str, headers: List[str] = None, operator: str = 'System',
                      op_employee_id: str = '', ip_address: str = '') -> int:
    if not headers:
        headers = ['Key', 'Value']
    c = _conn()
    cur = c.execute('INSERT INTO info_tables(name,headers_json,rows_json,created_at) VALUES(?,?,?,?)',
                    (name, json.dumps(list(headers), ensure_ascii=False), '[]', _now_minute()))
    table_id = cur.lastrowid
    c.commit()
    add_history(f"创建信息表: {name}", operator, op_employee_id, ip_address)
    return table_id


def add_info_row(table_id: int, row: Dict, operator: str = 'System',
                 op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = _get_info_table(table_id)
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    rows.append(row)
    c.execute('UPDATE info_tables SET rows_json=? WHERE id=?',
              (json.dumps(rows, ensure_ascii=False), table_id))
    c.commit()
    add_history(f"信息表「{t['name']}」添加数据", operator, op_employee_id, ip_address)


def update_info_row(table_id: int, row_index: int, row: Dict, operator: str = 'System',
                    op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = _get_info_table(table_id)
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    if 0 <= row_index < len(rows):
        rows[row_index] = row
        c.execute('UPDATE info_tables SET rows_json=? WHERE id=?',
                  (json.dumps(rows, ensure_ascii=False), table_id))
        c.commit()
    add_history(f"信息表「{t['name']}」更新第 {row_index + 1} 行", operator, op_employee_id, ip_address)


def delete_info_table(table_id: int, operator: str = 'System',
                      op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = c.execute('SELECT * FROM info_tables WHERE id=?', (table_id,)).fetchone()
    if t:
        _snapshot_revision('info_table', table_id, {
            'name': t['name'], 'headers': json.loads(t['headers_json'] or '[]'),
            'rows': json.loads(t['rows_json'] or '[]')})
    c.execute('DELETE FROM info_tables WHERE id=?', (table_id,))
    c.commit()
    add_history(f"删除信息表「{t['name']}」" if t else "删除信息表", operator, op_employee_id, ip_address)


def delete_info_row(table_id: int, row_index: int, operator: str = 'System',
                    op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = _get_info_table(table_id)
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    if 0 <= row_index < len(rows):
        rows.pop(row_index)
        c.execute('UPDATE info_tables SET rows_json=? WHERE id=?',
                  (json.dumps(rows, ensure_ascii=False), table_id))
        c.commit()
    add_history(f"信息表「{t['name']}」删除第 {row_index + 1} 行", operator, op_employee_id, ip_address)


def update_info_table_headers(table_id: int, new_headers: List[str], operator: str = 'System',
                              op_employee_id: str = '', ip_address: str = '') -> bool:
    """修改信息表的表头（重命名/新增/删除列），并按列顺序迁移已有数据。
    - 重命名：旧列数据移动到新列名下
    - 新增列：已有行该列填空
    - 删除列：丢弃该列数据
    """
    new_headers = [str(h).strip() for h in (new_headers or []) if str(h).strip()]
    if not new_headers:
        return False
    c = _conn()
    t = _get_info_table(table_id)
    if not t:
        return False
    old_headers = json.loads(t['headers_json'] or '[]')
    rows = json.loads(t['rows_json'] or '[]')
    _snapshot_revision('info_headers', table_id, {'headers': old_headers, 'rows': rows})
    new_rows = []
    for row in rows:
        nr = {}
        for i, nh in enumerate(new_headers):
            val = ''
            if i < len(old_headers):
                old_key = old_headers[i]
                if old_key in row:
                    val = row[old_key]
            if not val and nh in row:   # 兼容同名列直接命中
                val = row[nh]
            nr[nh] = val
        new_rows.append(nr)
    c.execute('UPDATE info_tables SET headers_json=?, rows_json=? WHERE id=?',
              (json.dumps(new_headers, ensure_ascii=False),
               json.dumps(new_rows, ensure_ascii=False), table_id))
    c.commit()
    add_history(f"信息表「{t['name']}」修改表头", operator, op_employee_id, ip_address)
    return True


# ===== 数据收集表格 =====
def _all_collector_rows():
    c = _conn()
    return c.execute('SELECT * FROM collector_sheets ORDER BY id ASC').fetchall()


def get_collector_sheets() -> List[Dict]:
    out = []
    for r in _all_collector_rows():
        out.append({
            'id': r['id'],
            'name': r['name'],
            'headers': json.loads(r['headers_json'] or '[]'),
            'rows': json.loads(r['rows_json'] or '[]'),
            'operator': r['operator'] or '',
            'created_at': r['created_at'],
            'locked': int(r['locked'] or 0),
        })
    return out


def get_collector_sheet(sheet_id: int) -> Optional[Dict]:
    r = _conn().execute('SELECT * FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not r:
        return None
    return {
        'id': r['id'],
        'name': r['name'],
        'headers': json.loads(r['headers_json'] or '[]'),
        'rows': json.loads(r['rows_json'] or '[]'),
        'operator': r['operator'] or '',
        'created_at': r['created_at'],
        'locked': int(r['locked'] or 0),
    }


def set_collector_sheet_locked(sheet_id: int, locked: bool, operator: str = 'System',
                               op_employee_id: str = '', ip_address: str = '') -> bool:
    """设置收集表格的锁定状态（锁定后不可删除）"""
    c = _conn()
    t = c.execute('SELECT name FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not t:
        return False
    c.execute('UPDATE collector_sheets SET locked=? WHERE id=?', (1 if locked else 0, sheet_id))
    c.commit()
    add_history(f"{'锁定' if locked else '解锁'}收集表格: {t['name']}",
                operator, op_employee_id, ip_address)
    return True


def is_collector_sheet_locked(sheet_id: int) -> bool:
    r = _conn().execute('SELECT locked FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    return bool(r and r['locked'])


def create_collector_sheet(sheet: Dict, ip_address: str = '', op_employee_id: str = '') -> None:
    c = _conn()
    cur = c.execute(
        'INSERT INTO collector_sheets(name,headers_json,rows_json,operator,created_at) VALUES(?,?,?,?,?)',
        (sheet.get('name', ''), json.dumps(sheet.get('headers', []), ensure_ascii=False),
         '[]', sheet.get('operator', ''), _now_minute()))
    sheet['id'] = cur.lastrowid
    sheet['created_at'] = _now_minute()
    c.commit()
    add_history(f"创建收集表格: {sheet.get('name', '')}", sheet.get('operator', 'System'),
                op_employee_id or sheet.get('employee_id', ''), ip_address)


def add_collector_row(sheet_id: int, row: Dict, ip_address: str = '',
                      op_employee_id: str = '') -> None:
    c = _conn()
    t = _conn().execute('SELECT name, rows_json FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    row['created_at'] = _now_minute()
    rows.append(row)
    c.execute('UPDATE collector_sheets SET rows_json=? WHERE id=?',
              (json.dumps(rows, ensure_ascii=False), sheet_id))
    c.commit()
    add_history(f"收集表格「{t['name']}」添加数据", row.get('operator', 'System'),
                op_employee_id or row.get('employee_id', ''), ip_address)


def update_collector_row(sheet_id: int, row_index: int, row_data: Dict, ip_address: str = '',
                         op_employee_id: str = '') -> None:
    c = _conn()
    t = c.execute('SELECT name, rows_json FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    if 0 <= row_index < len(rows):
        if isinstance(rows[row_index], dict):
            rows[row_index].update(row_data)
            rows[row_index]['updated_at'] = _now_minute()
        else:
            rows[row_index] = row_data
        c.execute('UPDATE collector_sheets SET rows_json=? WHERE id=?',
                  (json.dumps(rows, ensure_ascii=False), sheet_id))
        c.commit()
    add_history(f"收集表格「{t['name']}」更新第 {row_index + 1} 行", row_data.get('operator', 'System'),
                op_employee_id or row_data.get('employee_id', ''), ip_address)


def delete_collector_row(sheet_id: int, row_index: int, operator: str = 'System',
                         op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = c.execute('SELECT name, rows_json FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not t:
        return
    rows = json.loads(t['rows_json'] or '[]')
    if 0 <= row_index < len(rows):
        rows.pop(row_index)
        c.execute('UPDATE collector_sheets SET rows_json=? WHERE id=?',
                  (json.dumps(rows, ensure_ascii=False), sheet_id))
        c.commit()
    add_history(f"收集表格「{t['name']}」删除第 {row_index + 1} 行", operator, op_employee_id, ip_address)


def delete_collector_sheet(sheet_id: int, operator: str = 'System',
                           op_employee_id: str = '', ip_address: str = '') -> None:
    c = _conn()
    t = c.execute('SELECT name FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    sheet_name = t['name'] if t else ''
    full = c.execute('SELECT * FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if full:
        _snapshot_revision('collector_sheet', sheet_id, {
            'name': full['name'], 'headers': json.loads(full['headers_json'] or '[]'),
            'rows': json.loads(full['rows_json'] or '[]')})
    c.execute('DELETE FROM collector_sheets WHERE id=?', (sheet_id,))
    c.commit()
    if sheet_name:
        add_history(f"删除收集表格: {sheet_name}", operator, op_employee_id, ip_address)


def update_collector_sheet_headers(sheet_id: int, new_headers: List[str], operator: str = 'System',
                                   op_employee_id: str = '', ip_address: str = '') -> bool:
    """修改收集表格的表头（重命名/新增/删除列），并按列顺序迁移已有数据。
    行的键为 header 的小写形式（与新增/编辑行时一致）。"""
    new_headers = [str(h).strip() for h in (new_headers or []) if str(h).strip()]
    if not new_headers:
        return False
    c = _conn()
    t = c.execute('SELECT * FROM collector_sheets WHERE id=?', (sheet_id,)).fetchone()
    if not t:
        return False
    old_headers = json.loads(t['headers_json'] or '[]')
    rows = json.loads(t['rows_json'] or '[]')
    _snapshot_revision('collector_headers', sheet_id, {'headers': old_headers, 'rows': rows})
    new_rows = []
    for row in rows:
        nr = {}
        for i, nh in enumerate(new_headers):
            key = nh.lower()
            val = ''
            if i < len(old_headers):
                old_key = str(old_headers[i]).lower()
                if old_key in row:
                    val = row[old_key]
            if not val and key in row:   # 兼容同名列直接命中
                val = row[key]
            nr[key] = val
        # 保留系统字段（操作人/时间等），避免丢失
        for syskey in ('operator', 'created_at', 'updated_at', 'employee_id'):
            if syskey in row:
                nr[syskey] = row[syskey]
        new_rows.append(nr)
    c.execute('UPDATE collector_sheets SET headers_json=?, rows_json=? WHERE id=?',
              (json.dumps(new_headers, ensure_ascii=False),
               json.dumps(new_rows, ensure_ascii=False), sheet_id))
    c.commit()
    add_history(f"收集表格「{t['name']}」修改表头", operator, op_employee_id, ip_address)
    return True


def get_personnel_files_by_dept(dept: str) -> List[Dict]:
    """按部门取员工档案（用于部门分析中的奖惩信息）"""
    rows = _conn().execute(
        'SELECT * FROM personnel_files WHERE department=? ORDER BY employee_id', (dept,)).fetchall()
    return [dict(r) for r in rows]


def find_collector_sheet_by_name(keyword: str) -> Optional[Dict]:
    """按名称关键字查找收集表格（如 '专利'、'研发立项'、'激励专案'）"""
    r = _conn().execute(
        "SELECT * FROM collector_sheets WHERE name LIKE ? ORDER BY id LIMIT 1",
        ('%' + keyword + '%',)).fetchone()
    if not r:
        return None
    return {
        'id': r['id'],
        'name': r['name'],
        'headers': json.loads(r['headers_json'] or '[]'),
        'rows': json.loads(r['rows_json'] or '[]'),
    }


# 奖惩信息的简易分类关键字（用于把“奖惩信息”拆成奖励行 / 惩罚行）
REWARD_KEYWORDS = ('奖励', '表彰', '表扬', '嘉奖', '奖金', '记功', '荣誉', '奖状', '激励')
PUNISH_KEYWORDS = ('惩处', '警告', '大过', '小过', '记过', '申诫', '处罚', '罚款', '异常', '处分')


def classify_reward_punishment(text: str):
    """把奖惩信息按行拆分为 (奖励行列表, 惩罚行列表)。
    含奖励关键字且不含惩罚关键字的行 → 奖励；其余（含惩罚关键字或无关键字）→ 惩罚。"""
    rewards, punishments = [], []
    for line in str(text or '').split('\n'):
        s = line.strip()
        if not s:
            continue
        is_reward = any(k in s for k in REWARD_KEYWORDS) and not any(k in s for k in PUNISH_KEYWORDS)
        if is_reward:
            rewards.append(s)
        else:
            punishments.append(s)
    return rewards, punishments


# ===== 初始化 =====
def _ensure_schema_columns():
    """对已存在的数据库执行增量列迁移（幂等）。"""
    c = _conn()
    cols = [r['name'] for r in c.execute('PRAGMA table_info(action_items)').fetchall()]
    if 'progress' not in cols:
        c.execute('ALTER TABLE action_items ADD COLUMN progress TEXT')
    if 'extra_json' not in cols:
        c.execute("ALTER TABLE action_items ADD COLUMN extra_json TEXT DEFAULT '{}'")
    # 数据收集表格：锁定标记（锁定后不可删除）
    cols2 = [r['name'] for r in c.execute('PRAGMA table_info(collector_sheets)').fetchall()]
    if 'locked' not in cols2:
        c.execute('ALTER TABLE collector_sheets ADD COLUMN locked INTEGER DEFAULT 0')
    c.commit()


def init_all_data() -> None:
    """初始化数据库：建表、增量补列，并把现有 JSON 业务数据一次性导入（幂等）"""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    c = _conn()
    c.executescript(SCHEMA)
    c.commit()
    _ensure_schema_columns()
    _migrate_all()
    _migrate_users_from_json()       # users.json -> users 表（一次性）
    bootstrap_admin_if_empty()       # 全新部署可用环境变量创建初始管理员
    import_personnel_files_from_excel_once()  # 档案信息.xlsx -> personnel_files（一次性）


# ===== 通用表格文件解析（CSV / Excel）=====
def _cell_to_str(value) -> str:
    """把单元格值规范成字符串：日期->YYYY-MM-DD，整数值去掉 .0，None->''"""
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_tabular_rows(filename: str, content: bytes) -> List[List[str]]:
    """把上传的表格文件解析为二维字符串列表，支持 .csv / .xlsx / .xls。
    第一行通常是表头。解析失败会抛 ValueError。"""
    name = (filename or '').lower()
    if name.endswith('.csv') or name.endswith('.txt'):
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='replace')
        return [[(_cell_to_str(c)) for c in row] for row in csv.reader(io.StringIO(text))]
    if name.endswith(('.xlsx', '.xlsm', '.xls')):
        if openpyxl is None:
            raise ValueError('服务器未安装 openpyxl，无法解析 Excel')
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        except Exception as e:
            raise ValueError(f'Excel 解析失败: {e}')
        ws = wb.worksheets[0]
        return [[_cell_to_str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    raise ValueError('不支持的文件类型，请上传 CSV 或 Excel（.xlsx/.xls）')


# ===== Excel 导入导出 =====
def export_staff_to_excel(dept: str = None) -> bytes:
    """导出人员信息为 Excel。dept=None/'全体' 导出全部部门"""
    if openpyxl is None:
        raise Exception("openpyxl 库未安装，无法导出 Excel")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(['工号', '姓名', '部门', '级别', '智能机', '邮箱'])

    c = _conn()
    if dept is None or dept == '全体':
        rows = c.execute('SELECT * FROM staff ORDER BY department, employee_id').fetchall()
    else:
        rows = c.execute('SELECT * FROM staff WHERE department=? ORDER BY employee_id', (dept,)).fetchall()

    current = []
    for r in rows:
        current.append({'employee_id': r['employee_id'], 'name': r['name'], 'department': r['department'],
                        'level': r['level'], 'phone': r['phone'], 'email': r['email']})
    current.sort(key=lambda x: x['employee_id'])
    for s in current:
        ws.append([s['employee_id'], s['name'], s['department'], s['level'], s['phone'], s['email']])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def import_staff_from_excel(file_content: bytes, dept: str = None, operator: str = 'System',
                            op_employee_id: str = '', ip_address: str = '') -> Dict[str, Any]:
    """从 Excel 导入人员信息，返回 {'current_imported': int, 'errors': list}"""
    if openpyxl is None:
        raise Exception("openpyxl 库未安装，无法导入 Excel")
    wb = openpyxl.load_workbook(io.BytesIO(file_content))
    ws = wb.active
    result = {'current_imported': 0, 'errors': []}

    c = _conn()
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        emp_id = row[0] if row[0] else ''
        name = row[1] if row[1] else ''
        dept_name = row[2] if len(row) > 2 and row[2] else ''
        level = row[3] if len(row) > 3 and row[3] else ''
        phone = row[4] if len(row) > 4 and row[4] else ''
        email = row[5] if len(row) > 5 and row[5] else ''
        if not emp_id or not name:
            continue
        target_dept = dept
        if target_dept is None:
            target_dept = dept_name if dept_name in DEPT_SHORT_NAMES else full_to_short(dept_name)
        if target_dept not in DEPT_SHORT_NAMES:
            result['errors'].append(f"第 {row_idx} 行: 未知部门 '{dept_name}'")
            continue
        emp = str(emp_id)
        dup = c.execute('SELECT 1 FROM staff WHERE department=? AND employee_id=?',
                        (target_dept, emp)).fetchone()
        if dup:
            continue
        c.execute('INSERT INTO staff(department,employee_id,name,level,phone,email) VALUES(?,?,?,?,?,?)',
                  (target_dept, emp, str(name), str(level) if level else '',
                   str(phone) if phone else '', str(email) if email else ''))
        result['current_imported'] += 1
    c.commit()
    add_history(f"导入人员数据: {result['current_imported']} 人" + (f" 到 {dept}" if dept else ""),
                operator, op_employee_id, ip_address)
    return result


def reimport_all_from_json() -> None:
    """运维工具：清空业务数据表并从现有 JSON 重新导入（先备份！）"""
    c = _conn()
    for t in ('staff', 'staff_left', 'action_items', 'info_tables', 'collector_sheets', 'history'):
        c.execute('DELETE FROM ' + t)
    c.execute("DELETE FROM meta WHERE key='migrated'")
    c.commit()
    _migrate_all()
