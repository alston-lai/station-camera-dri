# Station & Camera DRI Management

部门信息管理与数据收集平台

## 功能模块

### 1. 部门信息
- 查看各月份部门在职人数、离职人数
- 管理部门成员列表
- 记录人员入职/离职变动
- 查看详细的变更历史

### 2. Action Items
- 管理项目任务列表
- 追踪 DRI（负责人）和 ETA（完成日期）
- 支持状态筛选（进行中/已完成/已取消）
- 逾期任务高亮提醒

### 3. 信息列表
- Key-Value 格式信息管理
- 快速添加/编辑/删除信息项
- 记录更新历史

### 4. 数据收集
- 创建收集表格（自定义表头）
- 多人协作填写数据
- 自动记录填写人
- 导出为 CSV 格式

### 5. 历史记录
- 查看所有数据操作记录
- 追踪操作人和操作时间

## 安装和运行

### 1. 安装依赖
```bash
cd station-camera-dri
pip install -r requirements.txt
```

### 2. 运行服务
```bash
cd scripts
python3 run.py
```

### 3. 访问
打开浏览器访问: http://localhost:5000

## 目录结构

```
station-camera-dri/
├── scripts/
│   ├── run.py           # 启动脚本
│   ├── app.py           # Flask 主应用
│   └── data_manager.py  # 数据管理模块
├── templates/           # HTML 模板
├── static/              # CSS 和 JS
├── data/                # SQLite 数据库 / 密钥 / 备份
├── requirements.txt     # Python 依赖
└── README.md
```

## 数据存储

所有数据存储在 SQLite 数据库 **`data/app.db`** 中（已加入 `.gitignore`）。

- **用户 / 人员 / 员工档案 / Action Items / 信息列表 / 数据收集 / 历史记录** 全部存于 `data/app.db`。
- `data/` 目录下只需保留：`app.db`（及运行时产生的 `app.db-wal`、`app.db-shm`、`.secret_key`）与 `backups/`。
  早期用于一次性迁移的 `staff.json`、`action_items.json`、`info_list.json`、`collector.json`、`history.json`、
  `users.json`、`initial_data.json` 均已删除（数据已全部落库，程序运行不再读取它们）。
- `data/users.json` 已删除，用户信息改存 `users` 表。

## 注意事项

- 部署在内网时，确保防火墙允许对应端口访问
- 建议定期做**加密备份**（见下文“安全与运维”）
- 如需改变数据存储位置，可设置环境变量 `LUXAI_DB_PATH`

### 后台维护数据库

服务器本机在项目根目录执行（使用项目 venv 的 python3）：

```bash
cd station-camera-dri/scripts

# 查看有哪些表及行数
python3 db_admin.py tables

# 查看某表内容
python3 db_admin.py dump staff
python3 db_admin.py dump staff --limit 50

# 执行自定义 SQL（只读建议先查看，修改需谨慎）
python3 db_admin.py query "SELECT department, COUNT(*) n FROM staff GROUP BY department"

# 加密备份数据库到 data/backups/（需 BACKUP_PASSWORD 环境变量）
BACKUP_PASSWORD='口令' python3 db_admin.py backup

# 把 SQLite 当前数据导出回 data/*.json（便于用编辑器查看/离线编辑；按需生成）
python3 db_admin.py export
```

> 注意：`db_admin.py import --force`（用 JSON 重建数据库）依赖 `data/*.json`。
> 这些遗留 JSON 已删除，如确需使用，请先执行 `export` 重新生成。

也可直接用系统自带的 `sqlite3 data/app.db` 或图形工具（如 DB Browser for SQLite）打开 `data/app.db`。
改数据前建议先 `backup`。

## Docker 部署

提供容器化运行所需文件：`Dockerfile`、`docker-compose.yml`、`.dockerignore`、`requirements.txt`。

### 镜像内端口约定

