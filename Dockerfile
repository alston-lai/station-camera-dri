# Station & Camera DRI Management - 容器运行镜像
# 构建：docker build -t station-camera-dri:latest .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    LUXAI_DB_PATH=/app/data/app.db \
    FLASK_DEBUG=

WORKDIR /app

# openssl 用于加密备份（scripts/backup.py）
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖，便于利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码与静态资源
COPY scripts ./scripts
COPY templates ./templates
COPY static ./static
COPY data ./data
COPY README.md ./

# 仅声明“容器内部”端口；宿主机访问端口由 docker run / docker-compose 的映射指定
# （默认 docker-compose 用 8080 → 容器内 8000）
EXPOSE 8000

# 健康检查：容器内访问 /login（无需登录的页面）判断存活
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4).status==200 else 1)"

# 单进程 + 多线程：与 SQLite(WAL) 最匹配，减少跨进程写锁
CMD ["gunicorn", "--chdir", "/app", "-b", "0.0.0.0:8000", \
     "-w", "1", "-k", "gthread", "--threads", "8", \
     "--timeout", "120", "--max-requests", "2000", \
     "scripts.app:app"]
