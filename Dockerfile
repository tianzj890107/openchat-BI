# eimosp-ontology-agentic-analytics 智能分析容器镜像
# 标准运行环境: Python 3.13.x（Docker 官方 python:3.13-slim）
# 统一容器内部端口: 8080（Dockerfile 显式注入，容器内监听 0.0.0.0:8080）
#   推荐宿主机映射: 8765:8080（8765 同时是非容器本地默认端口）
# 统一健康检查: GET /healthz（别名 /health）
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_NAME=eimosp-ontology-agentic-analytics \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir '.[web]'

# 以非 root 用户运行；/app 下的运行数据目录（会话/图表/上传等）保持可写
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status == 200 else 1)"

# 生产默认走远程本体 + Doris 实时查询；本地 SQLite 可覆盖 CMD 传 --db dataset/databases/HyperFusion.db
CMD ["python", "-m", "bi_agent.web", "--host", "0.0.0.0", "--port", "8080", "--db", "doris"]