- 容器**内部**固定监听 **8000**（`EXPOSE 8000`），由 gunicorn 启动，`Dockerfile` 无需改动。
- **宿主机**访问端口由 `docker-compose.yml` 的端口映射决定，默认 **8080**：
  `ports: "8080:8000"`。若 8080 被占用，改左侧数字即可，例如 `"9000:8000"`。

### 构建镜像

```bash
cd station-camera-dri
docker build -t station-camera-dri:latest .
```

### 运行（推荐 docker compose）

```bash
cd station-camera-dri
docker compose up -d --build
```

浏览器访问：`http://<服务器IP>:8080`（登录用数据库 `users` 表中的工号+姓名）。

### 不使用 compose 时

```bash
docker run -d --name dri --restart unless-stopped \
  -p 8080:8000 -v "$PWD/data:/app/data" \
  station-camera-dri:latest
```

### 数据持久化

- 用户、员工档案等数据现在**全部保存在 `data/app.db`（SQLite）**中：
  - 用户表 `users`（替代原 `data/users.json`，该文件已移除）；
  - 员工档案表 `personnel_files`（首次启动会从 `档案信息.xlsx` 一次性导入后即可删除该文件）。
- `data/` 目录以数据卷挂载到容器 `/app/data`，`app.db` 随容器重建保留。
- `data/app.db*`、`data/backups/`、`data/users.json`、`data/.secret_key` 已在 `.gitignore` / `.dockerignore` 中排除，不会进镜像。

### 安全与运维

- **文件权限**：建议 `chmod 700 data && chmod 600 data/app.db*`（限制同机其他账号读取）。
- **HTTPS**：正式环境建议前置反向代理提供 HTTPS，并设置 `SESSION_COOKIE_SECURE=true`；
  若临时以明文 HTTP 访问，请将其设为 `false`，否则无法登录。
- **用户管理入口**：仅工号 `12214253`（可用环境变量 `ADMIN_EMPLOYEE_ID` 覆盖）在首页可见
  “用户管理”卡片；其他用户看不到、直接访问也会被重定向。进入 `/admin/users` 后**每次都要输入管理密码**
  （环境变量 `ADMIN_PASSWORD`，默认 `DLJ360781dlj`，请务必修改）；密码校验通过后签发短期内存 token，
  页面刷新或重新进入即失效，因此每次进入都需重新验证。
- **加密备份**（需 `openssl`，镜像中已安装）：
  ```bash
  # 一键加密备份
  BACKUP_PASSWORD='你的备份密码' python3 scripts/backup.py
  # 或
  BACKUP_PASSWORD='你的备份密码' python3 scripts/db_admin.py backup
  ```
  输出 `data/backups/app_<时间>.db.enc`（AES-256-CBC，权限 600）。未设置 `BACKUP_PASSWORD` 时拒绝生成明文备份。
- **一键恢复**（`scripts/restore.py`）：
  ```bash
  python3 scripts/restore.py --list                       # 查看可用备份
  BACKUP_PASSWORD='口令' python3 scripts/restore.py --latest --dry-run   # 只校验不覆盖
  BACKUP_PASSWORD='口令' python3 scripts/restore.py --latest             # 正式恢复（会确认）
  ```
  流程：解密 → 完整性校验 → 把当前库另存为 `app.db.before_restore_*` → 覆盖 `app.db` → 清理 `-wal/-shm` → 权限 600。
  **执行前请先停服务**（本地 Ctrl+C / `docker compose stop dri`）。
- **全新部署**（数据库无用户时）：可设置环境变量 `ADMIN_EMPLOYEE_ID`（及可选 `ADMIN_NAME`）
  自动创建一个初始管理员，避免被锁在系统外。

### 常用运维命令

```bash
docker ps                      # 查看容器状态与健康
docker compose up -d --build   # 重建并启动
docker compose logs -f dri      # 查看实时日志
docker compose down             # 停止并移除容器（数据卷 data/ 仍保留）
```

> 容器内也内置了后台管理脚本：`docker compose exec dri python scripts/db_admin.py tables`。
