# 本地 Excel 本体回退部署说明

> 适用对象：客户现场无法部署远程本体平台，但需要保留智能分析 Agent 的本体语义查询与业务取数能力。
>
> 状态：现有能力，无需修改业务代码。本文只描述部署和运维方式。
>
> 结论：本地 Excel 本体模式仍然存在，但它是启动时显式选择的另一套数据源配置，不是远程本体平台故障后的自动降级。

## 1. 结论速览

| 问题 | 结论 |
| --- | --- |
| 是否还支持本地 Excel 本体 | 支持。启动时加载 `.xlsx` 本体工作簿到进程内存。 |
| 是否会自动从远程本体切换到 Excel | 不会。必须显式设置 `ONTOLOGY_BACKEND=local`，并重启服务。 |
| 只放 Excel 就能查询业务明细吗 | 不能。Excel 提供术语、指标、实体、属性、关系等语义元数据；业务明细还需要 SQLite 或 Doris 事实库。 |
| 客户没有 Doris 和本体平台时能否运行 | 可以。使用 `ONTOLOGY_BACKEND=local` + Excel 本体 + 本地 SQLite，事实查询走 `Ontology-FactQuery`。 |
| 是否等于完全离线 | 不完全是。本体和事实数据可以本地化，但大模型仍需要可用的模型网关或私有模型服务。 |
| 是否影响驾驶舱 POC | 本文只说明主分析工作台的本地本体模式；驾驶舱的 AP 快照/发布数据是另一条数据链路，不要混用。 |

## 2. 两套数据源分别负责什么

本地回退不是把 Excel 当成数据库。推荐按下面的职责拆分：

| 数据 | 推荐文件 | 作用 | 缺失后的影响 |
| --- | --- | --- | --- |
| 本体语义元数据 | `dataset/spreadsheets/*.xlsx` | 术语消歧、业务对象/逻辑实体/属性、关系、指标口径、活动、规则、维度 | 无法稳定识别业务术语、指标和实体关系，分析结果容易退化为通用问答。 |
| 业务事实数据 | `dataset/databases/*.db` | `Ontology-FactQuery`、`ListTables`、`DescribeTable` 的实际查询对象 | 仍可解释本体和指标，但不能回答“本期多少、哪些客户、哪个部门”等明细问题。 |
| 图库数据（可选） | `dataset/graphs/*.graphml` 等 | 本地图库检索模式的上下文扩展 | 不影响普通语义检索；没有图文件时不要启用图库检索模式。 |

本模式不会自动把 Excel 转成 SQLite。客户事实数据必须先形成可查询的 SQLite 数据库，或继续使用客户已有的 Doris 查询网关。

## 3. 两种可用组合

### 3.1 完全本地：Excel 本体 + SQLite 事实库

适用于客户无法部署远程本体平台、也没有可用 Doris 网关的场景。

```text
用户问题
  → 本地 Excel 本体：识别术语、指标、实体、属性和关系
  → 本地 SQLite：执行只读事实 SQL
  → 图表 / 表格 / 分析结论
```

启动时必须同时指定：

- `ONTOLOGY_BACKEND=local`
- `--ontology <本体.xlsx>`
- `--db <事实库.db>`

### 3.2 混合模式：本地 Excel 本体 + 客户 Doris

适用于客户已经有可用的只读 SQL 查询网关，只是没有部署本体平台。

```text
用户问题
  → 本地 Excel 本体：识别业务语义
  → 客户 Doris 查询网关：执行事实 SQL
  → 图表 / 表格 / 分析结论
```

此模式仍需配置 `DORIS_API_URL`（以及客户要求的连接参数），但不需要 `ONTOLOGY_BASE_URL`、`ONTOLOGY_REPOSITORY_ID` 或 `ONTOLOGY_AUTH_TOKEN` 才能加载本地本体。

> 注意：`--db` 不传时，程序默认使用 `doris`，即使 `ONTOLOGY_BACKEND=local` 也一样。因此，如果需要 SQLite 事实库，必须显式传入 `--db dataset/databases/<name>.db`。

## 4. 部署前置条件

### 4.1 运行环境

