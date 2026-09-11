#!/usr/bin/env python3
"""
从自动快照（revisions 表）恢复被误删的表格列 / 整表。

背景：
  当有人「修改表头」（删除列会丢弃该列数据）、或「删除信息表 / 删除收集表格」时，
  程序会先把【改动前的表头 + 全部行数据】存进 `revisions` 表（最多保留最近 100 条）。
  本脚本用来把这些快照还原回去。

revisions 的 kind 取值：
  - info_headers      ：信息列表 · 改表头前的快照
  - info_table        ：信息列表 · 删除整表前的快照（可整表重建）
  - collector_headers ：数据收集 · 改表头前的快照
  - collector_sheet   ：数据收集 · 删除整表前的快照（可整表重建）

用法：
  # 1) 查看所有可用快照
  python3 scripts/restore_revision.py --list

  # 2) 恢复指定快照（恢复前会先把“当前状态”也存成一条快照，可再次回滚）
  python3 scripts/restore_revision.py --restore 12

  # 3) 自动化场景跳过确认
  python3 scripts/restore_revision.py --restore 12 --yes

注意：
  - 快照只在“做了上述操作”时生成；更早的历史操作没有快照。
  - 只保留最近 100 条快照。
  - 脚本直接操作数据库，建议先停服务（或至少确保没有人在编辑该表）。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
DB_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(DATA_DIR, 'app.db')

# kind -> (目标表, 是否“整表删除”类快照)
KIND_MAP = {
    'info_headers': ('info_tables', False),
    'info_table': ('info_tables', True),
    'collector_headers': ('collector_sheets', False),
    'collector_sheet': ('collector_sheets', True),
}


def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c


def _payload(row):
    try:
        return json.loads(row['payload_json'] or '{}')
    except Exception:
        return {}


def cmd_list():
    c = connect()
    rows = c.execute('SELECT id,kind,ref_id,payload_json,created_at FROM revisions ORDER BY id DESC').fetchall()
    if not rows:
        print('暂无快照。快照会在“修改表头/删除表格”时自动生成。')
        return
    print('可用快照（新 → 旧）：')
    for r in rows:
        p = _payload(r)
        target = KIND_MAP.get(r['kind'], ('?', False))[0]
        cur = None
        if target in ('info_tables', 'collector_sheets'):
            cur = c.execute('SELECT name FROM %s WHERE id=?' % target, (r['ref_id'],)).fetchone()
        name = (cur['name'] if cur else None) or p.get('name') or '(表已删除)'
        print('  id=%-4s %-18s 表id=%-4s %s  列数=%s 行数=%s  %s' % (
            r['id'], r['kind'], r['ref_id'], name,
            len(p.get('headers') or []), len(p.get('rows') or []), r['created_at']))
    print('')
    print('恢复命令示例： python3 scripts/restore_revision.py --restore <id>')


def _snapshot_current(c, kind, ref_id, name, headers, rows):
    """恢复前把当前状态也存一份，保证“恢复”本身可回滚。"""
    c.execute('INSERT INTO revisions(kind,ref_id,payload_json,created_at) VALUES(?,?,?,?)',
              (kind, ref_id,
               json.dumps({'name': name, 'headers': headers, 'rows': rows}, ensure_ascii=False),
               datetime.now().strftime('%Y-%m-%d %H:%M')))
    c.execute('DELETE FROM revisions WHERE id NOT IN '
              '(SELECT id FROM revisions ORDER BY id DESC LIMIT 100)')


def cmd_restore(rev_id, assume_yes):
    c = connect()
    rev = c.execute('SELECT * FROM revisions WHERE id=?', (rev_id,)).fetchone()
    if not rev:
        print('找不到快照 id=%s（可用 --list 查看）' % rev_id)
        return 2
    if rev['kind'] not in KIND_MAP:
        print('未知的快照类型: %s' % rev['kind'])
        return 2

    table = KIND_MAP[rev['kind']][0]
    payload = _payload(rev)
    headers = payload.get('headers') or []
    rows = payload.get('rows') or []
    name = payload.get('name') or ''
    ref_id = rev['ref_id']

    cur = c.execute('SELECT * FROM %s WHERE id=?' % table, (ref_id,)).fetchone()
    cur_name = (cur['name'] if cur else '') or name or '(未命名)'
    print('快照 id  : %s (%s, 生成于 %s)' % (rev_id, rev['kind'], rev['created_at']))
    print('目标     : %s %s' % ('信息表' if table == 'info_tables' else '收集表格', cur_name))
    print('将恢复   : 表头 %s 列 / 数据 %s 行' % (len(headers), len(rows)))
    if cur:
        print('当前状态 : 表头 %s 列 / 数据 %s 行' % (
            len(json.loads(cur['headers_json'] or '[]')),
            len(json.loads(cur['rows_json'] or '[]'))))
    else:
        print('当前状态 : 表不存在（将按快照重建）')

    if not assume_yes:
        ans = input('确认恢复？（输入 yes 继续）: ')
        if ans.strip().lower() != 'yes':
            print('已取消。')
            return 0

    # 先给“当前状态”留一份快照（若表存在），实现可回滚
    if cur:
        try:
            _snapshot_current(c, rev['kind'], ref_id, cur['name'],
                              json.loads(cur['headers_json'] or '[]'),
                              json.loads(cur['rows_json'] or '[]'))
        except Exception:
            pass

    hj = json.dumps(headers, ensure_ascii=False)
    rj = json.dumps(rows, ensure_ascii=False)
    if cur:
        c.execute('UPDATE %s SET headers_json=?, rows_json=? WHERE id=?' % table, (hj, rj, ref_id))
    elif table == 'info_tables':
        c.execute('INSERT INTO info_tables(id,name,headers_json,rows_json,created_at) VALUES(?,?,?,?,?)',
                  (ref_id, cur_name, hj, rj, datetime.now().strftime('%Y-%m-%d %H:%M')))
    else:
        c.execute('INSERT INTO collector_sheets(id,name,headers_json,rows_json,operator,created_at,locked)'
                  ' VALUES(?,?,?,?,?,?,0)',
                  (ref_id, cur_name, hj, rj, 'restore', datetime.now().strftime('%Y-%m-%d %H:%M')))
    c.commit()
    print('✅ 恢复完成。请刷新页面查看。')
    return 0


def main():
    p = argparse.ArgumentParser(description='从自动快照(revisions)恢复表格列/整表')
    p.add_argument('--list', action='store_true', help='列出所有可用快照')
    p.add_argument('--restore', type=int, metavar='ID', help='恢复指定快照 id')
    p.add_argument('--yes', action='store_true', help='跳过交互确认')
    args = p.parse_args()
    if args.list or args.restore is None:
        cmd_list()
        return
    sys.exit(cmd_restore(args.restore, args.yes))


if __name__ == '__main__':
    main()
