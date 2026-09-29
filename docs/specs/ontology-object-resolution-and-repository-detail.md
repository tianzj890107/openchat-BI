# 本体对象消歧与本体库详情收口 Spec（分析 Agent P1 批）

> 依据：`API/本体MAL层API.md`（2026-09-18 工作区版本）§「意图确认(新)」
> `/api/v1/analysis/context/resolve-ontology-object`、§「获取本体库信息(新)」
> `/api/v1/analysis/context/ontology-repository/{id}`
> 红测：`tests/test_ontology_object_resolution_red.py`
> 实现提示词：`docs/specs/ontology-object-resolution-and-repository-detail-implementation-prompt.md`
>
> 本批只做**消费面收口**：把两个"代码已实现但无调用方"的权威接口接进真实链路，
> 并把本体库详情里的同步通道字段消费起来。不改分析策略、Prompt、评测集、图表与前端 UI。

---

## 0. 一句话结论

远程本体库已经提供了两个**权威**接口：按名字确认"这是哪一类本体对象"（意图确认）与
取单个本体库的完整信息。分析 Agent 侧 `RemoteOntologyClient.ensure_object()` 与
`repository_info()` **代码都已实现并已按新契约归一化，但没有任何生产调用方**
（`grep -rn "ensure_object\|repository_info" bi_agent/` 只命中定义本身）。

于是当前真实行为是：

* **对象消歧靠"全量下拉 + 本地排序猜"**：`Ontology-TermDisambiguate`、
  `Ontology-EntityDescribe`、`Ontology-SemanticQuery` 都先经
  `_candidate_results()`（`bi_agent/tools/remote_ontology_tools.py:156`），它对
  `_CANDIDATE_TYPES` 里的 **13** 种本体类型逐个执行
  `list_objects(type)` → `script_query("SELECT FROM <Type> LIMIT 2000")`
  （`bi_agent/ontology/remote.py:450-474`），再在本地按 code/label/alias/模糊规则排序。
  同一类型名在多个类型里出现时，**由本地排序决定最终类型**，而不是由本体服务判定。
* **本体库详情接口零调用**：数据源目录只走列表接口
  （`app.py:1359` `_remote_repository_catalog` → `list_repositories`），
  详情接口能给出的权威字段（尤其 `cdcTopicPrefix`）没有进入任何响应、提示词或诊断证据。

本批要求：**对象确认走权威接口（带回退）、本体库详情接进数据源目录（带回退）、
`cdcTopicPrefix` 作为数据同步通道字段被消费**，同时保持旧契约可用、不改动分析路由。

---

## 1. 范围与非目标

### 1.1 范围内

| 项 | 生产入口 |
| --- | --- |
| 对象确认走 `resolve-ontology-object` | `bi_agent/tools/remote_ontology_tools.py`（`_make_term` / `_make_describe` / `_make_query` 及其共享的确认层） |
| 确认失败/未命中的降级与文案 | 同上 |
| 本体库详情接入 | `bi_agent/web/app.py::_remote_repository_catalog`（`app.py:1348`） |
| `cdcTopicPrefix` 暴露 | `GET /api/sources` 的 `ontology.remote_repositories[]`（`app.py:1834`） |
| 客户端侧保证 | `bi_agent/ontology/remote.py::ensure_object` / `repository_info`（已实现，本批只补调用方需要的窄接口） |
| 文档 | `docs/analysis-agent-data-source-and-ontology-consumption.md` §7 表述更正、`API/系统接口调用与代码统计.md:180-190` |

### 1.2 非目标（本批明确不做）

* **不**改 `bi_agent/tools/analysis_policy.py`（路由、工具暴露、安全拒绝优先级一律不动）；
* **不**改 Prompt / SOP（`.claude/agents/bi-analyst.md`、`bi_agent/web/session.py::_SOP_TOOL_STEP`）；
* **不**改评测集（`dataset/evals/analytics/**` 保持 570 / P0 147 / P1 388 / P2 35 / known_gap 0）；
* **不**消费 `qualifiedTables`：该字段只出现在**智能建模任务上下文**
  （`API/本体MAL层API.md` §获取智能建模任务上下文信息 的 `database` 对象），
  分析 Agent 不消费建模任务上下文；跨 Schema 表范围属建模侧
  `eimosp-ontology-agentic-modeling/docs/specs/cross-schema-database-scope.md`。
  **本批同时更正** `docs/analysis-agent-data-source-and-ontology-consumption.md` §7 第 2 条
  把 `qualifiedTables` 列为"分析 Agent 未消费字段"的表述（该字段当前就取不到）。
