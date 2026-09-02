# eimosp-ontology-agentic-analytics · 智能分析

eimosp-ontology-agentic-analytics 是面向业务分析场景的对话式 BI Agent。产品名称为 **智能分析**，当前版本：`v0.1.0`。

系统以 Open Claude Agent Runtime 为执行底座，将业务本体、指标口径、事实数据查询、
表格与图表生成、根因分析和决策行动组织为可追踪的分析流程，并通过 Web 工作台交付结果。

- [v0.1.0 正式版本说明](docs/versions/v0.1.0.md)
- [版本历史](docs/versions/README.md)
- [版本管理规范](docs/versions/versioning-policy.md)
- [部署说明](DEPLOYMENT.md)
- [GitLab 统一推送工作流](docs/gitlab-push-workflow.md)
- [Open Claude Runtime 说明](open_claude/README.md)

## 应用信息（部署清单）

- **Git 项目地址**：`git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git`（开发分支 `20260727`，发布分支 `main`）
- **应用名**：`eimosp-ontology-agentic-analytics`（产品名：智能分析）
- **Python 版本**：`3.13.x`（标准运行环境；`pyproject.toml` 约束 `>=3.10,<3.14`）
- **统一应用端口**：`8765`（固定）
- **统一健康检查接口**：`GET /healthz`（别名 `GET /health`），就绪返回 `200`，未完成配置返回 `503`
- **Nacos 配置中心**：预留待对接（当前未接入，见 [DEPLOYMENT.md](DEPLOYMENT.md)）

## 核心能力

- 六步分析 SOP：意图识别、本体模型匹配、深度思考&分析规划、数据获取和可视化、根因分析、决策行动；
- 通过业务本体完成术语、指标、实体和关系匹配，支持 GraphContext 与 GraphExpand 子图查看；
- 支持指标配置查询和只读事实查询，并根据真实结果生成表格、图表和业务结论；
- 支持结构化 Claims 校验、根因分析、行动建议和转督办；
- 支持智能分析、报表分析、历史会话恢复和会话内数据源切换；
- 支持流式输出、请求终态隔离、并发保护和模型级 thinking 能力控制。

## 系统结构

```text
eimosp-ontology-agentic-analytics/
├── bi_agent/                    # BI Agent、本体、工具、可靠性与 Web API
│   ├── llm/                     # 模型与 Team 网关适配
│   ├── ontology/                # 本地/远程本体访问与检索
│   ├── tools/                   # 本体、取数、表格、图表和交互工具
│   └── web/                     # FastAPI、会话运行时与静态工作台
├── frontend/                    # React + Ant Design X 工作台源码（本体图渲染复用 @boulderaitech/ontology-graph）
├── open_claude/                 # 通用 Agent Runtime 与 CLI
├── .claude/agents/              # 智能分析、报表分析和报表生成角色
├── dataset/                     # 初始化数据及本地运行数据目录
├── docs/                        # 产品、Skills、Tools、版本与工程文档
├── changelog/                   # 日/周工程变更记录
├── scripts/                     # 数据、元数据和 Git 工作流脚本
└── tests/                       # 回归、可靠性、并发与文档契约测试
```

Open Claude 是仓库内的基础运行时组件，不是根项目名称。其 CLI、权限、Skills 和内部架构见
[open_claude/README.md](open_claude/README.md)。

## 环境要求

- Python 3.13.x（标准运行环境；兼容 `>=3.10,<3.14`，见 `pyproject.toml`）
- Node.js 与 npm（仅前端开发或重新构建时需要）
- 可用的大模型服务
- 远程本体服务或本地本体工作簿
- Doris 数据服务或本地开发用 SQLite 数据库

## 本地安装

```bash
git clone git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git
cd eimosp-ontology-agentic-analytics
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[web]'
cp .env.example .env
```

在 `.env` 中填写实际模型、本体和数据源配置。`.env` 已被忽略，禁止提交真实密钥。

## 配置

| 配置组 | 主要变量 | 用途 |
| --- | --- | --- |
| 模型网关 | `LLM_PROVIDER`、`TEAM_BASE_URL`、`TEAM_API_KEY`、`TEAM_MODEL` | 选择模型提供方与默认模型 |
| 本体服务 | `ONTOLOGY_BACKEND`、`ONTOLOGY_BASE_URL`、`ONTOLOGY_REPOSITORY_ID` | 选择本地或远程本体 |
| 事实数据 | `DORIS_API_URL`、`DORIS_DATABASE` | 配置业务事实查询 |
| 并发治理 | `CHATBI_MAX_ACTIVE_TURNS` 等 | 限制 turn、principal 和下游并发 |

