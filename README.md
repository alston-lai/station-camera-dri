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
├── data/                # JSON 数据存储
├── requirements.txt     # Python 依赖
└── README.md
```

## 数据存储

所有数据存储在 `data/` 目录下的 JSON 文件中：
- `staff.json` - 部门人员信息
- `action_items.json` - Action Items
- `info_list.json` - 信息列表
- `collector.json` - 数据收集表格
- `history.json` - 操作历史

## 注意事项

- 部署在内网时，确保防火墙允许 5000 端口访问
- 建议定期备份 `data/` 目录
- 可根据需要修改 `scripts/data_manager.py` 中的 DATA_DIR 变量改变数据存储位置
## 数据存储（SQLite）

主要业务数据已迁移到 SQLite，数据库文件：`data/app.db`（已加入 .gitignore）。

- **人员 / Action Items / 信息列表 / 数据收集 / 历史记录** 都存于 `data/app.db`。
- 首次启动（`init_all_data`）会自动把 `data/` 下对应的 JSON 一次性导入数据库（幂等，不会重复导入）。
- `data/*.json` 保留为“迁移快照 / 备份”，作为导入数据源；日常增删改请通过页面或数据库进行。
- `data/users.json`（账号权限白名单）仍使用 JSON，未纳入 SQLite。

### 后台维护数据库

服务器本机在项目根目录执行（使用项目 venv 的 python3）：

```bash
cd station-camera-dri/scripts
../venv/...  # 视你环境选择解释器，下面用 python3 代表

# 查看有哪些表及行数
python3 db_admin.py tables

# 查看某表内容
python3 db_admin.py dump staff
python3 db_admin.py dump staff --limit 50

# 执行自定义 SQL（只读建议先查看，修改需谨慎）
python3 db_admin.py query "SELECT department, COUNT(*) n FROM staff GROUP BY department"

# 一键备份数据库到 data/backups/
python3 db_admin.py backup

# 把 SQLite 当前数据导出回 data/*.json（便于用编辑器查看/离线编辑）
python3 db_admin.py export

# 用现有 data/*.json 重建数据库（危险，请先 backup 并加 --force）
python3 db_admin.py import --force
```

也可直接用系统自带的 `sqlite3 data/app.db` 或图形工具（如 DB Browser for SQLite）打开 `data/app.db`。
改数据前建议先 `backup`。
