# 实现提示词：本体 MAL 契约迁移（第八批）

> 把下面整段交给实现人员（人或 Agent）。本批只做**客户端与服务端的契约对齐**，
> 不改分析策略、Prompt、评测集与任何业务行为。

---

## 0. 你的任务

本体服务已把整族接口收敛为 `QueryRequest` + `QueryResponse(TABLE|GRAPH|TREE)`
（`/api/v1/analysis/...`），旧路径（`/agent/ontology/*`、`/system/manager/ontology-repository`、
`/agent/doris/query`）**仍然在线**。

当前客户端只说旧方言，于是换路径就会"静默拿到空数据"：

```
scriptQuery            data.results[].rows   →  新契约 data.result.rows
本体库目录             data.items / data.total →  新契约 data.result.rows / data.pagination.total
关联实体               data.objects            →  新契约 data.result.rows
业务数据 SQL           {"sql":...} / data.rows →  新契约 QueryRequest / data.result.rows
```

请让 `RemoteOntologyClient` 同时说两种方言，并在**传输边界**归一化成调用方已经在用的
内部结构；同时让 `_doris_query` 按配置的 URL 选择方言。**不要**改任何调用方语义。

## 1. 先读

1. `docs/specs/ontology-mal-contract-migration.md`（本批 Spec，逐节读完）
2. `tests/test_ontology_mal_contract_red.py`（红测 = 验收标准）
3. `API/本体MAL层API.md`（对外契约：§2.1 路径表、§2.2 响应形态差异）
4. 生产代码：
   - `bi_agent/ontology/remote.py`（`_request` / `ensure_object` / `find_related` /
     `graph_neighborhood` / `search_objects` / `list_objects` / `script_query` /
     `metadata_query` / `data_query` / `repository_info` / `list_repositories`）
   - `bi_agent/tools/sql_tools.py`（`_doris_query` 的 `DorisHttpConn` 分支）
   - `bi_agent/web/app.py`（`_remote_repository_catalog`）
   - `bi_agent/tools/remote_ontology_tools.py`（`_related_objects`、`_walk_rows`）
