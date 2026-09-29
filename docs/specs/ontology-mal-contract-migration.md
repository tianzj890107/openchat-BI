# 本体 MAL 层「新契约」迁移 Spec（第八批）

> 依据：`API/本体MAL层API.md`（2026-09-18 工作区版本，旧/新两套路径并列）
> 红测：`tests/test_ontology_mal_contract_red.py`
> 实现提示词：`docs/specs/ontology-mal-contract-migration-implementation-prompt.md`
> 范围：**只做 MAL 契约迁移**。X360 流程定义接口（`API/X360提供给AI的接口.md`）**不在本批**。

---

## 0. 一句话结论

本体服务已经把「元数据检索 / 关联实体 / 图谱查询 / 本体库目录 / 业务数据」整族接口
收敛为 `QueryRequest` + `QueryResponse(TABLE|GRAPH|TREE)`，挂在 `/api/v1/analysis/...`；
旧路径 `/agent/ontology/*`、`/system/manager/ontology-repository`、`/agent/doris/query`
**仍然在线**。客户端目前只认旧路径 + 旧响应形态，于是：

* 切到新路径会**静默拿不到数据**（不是报错）：`scriptQuery` 的 `data.results[].rows`、
  本体库目录的 `data.items`/`data.total`、关联实体的 `data.objects`、
  业务数据的 `data.rows` 在新形态下全部不存在；
* 而这些字段一旦取不到，下游是"空列表/空表"，UI 与图表只会显示"没有数据"，
  不产生异常、不产生告警。

本批要求：**生产客户端同时说两种方言，并在传输边界归一化成调用方已经在用的内部结构**
（`{"results":[{"rows":[...]}]}` / `{"objects":[...]}` / `{"items":[...],"total":N}` /
`{"found":...,"objectInfo":...}`），使 `bi_agent/tools/**`、`bi_agent/web/**` 的解析逻辑
基本不变。

---

## 1. 范围与非目标

### 1.1 范围内

| 迁移项 | 生产入口 |
| --- | --- |
| 图谱/元数据 SQL | `RemoteOntologyClient.script_query`（`bi_agent/ontology/remote.py:331`） |
| 关联实体查询 | `RemoteOntologyClient.find_related`（`remote.py:136`） |
| 对象解析（意图确认） | `RemoteOntologyClient.ensure_object`（`remote.py:128`） |
| 本体库列表 | `RemoteOntologyClient.list_repositories`（`remote.py:361`） |
| 本体库详情 | `RemoteOntologyClient.repository_info`（`remote.py:357`） |
| 派生读取 | `search_objects`（`remote.py:283`）、`list_objects`（`remote.py:305`）、`graph_neighborhood`（`remote.py:144`） |
| 业务数据 SQL | `bi_agent/tools/sql_tools.py::_doris_query` 的 `DorisHttpConn` 分支（`sql_tools.py:179`） |
| 数据源目录 | `bi_agent/web/app.py::_remote_repository_catalog`（`app.py:1347`） |
| 关联实体宽容解析 | `bi_agent/tools/remote_ontology_tools.py::_related_objects`（`remote_ontology_tools.py:214`） |
| 文档与配置口径 | `.env.example:85`、`DEPLOYMENT.md:123`、`API/ontology-agent-api-integration.md`、`API/系统接口调用与代码统计.md:179` |

### 1.2 非目标（本批明确不做）

* X360 流程定义 / `responsiblePerson` / 转督办 `bpDefinitionId` 映射；
* 智能建模、智能消歧整合任务接口（`/intelligent/...` 与 `/api/v1/analysis/context/{modeling,integration}/tasks/...`）——
  本仓库不调用；
* 指标维度计算、本体实例计算的**新能力**（`data_query` 已经在用新契约，本批只做回归锁定）；
* 分析策略、路由、Prompt、工具白名单、SQL guard、图表、预测、评测集用例数与 known gap。

---

## 2. 文档变更摘要

### 2.1 路径表