* **不**扩展图谱检索、指标维度计算、预测、X360 模型工具化、前端 UI；
* **不**新增数据库能力、不读取真实凭据、不跑 live。

---

## 2. 决策与优先级边界（为什么这批是 P1）

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| P0 · X360 第一批 | 「行动 → 转督办」按 X360 流程定义换真（`docs/specs/x360-process-definition-integration.md`） | Spec + 红测 + 提示词已交付，**实现待做** |
| P0 · 建模侧 | 跨 Schema 表范围（`qualifiedTables` / `search_path` / 抽取范围） | 在建模仓库，不属本仓库 |
| **P1 · 本批** | 对象消歧走权威接口 + 本体库详情 + `cdcTopicPrefix` | 本文档 |
| P2 · 未开始 | 图谱检索增强、指标维度计算、X360 模型工具化、前端消费 `source` | 另开批次 |

判 P1 而不是 P0 的理由：本批不修任何"输出错误答案"的缺陷（今天的本地排序在
现有本体库上仍能给出结果），但它决定**多类型同名对象的确权口径**与**数据同步信息的可获得性**，
且两个权威接口已经就绪、成本低、收益直接（少 13 次全量拉取、类型由上游判定、同步通道可见）。

---

## 3. 当前行为（生产复现）

真实入口：`bi_agent/tools/remote_ontology_tools.py::remote_specs(client)` 产出的
`Ontology-TermDisambiguate` / `Ontology-EntityDescribe` / `Ontology-SemanticQuery` 执行器，
以及 `bi_agent/web/app.py::_remote_repository_catalog`。离线 loopback 复现见红测文件。

### 3.1 对象消歧：13 次全量下拉 + 本地排序

```
Ontology-TermDisambiguate(term="prHeader")
  → _make_term → _search_type(client, "Term", "prHeader")
    → client.list_objects("Term") → script_query("SELECT FROM Term LIMIT 2000")
    → 本地 _rank_row 排序（99 = 未命中）
```

`Ontology-EntityDescribe` / `Ontology-SemanticQuery` 走 `_candidate_results()`：对
`_CANDIDATE_TYPES`（`BusinessObject, LogicalEntity, BusinessAttribute, Term, Dimension,
Indicator, Rule, Activity, Process, EntityRelation, MetaRelation, TableNode, Column`）
**逐个**调用 `list_objects`，每次都是一条 `SELECT FROM <Type> LIMIT 2000`。

后果：

1. **慢且随类型数线性放大**：一次实体确认最多 13 次全量元数据拉取；
2. **类型由本地排序决定**：同名对象出现在多个类型时，最终 `typeName` 来自
   `_rank_row` 的 tier 比较，而不是本体服务的判定；
3. **拿不到接口展开的属性**：`resolve-ontology-object` 会把命中行的 `properties`
   展开到行根级（文档 §意图确认(新) 返回参数），当前路径只能拿到列表行里的字段；
4. **多一次往返语义丢失**：`MetricCalculation` 只查 `Indicator`、`_make_term` 只查
   `Term`，都没有"候选类型按优先级依次确认"的能力，而接口原生支持
   `candidateTypes` 顺序优先匹配。

### 3.2 本体库详情：零调用

```
_remote_repository_catalog(client)
  → client.list_repositories(page, size)          # 只走列表
  → 条目字段：id / name / description / dorisDatabase / metaDatabase /
             knowledgeDatabase / namespace / value / databaseValue
```

`client.repository_info()`（`remote.py:516`，`GET /api/v1/analysis/context/ontology-repository/{id}`）
**没有调用方**，因此：

* 列表分页快照与单库详情不一致时无从校正（列表可能少一页、可能被缓存）；
* 详情里的 `cdcTopicPrefix` 没有任何出口——用户与诊断都看不到"这个本体库的业务库
  通过哪个 CDC 通道同步"，而它正是判断"数据是不是最新的"唯一可用线索。

---

## 4. 目标设计

### 4.1 客户端侧：确认层与详情层的窄接口

在 `bi_agent/ontology/remote.py` 保持既有签名不破坏调用方（红测只断言行为）：