5. 配置与文档：`.env.example`、`DEPLOYMENT.md`、`API/ontology-agent-api-integration.md`、
   `API/系统接口调用与代码统计.md`

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_ontology_mal_contract_red.py -p no:randomly
```

预期 **44 failed / 26 passed**（70 个测试方法）。先读懂每条失败，再动手；
**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。

绿的那 26 条（`ErrorSemanticsTests`、`ScopeGuardTests`、`LegacyDialectRegressionTests`
的旧方言项、`DorisHttpContractTests` 的旧 URL 项、`metadata_query`/`data_query` 回归项）
是**回归护栏**：迁移把它们弄红了就是引入了新缺陷。

## 3. 实现要求

### 3.1 传输边界归一化（核心）

在 `bi_agent/ontology/remote.py` 内新增私有抽取器，并且**只有这里**知道方言：

* `_table_of(data) -> (columns, rows)`：依次识别
  `data.result.columns`/`data.result.rows`（新）、`data.results[].rows`（旧）、
  `data.rows`（旧业务数据）、`data.result.vertices`（GRAPH）。
  任一层缺失 → 空，**不得**抛异常、**不得**伪造行。
* `_columns_of(data)`：新契约取 `result.columns[].identifierCode`；否则回退首行键顺序。

然后按下表归一化（调用方必须**零改动**）：

| 方法 | 返回（归一化后） |
| --- | --- |
| `script_query` | `{"results": [{"rows": [...], "columns": [...]}]}` |
| `search_objects` / `list_objects` | `list[dict]`（行；`list_objects` 保留"只缓存更大快照"的既有不变量） |
| `graph_neighborhood` | 既有 dict 结构不变（`objects`/`relations`/`relations_available`/`relation_error`） |
| `find_related` | `{"objects": [{"typeName":..., "properties": {...}}]}` |
| `ensure_object` | `{"found": bool, "objectInfo": {"typeName":..., "properties": {...}}\|None}` |
| `list_repositories` | `{"items": [dict], "total": int}` |
| `repository_info` | 单行 dict（并做 §3.3 字段别名） |
| `metadata_query` / `data_query` | 原样透传 `data`（**不要**改路径与请求体） |

### 3.2 路径与请求体

* `script_query` → `POST /api/v1/analysis/meta/query`，
  body `{"analysisConfig": {"language","sql","paramsList"?}, "commonConfig": {}}`
  （旧字段名 `script` 改为 `sql`）。
* `find_related` → `GET /api/v1/analysis/context/expand-ontology-context?type&code&depth`，
  `depth` 仍夹在 1..5。
* `ensure_object` → `POST /api/v1/analysis/context/resolve-ontology-object`，
  body `{"analysisConfig": {"name","candidateTypes"}, "commonConfig": {}}`；
  未命中 = 空 `columns`/`rows`，归一化成 `found=false`。
* `list_repositories` → `GET /api/v1/analysis/context/ontology-repository?page&size`，
  **不发送** `X-Ontology-Repository-Id`（既有行为，保留）。
* `repository_info` → `GET /api/v1/analysis/context/ontology-repository/{id}`。
* `metadata_query` / `data_query` 保持现状（`/api/v1/analysis/meta/query`、
  `/api/v1/analysis/data/query`），**只加回归锁定，不改一行请求体**。
* 请求头（`X-Ontology-Repository-Id` / `X-App-Id` / `Authorization`）不变。

### 3.3 本体库字段别名

归一化后的仓库 dict 同时携带两套名字：`dorisDatabase ⇄ currentDatabase`、
`metaDatabase ⇄ arcadedbMetaDatabase`、`knowledgeDatabase ⇄ arcadedbKnowledgeDatabase`。
`_remote_repository_catalog` 的条目必须保留 `metaDatabase` / `knowledgeDatabase`
（缺省空串），`namespace` 仍取 `namespaceCode`，`databaseValue` 仍为
`__metaerp_repository__:<id>` 形式。**不得**写死业务库名。

### 3.4 业务数据 SQL 的双方言

`_doris_query(conn: DorisHttpConn, sql)` 按 `conn.api_url` 选择方言：

| URL 路径 | 请求体 | 读取 |
| --- | --- | --- |
| 以 `/agent/doris/query` 结尾 | `{"sql": sql}` | `data.rows`（+ `data.columns`） |
| 其它（含 `/api/v1/analysis/data/query`） | `{"analysisConfig": {"sql": sql}, "commonConfig": {}}` | `data.result.rows`，列名取 `result.columns[].identifierCode` 顺序，缺失时回退首行键顺序 |

两种情况都**容忍**另一种响应形态（灰度期同 URL 可能返回任一形态）。
上游 `success=false` / 非 200 / 连接失败仍抛 `DorisApiError`，不得吞掉。
`DORIS_API_URL` 的取值由运维决定，本批**不改默认值**。

### 3.5 关联实体宽容化

`_related_objects(data)` 除 `objects` / `relatedObjects` 外，必须能从
`data["result"]["rows"]` 取到关联对象（一行一个，`typeName` 在行根级）。

### 3.6 错误语义（不得改坏）

`success is False` 或 `code not in (200,"200")` → `OntologyApiError(msg)`；
`data=null`、未知 `resultType`、空结果集 → 空结果，不抛异常、不伪造行；
HTTP 非 2xx / 非 JSON → `OntologyApiError`。

### 3.7 文档与配置

* `.env.example` 与 `DEPLOYMENT.md`：`DORIS_API_URL` 同时给出旧
  （`.../agent/doris/query`）与新（`.../api/v1/analysis/data/query`）两种取值示例，
  并说明客户端两种都支持。
* `API/ontology-agent-api-integration.md`：更新到新契约（请求体 + `result.rows`）。
* `API/系统接口调用与代码统计.md`：接口清单补上 `/api/v1/analysis/*` 家族，
  并注明 X360 两个接口本批**未接入**。
* 当周 `changelog/changelog_9_14_18.md` 增补一条（写最终行为，不写中间尝试）。

### 3.8 不得触碰

* `bi_agent/tools/analysis_policy.py`、`prompt`、工具白名单、SQL guard；
* `dataset/evals/analytics/**`（用例数 570、P0 147、`known_gap 0/0` 全部不变）；
* X360 流程定义/责任人/转督办映射（另开批次）；
* 智能建模、智能消歧整合任务接口（本仓库不调用）。

## 4. 完成后必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_ontology_mal_contract_red.py -p no:randomly
.venv/bin/python -m pytest -q tests
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
git diff --check
```

要求：

* 红测 70 项全绿（含 `MutationGuardTests` 全部被杀死的变异）；
* 五个套件全绿且用例数不变（smoke 140 / adversarial 62 / recorded-provider 122 /
  regression 570 / all 570，P0 147/147，`known_gap 0`）；
* 全量 `pytest -q tests` 全绿；25 条 opt-in skip 数量与原因不变（skip 不得写成 pass）；
* 迁移后**不得**出现"新路径失败却静默返回空结果"的路径：要么按 §3.6 抛错，
  要么返回明确空结果。

## 5. 报告要求

必须包含：

1. 修改文件清单（含四个生产文件的逐处说明）；
2. 归一化抽取器的位置与识别顺序；
3. 新旧方言等价性的证据（哪些用例断言"逐字节相等"）；
4. `_doris_query` 两种 URL 的请求体/解析对照；
5. 仓库字段别名与配对数据源的处理；
6. 红测从 44 failed / 26 passed 到全绿的对照，逐条说明失败原因如何被消除；
7. 六个 mutation 变异各自被哪条用例杀死；
8. 误伤验证：五个套件的用例数与结果、`build_cognitive_policy_decision` 的三条路由断言；
9. 未改动 `dataset/evals/analytics/**` 的证据（用例数/known_gap 不变）；
10. 剩余风险（真实服务未联调、X360 未接入、`DORIS_API_URL` 仍指向旧路径）；
11. 明确说明未部署、未重启服务、未改版本号、未读取真实凭据。

## 6. 禁止事项

* 禁止只加新路径、不管旧方言（旧路径仍在线）；
* 禁止只加旧方言兼容、不切新路径；
* 禁止用 `try/except: return []` 掩盖上游错误（错误必须可见）；
* 禁止把语义字段（单位、币种、指标名、维度名、filter、数值）纳入归一化；
* 禁止改动 `metadata_query` / `data_query` 的请求体；
* 禁止改动分析策略、路由、评测集、known gap 与任何业务行为；
* 禁止顺带接入 X360 或写死业务库名/环境地址；
* 禁止修改红测迁就实现；
* 禁止使用真实凭据或调用真实服务做"联调式"验证；
* 禁止 commit/push/tag/Release/部署（除非用户在当前任务中另行明确要求）。
