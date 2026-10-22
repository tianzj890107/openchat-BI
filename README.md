# eimosp-ontology-agentic-analytics · 智能分析

eimosp-ontology-agentic-analytics 是面向业务分析场景的对话式 BI Agent。产品名称为 **智能分析**，当前版本：`ontology-v0.1.3`。

系统以 Open Claude Agent Runtime 为执行底座，将业务本体、指标口径、事实数据查询、
表格与图表生成、根因分析和决策行动组织为可追踪的分析流程，并通过 Web 工作台交付结果。

- [ontology-v0.1.3 正式版本说明](docs/versions/ontology-v0.1.3.md)
- [ontology-v0.1.2 正式版本说明](docs/versions/ontology-v0.1.2.md)
- [ontology-v0.1.1 正式版本说明](docs/versions/ontology-v0.1.1.md)
- [ontology-v0.1.0 正式版本说明](docs/versions/ontology-v0.1.0.md)
- [ontology-v0.0.10 正式版本说明](docs/versions/ontology-v0.0.10.md)
- [ontology-v0.0.9 正式版本说明](docs/versions/ontology-v0.0.9.md)
- [ontology-v0.0.8 正式版本说明](docs/versions/ontology-v0.0.8.md)
- [ontology-v0.0.7 正式版本说明](docs/versions/ontology-v0.0.7.md)
- [ontology-v0.0.6 正式版本说明](docs/versions/ontology-v0.0.6.md)
- [ontology-v0.0.5 正式版本说明](docs/versions/ontology-v0.0.5.md)
- [ontology-v0.0.4 正式版本说明](docs/versions/ontology-v0.0.4.md)
- [ontology-v0.0.3 正式版本说明](docs/versions/ontology-v0.0.3.md)
- [ontology-v0.0.2 正式版本说明](docs/versions/ontology-v0.0.2.md)
- [ontology-v0.0.1 正式版本说明](docs/versions/ontology-v0.0.1.md)
- [版本历史](docs/versions/README.md)
- [版本管理规范](docs/versions/versioning-policy.md)
- [部署说明](DEPLOYMENT.md)
- [GitLab 统一推送工作流](docs/gitlab-push-workflow.md)
- [Open Claude Runtime 说明](open_claude/README.md)

## 应用信息（部署清单）

- **Git 项目地址**：`git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git`（日常开发在 `feature/*` / `bugfix/*` 临时分支，唯一发布主线 `master`；`20260727` 已归档，`main` 已退役并删除）
- **应用名**：`eimosp-ontology-agentic-analytics`（产品名：智能分析）
- **Python 版本**：`3.13.x`（标准运行环境；`pyproject.toml` 约束 `>=3.10,<3.14`）
- **容器内部端口**：`8080`（统一；Dockerfile `ENV APP_PORT=8080` + `EXPOSE 8080`，CMD 监听 `0.0.0.0:8080`）
- **推荐宿主机映射端口**：`8765`（`-p 8765:8080`；`8765` 同时也是非容器本地直接运行默认端口）
- **端口约定**：`8080` 是统一容器内部端口；`8765`/`47313`/`47314` 是推荐宿主机映射端口或非容器直接运行端口。不要把宿主机端口写成容器内部监听端口。
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
├── ontology-analytics-skill/    # 可移植分析规则包（SKILL.md、references、cases、纯规则 scripts）
├── ontology-analytics-mcp/      # MCP 工具模块（MetricFactQuery、CanvasGenerate、ECharts 资源）
├── dataset/                     # 初始化数据及本地运行数据目录
├── docs/                        # 产品、Skills、Tools、版本与工程文档
├── changelog/                   # 周工程变更记录（只按周维护，不创建日报）
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
| 远程 MCP | `ONTOLOGY_MCP_AUTH_TOKEN`（可选）、`MCP_PUBLIC_BASE_URL`（可选）、`ONTOLOGY_MCP_EXPOSED_TOOLS`（可选） | 控制 Fuxi 连接器鉴权、Artifact 公网基址和工具白名单 |
| 并发治理 | `CHATBI_MAX_ACTIVE_TURNS` 等 | 限制 turn、principal 和下游并发 |
| 子路径部署 | `APP_ROOT_PATH` | 外部网关子路径前缀（如 `/api/ontology-agentic-analytics`）；缺省为空字符串，保持域名根路径部署 |

模型、并发和转督办的基础示例见 [.env.example](.env.example)，本体、Doris 等完整生产配置
及运行边界见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 启动 Web 工作台

```bash
source .venv/bin/activate
python -m bi_agent.web --host 127.0.0.1 --port 8765 --db doris
```

