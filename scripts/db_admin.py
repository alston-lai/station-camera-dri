#!/usr/bin/env python3
"""
SQLite 后台管理工具（Station & Camera DRI）

用法示例（在 scripts 目录，或使用项目 venv 的 python3）：
  python3 db_admin.py tables                  # 查看所有表
  python3 db_admin.py dump staff              # 查看 staff 表（默认最多100行）
  python3 db_admin.py dump staff --limit 50
  python3 db_admin.py query "SELECT * FROM staff WHERE department='五部' LIMIT 5"
  python3 db_admin.py backup                  # 一键备份数据库到 data/backups/
  python3 db_admin.py export                  # 把 SQLite 当前数据导出回 data/*.json
  python3 db_admin.py import --force          # 从现有 JSON 重建数据库（危险，先 backup）

说明：数据库文件默认在 data/app.db。也可用环境变量 LUXAI_DB_PATH 指向其它库。
修改前建议先执行 backup。
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
DB_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(DATA_DIR, 'app.db')


DOMAINS = ['staff', 'action_items', 'info_list', 'collector', 'history']


def _connect():
    return sqlite3.connect(DB_PATH, timeout=30)


def cmd_tables():
    c = _connect()
    rows = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    print('数据库:', DB_PATH)
    for (name,) in rows:
        cnt = c.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
        print(f'  - {name}: {cnt} 行')


def cmd_dump(table, limit):
    c = _connect()
    names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    if table not in names:
        print(f'表不存在: {table}；可用表：{" ".join(names)}')
        sys.exit(1)
    cur = c.execute(f'SELECT * FROM {table} LIMIT ?', (limit,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print('列:', ', '.join(cols))
    print(f'共显示 {len(rows)} 行 (limit={limit})')
    for r in rows:
        print(json.dumps(dict(zip(cols, r)), ensure_ascii=False))


def cmd_query(sql):
    c = _connect()
    try:
        cur = c.execute(sql)
    except sqlite3.Error as e:
        print('SQL 错误:', e)
        sys.exit(1)
    if cur.description:
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print('列:', ', '.join(cols))
        for r in rows:
            print(json.dumps(list(r), ensure_ascii=False))
        print(f'共 {len(rows)} 行')
    else:
        c.commit()
        print('执行完成，影响行数:', cur.rowcount)


def cmd_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(BACKUP_DIR, f'app_{stamp}.db')
    shutil.copy2(DB_PATH, dst)
    for suffix in ('-wal', '-shm'):
        src = DB_PATH + suffix
        if os.path.exists(src):
            shutil.copy2(src, dst + suffix)
    print('备份完成:', dst)


def cmd_export():
    sys.path.insert(0, SCRIPT_DIR)
    import data_manager as dm
    dm.init_all_data()
    payloads = {
        'staff.json': dm.get_all_staff(),
        'action_items.json': {'items': dm.get_all_action_items()},
        'info_list.json': {'tables': dm.get_all_info_list()},
        'collector.json': {'sheets': dm.get_collector_sheets()},
        'history.json': {'records': dm.get_history(100000)},
    }
    for fname, data in payloads.items():
        path = os.path.join(DATA_DIR, fname)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print('已导出:', path)


def cmd_import(force):
    if not force:
        print('这是危险操作：会用 data/*.json 覆盖数据库全部业务数据。')
        print('请先执行 backup，再带上 --force 运行。')
        sys.exit(1)
    sys.path.insert(0, SCRIPT_DIR)
    import data_manager as dm
    dm.init_all_data()
    dm.reimport_all_from_json()
    print('已从 JSON 重建数据库。')


def main():
    p = argparse.ArgumentParser(description='SQLite 后台管理工具')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('tables')
    dp = sub.add_parser('dump')
    dp.add_argument('table')
    dp.add_argument('--limit', type=int, default=100)
    qp = sub.add_parser('query')
    qp.add_argument('sql')
    sub.add_parser('backup')
    sub.add_parser('export')
    ip = sub.add_parser('import')
    ip.add_argument('--force', action='store_true')
    args = p.parse_args()
    if args.cmd == 'tables':
        cmd_tables()
    elif args.cmd == 'dump':
        cmd_dump(args.table, args.limit)
    elif args.cmd == 'query':
        cmd_query(args.sql)
    elif args.cmd == 'backup':
        cmd_backup()
    elif args.cmd == 'export':
        cmd_export()
    elif args.cmd == 'import':
        cmd_import(args.force)
    else:
        p.print_help()


if __name__ == '__main__':
    main()
