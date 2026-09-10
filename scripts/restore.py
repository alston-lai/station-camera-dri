#!/usr/bin/env python3
"""
一键恢复工具：把加密备份 (data/backups/app_*.db.enc) 还原为 data/app.db

配套脚本：
  - scripts/backup.py   ：一键【加密备份】（生成 .db.enc）
  - scripts/restore.py  ：一键【恢复】（本文件）

════════════════════════════════════════════════════════════════════
常见用法
════════════════════════════════════════════════════════════════════
  # 1) 看看有哪些备份可用（按时间倒序）
  python3 scripts/restore.py --list

  # 2) 用“最新”的备份恢复（会提示确认；建议先停掉服务再执行）
  BACKUP_PASSWORD='你的备份口令' python3 scripts/restore.py --latest

  # 3) 指定某个备份文件恢复
  BACKUP_PASSWORD='你的备份口令' python3 scripts/restore.py \
      data/backups/app_20260910_144607.db.enc

  # 4) 只解密 + 校验，不覆盖正式库（演练/验证口令是否正确）
  BACKUP_PASSWORD='你的备份口令' python3 scripts/restore.py --latest --dry-run

  # 5) 自动化场景跳过交互确认
  BACKUP_PASSWORD='...' python3 scripts/restore.py --latest --yes

════════════════════════════════════════════════════════════════════
恢复流程（脚本自动完成）
════════════════════════════════════════════════════════════════════
  1. 解密 .enc -> 临时 .db（openssl AES-256-CBC + pbkdf2，200000 次迭代）
  2. 校验临时库：PRAGMA integrity_check == ok，并检查关键表是否存在
  3. 备份当前正式库为 data/app.db.before_restore_<时间>（防呆留档）
  4. 用解密后的库覆盖 data/app.db
  5. 删除旧的 app.db-wal / app.db-shm（避免旧事务回放导致不一致）
  6. 收紧权限 app.db -> 600

注意：
  - 运行前**请先停止服务**（本地 Ctrl+C / docker compose stop dri），
    否则正在写入的连接可能造成恢复后数据不一致。
  - 恢复是“回退到备份时间点”，该时间点之后的数据会丢失；
    脚本已自动把当前库另存为 before_restore 文件，方便反悔。
  - 忘记 BACKUP_PASSWORD 将无法解密，请务必妥善保管口令。
"""
import argparse
import getpass
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime

# ── 路径解析（与 backup.py / data_manager.py 保持一致）────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
# 目标数据库：优先环境变量 LUXAI_DB_PATH（Docker 里为 /app/data/app.db）
DB_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(DATA_DIR, 'app.db')

# 关键表：恢复后必须存在，否则认为备份不可用
REQUIRED_TABLES = ('users', 'staff', 'personnel_files')

# 与 backup.py 保持完全一致的加密参数（解密时必须一致）
OPENSSL_ITER = '200000'


def list_backups() -> list:
    """返回备份目录下的 .enc 文件列表，按修改时间从新到旧排序。"""
    if not os.path.isdir(BACKUP_DIR):
        return []
    files = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith('.db.enc')]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def cmd_list():
    """--list：打印可用备份。"""
    files = list_backups()
    if not files:
        print('没有找到任何备份文件（目录: %s）' % BACKUP_DIR)
        return
    print('可用备份（新 → 旧）：')
    for p in files:
        size_kb = os.path.getsize(p) / 1024.0
        ts = datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M:%S')
        print('  %s   %8.1f KB   %s' % (p, size_kb, ts))


def get_password(pwd_arg: str = '') -> str:
    """获取备份口令：命令行 > 环境变量 BACKUP_PASSWORD > 交互输入。"""
    if pwd_arg:
        return pwd_arg
    env_pwd = os.environ.get('BACKUP_PASSWORD', '')
    if env_pwd:
        return env_pwd
    # 交互输入（不回显）；无终端环境会抛异常，此时应改用环境变量
    return getpass.getpass('请输入备份口令 BACKUP_PASSWORD: ')


def decrypt_backup(enc_path: str, out_path: str, password: str) -> None:
    """用 openssl 解密备份文件。
    参数必须与 backup.py 加密时一致：aes-256-cbc + salt + pbkdf2 + 200000 次。
    口令通过环境变量传递（-pass env:...），避免出现在进程命令行里被 ps 看到。"""
    env = dict(os.environ)
    env['BACKUP_PASSWORD'] = password
    subprocess.run(
        ['openssl', 'enc', '-d', '-aes-256-cbc', '-salt', '-pbkdf2',
         '-iter', OPENSSL_ITER, '-in', enc_path, '-out', out_path,
         '-pass', 'env:BACKUP_PASSWORD'],
        check=True, env=env)


def verify_db(db_path: str) -> dict:
    """校验一个 SQLite 库是否可用：完整性检查 + 关键表行数。
    返回 {'ok': bool, 'integrity': str, 'counts': {table: n}, 'missing': [table]}"""
    info = {'ok': False, 'integrity': '', 'counts': {}, 'missing': []}
    c = sqlite3.connect(db_path)
    try:
        info['integrity'] = c.execute('PRAGMA integrity_check').fetchone()[0]
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in REQUIRED_TABLES:
            if t not in names:
                info['missing'].append(t)
                continue
            info['counts'][t] = c.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]
    finally:
        c.close()
    info['ok'] = (info['integrity'] == 'ok') and not info['missing']
    return info


