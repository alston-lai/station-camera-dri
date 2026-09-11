# Station & Camera DRI Management

部门信息管理与数据收集平台

## 功能模块

### 1. 部门信息
- 查看各月份部门在职人数、离职人数
- 管理部门成员列表
- 记录人员入职/离职变动
- 查看详细的变更历史
- **部门分析页面**（点击部门大卡片进入 `/department/analysis/<部门>`）：需「部门信息可编辑」权限
  （`can_edit_department`）；无权限用户点击部门卡片会提示无权限，直接访问会跳回部门信息页
- 部门分析页含 6 张明细表：惩罚 / 奖励 / 专利 / 研发立项 / 激励专案 / **Skills 开发信息**
  （Skills 表列为 部门、Skill 名称、描述、DRI，来自数据收集的 `Skills Tracker`）
- 部门写法自动归一化：`HWTE5/HWTE-5/HWTE 5` → **五部**，`HWTE6/7/8` → **六部/七部/八部**，
  页面上统一显示为五/六/七/八部

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

### 5. KPI 管理（`/kpi`）

主页「数据收集」卡片后的 **KPI 管理** 卡片进入，横向对比四部（五/六/七/八部）的 KPI，图形化呈现：

| 板块 | 数据来源 | 说明 |
| --- | --- | --- |
| NRE 比例对比 | 信息列表 · `NRE 比例` 表 | 横向柱状图对比 Station DRI（五部+六部）与 Camera（七部+八部）；若表内为 五/六/七/八部 明细行，则按 `在职 ÷ NRE HC` 合并计算 |
| 激励专案数量 | 收集表格 · 名称含 `激励专案` | 按「部门」列统计行数 |
| 专利数量 | 收集表格 · 名称含 `专利` | 按「部门」列统计行数 |
| 研发立项数量 | 收集表格 · 名称含 `研发立项` | 按「部门」列统计行数 |
| Skill 开发数量 | 收集表格 · 名称含 `Skills`（Skills Tracker） | 按「部门」列统计行数 |
| 惩罚信息数量 | 员工档案 · 奖惩信息 | 按部门统计惩罚条目数 |
| 奖励信息数量 | 员工档案 · 奖惩信息 | 按部门统计奖励条目数 |

- 只展示数量/比例，不展示具体人员、专利号等明细。
- NRE 柱状图满刻度为 **100%**：柱条长度=比例本身（如 77.5% 不会拉满），未拉满即未达 100%。
- 数量类柱条**可点击**，点击跳转到该部的「部门分析」页面对应表格（锚点高亮）：
  `#incentive` 激励专案 / `#patent` 专利 / `#rd` 研发立项 / `#skills` Skills 开发 / `#punish` 惩罚信息 / `#reward` 奖励信息。
- **权限**：需「部门信息可编辑」权限（`can_edit_department`，与历史记录同一权限）——
  无权限用户首页/导航栏不显示 KPI 入口，直接访问 `/kpi` 会跳回首页。
- 纯 CSS 横向柱状图，不依赖外网图表库；四部颜色固定：五部蓝、六部绿、七部橙、八部紫。

### 6. 历史记录
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
- **历史记录工号**：历史记录页展示「操作人（登录时输入的姓名）+ 工号」。若早期数据缺工号，可回填：
  ```bash
  python3 scripts/backfill_history_operator.py            # 预览
  python3 scripts/backfill_history_operator.py --apply    # 写入
  ```
- **误删表格列的恢复**（自动快照）：
  「修改表头」（删除列会丢弃该列数据）或「删除信息表/收集表格」前，程序会先把**改动前的表头+全部行数据**
  存入数据库 `revisions` 表（最多保留最近 100 条）。恢复方式：
  ```bash
  python3 scripts/restore_revision.py --list          # 查看可用快照
  python3 scripts/restore_revision.py --restore <id>  # 恢复（会先确认；恢复前再存一份当前状态，可回滚）
  ```
  （Docker：`docker compose exec dri python scripts/restore_revision.py --list`）
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
