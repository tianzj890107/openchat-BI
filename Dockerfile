# eimosp-ontology-agentic-analytics 智能分析容器镜像
# 标准运行环境: Python 3.13.x（华为云 SWR 镜像 swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim）
# 统一容器内部端口: 8080（Dockerfile 显式注入，容器内监听 0.0.0.0:8080）
#   推荐宿主机映射: 8765:8080（8765 同时是非容器本地默认端口）
# 统一健康检查: GET /healthz（别名 /health）
FROM swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ROOT_PATH=/api/ontology-agentic-analytics \
    APP_NAME=eimosp-ontology-agentic-analytics \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    LLM_PROVIDER=team \
    TEAM_BASE_URL=http://172.16.10.34:4000/v1 \
    TEAM_MODEL=direct-deepseek-v4-flash \
    TEAM_MODELS=mimo-v2.5,qwen3.5-397b-a17b,doubao-seed-2-0-code-preview-260215,Qwen/Qwen3-80B-AWQ,kimi-k2.6,doubao-seed-2-0-pro-260215,direct-deepseek-v4-pro,doubao-seed-2-0-lite-260428,glm-5.2,glm-5.1,qwen3.7-plus,glm-5v-turbo,mimo-v2.5-pro,doubao-seed-2-0-mini-260428,glm-5-turbo,doubao-seed-2-1-turbo-260628,qwen3-vl-plus,qwen3.5-122b-a10b,doubao-seed-2-1-pro-260628,qwen3-vl-flash,direct-deepseek-v4-flash,qwen3.8-2.4t-a95b,qwen3.8-27b,deepseek-v4-flash-0731 \
    TEAM_DEEPSEEK_ENABLE_THINKING=true \
    TEAM_QWEN_ENABLE_THINKING= \
    QWEN_TEXT_MODELS=qwen-plus-2025-07-28,qwen3.7-plus,qwen3.7-plus-2026-05-26,qwen3.7-max,qwen3.7-max-preview,qwen3.7-max-2026-05-20,qwen3.7-max-2026-06-08,qwen3.6-plus,qwen3.6-plus-2026-04-02,qwen3.6-flash,qwen3.6-flash-2026-04-16,qwen3.6-max-preview,qwen3.6-27b,qwen3.6-35b-a3b,qwen3.5-plus,qwen3.5-plus-2026-02-15,qwen3.5-plus-2026-04-20,qwen3.5-flash,qwen3.5-flash-2026-02-23,qwen3.5-27b,qwen3.5-122b-a10b,qwen3.5-397b-a17b,qwen3-235b-a22b,qwen3-235b-a22b-instruct-2507,qwen3-235b-a22b-thinking-2507,qwen3-32b,qwen3-30b-a3b,qwen3-30b-a3b-instruct-2507,qwen3-30b-a3b-thinking-2507,qwen3-14b,qwen3-next-80b-a3b-thinking,qwen3-next-80b-a3b-instruct,qwen-plus,qwen-plus-latest,qwen-plus-0112,qwen-plus-1220,qwen-plus-2025-01-25,qwen-plus-2025-04-28,qwen-plus-2025-07-14,qwen-plus-2025-09-11,qwen-plus-2025-12-01,qwen-max,qwen3-max,qwen3-max-preview,qwen3-max-2025-09-23,qwen3-max-2026-01-23,qwen-flash,qwen-flash-2025-07-28,qwen-turbo,qwen-long-latest,qwen-long-2025-01-25,deepseek-r1,deepseek-r1-0528,deepseek-r1-distill-qwen-7b,deepseek-r1-distill-qwen-14b,deepseek-r1-distill-qwen-32b,deepseek-v3,deepseek-v3.1,deepseek-v3.2,deepseek-v3.2-exp,deepseek-v4-flash,deepseek-v4-pro,glm-4.5,glm-4.5-air,glm-4.6,glm-4.7,glm-5,glm-5.1,glm-5.2,kimi-k2.5,kimi-k2.6,kimi-k2-thinking,kimi-k2.7-code,Moonshot-Kimi-K2-Instruct,MiniMax-M2.1,MiniMax-M2.5,qwen3-coder-plus,qwen3-coder-plus-2025-07-22,qwen3-coder-plus-2025-09-23,qwen3-coder-flash,qwen3-coder-flash-2025-07-28,qwen3-coder-next,qwen3-coder-30b-a3b-instruct,qwen-coder-plus,qwen-coder-turbo,qwen-math-turbo,qwen-math-plus,qwen-math-plus-0816,qwen-math-plus-0919,qwen-math-plus-latest,qwen-mt-flash,qwen-mt-lite,qwen-mt-plus,qwen-mt-turbo,qwen-plus-character,qwen-flash-character,qwen-flash-character-2026-02-26,qwen3.5-ocr,tongyi-xiaomi-analysis-flash,tongyi-xiaomi-analysis-pro,tongyi-intent-detect-v3,gui-plus,gui-plus-2026-02-26,qwq-plus \
    QWEN_VISION_MODELS=qwen3-vl-flash,qwen3-vl-235b-a22b-thinking,qwen3-vl-32b-thinking,qwen3-vl-30b-a3b-thinking,qwen3-vl-8b-thinking,qwen3-vl-32b-instruct,qwen3-vl-flash-2026-01-22,qwen-vl-max,qwen3-vl-30b-a3b-instruct,qwen3-vl-235b-a22b-instruct,qwen3-vl-plus,qwen3-vl-plus-2025-09-23,qwen3-vl-plus-2025-12-19,qwen3-vl-8b-instruct,qvq-max,qvq-plus,qwen-vl-ocr-latest,qwen-vl-ocr,qwen-vl-ocr-1028,qwen-vl-ocr-2025-04-13,qwen-vl-ocr-2025-08-28,qwen-vl-ocr-2025-11-20 \
    ONTOLOGY_BACKEND=production \
    ONTOLOGY_BASE_URL=http://172.16.5.181:30834 \
    ONTOLOGY_REPOSITORY_ID=3 \
    ONTOLOGY_APP_ID=ApTH1EHKdRk58WhDQB \
    ONTOLOGY_TIMEOUT_SECONDS=30 \
    ONTOLOGY_CACHE_TTL_SECONDS=30 \
    RETRIEVAL_MODE=semantic \
    DORIS_API_URL=http://172.16.5.181:30834/agent/doris/query \
    DORIS_DATABASE=ontology_demometaerp_scm_po \
    CONVERSATION_SYNC_URL=http://172.16.10.34:8765 \
    CHATBI_MAX_ACTIVE_TURNS=8 \
    CHATBI_MAX_ACTIVE_PER_PRINCIPAL=2 \
    CHATBI_MAX_WAITING_TURNS=32 \
    CHATBI_ADMISSION_WAIT_SECONDS=2 \
    CHATBI_LLM_CONCURRENCY=6 \
    CHATBI_DORIS_CONCURRENCY=12 \
    CHATBI_ONTOLOGY_CONCURRENCY=12 \
    CHATBI_SESSION_IDLE_TTL_SECONDS=7200 \
    CHATBI_MAX_IN_MEMORY_SESSIONS=500 \
    CHATBI_COORDINATION_MODE=local \
    CHATBI_COORDINATION_NAMESPACE=chatbi \
    CHATBI_COORDINATION_FAILURE_MODE=closed \
    TASK_ALERT_API_ENABLED=true \
    TASK_ALERT_API_URL=http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create \
    TASK_ALERT_DEFAULT_ASSIGNEE=400 \
    TASK_ALERT_DEFAULT_LEVEL=WARNING \
    TASK_ALERT_DEFAULT_BP_DEFINITION_ID= \
    TASK_ALERT_TIMEOUT_SECONDS=10

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
