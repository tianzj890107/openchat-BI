# 实现提示词：本体对象消歧走权威接口 + 本体库详情收口（分析 Agent P1 批）

> 把下面整段交给实现人员（人或 Agent）。本批只做**消费面收口**：把两个"代码已实现、
> 但没有任何生产调用方"的权威接口接进真实链路（对象确认、本体库详情），并把
> `cdcTopicPrefix` 消费出来。不改分析策略、Prompt、评测集、图表与前端 UI，不加 known gap。

---

## 0. 你的任务

远程本体库已经提供两个权威接口，但分析 Agent **一次都没调用过**：

* `POST /api/v1/analysis/context/resolve-ontology-object`（文档 §意图确认(新)）——
  按名字确认"这是哪一类本体对象"，原生支持 `candidateTypes` 顺序优先匹配，命中时把
  `properties` 展开到行根级；
* `GET /api/v1/analysis/context/ontology-repository/{id}`（文档 §获取本体库信息(新)）——
  单个本体库的完整信息，含 `cdcTopicPrefix`。

客户端侧 `RemoteOntologyClient.ensure_object()`（`bi_agent/ontology/remote.py::ensure_object`）
与 `repository_info()`（同文件 `:516`）**已经实现并已按新契约归一化**，
`grep -rn "ensure_object\|repository_info" bi_agent/` 只命中定义本身 —— 没有调用方。

于是今天：

1. `Ontology-TermDisambiguate` 只查 `Term`、`Ontology-EntityDescribe` / `Ontology-SemanticQuery`
   经 `_candidate_results()` 对 `_CANDIDATE_TYPES` 的 **13** 个类型逐个执行
   `SELECT FROM <Type> LIMIT 2000`，最终 `typeName` 由本地 `_rank_row` 决定 —— 同名对象
   出现在多个类型时，**谁赢由本地排序决定，而不是本体服务**；`MetricCalculation` 只查
   `Indicator`，完全没有"候选类型按优先级依次确认"的能力（接口原生支持）。
2. 数据源目录 `_remote_repository_catalog()`（`bi_agent/web/app.py:1349`）只翻列表分页，
   详情接口零调用，`cdcTopicPrefix` 没有任何出口 —— 而"这个库通过哪个 CDC 通道同步"
   正是判断"数据是不是最新的"唯一可用线索。

请把这两个接口接进真实链路，并保持旧契约可用。

**不要**只把 `_CANDIDATE_TYPES` 增减几个类型名，也不要只把 `SELECT FROM` 换一种写法——
那没修：问题不是"拉几个类型"，而是**确权口径必须来自本体服务**。

## 1. 先读

1. `docs/specs/ontology-object-resolution-and-repository-detail.md`（本批 Spec，逐节读完，§4 是重点）
2. `tests/test_ontology_object_resolution_red.py`（红测 = 验收标准）
3. `API/本体MAL层API.md`：§意图确认(新)、§获取本体库信息(新)、§分页查询本体列表(新)
4. 生产代码：
   - `bi_agent/ontology/remote.py`：`ensure_object`、`repository_info`、`_dual_request`、
     `_request`、`_object_info_of`、`_repository_fields`、`list_objects`、`script_query`
   - `bi_agent/tools/remote_ontology_tools.py`：`_CANDIDATE_TYPES`（26 行）、
     `_rank_row`、`_search_type`、`_candidate_results`（156 行）、`_format_object`、
     `_make_query`、`_make_term`、`_make_metric`、`_make_describe`、`remote_specs`
   - `bi_agent/web/app.py`：`_remote_repository_catalog`（1349 行）、`get_sources_endpoint`
     （1722 行）的 `ontology.remote_repositories` / `database.remote_databases` 两个出口