| 方法 | 契约 |
| --- | --- |
| `ensure_object(name, candidate_types)` | 已实现；本批要求 `candidate_types` **非空**、顺序即优先级；命中归一化 `{"found": True, "objectInfo": {"typeName", "properties"}}`；未命中 `{"found": False, "objectInfo": None}`；失败抛 `OntologyApiError` |
| `repository_info()` | 已实现；本批要求返回归一化后的单行 dict（同时含 `currentDatabase`/`dorisDatabase` 与 `cdcTopicPrefix` 若上游给出）；失败抛 `OntologyApiError` |

不得为了本批改变两个方法**已通过**的旧/新双语归一化行为
（`tests/test_ontology_mal_contract_red.py` 的 `DialectEquivalenceTests` /
`NewDialectParsingTests` 是硬约束）。

### 4.2 对象确认层（工具侧）

新增一个**共享确认函数**（命名自由，红测只按行为断言），供 `Ontology-TermDisambiguate` /
`Ontology-EntityDescribe` / `Ontology-SemanticQuery` 使用：

```
confirm_object(client, *, name, candidate_types) -> dict
```

契约：

1. 只在 `name` 是**单个对象名/编码**（无空格、无比较词、长度 ≤ 64）时走
   `resolve-ontology-object`；否则直接返回"未确认"，由调用方走既有搜索路径
   （避免把模型的模糊意图硬塞进确认接口）。
2. 请求体必须逐字符合文档：

```json
{
  "analysisConfig": {"name": "<name>", "candidateTypes": ["<权威类型优先>", "…"]},
  "commonConfig": {}
}
```

3. `candidateTypes` 规则：**非空**；首项是该工具的权威类型
   （TermDisambiguate → `Term`；MetricCalculation → `Indicator`；
   EntityDescribe / SemanticQuery → `BusinessObject`）；其余为回退类型且全部取自文档枚举
   （`BusinessObject, LogicalEntity, BusinessAttribute, Term, Dimension, Indicator,
   Rule, Activity, Process, EntityRelation, MetaRelation, TableNode, Column`）；
   **同一工具两次调用必须给出完全相同的列表**（顺序稳定，可断言）。
4. 命中：返回接口给出的 `typeName` 与展开后的属性；调用方**必须使用**这个 `typeName`
   （后续 `find_related` / 展示都以它为准），不得再用本地排序覆盖。
5. 未命中（`found=False`）：文案必须明确"本体库中没有该名字的对象/术语"，
   **不得**伪造对象名、属性或类型。
6. 失败（`OntologyApiError`）：**降级**到今天的候选列路径（`_candidate_results`
   / `_search_type`），工具返回值中必须带一句降级说明（例如
   `（本体确认接口不可用，已回退到本地候选）`），**不得**抛错给模型、
   **不得**返回空结果冒充"没有这个对象"。
7. 确认成功后**不得**再对该名称做全量类型下拉：命中路径不得出现
   `SELECT FROM <Type> LIMIT …` 形态的脚本查询。

### 4.3 本体库详情层

1. `_remote_repository_catalog` 在列表阶段之后，对**当前激活本体库**（
   `client.repository_id`）调用一次 `repository_info()`，用详情行覆盖/补齐该条目字段；
   其余条目保持列表值（避免 N 次详情请求）。
2. 详情行必须经过既有 `_repository_fields` 归一化（`currentDatabase`/`dorisDatabase`
   双向可读），并额外透传 `cdcTopicPrefix`。
3. 条目字段集（契约）：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `id` / `name` / `description` / `namespace` | 列表（详情可覆盖） | 既有字段，保持不变 |
| `dorisDatabase` / `metaDatabase` / `knowledgeDatabase` | 列表（详情可覆盖） | 既有字段，保持不变 |
| `value` / `databaseValue` | 派生 | 既有字段，保持不变 |
| `cdcTopicPrefix` | 详情（列表也有则用列表） | **新增**，字符串，无值时空串 |

4. 详情失败（`OntologyApiError`）→ 保留列表值，`remote_status.available` 仍为 `True`、
   `message` 不得被详情失败污染（目录可用性与详情可用性分开表达）；
5. `GET /api/sources` 的 `ontology.remote_repositories[]` 与
   `database.remote_databases[]` 都要带上 `cdcTopicPrefix`（同一份条目，两个出口一致）。

### 4.4 不放大：确认层与搜索层的边界

`Ontology-SemanticQuery` 的用途是**按关键词搜索**，因此：

