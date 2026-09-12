# Station & Camera DRI Management

部门信息管理与数据收集平台

### 0. 登录与密码

- 登录需 **工号 + 姓名 + 密码**，其中**工号与密码必须完全匹配**（工号还需在 `users` 白名单中）。
- **初始密码为 `test`**：所有用户首次可用 `test` 登录；新用户由管理员在「用户管理」中新增时也自动获得初始密码 `test`。
- 密码以 **PBKDF2-SHA256 加盐哈希**存于 `users.password`（不存明文，接口也不会返回哈希）。
- 登录后导航栏用户名右侧有 **修改密码** 按钮，进入 `/change-password`：
  填写「工号 + 新密码（+ 确认新密码）」，可 **取消** 返回首页；只能修改本人密码（工号须与当前登录账号一致），提交成功后立即写入数据库。
- **忘记密码**：管理员在「用户管理」页可对任意用户点 **重置密码**，一键恢复为初始密码 `test`
  （接口 `POST /api/admin/users/<工号>/reset-password`，需管理员令牌；操作会记入历史记录）。
  重置后请告知本人，并建议其登录后立即自行修改。
- 登录失败限流：同一 IP / 同一工号 5 分钟内尝试次数过多会被暂时拒绝。

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

> 工作模式：**本地用 `start.command` 开发/调试**；调试完成后用 `package_for_docker.command`
> 打成一个 Docker 部署包（`forDocker.tar.gz`），上传到服务器用 Docker 运行。详见
> [本地运行](#本地运行startcommand) 与 [Docker 部署](#docker-部署服务器) 两节。

### 本地运行（start.command）

#### 1. 安装依赖（首次）
```bash
cd station-camera-dri
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

#### 2. 启动服务
- 推荐：双击项目根目录的 **`start.command`**
  （自动选择 Python 环境：优先项目内 `venv`，其次 `/Users/alston/Documents/Cline/Workflows/venv`，最后系统 `python3`）
- 或在终端执行：
  ```bash
  ./start.command
  ```
- 重启（结束 5001 端口旧进程后重新启动）：双击 **`restart.command`**

#### 3. 访问
浏览器打开: http://localhost:5001

- 数据库文件：`data/app.db`（本地运行时直接读写该文件）
- 停止服务：在启动服务的终端窗口按 `Ctrl+C`

### 打包给服务器（package_for_docker.command）

本地调试完成后，双击 **`package_for_docker.command`**（或终端 `./package_for_docker.command`），
它会自动完成：**构建最新镜像 → 收集 Docker 运行所需文件 → 打包成一个文件**：

```
dist/forDocker.tar.gz      ← 上传这个文件到服务器即可（约 50MB）
dist/forDocker/            ← 未压缩的同内容目录（便于检查）
```

包内包含：

| 内容 | 说明 |
| --- | --- |
| `dri-image.tar.gz` | 本地构建好的镜像（`docker load` 离线加载） |
| `docker-compose.yml` / `Dockerfile` / `.dockerignore` / `requirements.txt` | **与仓库完全一致**，未做任何改动 |
| `scripts/ templates/ static/` | 源码与静态资源（服务器可自行 `docker compose up -d --build`） |
| `data-seed/` | 数据库快照 `app.db` + 会话密钥 `.secret_key`（**仅首次部署**导入 `data/`，更新时不会覆盖线上数据） |
| `deploy.sh` | 服务器一键部署脚本（检查 Docker → 按需加载镜像 → 启动 → 打印访问地址） |
| `DEPLOY.md` | 服务器部署说明（端口、环境变量、备份、更新回滚、常见问题） |
| `.env.example` | 环境变量参考 |

可选参数：

```bash
./package_for_docker.command --skip-build   # 不重新构建镜像，直接用本地现有镜像
./package_for_docker.command --no-image     # 不打包镜像（服务器自行 build）
./package_for_docker.command --no-data      # 不打包数据库快照（服务器空库开始）
```

> ⚠️ 本机为 **arm64**（Apple Silicon），打包出的镜像也是 arm64；若服务器是 x86_64，
> 请在服务器上用 `docker compose up -d --build` 自行构建（`deploy.sh` 会自动识别架构不一致并切换）。

## 目录结构

```
station-camera-dri/
├── start.command              # 本地启动（双击即可，端口 5001）
├── restart.command            # 本地重启
├── package_for_docker.command # 打包 Docker 部署包（生成 dist/forDocker.tar.gz）
├── scripts/
│   ├── run.py                 # 本地启动脚本
│   ├── app.py                 # Flask 主应用
│   ├── data_manager.py        # 数据管理模块（SQLite）
│   ├── backup.py / restore.py # 加密备份 / 恢复
│   ├── restore_revision.py    # 从自动快照恢复被误删的表格列
│   └── db_admin.py            # 后台数据库查看
├── templates/                 # HTML 模板
├── static/                    # CSS 和 JS
├── data/                      # SQLite 数据库 / 会话密钥 / 备份
├── Dockerfile                 # 服务器容器镜像（本地不跑，打包用）
├── docker-compose.yml         # 服务器编排（端口 8080→8000）
├── requirements.txt           # Python 依赖
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

## Docker 部署（服务器）

> 部署流程：本地用 `start.command` 开发 → 双击 `package_for_docker.command` 打包 →
> 上传 `dist/forDocker.tar.gz` 到服务器 → 解压后执行 `./deploy.sh`（详见包内 `DEPLOY.md`）。

- 服务器要求：Linux + Docker（含 `docker compose` v2 插件）
- 本机（Apple Silicon / arm64）打出的镜像是 arm64；x86_64 服务器会由 `deploy.sh` 自动改为在服务器构建

### 子路径部署（反向代理，如 `/AL/`）

站点若挂在 `http://hwte.luxsan-ict.com/AL/` 这类子路径下，只需设置环境变量 `URL_PREFIX`：

```yaml
# docker-compose.yml
    environment:
      URL_PREFIX: "/AL"      # 子路径前缀；本地直连留空
```

设置后应用会自动：

| 项目 | 效果 |
| --- | --- |
| `url_for('static', ...)` | `http://hwte.luxsan-ict.com/AL/static/style.css`（`app.js` 同理） |
| 未登录访问任意页面 | 302 → `http://hwte.luxsan-ict.com/AL/login` |
| 页面内所有 `fetch('/api/...')` | 自动变成 `/AL/api/...`（页面注入 `window.APP_BASE` + `fetch` 包装） |
| 所有站内链接 / 跳转 / 导出下载 | 自动带 `/AL` 前缀 |

要点：

- **Nginx 无需改动**：`proxy_pass` 是否剥离子路径都能正常工作（`/AL/...` 与 `/...` 两种转发方式都兼容）。
- 代理若转发 `X-Forwarded-Prefix: /AL`，即使不设 `URL_PREFIX` 也会自动生效（`URL_PREFIX` 优先）。
- `/AL`（无尾斜杠）会自动规范化到 `/AL/`。
- 容器健康检查走容器内 `/login`（不带前缀），不受影响。
- 本地 `start.command`（`http://localhost:5001/`）不设该变量，行为与之前完全一致。

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
  （本地运行：`./venv/bin/python scripts/restore_revision.py --list`）
- **全新部署**（数据库无用户时）：可设置环境变量 `ADMIN_EMPLOYEE_ID`（及可选 `ADMIN_NAME`）
  自动创建一个初始管理员，避免被锁在系统外。

### 常用运维命令

```bash
docker ps                      # 查看容器状态与健康
docker compose up -d --build   # 重建并启动
docker compose logs -f dri      # 查看实时日志
docker compose down             # 停止并移除容器（数据卷 data/ 仍保留）
```

> 本地运行时用项目内 venv 执行后台管理脚本：`./venv/bin/python scripts/db_admin.py tables`。