- Python `>=3.10,<3.14`，标准运行环境为 Python `3.13.x`；
- 项目依赖已安装：`python -m pip install -e '.[web]'`；
- 可用的大模型服务或模型网关；
- 只读业务事实库：本地 SQLite 或客户 Doris 查询网关；
- 已脱敏的 Excel 本体文件和客户事实数据文件。

### 4.2 目录约定

所有相对路径都相对于启动时的 `--cwd`（缺省为当前工作目录）解析。建议交付时显式指定项目根目录：

```text
/opt/eimosp-ontology-agentic-analytics/
├── .env
├── bi_agent/
├── dataset/
│   ├── spreadsheets/
│   │   └── 客户本体.xlsx
│   ├── databases/
│   │   └── 客户事实库.db
│   ├── graphs/                 # 可选
│   └── conversations/          # 运行时持久化，禁止覆盖
└── ...
```

不要为了替换本体或数据库而整体覆盖 `dataset/`，否则可能误删历史会话、上传文件、图表和日志。只替换明确的 `spreadsheets/*.xlsx` 与 `databases/*.db` 文件。

### 4.3 文件交付检查

至少记录以下信息，便于回滚和验收：

```bash
sha256sum dataset/spreadsheets/客户本体.xlsx dataset/databases/客户事实库.db
ls -lh dataset/spreadsheets/客户本体.xlsx dataset/databases/客户事实库.db
```

Excel 中不要包含客户不希望交付的敏感数据。本体工作簿虽然只保存元数据，也可能包含业务对象、指标定义和内部命名。

## 5. 配置 `.env`

完全本地模式的最小配置示例：

```dotenv
# 显式选择本地 Excel 本体
ONTOLOGY_BACKEND=local

# 非容器直接运行时的默认端口；也可用 --port 覆盖
APP_PORT=8765

# 普通语义检索；只有准备好 graphml 时才改为 graph
RETRIEVAL_MODE=semantic

# 模型网关：按客户环境填写，不能把真实密钥提交到仓库
LLM_PROVIDER=team
TEAM_BASE_URL=<客户模型网关地址>
TEAM_MODEL=<模型名>
TEAM_API_KEY=<按环境注入>
```

说明：

- `ONTOLOGY_BACKEND=local` 是启动期配置，修改后必须重启进程。
- 本地模式下 `ONTOLOGY_BASE_URL`、`ONTOLOGY_REPOSITORY_ID`、`ONTOLOGY_AUTH_TOKEN` 不再参与本地 Excel 加载；可以保留为空或删除，避免误以为仍在连接远程本体。
- 走 SQLite 时不需要 `DORIS_API_URL`。
- 走客户 Doris 时，保留 `.env` 或服务环境中的 `DORIS_API_URL`，并用 `--db doris` 启动。
- 密钥只通过 `.env`、容器 secret 或服务器环境注入，禁止写入镜像和 Git。

## 6. 启动命令

### 6.1 非容器直接运行（推荐用于客户现场）

```bash
cd /opt/eimosp-ontology-agentic-analytics
source .venv/bin/activate

export ONTOLOGY_BACKEND=local

python -m bi_agent.web \
  --host 0.0.0.0 \
  --port 8765 \
  --cwd /opt/eimosp-ontology-agentic-analytics \
  --ontology "dataset/spreadsheets/客户本体.xlsx" \
  --db "dataset/databases/客户事实库.db"
```

启动日志中应能看到类似：

```text
[bi-agent-web] agent=bi-analyst  ontology=客户本体.xlsx  db=客户事实库.db
```

如果没有出现 `db=客户事实库.db`，而是 `db=Doris(实时查询)`，说明 `--db` 没有正确传入，SQLite 并没有成为事实查询后端。

### 6.2 systemd 示例

