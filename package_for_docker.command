#!/bin/bash

# ============================================================
# Station & Camera DRI Management - Docker 部署包打包脚本
# ------------------------------------------------------------
# 用途：
#   1) 在本地构建最新镜像（可选）
#   2) 把「在服务器上用 Docker 运行所需的所有文件」收集到一个目录
#   3) 打包成一个文件：dist/forDocker.tar.gz
#
# 用法：双击本文件，或在终端执行
#   ./package_for_docker.command              # 构建镜像 + 打包（推荐）
#   ./package_for_docker.command --skip-build # 不重新构建，直接用本地已有镜像
#   ./package_for_docker.command --no-image   # 不打包镜像文件（服务器自行 build）
#   ./package_for_docker.command --no-data    # 不打包数据库快照（服务器空库开始）
#   ./package_for_docker.command --help
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="station-camera-dri:latest"
DIST_DIR="$SCRIPT_DIR/dist"
STAGE_DIR="$DIST_DIR/forDocker"
ARCHIVE="$DIST_DIR/forDocker.tar.gz"
VERSION="$(grep -m1 '__version__' scripts/version.py 2>/dev/null | cut -d'"' -f2 || true)"
VERSION="${VERSION:-unknown}"

BUILD=1
WITH_IMAGE=1
WITH_DATA=1

info() { echo "  $*"; }
step() { echo ""; echo "➤ $*"; }
warn() { echo "  ⚠️  $*"; }
die()  { echo ""; echo "❌ $*"; echo ""; echo "按 Enter 键退出..."; read; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --skip-build) BUILD=0 ;;
        --no-image)   WITH_IMAGE=0 ;;
        --no-data)    WITH_DATA=0 ;;
        -h|--help)
            sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
            echo ""
            echo "按 Enter 键退出..."
            read
            exit 0 ;;
        *) die "未知参数：$arg（可用 --skip-build / --no-image / --no-data / --help）" ;;
    esac
done

echo "============================================"
echo "   Station & Camera DRI - Docker 部署包打包"
echo "============================================"
echo "   版本   : v$VERSION"
echo "   项目   : $SCRIPT_DIR"
echo "   输出   : $ARCHIVE"
echo ""

# ---------- 1. 检查 Docker ----------
step "检查 Docker 环境"
if [ "$WITH_IMAGE" = "1" ]; then
    command -v docker >/dev/null 2>&1 || die "未检测到 docker 命令，请先安装/启动 Docker Desktop。"
    docker info >/dev/null 2>&1 || die "Docker 未运行。请先启动 Docker Desktop（应用容器可以不启动，但守护进程必须在运行）。"
    info "Docker 版本: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)"
    info "本机架构  : $(uname -m)（保存的镜像为该架构；x86_64 服务器请注意架构兼容）"
else
    info "已指定 --no-image：跳过镜像构建与导出（不需要 Docker）"
fi

# ---------- 2. 构建镜像 ----------
step "准备镜像"
if [ "$WITH_IMAGE" = "0" ]; then
    info "跳过（包内不含镜像，服务器将用源码构建）"
elif [ "$BUILD" = "1" ]; then
    info "构建中：docker build -t $IMAGE_NAME ."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR" || die "镜像构建失败，请查看上面的构建日志。"
    info "构建完成。"
    info "镜像大小: $(docker image inspect "$IMAGE_NAME" --format '{{.Size}}' | awk '{printf "%.1f MB", $1/1024/1024}')"
    info "镜像架构: $(docker image inspect "$IMAGE_NAME" --format '{{.Architecture}}')"
else
    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        info "已按参数跳过构建，使用本地已有镜像。"
        info "镜像大小: $(docker image inspect "$IMAGE_NAME" --format '{{.Size}}' | awk '{printf "%.1f MB", $1/1024/1024}')"
        info "镜像架构: $(docker image inspect "$IMAGE_NAME" --format '{{.Architecture}}')"
    else
        warn "本地没有 $IMAGE_NAME，改为执行构建。"
        docker build -t "$IMAGE_NAME" "$SCRIPT_DIR" || die "镜像构建失败。"
    fi