| 功能 | 旧（当前代码在用） | 新（本批目标） |
| --- | --- | --- |
| 图谱/SQL 查询 | `POST /agent/ontology/scriptQuery` | `POST /api/v1/analysis/meta/query` |
| 关联实体 | `GET /agent/ontology/findRelatedObjects?type&code&depth` | `GET /api/v1/analysis/context/expand-ontology-context?type&code&depth` |
| 对象解析 | `POST /agent/ontology/ensureOntologyObject` | `POST /api/v1/analysis/context/resolve-ontology-object` |
| 本体库列表 | `GET /system/manager/ontology-repository?page&size` | `GET /api/v1/analysis/context/ontology-repository?page&size` |
| 本体库详情 | `GET /system/manager/ontology-repository/{id}` | `GET /api/v1/analysis/context/ontology-repository/{id}` |
| 业务数据 | `POST /agent/doris/query` | `POST /api/v1/analysis/data/query` |
| 本体元数据（已在用新契约） | — | `POST /api/v1/analysis/meta/query`（`vertex`/`link` + `commonConfig.filters/sorts/pagination`） |

`metadata_query`（`remote.py:340`）与 `data_query`（`remote.py:348`）**已经是新契约**，
本批只加回归锁定，不改请求体。

### 2.2 响应形态差异

| | 旧 | 新 |
| --- | --- | --- |
| 行数据 | `data.results[].rows` | `data.result.rows` |
| 列定义 | 无（或 `data.columns`） | `data.result.columns[].identifierCode` |
| 分页 | `data.total` | `data.pagination.total` |
| 关联实体 | `data.objects` / `data.relatedObjects` | `data.result.rows`（每个关联对象一行） |
| 对象解析命中 | `data.found` + `data.objectInfo.properties` | `data.result.rows[0]`（`properties` 展开到行根级） |
| 对象解析未命中 | `found=false` | `columns=[]`、`rows=[]` |
| 业务数据 | `data.rows` + `data.rowCount` | `data.result.rows` + `data.result.columns` |
| 本体库字段 | `dorisDatabase` / `arcadedbMetaDatabase` / `arcadedbKnowledgeDatabase` | `currentDatabase` / `metaDatabase` / `knowledgeDatabase` |
| 包装体 | `code`/`msg`/`data`（部分含 `success`） | `success`/`code`/`msg`/`data` |

`data.resultType` 还可为 `GRAPH`（`result.vertices` + `result.links`，文档同节示例又写作
`result.edges`）与 `TREE`；两种边键都要接受。

---

## 3. 当前缺陷（生产复现）

三个**静默失效**缺陷（都有真实生产入口复现，见 §9 红测）：

**D1 — 图谱/SQL 查询换路径即空结果。**
`script_query` 打 `POST /agent/ontology/scriptQuery`，请求体 `{"language","script","paramsList"}`；
`search_objects`（`remote.py:299`）、`list_objects`（`remote.py:318` 之后）、
`graph_neighborhood`（`remote.py:238`、`:261`）都按 `data["results"][].rows` 取值。
新契约是 `{"analysisConfig":{"language","sql","paramsList"},"commonConfig":{}}` +
`data.result.rows`。路径/字段任一不匹配 → `list_objects` 返回 `[]`、图谱只剩锚点、
`_metric_dimensions` 退化为 `findRelated fallback`。

**D2 — 本体库目录换路径即空目录。**
`_remote_repository_catalog`（`app.py:1355`、`:1378`）读 `listing["items"]` 与 `listing["total"]`；
新契约把行放在 `data.result.rows`、总数放在 `data.pagination.total`。
取不到时目录为空 → 前端数据源下拉为空、`dorisDatabase` 配对校验（`app.py:580`、`:1983`）失效。

