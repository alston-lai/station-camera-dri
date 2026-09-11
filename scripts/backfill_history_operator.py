#!/usr/bin/env python3
"""
回填历史记录中缺失的「工号」。

背景：早期版本在“收集表格行操作 / Action Item”写历史时没带工号，
导致 history.employee_id 为空。本脚本按操作人姓名回填：
  1) 优先用该操作人其他历史记录里已出现的工号（取出现次数最多的一个）；
  2) 若历史里没有，则查 users 表（姓名唯一时才回填，避免同名误配）。

用法：
  python3 scripts/backfill_history_operator.py            # 只看（dry-run）
  python3 scripts/backfill_history_operator.py --apply    # 实际写入
  python3 scripts/backfill_history_operator.py --apply --delete-operators tester,op,u
        # 额外删除指定的测试账号记录（逗号分隔）
"""
import argparse
import os
import sqlite3
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(PROJECT_DIR, 'data', 'app.db')


def main():
    p = argparse.ArgumentParser(description='回填历史记录中缺失的工号')
    p.add_argument('--apply', action='store_true', help='实际写入（默认只预览）')
    p.add_argument('--delete-operators', default='', help='删除这些操作人的记录，逗号分隔')
    args = p.parse_args()

    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row

    rows = c.execute('SELECT id,operator,employee_id FROM history').fetchall()

    # 1) 从已有记录里统计每个操作人的工号
    votes = {}
    for r in rows:
        if (r['employee_id'] or '').strip():
            votes.setdefault(r['operator'], Counter())[r['employee_id']] += 1
    name_to_id = {n: v.most_common(1)[0][0] for n, v in votes.items()}

    # 2) users 表兜底（姓名唯一才用）
    try:
        uname = Counter()
        usermap = {}
        for u in c.execute('SELECT employee_id,name FROM users'):
            nm = (u['name'] or '').strip()
            if nm:
                uname[nm] += 1
                usermap[nm] = u['employee_id']
        for nm, n in uname.items():
            if n == 1 and nm not in name_to_id and usermap.get(nm):
                name_to_id[nm] = usermap[nm]
    except Exception:
        pass

    todo = [r for r in rows if not (r['employee_id'] or '').strip()
            and name_to_id.get(r['operator'])]
    print('待回填记录: %s 条' % len(todo))
    brief = Counter(r['operator'] for r in todo)
    for nm, n in brief.most_common():
        print('  %-12s -> %-12s %s 条' % (nm, name_to_id[nm], n))

    if args.apply and todo:
        for r in todo:
            c.execute('UPDATE history SET employee_id=? WHERE id=?',
                      (name_to_id[r['operator']], r['id']))
        c.commit()
        print('✅ 已回填 %s 条' % len(todo))
    elif todo:
        print('（预览模式，加 --apply 才会写入）')

    if args.delete_operators:
        names = [s.strip() for s in args.delete_operators.split(',') if s.strip()]
        for nm in names:
            n = c.execute('SELECT COUNT(*) FROM history WHERE operator=?', (nm,)).fetchone()[0]
            print('待删除 operator=%s: %s 条' % (nm, n))
            if args.apply:
                c.execute('DELETE FROM history WHERE operator=?', (nm,))
        if args.apply:
            c.commit()
            print('✅ 已删除测试记录')

    if not args.apply:
        print('（dry-run：数据库未做任何修改）')


if __name__ == '__main__':
    main()