```ini
[Unit]
Description=eimosp ontology agentic analytics (local Excel fallback)
After=network.target

[Service]
Type=simple
User=eimosp
WorkingDirectory=/opt/eimosp-ontology-agentic-analytics
EnvironmentFile=/opt/eimosp-ontology-agentic-analytics/.env
Environment=ONTOLOGY_BACKEND=local
ExecStart=/opt/eimosp-ontology-agentic-analytics/.venv/bin/python -m bi_agent.web --host 0.0.0.0 --port 8765 --cwd /opt/eimosp-ontology-agentic-analytics --ontology "dataset/spreadsheets/客户本体.xlsx" --db "dataset/databases/客户事实库.db"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

不要添加 `--workers N`。当前会话和并发状态保存在进程内，按单 worker 部署。

### 6.3 Docker

Dockerfile 默认是 `ONTOLOGY_BACKEND=production`，并且默认 CMD 使用 `--db doris`。本地回退必须在 `docker run` 时覆盖环境变量和启动命令：

```bash
docker run -d \
  --name eimosp-ontology-agentic-analytics-local \
  -p 8765:8080 \
  -e ONTOLOGY_BACKEND=local \
  -e APP_PORT=8080 \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/dataset/spreadsheets/客户本体.xlsx:/app/dataset/spreadsheets/客户本体.xlsx:ro" \
  -v "$(pwd)/dataset/databases/客户事实库.db:/app/dataset/databases/客户事实库.db" \
  -v eimosp-conversations:/app/dataset/conversations \
  -v eimosp-charts:/app/dataset/charts \
  -v eimosp-uploads:/app/dataset/uploaded_reports \
  -v eimosp-logs:/app/dataset/logs \
  eimosp-ontology-agentic-analytics:<版本> \
  python -m bi_agent.web \
    --host 0.0.0.0 \
    --port 8080 \
    --cwd /app \
    --ontology "dataset/spreadsheets/客户本体.xlsx" \
    --db "dataset/databases/客户事实库.db"