浏览器访问 `http://127.0.0.1:8765/workbench`（`8765` 为非容器本地默认端口；容器内部统一为 `8080`，见下），健康检查：

```bash
curl -fsS http://127.0.0.1:8765/healthz
```

本地本体与 SQLite 参数通过 `python -m bi_agent.web --help` 查看。

### V3 经营驾驶舱 POC

主服务提供三个独立看板入口（支持 `APP_ROOT_PATH` 子路径）：
`/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`；`/cockpit` 仍只跳到经营看板。
`/cockpit/home` 保留为兼容地址（FastAPI 307、静态站客户端改写为 `overview`），不再单独渲染第四个页面。
三个入口共用同一路径和 Fuxi 身份参数 `id`：`id=1` 对应总裁，`id=2` 对应分析员；当前三页内容与功能对两个 `id` 完全一致，
两个人都可访问，`id` 仅作为将来差异化的预留标识。不使用 `role` 或两套身份地址，总入口和页内跳转均保留当前 `id`。
页面直接使用 `iba-demo` 交付看板 `feature/demo_1021@37975c7` 的根配置：一个 `ProBiDashboard` 同时渲染
`composite-filter`、根 `tab-container` 和三个 Tab 模板。顶部 Tab 由交付配置生成，不再由宿主手写；
三个路由只负责激活对应 Tab，并把当前 `id` 保留在地址中。页面不渲染工作区、会话区、宿主标题或第二套导航。

发布包包含 13 份模板、122 个组件和交付的顶部筛选器。三页的 `position`、`parentId`、容器、标题和样式
均按交付配置原样交给 `ProBiDashboard`；宿主不增删或重排卡片。浏览器通过同目录
`data-snapshots.json` 回放 pdt 正式页抓取的 39 个 AP 查询、3 个批量查询和 4 个头盔图请求，
快照只包含业务响应体，不包含 Cookie、Token 或用户身份；未捕获查询在原卡片显示快照缺失提示。

交付根配置没有 `insights` 字段，宿主从交付目录补入 12 个插槽声明：经营看板 0 个、运营 360 4 个、
穿透式问题分析 8 个。插槽内容直接使用交付 `insight-components/` 的静态组件，本轮不调用模型；
主服务 `/api/cockpit` 的实时分析、历史和任务令接口仍保留，后续需要实时 AI 时再接入。
交付配置中 AP 指标的业务口径与卡片标题存在差异时，页面保持原值，不在宿主层改写。
详见 [驾驶舱范围与接口](docs/specs/cockpit-v3-poc.md)及[组件覆盖与缺失](docs/specs/cockpit-v3-metadata-gaps.md)。

### Fuxi 远程 MCP

主服务已内置 Streamable HTTP MCP，入口与健康检查：

```text
POST http://<host>:8765/api/mcp
GET  http://<host>:8765/api/mcp/health
GET  http://<host>:8765/api/mcp/artifacts/<filename>
```

Fuxi 连接器配置：

```json
{
  "transport": "http",
  "url": "http://<host>:8765/api/mcp",
  "headers": {}
}
```

连接后可以看到 16 个真实分析工具（`AnalysisRoute`、`MetricFactQuery`、
`ChartGenerate`、`TableGenerate`、`CanvasGenerate`、`OutputGateCheck` 等），
不会出现 `AnalysisRun`、`AskUser`、`TodoWrite` 或原始 SQL 工具。客户端不需要
`.env`、App ID 或 Token；demo2 本体和 Doris 配置由主服务持有。若在网关后使用，
用 `MCP_PUBLIC_BASE_URL` 指定外部可访问基址，使 `CanvasGenerate` 返回的
`Artifact URL` 不指向容器内地址。

## 反向代理子路径部署（`APP_ROOT_PATH`）

应用可完整运行在网关保留的子路径下，例如配置：

```bash
APP_ROOT_PATH=/api/ontology-agentic-analytics
```

配置后对外入口统一为：

- `http://<host>/api/ontology-agentic-analytics/workbench`
- `http://<host>/api/ontology-agentic-analytics/static/...`
- `http://<host>/api/ontology-agentic-analytics/api/...`
- `http://<host>/api/ontology-agentic-analytics/healthz`

网关负责把该前缀流量转发给应用，并在 ASGI 层按 `root_path` 语义剥离前缀；应用内部
路由仍为 `/workbench`、`/static/*`、`/api/*`、`/healthz`。不设置 `APP_ROOT_PATH`
时行为与域名根路径部署完全一致。容器内部 `HEALTHCHECK` 仍探测
`http://127.0.0.1:8080/healthz`（不带外部前缀），外部健康检查才使用
`/api/ontology-agentic-analytics/healthz`。非法前缀（含协议、域名、查询串、
`/` 重复或 `.`/`..` 段）会在启动时快速失败。

