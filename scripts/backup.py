#!/usr/bin/env python3
"""
一键加密备份工具：把 SQLite 数据库在线备份并用 AES-256-CBC 加密保存。

配套脚本：
  - scripts/backup.py   ：一键【加密备份】（本文件，生成 .db.enc）
  - scripts/restore.py  ：一键【恢复】（解密 .enc 并覆盖 app.db，含校验/留档）

用法：
  本地：
    BACKUP_PASSWORD='你的备份密码' python3 scripts/backup.py
  Docker：
    docker compose exec dri sh -lc "BACKUP_PASSWORD='你的备份密码' python scripts/backup.py"
  定时（cron 示例，每天 02:00）：
    0 2 * * * cd /你的路径/station-camera-dri && BACKUP_PASSWORD='口令' ./venv/bin/python scripts/backup.py >> /var/log/dri_backup.log 2>&1

输出：
  data/backups/app_YYYYmmdd_HHMMSS.db.enc （整个 app.db 的快照，权限 600）

说明：
  - 使用 Python sqlite3 的在线 backup API，兼容 WAL 模式、无需停止服务。
  - 使用 openssl 命令行做加密（aes-256-cbc + salt + pbkdf2，200000 次迭代）。
  - 未设置 BACKUP_PASSWORD 时拒绝执行，以免生成未加密的明文备份。
  - 恢复请用 scripts/restore.py（解密参数必须与这里完全一致）。
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
DB_PATH = os.environ.get('LUXAI_DB_PATH') or os.path.join(DATA_DIR, 'app.db')


def make_backup(password: str = None, db_path: str = None, out_dir: str = None) -> str:
    password = password or os.environ.get('BACKUP_PASSWORD', '')
    db_path = db_path or DB_PATH
    out_dir = out_dir or BACKUP_DIR

    if not password:
        raise SystemExit('未设置 BACKUP_PASSWORD 环境变量，拒绝生成未加密备份。')
    if not os.path.exists(db_path):
        raise SystemExit('数据库不存在: ' + db_path)

    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)          # 在线一致性备份
    finally:
        dst.close()
        src.close()

    out = os.path.join(out_dir, f'app_{stamp}.db.enc')
    try:
        env = dict(os.environ)
        env['BACKUP_PASSWORD'] = password
        subprocess.run(
            ['openssl', 'enc', '-aes-256-cbc', '-salt', '-pbkdf2', '-iter', '200000',
             '-in', tmp, '-out', out, '-pass', 'env:BACKUP_PASSWORD'],
            check=True, env=env)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    return out


if __name__ == '__main__':
    path = make_backup()
    print('加密备份完成:', path)