```

注意：

- 容器内部端口仍为 `8080`；`8765` 只是宿主机映射端口。
- 不要用 `-v /客户/dataset:/app/dataset:ro` 覆盖整个运行数据目录，否则会话、图表、上传和日志将不可写。
- SQLite 事实库未加 `:ro`，是为了兼容 WAL 模式在连接时创建/访问同目录临时文件；只读约束由 `Ontology-FactQuery` 在 SQL 层保证。若客户要求文件系统级只读，应使用宿主 ACL/只读存储账号，并先用实际数据库验证 WAL 文件可访问。
- 如果使用镜像内置示例数据做验收，可以不挂载业务文件，但示例数据不能冒充客户数据。

## 7. Excel 本体文件格式

加载入口是 `OntologyStore.from_xlsx()`。程序按工作表名称和表头识别内容，不依赖固定列顺序。

### 7.1 必需工作表

| 工作表 | 主要内容 |
| --- | --- |
| `术语` | 术语编码、名称、英文名、定义、分类、别名 |
| `业务对象` | 业务对象编码、名称、英文名、定义、类型 |
| `逻辑实体` | 业务对象、逻辑实体编码、名称、英文名、定义、物理表名 |
| `业务属性` | 属性编码、逻辑实体、属性名称、英文名、定义、数据类型 |
| `实体关系` | 源实体、目标实体、关系类型、基数等 |
| `指标` | 指标编码、名称、类型、定义、别名、对应表名、业务对象、维度列等 |
| `活动` | 活动编码、名称、描述、上游活动、操作业务对象 |
| `业务规则` | 规则编码、所属活动、规则描述、规则分类、解释部门 |
| `指标维度矩阵` | 前两列为指标编码/名称，后续列为维度短名；单元格使用 `Y`、`yes`、`1`、`true` 或 `是` 表示适用 |

### 7.2 可选工作表

| 工作表 | 用途 |
| --- | --- |
| `维度` | 维度编码、名称、英文名、层级、别名 |
| `活动流` | 活动流转和场景子流程 |
| `本体元模型关系` | 类型级关系，例如业务对象与逻辑实体的关系 |

### 7.3 格式约束

- 只支持 `.xlsx`；不要用旧式 `.xls`。
- 每张工作表第一个非空行作为表头；表头前可以有空行。
- 部分工作表按表头名称匹配列，列顺序可以与示例文件不同；但必需的表头名称不能缺失。
- 多值字段支持英文逗号、中文逗号、分号和顿号分隔。
- 有些导出的 xlsx 带有损坏的 `autoFilter` XML；加载器会在内存中剥离该节点后读取，不修改磁盘上的原文件。仍然建议业务方在交付前用 Excel/WPS 重新保存一次干净文件。
- 修改 Excel 后不会自动热更新。需要重启，或在数据源设置页重新选择本体文件（仅当前会话生效）。

## 8. SQLite 事实库

### 8.1 内置示例

仓库自带的 `dataset/databases/HyperFusion.db` 是超聚变示例数据，不是客户生产数据。当前示例包含：

- 表：`T_HF_PL_Detail`、`T_HF_RevenueForecast`、`T_HF_DemoData`、`T_HF_RefreshData`、`T_META_ColumnMap`
- 视图：`V_HF_DataAll`、`V_HF_DataAll_Summary`、`V_HF_PL_Summary`

可用下面的只读查询验证事实库是否可访问：

```sql
SELECT FPeriod, COUNT(*) AS n
FROM T_HF_PL_Detail
GROUP BY FPeriod
ORDER BY FPeriod
LIMIT 5;
```

### 8.2 客户自己的 SQLite

客户数据需要单独生成 SQLite 文件。Excel 本体只描述语义，不会自动生成业务表、字段映射或数据行。

交付前至少确认：

- 本体 `指标` 工作表中的“对应表名/来源实体”能在 SQLite 中对应到真实表或视图；
- 日期、组织、客户、产品等维度字段的编码和显示值一致；
- 金额、数量、电量等单位与指标定义一致；
- 客户事实库中有稳定的主键或可去重字段；
- 已用只读账号或只读文件权限验证。

### 8.3 重建示例库

仅在需要重建仓库自带的超聚变示例库时使用：

```bash
python scripts/data/build_hyperfusion_db.py
```

警告：该脚本会删除并重建 `dataset/databases/HyperFusion.db`，并依赖：

- `dataset/spreadsheets/超聚变报表.xlsx`
- `dataset/spreadsheets/超聚变数据.xlsx`

在生产客户机上不要直接对客户共享库执行该脚本。先停止服务、备份现有数据库，并确认目标文件不是客户唯一数据源。

### 8.4 只读限制

`Ontology-FactQuery` 只允许单条只读语句，禁止写操作、DDL、多语句和会改变数据库状态的 `PRAGMA` 赋值；默认最多返回 1000 行。`PRAGMA table_info(...)` 这类只读结构查询在 SQLite 模式下可用。

## 9. 部署验证

### 9.1 健康检查

```bash
curl -fsS http://127.0.0.1:8765/healthz
```

预期返回 HTTP 200。

### 9.2 数据源检查

```bash
curl -fsS http://127.0.0.1:8765/api/sources | python -m json.tool
```

重点检查：

- `ontology.active` 指向客户本体 `.xlsx`；
- `database.active` 指向客户 SQLite `.db`；
- `doris.active` 为 `false`；
- `ontology.options` 和 `database.options` 中包含本次交付的文件。

### 9.3 本体加载检查

用仓库内置 MetaERP 本体做冒烟检查时，当前版本可加载出以下规模（2026-10-26 实测，仅作为示例）：

```text
terms 120
business_objects 8
logical_entities 19
attributes 695
relations 17
metrics 12
activities 15
rules 2
dimensions 6
processes 5
```

客户本体文件的行数会不同，不要求与上表一致；但加载不能报错，且关键术语、业务对象、指标应能在工作台中检索到。

### 9.4 事实查询检查

在工作台或工具调试入口执行一条只读 SQL，确认事实库生效。可使用第 8.1 节示例查询，或：

```sql
SELECT name, type
FROM sqlite_master
WHERE type IN ('table', 'view')
  AND name NOT LIKE 'sqlite_%'
