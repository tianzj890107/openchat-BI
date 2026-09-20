# 智能分析 Agent：数据库模版与本体内容消费路径

> 现状说明文档（as-is）。基线：2026-09-20，仓库工作区当前代码
> （含第七批「本体 MAL 层契约迁移」改动，尚未提交）。本文只描述**已经实现的真实行为**，
> 所有结论都给出代码位置；不含任何真实凭据、密钥或内部绝对路径。

## 0. 术语澄清：这里说的「数据库模版」指什么

仓库里**不存在**一份独立的「数据库建表 DDL 模版」文件。结合代码与产品行为，「数据库模版」
在三层含义上都成立，本文全部覆盖：

| 理解 | 本文对应章节 | 结论 |
|---|---|---|
| ① 智能分析 Agent 当前连的**哪一个库 / 什么 schema** | §2 | 不是固定写死的某个库，而是「本体库 → 其声明的 Doris 库」原子配对 |
| ② 库里的表**怎么被模板化引用**（库前缀、只读约束、结构读取） | §3 | 表名必须 `库.表` 全限定；只读白名单；结构靠 `ListTables` / `DescribeTable` |
| ③ 本体元数据里表/列的**物理映射模板**（TableNode / Column 与指标口径） | §4 | 由本体服务侧持有，Agent 只通过 MAL 接口按需读取，本地不留副本 |

## 1. 结论速览（TL;DR）

1. **数据源是"原子配对"**：一个本体库（repository）在服务端成对声明它的 Doris 业务库
   （`dorisDatabase`/`currentDatabase`）、ArcadeDB 元数据库（`metaDatabase`）、知识库
   （`knowledgeDatabase`）以及 `namespaceCode`。前端只暴露「本体库」「数据库」两个下拉，
   但改任意一侧都会同时改另一侧（`bi_agent/web/app.py:1916` `_put_sources_endpoint_impl`）。
2. **Agent 内不存本体数据**：生产模式下 `STATE.ontology_store = OntologyStore()`（空表，
   仅满足旧接口类型），所有本体内容 100% 走 HTTP（`bi_agent/web/app.py:554`）。
3. **本体内容消费分五层**：源选择 → 策略路由（工具暴露）→ 工具 → HTTP 客户端（新旧契约双栈）
   → Prompt/SOP（六步 SOP + L1–L5 + 图库检索加餐）。
4. **事实取数有两条路，且有优先级**：本体指标语义查询 `Ontology-MetricQuery`
   （`POST /api/v1/analysis/data/query`）优先；手写只读 SQL `Ontology-FactQuery`
   （Doris 查询网关）作为兜底（`bi_agent/tools/analysis_policy.py:899`）。
5. **本体只读**：语义检索/元数据查询/OpenCypher 遍历全部是只读调用；SQL 侧只放行
   `select / with / pragma / explain`，其余关键字一律拒绝（`bi_agent/tools/sql_tools.py:289`）。

## 2. 数据源（数据库模版）当前构成

### 2.1 拓扑

```
浏览器（数据源设置 / 会话）
   │  GET/PUT /api/sources  ←→  bi_agent/web/app.py:1721 / :1869
   ▼
智能分析 Agent 进程（FastAPI + WebSession）
   ├── 本体服务（MAL 网关）    ONTOLOGY_BASE_URL   → /api/v1/analysis/**（旧 /agent/**、/system/manager/** 兼容）
   ├── Doris 查询网关          DORIS_API_URL       → /api/v1/analysis/data/query（旧 /agent/doris/query 兼容）
   └── 本地回退（仅非生产）     dataset/databases/*.db、dataset/spreadsheets/*.xlsx、dataset/graphs/*.graphml
```

### 2.2 本体库目录返回的配对字段

目录接口（新 `GET /api/v1/analysis/context/ontology-repository`，旧
`GET /system/manager/ontology-repository`）返回的每个本体库都会被归一化成结构化配对：