模型、并发和转督办的基础示例见 [.env.example](.env.example)，本体、Doris 等完整生产配置
及运行边界见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 启动 Web 工作台

```bash
source .venv/bin/activate
python -m bi_agent.web --host 127.0.0.1 --port 8765 --db doris
```

浏览器访问 `http://127.0.0.1:8765/workbench`（`8765` 为固定统一应用端口），健康检查：

```bash
curl -fsS http://127.0.0.1:8765/healthz
```

本地本体与 SQLite 参数通过 `python -m bi_agent.web --help` 查看。

## Docker 运行

```bash
# 构建（无需 Node.js，前端构建产物已随仓库提供）
docker build -t eimosp-ontology-agentic-analytics:0.1.0 .

# 运行：生产默认远程本体 + Doris 实时查询
# 配置经 .env 或 -e 注入；运行数据目录（会话/图表/上传/日志）挂载持久卷
docker run -d --name eimosp-ontology-agentic-analytics -p 8765:8765 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v eimosp-ontology-agentic-analytics-conversations:/app/dataset/conversations \
  -v eimosp-ontology-agentic-analytics-charts:/app/dataset/charts \
  -v eimosp-ontology-agentic-analytics-uploads:/app/dataset/uploaded_reports \
  -v eimosp-ontology-agentic-analytics-logs:/app/dataset/logs \
  eimosp-ontology-agentic-analytics:0.1.0

# 健康检查（容器内置 HEALTHCHECK，也可手动探测）
curl -fsS http://127.0.0.1:8765/healthz
```

Dockerfile 固定使用 `python:3.13-slim`、统一端口 `8765`，镜像内 `HEALTHCHECK` 探测
`/healthz`；本地 SQLite 演示模式可覆盖启动命令传
`--db dataset/databases/HyperFusion.db`（本地模式需保留镜像内的初始化数据文件）。

## 前端开发与构建

```bash
cd frontend
npm install
npm run dev
```

生产构建：

```bash
cd frontend
npm run build
```

构建会更新 `bi_agent/web/static/vendor/antd/workbench.js` 和
`bi_agent/web/static/vendor/antd/eimosp-ontology-agentic-analytics-workbench.css`。

## 测试

```bash
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
cd frontend && npm run build
```

前端当前没有独立的 `npm test` 命令；SOP、流式终态和生命周期等纯函数由回归测试中的
Node 子进程执行。

## Agent 与工具

角色定义位于 `.claude/agents/`：

- `bi-analyst`：智能分析；
- `report-analyst`：报表解读与数据库扩展分析；
- `report-generator`：报表生成。

工具清单见 [docs/ChatBI_Tools.md](docs/ChatBI_Tools.md)，分析 SOP 见
[docs/ChatBI_Agent场景分析SOP.md](docs/ChatBI_Agent场景分析SOP.md)。

## 数据安全

历史会话、上传文件、图表、日志和导出文件属于用户数据，不属于代码发布内容。未经明确授权，
禁止删除、清空、迁移或覆盖 `dataset/conversations/`、`dataset/uploaded_reports/`、
`dataset/charts/`、`dataset/logs/` 等运行目录。

不要提交 `.env`、API key、访问令牌、生产数据库凭据或运行数据。

## 版本、提交与发布

- commit、push、部署不自动触发版本升级；
- commit、push、Git tag、GitLab Release 和部署是彼此独立的动作；
- 普通修改默认验证、commit，并将同一 commit 推送到 GitLab 统一开发分支 `gitlab/20260727`；merge 到 `main` 需要 `tianzijing` code review 后单独发起；
- 版本号不按日期或部署次数机械增长，详见
  [语义化版本与正式发布规范](docs/versions/versioning-policy.md)；
- push 不等于部署，部署必须由用户在当前任务中明确授权；
- GitLab Release 授权后在 GitLab 仓库 `ai-team/eimosp-ontology-agentic-analytics` 上基于同名 tag 创建（只补缺失项，不覆盖已有 Release）；
- 已发布 Release：[智能分析 v0.1.0](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/v0.1.0)

## 相关文档

- [部署与运行](DEPLOYMENT.md)
- [系统接口调用与代码统计](API/系统接口调用与代码统计.md)
- [Skills 说明](docs/skills/README.md)
- [Agent 场景分析 SOP](docs/ChatBI_Agent场景分析SOP.md)
- [Tools 清单](docs/ChatBI_Tools.md)
- [脚本说明](scripts/README.md)

## License

仓库中的 Open Claude Runtime 沿用 MIT License；eimosp-ontology-agentic-analytics 其他业务代码的授权范围请联系项目维护者确认。