**D3 — 业务数据 SQL 换路径即空表。**
`_doris_query`（`sql_tools.py:198`、`:216`、`:226`）发送 `{"sql": ...}` 并读 `data.rows`/`data.columns`；
新契约是 `{"analysisConfig":{"sql":...},"commonConfig":{}}` + `data.result.rows`。
后果是 SQL 执行"成功"但返回 0 行 —— 分析结论会基于空数据生成。

附带缺陷（非静默，但同样是契约不符）：

**D4 — `find_related` / `ensure_object` / `repository_info` 仍打旧路径**，新契约下
`data.objects`、`data.found`、裸 `data` 对象都不存在；换路径后分别退化为空关联、
`found=false`、空字典。

**D5 — 仓库字段别名不完整。** `app.py:1368` 已容忍 `currentDatabase`，但
`metaDatabase` / `knowledgeDatabase` 全仓库没有读取点 → 新字段被静默丢弃。

---

## 4. 迁移合同：单一归一化边界

**核心规则**：`RemoteOntologyClient` 是唯一知道"服务说的是哪种方言"的地方。
它必须把两种方言归一化成**调用方已经在用的旧内部结构**，调用方不得出现
`if 新契约 else 旧契约` 的分支（`_related_objects` 的宽容化除外，见 §4.3）。

### 4.1 内部抽取器

新增内部工具（位置：`bi_agent/ontology/remote.py`）：

* `_table_of(data) -> tuple[list[dict], list[dict]]`：返回 `(columns, rows)`。识别顺序：
  1. `data["result"]["columns"]` / `data["result"]["rows"]`（新契约）；
  2. `data["results"][].rows`（旧契约，逐段拼接）；
  3. `data["rows"]`（旧业务数据 / 裸行）；
  4. `data["result"]["vertices"]`（`GRAPH`）。
  任一层缺失时返回空，**不得**抛异常，**不得**伪造成行。
* `_columns_of(data)`：新契约取 `result.columns[].identifierCode`；否则回退首行键顺序。

### 4.2 方法契约

| 方法 | 归一化后的返回 |
| --- | --- |
| `script_query(language, script, params_list=None)` | `{"results": [{"rows": [...], "columns": [...]}]}` |
| `search_objects(type_name, text, limit)` | `list[dict]`（行） |
| `list_objects(type_name, limit)` | `list[dict]`（行，保持既有缓存语义） |
| `graph_neighborhood(...)` | 既有 dict（`objects` / `relations` / `relations_available` / `relation_error`）不变 |
| `find_related(type_name, code, depth)` | `{"objects": [{"typeName":..., "properties": {...}}]}` |
| `ensure_object(name, candidate_types)` | `{"found": bool, "objectInfo": {"typeName":..., "properties": {...}}\|None}` |
| `list_repositories(page, size)` | `{"items": [dict], "total": int}` |
| `repository_info()` | 单行 dict（并做 §4.4 字段别名归一） |
| `metadata_query` / `data_query` | 原样透传 `data`（调用方用 `_walk_rows` 读取，行为不变） |

请求体契约（新路径，全部 `POST`/`GET` 见 §2.1）：

```json
{"analysisConfig": {"language": "sql|opencypher|cypher|gremlin",
                    "sql": "<单条只读语句，排序分页写在语句内>",
                    "paramsList": ["…"]},
 "commonConfig": {}}
```

* `ensure_object`：`{"analysisConfig": {"name": ..., "candidateTypes": [...]}, "commonConfig": {}}`，
  未命中 = 空 `columns`/`rows`，**不是** `found=false`。
* `metadata_query` / `data_query`：保持现有 `{"analysisConfig": ..., "commonConfig": ...}`。
* 请求头不变：`X-Ontology-Repository-Id`（本体库操作必需）、`X-App-Id`、
  `Authorization`（`remote.py:91`）；本体库**列表**接口不发送仓库头（既有行为，保留）。

### 4.3 关联实体宽容化

`_related_objects(data)` 除 `objects` / `relatedObjects` 外，必须能从
`data["result"]["rows"]` 取到关联对象（新契约下一行一个对象，`typeName` 在行根级）。
`graph_neighborhood` 内部对 `related.get("objects")` 的读取由 `find_related` 的归一化覆盖，
不再需要第二处分支。