fi

# ---------- 3. 准备打包目录 ----------
step "准备打包目录"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/data-seed"
info "$STAGE_DIR"

# ---------- 4. 拷贝 Docker 运行所需文件（与仓库保持一致，不做改动）----------
step "拷贝源码与 Docker 配置文件"
RSYNC_EXCLUDES=(--exclude '__pycache__' --exclude '*.pyc' --exclude '*.pyo'
                --exclude '.DS_Store' --exclude 'venv' --exclude '.git'
                --exclude 'dist' --exclude 'app.db-wal' --exclude 'app.db-shm')

if command -v rsync >/dev/null 2>&1; then
    rsync -a "${RSYNC_EXCLUDES[@]}" scripts   "$STAGE_DIR/"
    rsync -a "${RSYNC_EXCLUDES[@]}" templates "$STAGE_DIR/"
    rsync -a "${RSYNC_EXCLUDES[@]}" static    "$STAGE_DIR/"
else
    for d in scripts templates static; do
        cp -R "$SCRIPT_DIR/$d" "$STAGE_DIR/$d"
        find "$STAGE_DIR/$d" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
        find "$STAGE_DIR/$d" -name '.DS_Store' -delete 2>/dev/null || true
    done
fi
for f in Dockerfile docker-compose.yml .dockerignore requirements.txt README.md; do
    [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$STAGE_DIR/$f"
done
info "已拷贝: scripts/ templates/ static/ Dockerfile docker-compose.yml .dockerignore requirements.txt README.md"

# ---------- 5. 数据库快照（放入 data-seed/，避免更新时覆盖线上 data/）----------
step "准备数据库快照"
if [ "$WITH_DATA" = "1" ] && [ -f "$SCRIPT_DIR/data/app.db" ]; then
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$SCRIPT_DIR/data/app.db" "$STAGE_DIR/data-seed/app.db" <<'PY'
import os, shutil, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
c = sqlite3.connect(src, timeout=30)
try:
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')   # 把 WAL 写回主库，保证快照完整
    c.commit()
finally:
    c.close()
shutil.copy2(src, dst)
print('  data-seed/app.db 已快照（%.0f KB）' % (os.path.getsize(dst) / 1024))
PY
    else
        cp "$SCRIPT_DIR/data/app.db" "$STAGE_DIR/data-seed/app.db"
        info "data-seed/app.db 已拷贝（未做 WAL checkpoint，建议停服后打包）"
    fi
    for k in "$SCRIPT_DIR/data/.secret_key" "$SCRIPT_DIR/.secret_key"; do
        if [ -f "$k" ]; then
            cp "$k" "$STAGE_DIR/data-seed/.secret_key"
            info "已包含会话密钥（部署时导入 data/.secret_key，用户重启后不掉线）"
            break
        fi
    done
else
    info "不包含数据库快照（服务器首次启动会自动建库）"
fi

# ---------- 6. 生成服务器端文件 ----------
step "生成服务器端文件（deploy.sh / DEPLOY.md / .env.example）"

cat > "$STAGE_DIR/.env.example" <<'EOF'
# ============================================================
# 环境变量参考（Station & Camera DRI）
# ------------------------------------------------------------
# 说明：docker-compose.yml 里已直接写好下列值，本文件仅作记录/备查，
#       不会被 compose 自动读取。如需用 .env 统一管理，可把 compose 中
#       对应项改成：  ADMIN_PASSWORD: "${ADMIN_PASSWORD:-请填密码}"
#       然后复制本文件为 .env。
# ============================================================

# 时区（影响写入数据库的时间戳）
TZ=Asia/Shanghai

# 会话 Cookie 是否仅走 HTTPS。
# ⚠️ 直接用 http://IP:端口 访问时必须为 false，否则登录后 Cookie 带不上（表现为登录不了）
SESSION_COOKIE_SECURE=false

# 用户管理入口密码（务必修改）
ADMIN_PASSWORD=change-me-please

# 加密备份口令（scripts/backup.py、scripts/restore.py 使用，务必修改并妥善保管）
BACKUP_PASSWORD=change-me-please

# 可选：固定会话签名密钥（不填则用 data/.secret_key，或自动生成）
# SECRET_KEY=

# 可选：数据库无用户时，用该工号自动创建初始管理员（防止全新部署被锁在外面）
# ADMIN_EMPLOYEE_ID=12214253
# ADMIN_NAME=Admin
EOF
info ".env.example"

cat > "$STAGE_DIR/deploy.sh" <<'EOF'
#!/bin/bash
# ============================================================
# 服务器一键部署脚本（在解压后的 forDocker 目录里执行）
#   1) 检查 Docker 环境
#   2) 镜像包架构匹配 → 直接加载运行；否则在服务器上自行构建
#   3) 启动容器并打印访问地址
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  Station & Camera DRI - 服务器部署"
echo "============================================"

if ! command -v docker >/dev/null 2>&1; then
    echo "❌ 未检测到 docker，请先安装 Docker（建议含 compose 插件 v2）"
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker 服务未运行，请先启动（如 systemctl start docker）"
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "❌ 未检测到 docker compose 插件（docker compose version 失败）"
    exit 1
fi

mkdir -p data
# 首次部署才导入包内数据库快照；已有 data/app.db 时绝不覆盖（更新部署安全）
if [ ! -f data/app.db ] && [ -f data-seed/app.db ]; then
    cp data-seed/app.db data/app.db
    echo "==> 已导入初始数据库：data-seed/app.db → data/app.db"
fi
if [ ! -f data/.secret_key ] && [ -f data-seed/.secret_key ]; then
    cp data-seed/.secret_key data/.secret_key
    chmod 600 data/.secret_key 2>/dev/null || true
    echo "==> 已导入会话密钥：data-seed/.secret_key → data/.secret_key"
fi
chmod 700 data 2>/dev/null || true

HOST_ARCH="$(docker info --format '{{.Architecture}}' 2>/dev/null || echo unknown)"
USE_IMAGE=0
if [ -f dri-image.tar.gz ]; then
    CUR_ARCH="$(docker image inspect station-camera-dri:latest --format '{{.Architecture}}' 2>/dev/null || true)"
    if [ -n "$CUR_ARCH" ] && [ "$CUR_ARCH" = "$HOST_ARCH" ]; then
        echo "==> 本机已有架构匹配的镜像（$CUR_ARCH），跳过加载"
        USE_IMAGE=1
    else
        echo "==> 加载镜像包 dri-image.tar.gz ..."
        if gunzip -c dri-image.tar.gz | docker load; then
            IMG_ARCH="$(docker image inspect station-camera-dri:latest --format '{{.Architecture}}' 2>/dev/null || echo unknown)"
            echo "    镜像架构: $IMG_ARCH  /  本机架构: $HOST_ARCH"
            if [ "$IMG_ARCH" = "$HOST_ARCH" ]; then
                USE_IMAGE=1
            else
                echo "    ⚠️ 架构不一致，镜像无法在本机运行，改为在服务器上构建。"
            fi
        else
            echo "    ⚠️ 镜像加载失败，改为在服务器上构建。"
        fi
    fi
else
    echo "==> 包内没有镜像文件，将在服务器上构建镜像。"
fi

if [ "$USE_IMAGE" = "1" ]; then
    echo "==> 启动：docker compose up -d"
    docker compose up -d
else
    echo "==> 启动并构建：docker compose up -d --build（需要服务器能访问网络/镜像源）"
    docker compose up -d --build
fi

echo ""
echo "==> 等待服务启动 ..."
sleep 6
docker compose ps || true

PORT="$(grep -oE '"?[0-9]+:8000"?' docker-compose.yml | head -1 | tr -dc '0-9:' | cut -d: -f1)"
PORT="${PORT:-8080}"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP="${IP:-<服务器IP>}"

echo ""
echo "✅ 部署完成"
echo "   访问地址 : http://${IP}:${PORT}"
echo "   查看日志 : docker compose logs -f --tail=100"
echo "   停止服务 : docker compose down"
echo "   重启服务 : docker compose restart"
echo "   数据目录 : ./data （数据库 ./data/app.db，请定期备份）"
echo ""
echo "⚠️ 安全提醒：请修改 docker-compose.yml 里的 ADMIN_PASSWORD / BACKUP_PASSWORD，"
echo "   并确认 SESSION_COOKIE_SECURE 与访问方式匹配（http 访问必须为 false）。"
EOF
chmod +x "$STAGE_DIR/deploy.sh"
info "deploy.sh"

cat > "$STAGE_DIR/DEPLOY.md" <<'EOF'
# Station & Camera DRI - Docker 部署包（forDocker）

- 版本：**v__VERSION__**
- 打包时间：__BUILT__
- 打包机器架构：**__ARCH__**（包内镜像 `dri-image.tar.gz` 即该架构）

## 一、包内容

| 文件/目录 | 说明 |
| --- | --- |
| `deploy.sh` | **一键部署脚本**（加载镜像 → 启动容器 → 打印访问地址） |
| `dri-image.tar.gz` | 本地构建好的镜像，离线服务器用 `docker load` 加载 |
| `docker-compose.yml` | 服务编排（端口 8080→8000、时区、环境变量、数据卷） |
| `Dockerfile` | 镜像构建文件（服务器自行构建时使用） |
| `requirements.txt` | Python 依赖清单 |
| `scripts/ templates/ static/` | 应用源码与静态资源（服务器自行构建时使用） |
| `data-seed/app.db` | 数据库快照（**首次部署**时自动导入到 `data/app.db`；已有数据时不会覆盖） |
| `data-seed/.secret_key` | 会话签名密钥（首次部署导入 `data/`，用户重启后不掉线） |
| `.env.example` | 环境变量参考（含必须修改项说明） |
| `README.md` | 项目说明 |

## 二、服务器要求

- Linux（x86_64 或 arm64），已安装 **Docker**（含 `docker compose` v2 插件）
- 开放访问端口：默认宿主机 **8080**（在 `docker-compose.yml` 的 `ports` 中修改）
- 若架构与包内镜像不一致或不带镜像，则服务器需能访问网络以自行构建

## 三、部署步骤

```bash
# 1. 上传（在本地执行）
scp dist/forDocker.tar.gz user@server:/opt/

# 2. 解压（在服务器执行）
cd /opt && tar -xzf forDocker.tar.gz && cd forDocker

# 3. 一键部署
./deploy.sh
```

不想用脚本时，手动执行等价命令：

```bash
gunzip -c dri-image.tar.gz | docker load   # 加载镜像（架构一致时）
docker compose up -d                       # 用镜像启动
# 架构不一致时改为：docker compose up -d --build
```

启动后浏览器访问 `http://<服务器IP>:8080`。
EOF
info "DEPLOY.md（第 1 部分）"

cat >> "$STAGE_DIR/DEPLOY.md" <<'EOF'

## 四、环境变量（在 docker-compose.yml 的 environment 中）

| 变量 | 建议值 | 说明 |
| --- | --- | --- |
| `TZ` | `Asia/Shanghai` | 时区，影响数据库时间戳（不设置会差 8 小时） |
| `SESSION_COOKIE_SECURE` | `"false"` | 用 http://IP:8080 访问时必须为 false，否则登录不上；配好 HTTPS 再改 true |
| `ADMIN_PASSWORD` | 自行修改 | 用户管理入口密码 |
| `BACKUP_PASSWORD` | 自行修改 | 加密备份口令 |
| `SECRET_KEY` | 可选 | 固定会话签名密钥；不设则用 `data/.secret_key` |

## 五、数据与备份

- 数据库：宿主机 `./data/app.db`（数据卷挂载，容器重建不丢数据）
- 会话密钥：`data/.secret_key`（保留可让已登录用户重启后不掉线）
- 备份：`docker compose exec dri python scripts/backup.py`（需 `BACKUP_PASSWORD`），产物在 `./data/backups/`
- 恢复：`docker compose exec dri python scripts/restore.py <备份文件>`
- 误删表格列恢复：`docker compose exec dri python scripts/restore_revision.py --list`

## 六、更新与回滚

**更新**：本地重新双击 `package_for_docker.command` 生成新的 `forDocker.tar.gz` → 上传服务器 →
`cd /opt && tar -xzf forDocker.tar.gz`（覆盖代码即可，**线上数据在 `data/` 里，包内快照是 `data-seed/`，不会互相覆盖**）→ `cd forDocker && ./deploy.sh`。

**回滚**：保留上一个部署包，重复上面步骤即可（或 `docker load` 旧镜像后 `docker compose up -d`）。

## 七、常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `exec format error` / 容器起不来 | 镜像架构与服务器不一致（例如在 Apple Silicon 上打包）。改用 `docker compose up -d --build` 在服务器构建 |
| 登录后仍跳回登录页 | `SESSION_COOKIE_SECURE` 为 true 但用 http 访问 → 改成 `"false"` |
| 8080 端口被占用 | 修改 `docker-compose.yml` 的 `ports`（如 `"9090:8000"`） |
| 时间戳差 8 小时 | 确认 `TZ=Asia/Shanghai` |
| 网站偶发打不开 | 不要给 gunicorn 加 `--max-requests`；必须保留 `-k gthread` 多线程 |
| 忘记用户登录密码 | 用户管理页（工号 12214253 + 管理员密码）里点「重置密码」恢复为初始密码 test |

## 八、安全建议

1. 部署前修改 `ADMIN_PASSWORD`、`BACKUP_PASSWORD`，并妥善保管（不要提交到代码库）。
2. 收紧数据目录权限：`chmod 700 data`（内含数据库与会话密钥）。
3. 对外提供服务建议加 HTTPS 反向代理，之后把 `SESSION_COOKIE_SECURE` 改为 `true`。
EOF

# 把版本/架构/时间写入文档（macOS/Linux 通用写法：先写临时文件再覆盖）
sed "s/__VERSION__/$VERSION/g; s/__ARCH__/$(uname -m)/g; s|__BUILT__|$(date '+%Y-%m-%d %H:%M')|g" \
    "$STAGE_DIR/DEPLOY.md" > "$STAGE_DIR/DEPLOY.md.tmp"
mv "$STAGE_DIR/DEPLOY.md.tmp" "$STAGE_DIR/DEPLOY.md"
info "DEPLOY.md"

# ---------- 7. 导出镜像 ----------
step "导出镜像文件"
if [ "$WITH_IMAGE" = "1" ]; then
    info "docker save | gzip（大小约 100~200MB，请稍候）..."
    docker save "$IMAGE_NAME" | gzip -9 > "$STAGE_DIR/dri-image.tar.gz"
    info "已生成 dri-image.tar.gz（$(du -h "$STAGE_DIR/dri-image.tar.gz" | cut -f1)）"
else
    info "已按参数跳过镜像导出（服务器将用源码构建）"
fi

# ---------- 8. 打包成一个文件 ----------
step "打包为单个文件"
mkdir -p "$DIST_DIR"
rm -f "$ARCHIVE"
# COPYFILE_DISABLE=1：避免 macOS 把 ._ 资源分叉文件打进包
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$DIST_DIR" forDocker

SHA="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"

# ---------- 9. 汇总 ----------
step "完成"
echo "  部署包   : $ARCHIVE"
echo "  大小     : $(du -h "$ARCHIVE" | cut -f1)"
echo "  SHA256   : $SHA"
echo "  包内结构 :"
( cd "$STAGE_DIR" && find . -maxdepth 1 | sort | sed 's|^\./|    |; s|^\.$|    forDocker/|' )
echo ""
echo "  下一步（上传到服务器后执行）："
echo "    1) scp \"$ARCHIVE\" user@server:/opt/"
echo "    2) ssh user@server"
echo "    3) cd /opt && tar -xzf forDocker.tar.gz && cd forDocker && ./deploy.sh"
echo ""
echo "  服务器要求：Linux + Docker（含 compose v2 插件），放通 8080 端口"
echo ""
echo "按 Enter 键退出..."
read