| 目录字段（新/旧） | 归一化字段 | Agent 用途 |
|---|---|---|
| `dorisDatabase` / `currentDatabase` | `dorisDatabase` | 绑定 Doris 业务库（写 SQL 的库前缀、`information_schema` 过滤条件） |
| `metaDatabase` / `arcadedbMetaDatabase` | `metaDatabase` | 本体元数据所在图库库名（服务端使用） |
| `knowledgeDatabase` / `arcadedbKnowledgeDatabase` | `knowledgeDatabase` | 本体知识库库名（服务端使用） |
| `namespaceCode` / `namespace` | `namespace` | 注入会话上下文头与 `RemoteOntologyClient.namespace` |
| `id` / `name` / `description` | 同名字段 | 下拉项与展示 |

归一化位置：`bi_agent/web/app.py:1348` `_remote_repository_catalog()`、
`bi_agent/ontology/remote.py:81` `_repository_fields()`（同时兼容新旧字段名）。

选中的配对会生成两个内部值：本体侧 `__metaerp_repository__:<id>`、
数据库侧 `__doris_repository__:<id>`；另有纯 Doris 哨兵值 `__doris_api__`
（自定义 schema 时使用）与本地 SQLite 文件选项（仅非生产模式可见）
（`bi_agent/web/app.py:843`–`:849`）。

### 2.3 各环境实际取值（来源：`.env.example` 注释 + 当前 `.env` 的非密钥键）

| 项 | PDT | demo2（当前本机 `.env`） | 代码默认值 |
|---|---|---|---|
| `ONTOLOGY_BACKEND` | `production` | `production` | `production` |
| `ONTOLOGY_BASE_URL` | `http://pdt-dev.eimos.com/api/gateway2/ontology` | `http://demo2.eimos.com/api/gateway2/ontology` | 无默认（远程模式必须显式注入） |
| `ONTOLOGY_REPOSITORY_ID` | `3` | `1` | 无默认 |
| `DORIS_API_URL` | `.../ontology/agent/doris/query` | `.../ontology/agent/doris/query` | 空（缺失即启动失败） |
| `DORIS_DATABASE` | 由本体库目录的 `dorisDatabase` 决定 | `ontology_demometaerp_scm_po` | `ontology_demometaerp_scm_po`（`bi_agent/tools/sql_tools.py:42`） |
| `ONTOLOGY_NAMESPACE` | 未注入 → 取目录 `namespaceCode` | 未注入 → 取目录 `namespaceCode` | 空 |
| `RETRIEVAL_MODE` | – | `semantic` | `semantic`（另有 `graph`） |

说明：

- 远程模式下 `ONTOLOGY_BASE_URL`、`DORIS_API_URL` 缺失会在**启动阶段**直接失败，禁止跨环境复用
  （`bi_agent/web/app.py:540`–`:548`）。
- 启动时会用目录接口校验配置的 `ONTOLOGY_REPOSITORY_ID` 是否存在、是否配了 `dorisDatabase`
  与 `namespaceCode`，并把目录里的库名/命名空间写回运行态（`bi_agent/web/app.py:565`–`:590`）。
- 目录接口不可用时**不阻塞启动**，仅把错误缓存并在数据源设置页提示（30s 冷却重试）。
- 评测用例里还出现过 `doris_database = ontology_dev`（评测回放 fixture 的取值，非线上配置）。

### 2.4 本地 / 离线回退（非生产模式）

| 类型 | 位置 | 说明 |
|---|---|---|
| SQLite 业务库 | `dataset/databases/*.db` | 当前仓库内置 `HyperFusion.db`、`Kingdee.db` |
| 本体工作簿 | `dataset/spreadsheets/*.xlsx` | `OntologyStore.from_xlsx()` 载入内存（`bi_agent/ontology/store.py`） |
| 图库文件 | `dataset/graphs/*.graphml` 等 | 图库检索模式的本地回退（`GRAPH_PATTERNS`，`bi_agent/web/app.py:857`） |