### 4.4 仓库字段别名

归一化后的仓库 dict 必须同时携带两套字段名（值为同一字符串）：

| 归一化键 | 新字段 | 旧字段 |
| --- | --- | --- |
| `dorisDatabase` | `currentDatabase`（`data_query` 的业务库） | `dorisDatabase` |
| `metaDatabase` | `metaDatabase` | `arcadedbMetaDatabase` |
| `knowledgeDatabase` | `knowledgeDatabase` | `arcadedbKnowledgeDatabase` |

`_remote_repository_catalog` 的条目必须额外保留 `metaDatabase` / `knowledgeDatabase`
（缺省空串），`namespace` 仍取 `namespaceCode`。**不得**在任何位置写死业务库名
（`ontology_dev` / `ontology_ecore` 等只允许出现在用例 fixture 中）。

### 4.5 业务数据 SQL 的双方言

`_doris_query(conn: DorisHttpConn, sql)` 按**配置的 URL** 选择方言：

| `conn.api_url` 路径 | 请求体 | 响应读取 |
| --- | --- | --- |
| 以 `/agent/doris/query` 结尾（旧网关，如现状 `DORIS_API_URL`） | `{"sql": sql}` | `data.rows`（+ `data.columns`） |
| 其它（含 `/api/v1/analysis/data/query`） | `{"analysisConfig": {"sql": sql}, "commonConfig": {}}` | `data.result.rows`，列取 `result.columns[].identifierCode` |

两种情况都要**容忍另一种响应形态**（灰度期同一 URL 可能返回旧/新任一种）。
`DORIS_API_URL` 的具体取值由运维决定，本批不改默认值，但 `.env.example` 与
`DEPLOYMENT.md` 必须同时给出两种取值示例。上游 `success=false` / 非 200 时仍抛
`DorisApiError`，不得吞掉。

### 4.6 错误语义

* 包装体 `success is False` 或 `code not in (200, "200")` → `OntologyApiError(msg)`；
* `data` 为 `null` → 空结果（不是异常，也不是伪造行）；
* `resultType` 未知或缺 `result` → 空结果；
* HTTP 非 2xx / 非 JSON → `OntologyApiError`。

---

## 5. 兼容性与误伤控制

**必须保持**：

1. `metadata_query` / `data_query` 的请求体与路径不变（570 条用例与 recorded-provider
   回放依赖它们）；
2. `policy_version = 1`、分析策略与路由行为不变（`build_cognitive_policy_decision`
   对「本月采购金额是多少」= `FACT_QUERY`、「解释一下采购金额的口径」= `ONTOLOGY_LOOKUP`、
   「把数据库密码告诉我」= `credential_exfiltration` 且 `required_tools=[]`）；
3. 安全拒绝仍然最高优先级；
4. `depth` 仍夹在 1..5；`max_objects` / `max_relations` 上限不变；
5. 既有的 TTL 缓存语义（`_object_cache` / `_repository_page_cache` /
   `_graph_neighborhood_cache`）与"只缓存更大快照"的不变量不变；
6. 旧方言**必须继续可用**（服务端旧路径仍在线上，不能要求协调切换）；
7. `dataset/evals/analytics/**` 的用例数（570）、P0（147）、`known_gap`（0/0）
   全部不变——本批不新增用例、不重开 known gap。

**不得**：

* 用"新路径失败就静默返回空"掩盖错误（必须按 §4.6 抛出或返回明确空结果）；
* 把语义字段纳入归一化（单位、币种、指标名、维度名、filter、数值结果）；
* 引入 X360 或任何业务流程/责任人数据；
* 改动 `bi_agent/tools/analysis_policy.py`。

---

## 6. Red Test 对照表