## Docker 运行

```bash
# 构建（无需 Node.js，前端构建产物已随仓库提供）
docker build -t eimosp-ontology-agentic-analytics:0.1.2 .

# 运行：容器内部统一监听 8080，宿主机推荐映射 8765:8080
# 生产默认远程本体 + Doris 实时查询；配置经 .env 或 -e 注入
# 运行数据目录（会话/图表/上传/日志）挂载持久卷
docker run -d --name eimosp-ontology-agentic-analytics -p 8765:8080 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v eimosp-ontology-agentic-analytics-conversations:/app/dataset/conversations \
  -v eimosp-ontology-agentic-analytics-charts:/app/dataset/charts \
  -v eimosp-ontology-agentic-analytics-uploads:/app/dataset/uploaded_reports \
  -v eimosp-ontology-agentic-analytics-logs:/app/dataset/logs \
  eimosp-ontology-agentic-analytics:0.1.2

# 健康检查（容器内置 HEALTHCHECK 探测容器内 http://127.0.0.1:8080/healthz，
# 从宿主机经映射端口 8765 探测）
curl -fsS http://127.0.0.1:8765/healthz
```

`8765:8080` 中左侧 `8765` 是宿主机端口，右侧 `8080` 是容器内部监听端口
（Dockerfile `ENV APP_PORT=8080` + `EXPOSE 8080`）。镜像基于官方
`python:3.13-slim`，`HEALTHCHECK` 探测容器内 `/healthz`；本地 SQLite 演示模式
可覆盖启动命令传 `--db dataset/databases/HyperFusion.db`
（本地模式需保留镜像内的初始化数据文件）。

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
- 普通修改默认验证、commit，并从 `master` 拉出 `feature/*` / `bugfix/*` 临时分支推送到 GitLab 同名分支；正式交付通过 Merge Request 合入唯一发布主线 `master`（reviewer `tianzijing`，code review 后由有权限人员合并）；线上紧急缺陷走 `hotfix/*`，从 `release/*` 拉出并向 `release/*` 与 `master` 各开一条 MR；
- 版本号不按日期或部署次数机械增长，详见
  [语义化版本与正式发布规范](docs/versions/versioning-policy.md)；
- push 不等于部署，部署必须由用户在当前任务中明确授权；
- GitLab Release 授权后在 GitLab 仓库 `ai-team/eimosp-ontology-agentic-analytics` 上基于同名 tag 创建（只补缺失项，不覆盖已有 Release）；
- 当前版本 `ontology-v0.1.3` 的 tag 与 GitLab Release 尚未创建；必须在 MR 合入 `master` 后由用户单独授权，不能由本次版本收口自动触发；
- 已发布 Release：[智能分析 ontology-v0.1.2](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.2)、对应 tag 指向定版 commit `3c4de1e`；[智能分析 ontology-v0.1.1](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.1)、对应 tag 指向定版 commit `c82221f`（2026-10-15 补建）；上一版本：[智能分析 ontology-v0.1.0](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.0)、对应 tag 指向定版 commit `74fca80`；此前版本：[智能分析 ontology-v0.0.10](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.10)、[智能分析 ontology-v0.0.9](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.9)、[智能分析 ontology-v0.0.8](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.8)、[智能分析 ontology-v0.0.7](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.7)、[智能分析 ontology-v0.0.6](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.6)、[智能分析 ontology-v0.0.5](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.5)、[智能分析 ontology-v0.0.4](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.4)、[智能分析 ontology-v0.0.3](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.3)、[智能分析 ontology-v0.0.2](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.2)、[智能分析 ontology-v0.0.1](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.1)

## 相关文档

- [部署与运行](DEPLOYMENT.md)
- [系统接口调用与代码统计](API/系统接口调用与代码统计.md)
- [智能分析 Agent 前端 API 接口文档](API/智能分析Agent前端API.md)
- [Skills 说明](docs/skills/README.md)
- [Agent 场景分析 SOP](docs/ChatBI_Agent场景分析SOP.md)
- [Tools 清单](docs/ChatBI_Tools.md)
- [脚本说明](scripts/README.md)

## License

仓库中的 Open Claude Runtime 沿用 MIT License；eimosp-ontology-agentic-analytics 其他业务代码的授权范围请联系项目维护者确认。