路径统一由 `bi_agent/paths.py` 提供，业务代码不硬编码目录。

### 2.5 会话级隔离

每个浏览器会话持有一份数据源快照（`_SOURCE_CONTEXT_FIELDS`，
`bi_agent/web/app.py:1393`）：包括 `remote_ontology / ontology_backend / ontology_namespace /
db_path / use_doris / doris_* / retrieval_mode / graph_path` 等。切换数据源走
`_source_binding_signature()`（`bi_agent/web/app.py:1702`）比对，只有签名变化才重建会话与工具绑定，
一个浏览器换库不会改到另一个浏览器正在用的工具。

## 3. 连接与传输契约（数据库侧）

### 3.1 两种传输，共存灰度

`bi_agent/tools/sql_tools.py` 按 `api_url` 后缀自动选方言，两条路都在线：

| 方言 | 触发条件 | 请求体 | 响应读取 |
|---|---|---|---|
| 旧网关 | URL 以 `/agent/doris/query` 结尾 | `{"sql": "..."}` | `data.rows` + `data.columns` |
| 新 MAL | 其他（如 `/api/v1/analysis/data/query`） | `{"analysisConfig":{"sql":"..."},"commonConfig":{}}` | `data.result.rows` + `data.result.columns[].identifierCode` |

两套响应形态互相容错，因此灰度期同一网关返回任一形态都能解析（`bi_agent/tools/sql_tools.py:179`–`:250`）。
若配置了 `DorisConn`（MySQL 协议，`pymysql` 直连 9030），则绕过 HTTP 网关直连 Doris。

### 3.2 只读与安全约束（SQL 侧）

- 只允许单条 `select / with / pragma / explain` 语句；出现
  `insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex`
  直接拒绝（`_ALLOWED_LEAD` / `_FORBIDDEN`，`bi_agent/tools/sql_tools.py:289`；
  校验函数 `_validate_sql` 在 `:296`）。
- 结果行数上限 `MAX_RESULT_ROWS = 1000`。
- Doris 库名走 `_validate_doris_identifier()` 白名单校验（库名会被拼进 `information_schema` 查询）。
- 请求头复用本体侧身份：`X-Ontology-Repository-Id`、`X-App-Id`、`Authorization`
  （未配置时回落到同名环境变量）。

### 3.3 表怎么被"模板化"引用

| 工具 | 行为 |
|---|---|
| `ListTables` | Doris：`SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = '<当前库>'`，并在输出里明确提示"写 SQL 时表名必须带库前缀 `库.表`"（`bi_agent/tools/sql_tools.py:485`） |
| `DescribeTable` | 接受裸表名或 `schema.table`，缺省 schema = 当前激活库；查 `information_schema.columns`（`bi_agent/tools/sql_tools.py:567`） |
| `Ontology-FactQuery` | 工具描述里强制要求 Doris 模式下表名为 `database.table` 全限定；仅只读（`bi_agent/tools/sql_tools.py:386`） |

## 4. 本体内容怎么被消费

### 4.1 全链路五层

```
①源选择  /api/sources GET/PUT（原子配对、会话快照、切库即重建工具）
   ▼
②策略    build_cognitive_policy_decision()（安全拒绝 > 诊断/预测/行动 > 本体 > 事实 > 通用）
   ▼
③工具    build_source_executors() / register_all()（本体 6 + 图库 2 + 指标计算 + SQL 3 + 渲染/交互）
   ▼
④客户端  RemoteOntologyClient（新 MAL 优先，旧 agent/system 兼容）/ DorisHttpConn
   ▼
⑤提示词  bi-analyst.md 六步 SOP + L1–L5；图库模式追加 SOP；会话上下文头注入 repository/namespace/doris 库
```

### 4.2 ②策略层：谁决定"能不能查本体"

`bi_agent/tools/analysis_policy.py:862` `build_cognitive_policy_decision()` 是唯一决策点，
优先级（自上而下，命中即返回）：

