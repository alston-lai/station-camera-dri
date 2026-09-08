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