ORDER BY type, name;
```

如果工具仍提示 Doris 或远程网关，检查启动命令是否真的带上了 `--db`。

### 9.5 业务验收

至少用三个问题验收：

1. 术语或指标解释：能否从本地 Excel 中找到指标定义、业务对象和适用维度；
2. 事实查询：能否基于 SQLite 查出真实行数、金额或分组结果；
3. 分析链路：图表、表格、结论是否引用了同一次查询结果，而不是模型臆造。

## 10. 切换与回滚

### 10.1 从远程本体切到本地 Excel

1. 停止服务，避免运行中的会话持有旧数据源。
2. 备份 `.env`、当前本体文件和事实库。
3. 把客户本体放入 `dataset/spreadsheets/`，事实库放入 `dataset/databases/`。
4. 设置 `ONTOLOGY_BACKEND=local`。
5. 使用第 6 节的命令启动，并确保 `--db` 指向 SQLite（或显式传 `--db doris` 使用客户 Doris）。
6. 完成第 9 节验证。

不要只修改 `.env` 而不重启；`ONTOLOGY_BACKEND` 是启动期读取。

### 10.2 从本地 Excel 切回远程本体

1. 停止服务并备份本地文件。
2. 恢复 `ONTOLOGY_BACKEND=production`（或 `remote`）。
3. 注入该环境自己的 `ONTOLOGY_BASE_URL`、`ONTOLOGY_REPOSITORY_ID`、`DORIS_API_URL` 和认证令牌。
4. 使用 `--db doris` 或环境默认命令启动。
5. 检查 `/api/sources` 中远程本体库目录、`doris.active` 和远程仓库编号是否与当前环境一致。

### 10.3 会话与历史数据

切换数据源不要求清空会话。不得删除、覆盖或迁移 `dataset/conversations/`、`dataset/uploaded_reports/`、`dataset/charts/`、`dataset/logs/`。回退只替换本体/事实文件，不处理用户历史数据。

## 11. 已知差异与限制

| 能力 | 远程本体平台 | 本地 Excel 回退 |
| --- | --- | --- |
| 本体库目录、版本管理、多库切换 | 支持 | 不具备平台级目录；以文件和会话选择为主 |
| 远程权限、审计、认证 | 由平台提供 | 不提供；需在反向代理或网关层补鉴权 |
| 远程 Graph/MAL 图检索 | 支持 | 仅能用本地 `.graphml` 等文件，能力有限 |
| `Ontology-MetricQuery` | 远程专有 | 不使用；按策略退回 `Ontology-FactQuery` |
| 语义检索 | 远程图/服务检索 | 进程内关键词和索引匹配，结果可解释但不等同完整图检索 |
| 事实查询 | Doris 网关 | SQLite 或客户 Doris；SQLite 数据质量自行负责 |
| 指标口径与事实库一致性 | 依赖平台治理 | 交付方必须自行对齐 Excel 指标与 SQLite 表字段 |
| 热更新 | 依平台 | 修改文件后需重启或重新选择数据源 |
| 多实例/横向扩容 | 可另行设计 | 当前单进程，不建议 `--workers N` |
| 驾驶舱 AP 快照 | 另一条链路 | 本文不覆盖；不要用本地本体替代驾驶舱发布快照 |

另外，本地模式不会自动回退：远程模式启动失败时应报告依赖错误；如果客户无法部署远程本体，必须按本文重新配置并重启，而不是等待程序自行切换。

## 12. 交付检查表

- [ ] 客户确认本体 Excel 已脱敏，必需工作表齐全，关键指标和业务对象可检索。
- [ ] 客户事实数据已生成 SQLite，或客户 Doris 网关已开通只读访问。
- [ ] `.env` 已设置 `ONTOLOGY_BACKEND=local`，模型网关和密钥已按环境注入。
- [ ] 启动命令显式包含 `--ontology` 和 `--db`，日志显示的是本地 xlsx/db。
- [ ] `GET /healthz` 返回 200，`GET /api/sources` 的 active 项正确，`doris.active=false`（使用 SQLite 时）。
- [ ] 已执行至少一条只读事实 SQL，结果与会话中的图表/表格一致。
- [ ] 已记录本体文件、事实库文件的大小和 SHA-256，并保留一份可回滚副本。
- [ ] 会话、上传、图表、日志目录已独立持久化，未随版本替换被覆盖。
- [ ] 已确认没有使用 `--workers N`，并在客户现场完成并发和响应时间观察。

## 13. 相关代码与文档

- 启动参数与本地模式判定：`bi_agent/web/__main__.py`
- 启动期加载和工具注册：`bi_agent/web/app.py` 的 `configure()`
- Excel 解析：`bi_agent/ontology/store.py`
- SQLite/Doris 只读查询：`bi_agent/tools/sql_tools.py`
- 示例 SQLite 构建脚本：`scripts/data/build_hyperfusion_db.py`
- 数据源与本体消费细节：`docs/analysis-agent-data-source-and-ontology-consumption.md`
- 生产部署与端口：`DEPLOYMENT.md`