| 顺序 | 分支 | mode / next_step | required_tools |
|---|---|---|---|
| 0 | 凭据/内部环境/破坏性等安全拒绝 | `general_response` | **空**（不暴露任何工具） |
| 1 | 空问题或纯泛化请求 | `clarification` | `AskUser` |
| 1b | 无对象的生成式预测 | `clarification` / 能力限制 | `AskUser` / 空 |
| 2 | 诊断 / 根因 / 行动 / 预测情景 | `diagnostic_analysis` | 指标查询优先，事实查询兜底 |
| 3 | 术语/定义/口径/物理表/关系 | `ontology_lookup` | `Ontology-SemanticQuery` |
| 4 | 事实/指标/列表/趋势 | `fact_query` | 指标查询优先，事实查询兜底 |
| 5 | 兜底 | `general_response` | 空 |

关键点：`required_tools` 只会从**当前会话真实允许的工具**里挑
（`doris_route_tools()`，`bi_agent/tools/analysis_policy.py:899`），因此
"远程模式才有 `Ontology-MetricQuery`"这一事实会自动降级为 `Ontology-FactQuery`，
策略不会声明一个不存在的工具。

### 4.3 ③工具层：Agent 实际能看到的工具与后端

注册入口 `bi_agent/tools/__init__.py:81` `register_all()` / `:48` `build_source_executors()`；
远程模式用 `remote_specs()` 覆盖 9 个本体类工具
（`bi_agent/tools/remote_ontology_tools.py:732`）。

| 工具 | 远程后端（生产） | 本地后端（离线） |
|---|---|---|
| `Ontology-SemanticQuery` | `_candidate_results` → 各类型 `search_objects` | 工作簿关键词/索引检索 |
| `Ontology-TermDisambiguate` | 类型固定为 `Term` 的远程检索 | 工作簿术语检索 |
| `MetricCalculation` | 类型固定为 `Indicator` 检索 + 维度元数据 | 工作簿指标 `to_prompt()` |
| `Ontology-RelationQuery` | `RemoteGraphRetriever.relation_bundle()` | 本地 ER 索引 |
| `Ontology-EntityDescribe` | 候选检索 + `find_related(depth=1)` | 本地对象 + 关系 |
| `ListBusinessObjects` | `list_objects()`（整类型属性快照，带缓存） | 工作簿列举 |
| `Ontology-MetricQuery` | **仅远程**：`POST /api/v1/analysis/data/query` | 不存在（策略自动退回 FactQuery） |
| `Ontology-GraphContext` / `Ontology-GraphExpand` | `RemoteGraphRetriever.context_bundle()/expand()` | 本地图库检索 |
| `Ontology-FactQuery` / `ListTables` / `DescribeTable` | Doris 查询网关（§3） | 本地 SQLite 文件 |
| `ChartGenerate` / `ChartGenerateMultiDim` / `TableGenerate` / `AskUser` | 进程内渲染 / 交互 | 同左 |

工具说明书：`docs/ChatBI_Tools.md`；默认白名单来自 `.claude/agents/bi-analyst.md:5`（14 个），
图库检索模式下追加 `Ontology-GraphContext`、`Ontology-GraphExpand`
（`bi_agent/web/app.py:3513`）。

### 4.4 ④客户端层：本体接口调用点（新旧双栈）

`bi_agent/ontology/remote.py` `RemoteOntologyClient` 是唯一传输层，新路径优先、旧路径回退
（`_dual_request`，`:204`）：