def cleanup_old_backups(days: int):
    """删除超过 days 天的旧加密备份（默认不启用）。"""
    now = time.time()
    removed = 0
    for p in list_backups():
        if (now - os.path.getmtime(p)) > days * 86400:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    if removed:
        print('  已清理 %d 个超过 %d 天的旧备份。' % (removed, days))


def restore(enc_path: str, password: str, db_path: str, dry_run: bool,
            assume_yes: bool, cleanup_days: int = 0) -> int:
    """执行恢复主流程。返回 0 表示成功，非 0 表示失败。"""
    if not os.path.exists(enc_path):
        print('备份文件不存在: %s' % enc_path)
        return 2

    print('备份文件 : %s' % enc_path)
    print('目标数据库: %s' % db_path)
    print('模式     : %s' % ('演练(--dry-run，不覆盖正式库)' if dry_run else '正式恢复'))

    # ── 步骤 1：解密到临时文件 ──────────────────────────────────────
    fd, tmp_db = tempfile.mkstemp(prefix='restore_', suffix='.db')
    os.close(fd)
    try:
        print('[1/5] 解密中…')
        try:
            decrypt_backup(enc_path, tmp_db, password)
        except subprocess.CalledProcessError:
            print('  解密失败：口令错误或文件损坏。')
            return 3

        # ── 步骤 2：校验解密结果 ────────────────────────────────────
        print('[2/5] 校验数据库完整性…')
        info = verify_db(tmp_db)
        print('  integrity_check = %s' % info['integrity'])
        for t in REQUIRED_TABLES:
            if t in info['counts']:
                print('  %s 行数 = %d' % (t, info['counts'][t]))
        if info['missing']:
            print('  缺少关键表: %s' % ', '.join(info['missing']))
        if not info['ok']:
            print('  校验失败，已中止（未改动正式库）。')
            return 4

        if dry_run:
            print('[dry-run] 校验通过，未覆盖正式库。临时解密文件已删除。')
            return 0

        # ── 步骤 3：确认 + 给当前库留退路 ───────────────────────────
        if not assume_yes:
            print('')
            print('⚠️  请确认已停止服务（本地 Ctrl+C / docker compose stop dri）。')
            ans = input('将用备份覆盖 %s，该时间点之后的数据会丢失。输入 yes 继续: ' % db_path)
            if ans.strip().lower() != 'yes':
                print('已取消。')
                return 0

        print('[3/5] 备份当前数据库（留退路）…')
        if os.path.exists(db_path):
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safety = db_path + '.before_restore_' + stamp
            shutil.copy2(db_path, safety)
            print('  已保存: %s' % safety)
        else:
            print('  （当前库不存在，跳过）')

        # ── 步骤 4：覆盖数据库并清理 WAL/SHM ────────────────────────
        print('[4/5] 覆盖数据库…')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        shutil.copy2(tmp_db, db_path)
        for suffix in ('-wal', '-shm'):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)
                print('  已删除旧文件: %s' % p)

        # ── 步骤 5：权限收紧 ────────────────────────────────────────
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
        print('[5/5] 完成，权限已设为 600。')

        # 可选：清理 N 天前的旧备份
        if cleanup_days > 0:
            cleanup_old_backups(cleanup_days)

        print('✅ 恢复成功。请启动服务验证（本地 run.py / docker compose up -d）。')
        return 0
    finally:
        # 无论成功失败都删除临时解密文件（避免明文残留）
        try:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)
        except OSError:
            pass


def main():
    p = argparse.ArgumentParser(description='从加密备份一键恢复 SQLite 数据库')
    p.add_argument('enc', nargs='?', help='备份文件路径（.db.enc）；配合 --latest 时可省略')
    p.add_argument('--list', action='store_true', help='列出可用备份后退出')
    p.add_argument('--latest', action='store_true', help='使用最新的备份文件')
    p.add_argument('--db-path', default=DB_PATH, help='目标数据库路径（默认 data/app.db）')
    p.add_argument('--password', default='', help='备份口令（不推荐明文，建议用环境变量 BACKUP_PASSWORD）')
    p.add_argument('--dry-run', action='store_true', help='只解密校验，不覆盖正式库')
    p.add_argument('--yes', action='store_true', help='跳过交互确认（自动化用）')
    p.add_argument('--cleanup-days', type=int, default=0,
                   help='恢复后清理 N 天前的旧备份（默认 0=不清理）')
    args = p.parse_args()

    # --list：只展示备份列表
    if args.list:
        cmd_list()
        return

    # 决定用哪个备份文件：显式路径 或 --latest（或缺省取最新）
    enc_path = args.enc
    if args.latest or not enc_path:
        files = list_backups()
        if not files:
            print('没有可用备份。请先执行 scripts/backup.py 生成备份。')
            sys.exit(1)
        enc_path = files[0]
        print('使用最新备份: %s' % enc_path)

    password = get_password(args.password)
    code = restore(enc_path, password, args.db_path, args.dry_run, args.yes, args.cleanup_days)
    sys.exit(code)


if __name__ == '__main__':
    main()