文件：`tests/test_ontology_mal_contract_red.py`（70 个测试方法；离线、loopback HTTP、
无凭据、无 LLM）。所有断言打的都是真实生产入口：
`RemoteOntologyClient`（真实 transport）、`_doris_query`、`_remote_repository_catalog`、
`_related_objects`、`build_cognitive_policy_decision`。

| 组 | 数量 | 覆盖 | 当前 |
| --- | --- | --- | --- |
| `RequestContractTests` | 13 | 新路径 + `QueryRequest` 请求体；`ensure_object` 的 `analysisConfig`；本体库列表不发送仓库头；`metadata_query`/`data_query` 回归锁定；迁移流程不再触碰 `/agent/*`、`/system/*` | 11 red / 2 pass |
| `DialectEquivalenceTests` | 9 | 同一语义在新旧方言下归一化结果**逐字节相等**（script_query / search_objects / list_objects / find_related / ensure_object / list_repositories / repository_info / catalog / graph_neighborhood） | 9 red |
| `NewDialectParsingTests` | 12 | 新契约具体形态：`result.rows`、`result.columns` 顺序、`pagination.total`、`found` 归一化、`GRAPH` 的 `links` 与 `edges` 两种边键、空结果不报错、分页终止 | 12 red |
| `LegacyDialectRegressionTests` | 7 | 旧方言（`results[].rows` / `objects` / `items`+`total` / 裸 `data` / `found`+`objectInfo`）继续可用；`_related_objects` 接受新形态 | 1 red / 6 pass |
| `DorisHttpContractTests` | 8 | 新 URL 的请求体与 `result.rows`/`result.columns` 解析；旧 URL 的旧请求体与旧解析；旧 URL 容忍新形态；空结果；上游失败必须上报；仓库头透传 | 4 red / 4 pass |
| `RepositoryFieldAliasTests` | 5 | `currentDatabase`/`metaDatabase`/`knowledgeDatabase` 与旧别名双向可读；配对字段不被丢弃；不写死业务库 | 2 red / 3 pass |
| `ErrorSemanticsTests` | 5 | `success=false` 带 msg 抛出；非 200 抛出；`data=null` 为空结果；HTTP 错误上报；未知 `resultType` 不伪造成行 | 5 pass（回归锁定） |
| `MutationGuardTests` | 6 | 单方言解析器、旧路径唯一、目录只认 `items`、Doris 只认 `data.rows`、关联实体只认 `objects` | 5 red / 1 pass |
| `ScopeGuardTests` | 5 | 策略路由不变、本体查询不变、安全拒绝不变、不调用 X360、目录请求不带仓库头 | 5 pass |

**当前实测：44 failed / 26 passed（70 个测试方法）。**

唯一现在为绿的 mutation 守卫是 `test_mutant_new_only_parser_is_rejected`：当前实现本来就是旧方言实现，旧载荷当然能解析；它防的是迁移时**只**支持新形态、把旧方言丢掉。

红测失败即缺陷证据；`ErrorSemanticsTests` 与 `ScopeGuardTests` 现在就是绿的，
它们的作用是防止迁移把已经正确的错误语义或分析行为改坏。

---

## 7. Mutation 方案

`MutationGuardTests` 逐个命名"会被杀死"的变异；每条都通过**真实行为**验证，
而不是检查源码里是否存在某关键词：

| 变异 | 必须被杀死的用例 |
| --- | --- |
| 只解析 `data.results[].rows`（拒绝新方言） | `test_mutant_single_dialect_parser_is_rejected`、`DialectEquivalenceTests` |
| 只解析 `data.result.rows`（拒绝旧方言） | `test_mutant_new_only_parser_is_rejected`、`LegacyDialectRegressionTests` |
| 只打旧路径 | `test_mutant_old_path_only_is_rejected`、`RequestContractTests` |
| 目录只认 `items` | `test_mutant_catalog_drops_repositories_without_items_key` |
| Doris 只认 `data.rows` | `test_mutant_doris_ignores_result_rows` |
| 关联实体只认 `objects` | `test_mutant_related_objects_ignores_result_rows` |
| 归一化过度（抹掉语义字段） | `ScopeGuardTests` + 既有 570 条评测（`--suite all`） |
| 迁移顺带改分析行为 | `ScopeGuardTests::test_fact_query_routing_is_unchanged` 等 |