* `name` 形如 `prHeader`、`HTTONG`、`BO0004` → 先确认，再搜索/展示；
* `name` 形如 `采购金额下降的原因`、`华东 逾期 订单`（含空格或非标识符）→ 直接走既有搜索路径，
  **不得**发确认请求（红测 H 项锁定）。

### 4.5 安全与凭据

* 确认与详情请求沿用既有鉴权（`X-Ontology-Repository-Id` / `X-App-Id` / 可选 `Authorization`），
  不为本批新增任何头或凭据来源；
* `cdcTopicPrefix` 是**非密钥**（CDC 主题前缀），可以进入 `/api/sources`；
  `username`/`password` 等字段仍然**不得**出现在任何响应中（既有约定，`app.py:1861`）；
* 错误文案不得回显 base URL、token 或内部绝对路径。

---

## 5. 兼容性与误伤控制

| 既有契约 | 要求 |
| --- | --- |
| `tests/test_ontology_mal_contract_red.py`（70 项，当前 69 passed / 1 pre-existing failure） | `ensure_object` / `repository_info` 的旧新双语归一化断言必须保持；本批不得让它变差 |
| `tests/test_regressions.py`（本体/显示名/图谱相关用例） | 工具输出格式（`_format_object` 前缀、`Ontology-*: ` 文案）保持可识别；新增降级说明只能**追加**在既有文案之后 |
| `Ontology-SemanticQuery` / `Ontology-EntityDescribe` 的既有输出形状 | 保持 `# Remote Ontology-SemanticQuery`、`Ontology-EntityDescribe:` 等首行标识不变 |
| 评测集 | `--suite smoke/regression/all` 570 / P0 147 / known_gap 0 不变；`ontology` 套件 46 条不变 |
| 前端 | 本批不改前端；`/api/sources` 只新增字段，不删改既有字段（前端忽略未知字段） |
| 数据源原子配对 | `_remote_repository_catalog` 的 `value`/`databaseValue` 生成规则与去重、分页终止条件保持不变（`tests/test_regressions.py` 有守卫） |

误伤控制（明确不做）：

* 不因为接了确认接口就把"关键词搜索"改成"精确确认"（搜索结果变少是退化）；
* 不把确认失败当成"对象不存在"；
* 不引入同义词表或模糊前缀规则；
* 不对每个本体库都发详情请求（只对当前激活库）；
* 不让详情失败影响目录可用性与数据源切换。

---

## 6. Red Test 对照表

文件：`tests/test_ontology_object_resolution_red.py`（离线 loopback，假 MAL 服务，
无凭据、无 LLM、不碰用户数据）。断言全部打真实生产入口：`remote_specs()` 产出的执行器、
`_remote_repository_catalog`、`GET /api/sources`。

| 编号 | 覆盖 | 期望今天为红 |
| --- | --- | --- |
| R1 | `Ontology-TermDisambiguate` 对单个术语发出 `POST /api/v1/analysis/context/resolve-ontology-object` | 红 |
| R2 | 请求体形状：`analysisConfig.name` / 非空 `candidateTypes` / `commonConfig == {}` | 红 |
| R3 | `candidateTypes` 首项为工具权威类型、全部来自文档枚举、两次调用完全一致 | 红 |
| R4 | 命中时输出使用接口给出的 `typeName` 与展开属性 | 红 |
| R5 | `Ontology-EntityDescribe` 命中后用接口 `typeName` 去 `expand-ontology-context` | 红 |
| R6 | 命中路径不再出现 `SELECT FROM <Type> LIMIT …` 全量下拉 | 红 |
| R7 | 未命中 → 明确"没有该对象"文案，不伪造类型/属性 | 红 |
| R8 | 确认接口失败 → 降级到本地候选并附降级说明，不抛错、不误报"不存在" | 红 |
| R9 | 模糊/多词输入不发确认请求（不放大） | 绿（护栏） |
| R10 | `MetricCalculation` 的确认首项是 `Indicator` | 红 |
| R11 | 目录对当前激活库调用 `GET /api/v1/analysis/context/ontology-repository/{id}` | 红 |
| R12 | 目录条目透出 `cdcTopicPrefix`（详情有值） | 红 |
| R13 | `/api/sources` 的 ontology 与 database 两个出口都带 `cdcTopicPrefix` 且一致 | 红 |
| R14 | 详情接口失败 → 目录仍可用（`available=True`）、既有字段不丢 | 红（今天根本没调详情，断言"调用过详情"即红） |
| R15 | 只给旧契约 payload 时确认与详情仍工作（旧方言回归） | 绿（护栏） |
| R16 | 未配置该字段时 `cdcTopicPrefix` 为空串而不是缺失/报错 | 红 |
| R17 | 确认/详情请求都带既有鉴权头，且响应/错误里不出现 token 或 base URL | 半红（详情侧未发起） |