| 客户端方法 | 新契约（优先） | 旧契约（回退） | 谁在用 |
|---|---|---|---|
| `list_repositories()` `:530` | `GET /api/v1/analysis/context/ontology-repository` | `GET /system/manager/ontology-repository` | 数据源设置页目录、启动校验 |
| `repository_info()` `:516` | `GET /api/v1/analysis/context/ontology-repository/{id}` | `GET /system/manager/ontology-repository/{id}` | **当前无调用方** |
| `ensure_object()` `:239` | `POST /api/v1/analysis/context/resolve-ontology-object` | `POST /agent/ontology/ensureOntologyObject` | **当前无调用方** |
| `find_related()` `:265` | `GET /api/v1/analysis/context/expand-ontology-context` | `GET /agent/ontology/findRelatedObjects` | EntityDescribe / 图库遍历 |
| `script_query()` `:476` | `POST /api/v1/analysis/meta/query`（`analysisConfig.language/sql`） | `POST /agent/ontology/scriptQuery` | 语义检索、列举、OpenCypher 遍历 |
| `data_query()` `:507` | `POST /api/v1/analysis/data/query` | 无（旧口径走 Doris 网关） | `Ontology-MetricQuery` 指标计算 |
| `metadata_query()` `:499` | `POST /api/v1/analysis/meta/query` | 无 | 指标维度元数据 |

响应归一化在传输边界完成（`_table_of()` `:47` 兼容 `data.result.rows` / `data.result` 图结构 /
`data.results[].rows` / `data.rows`），调用方不需要区分方言。

### 4.5 ⑤提示词层：本体内容怎么进入模型上下文

- 会话上下文头（仅远程模式注入）：`repository_id` / `namespace` / `doris_database`
  （`bi_agent/web/app.py:3508`）。
- 主体是 `bi-analyst.md` 的**六步 SOP**：意图识别（含角色识别、术语消歧、L1–L5 定级）→
  本体模型匹配 → 规划 → 取数 → 根因 → 决策行动；每一步都要求用工具落地。
- 图库检索模式追加 `GRAPH_MODE_SOP`（`bi_agent/web/app.py:862`），覆盖第 2/3 步，第 5 步可
  调用「图库扩散探索」skill。
- 术语消歧/口径确认不唯一时，SOP 要求调用 `AskUser` 让用户确认，而不是默默挑一个口径。

### 4.6 图库检索（graph 模式）的真实数据来源

`RemoteGraphRetriever`（`bi_agent/ontology/remote_retriever.py`）在远程模式下：

1. `find_related()` 拿到有界邻域（顶点，去重、无向证据）；
2. 用只读 OpenCypher（`language=opencypher`）在边界内补齐**有向边与关系属性**；
3. 仓储不支持通用边查询时降级为"仅顶点"邻域（`relations_available=False`），
   并对 `TableNode` 类型的已知报错做兜底。

结果缓存 30s（`_graph_neighborhood_cache`），键含类型/编码/深度/上限。

## 5. 一次提问的完整调用链

```
用户提问
 → WebSession 取会话数据源快照（§2.5）
 → build_cognitive_policy_decision(question, allowed_tools)  得到 mode/required_tools/证据要求
 → 拒绝路径：allowed_tools 直接为空，工具循环不启动
 → 正常路径：模型按 SOP 调工具
      ├─ 本体类 → RemoteOntologyClient → MAL/旧接口 → 归一化（含 provenance）
      ├─ 指标类 → POST /api/v1/analysis/data/query（indicators/dimensions/filters/sorts/pagination）
      └─ SQL 类 → Doris 查询网关（只读校验 + 行数上限）
 → 结果经 normalize_query_result + Provenance 打标 → 进入回答/图表
```

`Ontology-MetricQuery` 的请求构造位置：`bi_agent/tools/remote_ontology_tools.py:625`
（先解析指标/维度显示名做 alias，再拼 `analysisConfig.indicators/dimensions` 与
`commonConfig.pagination/filters/sorts`；5xx 失败会短期缓存并建议回退 FactQuery）。

## 6. 缓存、并发、超时与降级