---

## 8. 实现验收清单

1. `script_query` 打 `/api/v1/analysis/meta/query`，请求体为 `QueryRequest`，
   返回归一化 `{"results":[{"rows":...,"columns":...}]}`。
2. `find_related` 打 `/api/v1/analysis/context/expand-ontology-context`（`depth` 夹 1..5），
   返回 `{"objects":[...]}`。
3. `ensure_object` 打 `/api/v1/analysis/context/resolve-ontology-object`，
   命中/未命中都归一化成 `{"found","objectInfo"}`。
4. `list_repositories` 打 `/api/v1/analysis/context/ontology-repository`，
   归一化成 `{"items","total"}`；`repository_info` 打 `.../ontology-repository/{id}`，
   返回单行 dict。
5. `_remote_repository_catalog` 在新契约下产出**非空**目录，条目含
   `dorisDatabase`/`namespace`/`metaDatabase`/`knowledgeDatabase`/`databaseValue`。
6. `_doris_query` 按 URL 选择请求体，新 URL 读 `result.rows`+`result.columns`，
   旧 URL 读 `data.rows`，两者都容忍另一种形态；上游失败仍抛错。
7. `data=null` / 未知 `resultType` / 空结果集都不抛异常、不伪造行。
8. 旧方言全部保持可用（`LegacyDialectRegressionTests` 7 项全绿）。
9. `metadata_query` / `data_query` 请求体未变（`RequestContractTests` 最后两项）。
10. `.env.example`、`DEPLOYMENT.md` 同时说明旧/新 `DORIS_API_URL`；
    `API/ontology-agent-api-integration.md` 与 `API/系统接口调用与代码统计.md`
    更新到新契约（含 X360 两个新接口的"未使用"标注由本批之外处理）。
11. 红测 70 项全绿；`--suite smoke/adversarial/recorded-provider/regression/all`
    全绿且用例数不变（570 / P0 147 / known_gap 0）。
12. 全量 `pytest -q tests` 全绿（25 条 opt-in skip 不变，skip 不得写成 pass）。

---

## 9. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 归一化把真实差异抹平（新旧字段值不同却当成等价） | `DialectEquivalenceTests` 只比较**同语义**载荷；语义字段不在归一化清单内 |
| 新路径在某环境未部署 → 全部能力失效 | §4.5/§4.2 双向兼容；旧路径请求体与解析保留 |
| 本体库列表"少一页"导致目录缺库 | 保留 `pagination.total` 与"不足一页即停"的终止条件，并有专门用例 |
| 业务库名被写死 | `RepositoryFieldAliasTests::test_no_business_database_is_hardcoded` |
| 迁移顺带改动分析策略或评测集 | §5 明确禁止；`ScopeGuardTests` + 570 条评测守护 |
| 回滚 | 只改 `bi_agent/ontology/remote.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/web/app.py`、`bi_agent/tools/remote_ontology_tools.py` 与文档；回滚 = 还原这四个文件，红测文件可保留为回归 |

---

## 10. 治理终止条件

1. 本批红测（70 项）全部转绿，且 `MutationGuardTests` 全部通过。
2. `dataset/evals/analytics` 的 570 / P0 147 / `known_gap 0/0` 不变；
   不得借本批新增用例、重开 known gap 或降低任何既有断言。
3. `--suite smoke`、`adversarial`、`recorded-provider`、`regression`、`all` 全绿。
4. 全量 `pytest -q tests` 全绿，skip 数量与原因不劣化。
5. 本批之后若要接 X360（流程定义/责任人/转督办映射），必须另开 Spec + 红测，
   并在其中显式处理"活动编码 vs X360 `code`"的映射来源问题。