**当前基线（2026-09-21，HEAD `537e01e`）**：R1–R8、R10–R14、R16、R17 为红，
R9 与 R15 为绿（护栏）。实测数字见实现提示词 §2 与交付报告。

---

## 7. Mutation 方案

| 变异 | 会被杀死的用例 |
| --- | --- |
| 确认层不接接口，继续全量下拉 | R1、R6 |
| 接了接口但用本地排序覆盖返回的 `typeName` | R4、R5 |
| `candidateTypes` 传空数组 / 传非文档枚举 / 顺序漂移 | R2、R3 |
| 所有输入都强制走确认（把搜索变成精确匹配） | R9 |
| 确认失败时报错或返回"对象不存在" | R8 |
| 未命中时用近似名补一个候选 | R7 |
| 详情只对第一个库调一次就复用到所有库 | R12（多库场景断言每个条目的值来自其自身来源） |
| 详情失败污染目录可用性 | R14 |
| `cdcTopicPrefix` 缺失时返回 `null` 或抛错 | R16 |
| 详情/确认把凭据或 base URL 带进错误文案 | R17 |

---

## 8. 实现验收清单

1. 确认层按 §4.2 实现，`Ontology-TermDisambiguate` / `Ontology-EntityDescribe` /
   `Ontology-SemanticQuery` / `MetricCalculation` 均使用它；
2. 命中路径不再有 `SELECT FROM <Type> LIMIT`；`typeName` 一律来自接口；
3. 未命中与失败两种路径的文案符合 §4.2 第 5、6 条；
4. 模糊输入不发确认请求（§4.4）；
5. `_remote_repository_catalog` 按 §4.3 调用详情、透出 `cdcTopicPrefix`、失败不影响目录；
6. `/api/sources` 两个出口字段一致；
7. 红测 `tests/test_ontology_object_resolution_red.py` 全绿；
8. `tests/test_ontology_mal_contract_red.py` 不劣化（≥69 passed）；
9. `--suite smoke/adversarial/recorded-provider/regression/all` 全绿，570 / P0 147 /
   known_gap 0 不变；
10. 全量 `pytest -q tests` 失败项不多于基线（本批红测从红转绿）；
11. `docs/analysis-agent-data-source-and-ontology-consumption.md` §7 更正、
    `API/系统接口调用与代码统计.md:180-190` 更新（详情接口不再"无调用方"）；
12. 未部署、未读取真实凭据、未改动路由与评测集。

---

## 9. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 确认接口在旧环境不存在（404） | 失败即降级到本地候选（§4.2 第 6 条），工具仍可用；红测 R8 锁定 |
| 确认接口返回的类型名与本地别名不一致 | 命中徽标以接口为准；显示名仍走既有 `_aliases`/`display_names` 逻辑，不改展示口径 |
| 精确确认让"关键词搜索"结果变少 | §4.4 边界 + R9 守卫；搜索结果路径不动 |
| 详情请求增加数据源页延迟 | 只对当前激活库请求一次，且沿用客户端 TTL 缓存；失败不影响目录 |
| `cdcTopicPrefix` 被误当敏感信息 | 该字段是 CDC 主题前缀（非密钥）；响应中仍不回显 username/password |
| 回滚 | 代码回滚 = 还原 `remote_ontology_tools.py` 确认层与 `app.py` 目录函数；红测文件保留为回归 |

---

## 10. 待确认与后续批次

1. `cdcTopicPrefix` 的**产品口径**需要上游确认一句：它是"该本体库业务库的 CDC 主题前缀"
   还是"本体库自身的命名空间前缀"（本批只做透传展示，不做语义推断）。
2. P2 批次候选（另开）：图谱检索增强、指标维度计算消费、X360 模型工具化、
   前端消费 X360 `source`、`live` 套件的真实 Provider 测量。
3. 本批与 X360 第一批相互独立：X360 改的是转督办链路，本批改的是本体消费链路，
   两者不得互相阻塞，也不得合并为一次改动。