| 项 | 取值 | 位置 |
|---|---|---|
| 本体缓存 TTL | `ONTOLOGY_CACHE_TTL_SECONDS=30` | `bi_agent/ontology/remote.py:128` |
| 本体请求超时 | `ONTOLOGY_TIMEOUT_SECONDS=30`（上限 120） | `remote.py:140` |
| 本体并发信号量 | `CHATBI_ONTOLOGY_CONCURRENCY=12` | `.env.example` + `bi_agent/concurrency.py` |
| Doris 并发信号量 | `CHATBI_DORIS_CONCURRENCY=12` | 同上 |
| Doris HTTP 超时 | 60s | `bi_agent/tools/sql_tools.py:213` |
| 指标查询 5xx 降级 | 短期缓存失败并提示回退 `Ontology-FactQuery` | `remote_ontology_tools.py:723` |

## 7. 与最新接口文档的差距（信息项，非缺陷）

1. `POST /api/v1/analysis/context/resolve-ontology-object`（`ensure_object`）与
   `GET /api/v1/analysis/context/ontology-repository/{id}`（`repository_info`）**代码已实现但无调用方**，
   与 `API/系统接口调用与代码统计.md` 的结论一致。当前对象消歧走的是
   `script_query(sql LIKE)` + `expand-ontology-context` 组合。
2. 最新 MAL 文档把 `qualifiedTables` 定义为权威数据库范围；Agent 侧目前**尚未**消费该字段，
   只使用 `dorisDatabase` + `information_schema` 反射（见 `docs/specs/ontology-mal-contract-migration.md`）。
3. X360 提供的能力里，目前实际接入的是"行动 → 转督办"任务令代理
   （`TASK_ALERT_API_URL` / `TASK_ALERT_API_ENABLED`，`.env.example`），未接入 X360 其它接口。

## 8. 证据索引（代码位置）

| 主题 | 位置 |
|---|---|
| 数据源运行态与默认值 | `bi_agent/web/app.py:140`–`:160`、`bi_agent/tools/sql_tools.py:32`–`:47` |
| 启动期本体/数据库配对校验 | `bi_agent/web/app.py:540`–`:600` |
| 数据源列表 / 切换 | `bi_agent/web/app.py:1721` `get_sources_endpoint`、`:1869` `put_sources_endpoint`、`:1916` `_put_sources_endpoint_impl` |
| 本体库目录归一化 | `bi_agent/web/app.py:1348`、`bi_agent/ontology/remote.py:81` |
| 会话快照与隔离 | `bi_agent/web/app.py:1393` `_SOURCE_CONTEXT_FIELDS`、`:1702` `_source_binding_signature` |
| 路由/工具暴露 | `bi_agent/tools/analysis_policy.py:862`、`:899`（指标优先/事实兜底） |
| 工具注册与远程覆盖 | `bi_agent/tools/__init__.py:48`、`:81`；`bi_agent/tools/remote_ontology_tools.py:732` |
| SQL 只读与库限定 | `bi_agent/tools/sql_tools.py:179`、`:289`、`:485`、`:567` |
| 本体 HTTP 客户端 | `bi_agent/ontology/remote.py:204`、`:427`、`:476`、`:507`、`:530` |
| 图库检索 | `bi_agent/ontology/remote_retriever.py:132`、`:418`、`:496`、`:528` |
| Prompt / SOP | `.claude/agents/bi-analyst.md`、`bi_agent/web/app.py:862`、`:3508` |
| 本地本体回退 | `bi_agent/ontology/store.py`、`bi_agent/paths.py` |

## 9. 自查命令（不联网即可核对结构性事实）

```bash
grep -n "ONTOLOGY_BASE_URL\|DORIS_DATABASE\|RETRIEVAL_MODE" .env | grep -v TOKEN
grep -n "def build_cognitive_policy_decision" -A 40 bi_agent/tools/analysis_policy.py
grep -n "remote_specs\|register_all" bi_agent/tools/__init__.py bi_agent/tools/remote_ontology_tools.py
grep -n "def data_query\|def script_query\|def list_repositories" bi_agent/ontology/remote.py
```

---

_本文档为只读现状说明，未修改任何生产实现；不含真实凭据、环境变量密文或内部绝对路径。_