5. 既有门禁：
   - `tests/test_ontology_mal_contract_red.py`（70 条，当前 **69 passed / 1 pre-existing
     failure**，其中 `DialectEquivalenceTests` / `NewDialectParsingTests` 是硬约束：
     `ensure_object` / `repository_info` 的双方言归一化不得改坏）
   - `tests/test_regressions.py`（本体显示名、数据源原子配对、`TaskAlertProxyTests`）
   - `dataset/evals/analytics`（570 / P0 147 / P1 388 / P2 35 / known_gap 0）

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_ontology_object_resolution_red.py
```

当前实测 **15 failed / 9 passed**（24 条）。失败逐条如下：

| 用例 | 实测失败原因 |
| --- | --- |
| R1 | `POST /api/v1/analysis/context/resolve-ontology-object` 调用数 = 0 |
| R2 | 同上，因此请求体形状无从断言 |
| R3 | 四个工具都没有 `candidateTypes`（确认请求 0 次） |
| R4 | 命中答案为 `[T0001] 采购申请头 (Term)`：缺权威 `code`/`typeName`/展开属性，且泄露本地候选 |
| R5 | `expand-ontology-context` 的 `type` 是本地排序结果 `Term`，不是权威 `LogicalEntity` |
| R6 | 命中后仍有全量下拉：`TermDisambiguate` 1 次、`EntityDescribe` **13** 次 `SELECT FROM <Type> LIMIT …` |
| R7 | 未命中路径没有权威确认请求，今天用本地近似候选作答 |
| R8 | 确认失败路径不存在（0 次请求），因此也没有降级说明 |
| R10 | `MetricCalculation` 确认请求 0 次 |
| R11 | 目录只调 `GET /api/v1/analysis/context/ontology-repository`，详情调用 0 次 |
| R12 | 目录条目缺 `cdcTopicPrefix` 键（`['cdcTopicPrefix_missing:1','cdcTopicPrefix_missing:2']`） |
| R13 | `/api/sources` 的 ontology / database 两个出口都缺该字段 |
| R14 | 详情失败路径不会被触发（详情请求 0 次） |
| R16 | 未配置该字段时是**缺键**，不是空串 |
| R17 | 确认请求未发起，无法携带既有鉴权头（`X-Ontology-Repository-Id` / `X-App-Id`） |

9 条绿色用例是护栏，**必须保持绿**：R9（模糊/多词输入不得走精确确认）、R15（只有旧方言时
确认与目录仍可用）、以及 7 条 Mutation Guard（空 `candidateTypes`、权威类型不在首位、
非文档枚举类型、重复类型、本地排序覆盖权威、详情值串库、`cdcTopicPrefix` 缺键/为 null）。

**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。

## 3. 实现要求

### 3.1 确认层（工具侧）

在 `bi_agent/tools/remote_ontology_tools.py` 新增一个**共享确认函数**（命名自由，红测只按行为断言）：

```
confirm_object(client, *, name, candidate_types) -> dict
```

1. **只在 `name` 是单个对象名/编码时**走确认：无空格、无比较词、长度 ≤ 64；否则返回"未确认"，
   由调用方走既有搜索路径 —— 搜索不能被换成精确匹配（R9 锁定）。
2. 请求体逐字符合文档：

```json
{"analysisConfig": {"name": "<name>", "candidateTypes": ["<权威类型优先>", "…"]},
 "commonConfig": {}}
```

3. `candidateTypes`：非空；**首项是该工具的权威类型**
   （`Ontology-TermDisambiguate` → `Term`；`MetricCalculation` → `Indicator`；
   `Ontology-EntityDescribe` / `Ontology-SemanticQuery` → `BusinessObject`）；
   其余回退类型全部取自文档枚举（`BusinessObject, LogicalEntity, BusinessAttribute, Term,
   Dimension, Indicator, Rule, Activity, Process, EntityRelation, MetaRelation, TableNode,
   Column`）；同一工具两次调用**逐字一致**（顺序稳定，R3 断言）。
4. 命中：**必须使用接口返回的 `typeName`**（后续 `find_related` / 展示都以它为准），
   不得再用本地 `_rank_row` 覆盖；命中路径**不得**再出现 `SELECT FROM <Type> LIMIT …`
   （R4、R5、R6）。
5. 未命中（`found=False`）：文案明确"本体库中没有该名字的对象/术语"，**不得**用本地近似候选
   冒名，不得伪造类型或属性（R7）。
6. 失败（`OntologyApiError`）：**降级**到今天的候选路径（`_candidate_results` / `_search_type`），
   并在答案里**追加**降级说明（例如 `（本体确认接口不可用，已回退到本地候选）`），
   不得抛错给模型、不得返回空结果冒充"没有这个对象"（R8）。
7. 不改 `ensure_object` / `repository_info` 的双方言归一化行为（现有 70 条 MAL 契约测试是硬约束）。

### 3.2 接线四个工具

`_make_query`、`_make_term`、`_make_metric`、`_make_describe` 都要先经确认层，并保持既有输出形状：

* 首行标识不变（`# Remote Ontology-SemanticQuery`、`Ontology-EntityDescribe:` 等）；
* `_format_object` 前缀、`Ontology-*:` 文案保持可识别；新增说明只能**追加**在既有文案之后；
* `MetricCalculation` 仍要输出指标块（维度、口径、来源表等），只是"这个指标是哪个对象"
  由权威接口先确认。

### 3.3 本体库详情

`bi_agent/web/app.py::_remote_repository_catalog`：

1. 列表阶段之后，对**当前激活本体库**（`client.repository_id`）调用**一次**
   `client.repository_info()`，用详情行补齐该条目；**其余条目保持列表值**（不要 N 次详情请求，
   也不要把激活库的详情复用到别的库）。
2. 详情行经既有 `_repository_fields` 归一化（`currentDatabase` / `dorisDatabase` 双向可读），
   并透传 `cdcTopicPrefix`：字符串；未配置时是**空串**（不是缺键、不是 `null`，不抛错）。
3. 详情失败（`OntologyApiError`）→ 保留列表值，`remote_status.available` 仍为 `True`，
   `remote_status.message` 不得被详情失败污染（目录可用性与详情可用性分开表达）。
4. `GET /api/sources` 的 `ontology.remote_repositories[]` 与 `database.remote_databases[]`
   都要带 `cdcTopicPrefix`，且两处一致；`username`/`password` 等字段仍然不得出现在响应中。

### 3.4 文档同步

* `docs/analysis-agent-data-source-and-ontology-consumption.md` §7：更正 `qualifiedTables` 一项
  （该字段只出现在**智能建模任务上下文**，分析 Agent 不消费建模任务上下文，属建模侧
  `eimosp-ontology-agentic-modeling/docs/specs/cross-schema-database-scope.md`）；并更新
  `ensure_object` / `repository_info` "无调用方"的表述。
* `API/系统接口调用与代码统计.md:180-190`：详情接口不再"无调用方"。

### 3.5 明确不做

* 不改 `bi_agent/tools/analysis_policy.py`（路由、工具暴露、安全拒绝优先级一律不动）；
* 不改 Prompt / SOP（`.claude/agents/bi-analyst.md`、`bi_agent/web/session.py::_SOP_TOOL_STEP`）；
* 不改 `dataset/evals/analytics/**`（570 / P0 147 / P1 388 / P2 35 / known_gap 0 必须不变）；
* 不消费 `qualifiedTables`（跨 Schema 表范围属建模仓库），不改图谱检索、指标维度计算、
  X360 模型工具化与前端 UI；
* 不引入同义词表或模糊前缀规则；不对每个本体库都发详情请求；
* 不读取真实凭据、不跑 live、不部署。

## 4. 环境未确认项（不得假装已确认）

1. `cdcTopicPrefix` 的**产品口径**需要上游一句话：它是"该本体库业务库的 CDC 主题前缀"还是
   "本体库自身的命名空间前缀"？本批只做**透传展示**，不做任何语义推断。
2. `resolve-ontology-object` 返回空 `result.rows` 时，"本体库没有这个对象"与"该部署不支持精确
   确认"这两种语义是否需要区分？如上游能给显式 `found` 字段，按字段实现；否则按本文档
   §4.2 第 5 条处理并在交付报告里说明。
3. `Ontology-EntityDescribe` / `Ontology-SemanticQuery` 的权威类型取 `BusinessObject` 是否与
   上游一致（尤其 `LogicalEntity` 谁优先）；如需调整，只改 `candidateTypes` 顺序，
   不改"首项必须是该工具权威类型"的契约。
4. 上游是否支持"一次请求多级候选、命中即返回展开属性"的并发/超时预算（避免确认层成为新的
   慢点）。若上游有更严格的超时要求，用现有 `ONTOLOGY_TIMEOUT_SECONDS` 表达，不新增配置。

## 5. 完成前必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_ontology_object_resolution_red.py      # 目标：24 passed
.venv/bin/python -m pytest -q tests/test_ontology_mal_contract_red.py           # 不得劣化（≥69 passed）
.venv/bin/python -m pytest -q tests/test_regressions.py -k "Ontology or Source or Catalog"
.venv/bin/python -m pytest -q tests/
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
```

* 570 / P0 147 / known_gap 0 必须不变；安全（67 条）与行动建议等既有批次测试必须保持通过；
* 全量 `pytest -q tests` 的失败项不得多于改动前基线；
* 若某项因缺少真实 Provider 而无法运行，如实标为 `not_measured`，**不得**写成 passed。

## 6. 交付报告（必须包含）

1. 修改文件清单与每个文件的改动要点；
2. 红测从 15 failed / 9 passed 到全绿的实际输出（贴数字，不贴结论）；
3. 命中路径的请求数对比（改动前 `EntityDescribe` 13 次全量下拉 → 改动后几次请求）；
4. 旧方言与旧契约回归结果（MAL 契约 70 条、`test_regressions.py`）；
5. 误伤验证：模糊搜索（R9）、纯搜索路径、`Ontology-ListBusinessObjects`、
   `Ontology-RelationLookup`、图谱检索与指标维度计算未被确认层影响；
6. 评测门禁结果与 known gap 数量；
7. §4 未确认项的处理方式（哪些按默认实现、哪些留给上游）；
8. 明确说明：未读取真实凭据、未跑 live、未部署、未创建 MR/tag/Release。
