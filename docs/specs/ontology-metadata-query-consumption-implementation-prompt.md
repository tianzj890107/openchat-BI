# 实现提示词：本体元数据查询消费收口（分析 Agent P2 批）

> 把下面整段交给实现人员（人或 Agent）。本批只做**消费面收口**：把"按名字取元数据"从
> 本地全量下拉换成文档已给出的分页树查询，把"业务属性"从图邻域遍历换成文档的
> `LEContainATT` 查询。不改分析策略、Prompt、评测集、图表与前端 UI，不加 known gap。
> 前置：P1 批（对象确权 + 库详情）**已实现**，本批不得回退它。

---

## 0. 你的任务

P1 之后"这是哪个对象"已经由本体服务确权；但"按名字检索元数据"仍然是本地全量下拉：

* `MetricCalculation` 在权威确认不可用时 → `_search_type(client,"Indicator",…)` →
  `list_objects` → `SELECT FROM Indicator LIMIT 2000`；
* `Ontology-SemanticQuery` 的模糊检索 → `_candidate_results` 对 **13** 个类型各发一次
  `SELECT FROM <Type> LIMIT 2000`（其中就包含文档已给出树查询的 `Indicator` / `Dimension`）；
* `Ontology-EntityDescribe` 的业务属性 → `find_related(kind, code, depth=1)`
  （`expand-ontology-context` 图邻域遍历）。

而 `API/本体元数据查询API-WIP.md` 已经把三条分页查询写清楚了：`POST /api/v1/analysis/meta/query`
+ `analysisConfig.vertex` + `commonConfig.filters`（`label LIKE` / `LEContainATT` 边）
+ `sorts` + `pagination`。

请把这三条接进真实链路：

1. 指标 / 维度检索走**指标树 / 维度树**查询（含分页与翻页）；
2. `Ontology-EntityDescribe` 的业务属性走**逻辑实体关联的业务属性**查询（含分页与翻页）；
3. 树查询失败时降级到既有兜底路径，并**追加**一句如实说明。

**不要**只把 `LIMIT 2000` 改成 `LIMIT 5000`，也不要只给现有查询加一个 `pagination`
字段——那没修：问题不是"拉多少行"，而是**元数据检索没有分页能力**，超出单页的对象
会与"对象不存在"无法区分。

## 1. 先读

1. `docs/specs/ontology-metadata-query-consumption.md`（本批 Spec，逐节读完，§4 与 §6 是重点）
2. `tests/test_ontology_metadata_query_consumption_red.py`（红测 = 验收标准）
3. `API/本体元数据查询API-WIP.md`：§获取指标树、§获取维度树、§获取指标关联的维度列表、
   §获取逻辑实体关联的业务属性（请求体与响应体 mock 都在里面）
4. 生产代码：
   - `bi_agent/tools/remote_ontology_tools.py`：`_make_metric`、`_make_query`、
     `_make_describe`、`_candidate_results`、`_search_type`、`_rank_row`、
     `_metric_dimensions`（**指标关联维度查询保持不动**）、`confirm_object`（P1，保持不动）、
     `_format_object`、`_format_metric`、`_related_text`、`_with_degraded_note`
   - `bi_agent/ontology/remote.py`：`metadata_query`、`list_objects`、`find_related`
5. 前置批次：`docs/specs/ontology-object-resolution-and-repository-detail.md`（P1 契约）
6. 既有门禁：`tests/test_ontology_object_resolution_red.py`（24 条，须保持全绿）、
   `tests/test_ontology_mal_contract_red.py`（70 条）、`tests/test_regressions.py`、
   `dataset/evals/analytics`（570 / P0 147 / known_gap 0）

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_ontology_metadata_query_consumption_red.py
```

当前实测 **12 failed / 15 passed**（27 条）。失败逐条如下：

| 用例 | 实测失败原因 |
| --- | --- |
| R1 | 指标检索没有发出文档指标树查询（`vertex[Indicator]` 0 次），只有 `SELECT FROM Indicator LIMIT 2000` |
| R2 | 同上，请求体形状无从断言 |
| R3 | 同上，没有分页 |
| R4 | 指标在第 2 页时输出 `No metric matches '采购金额'.`：单页截断被当成"没有该指标" |
| R5 | 模糊搜索仍对 `Indicator` 发全量下拉，且没有任何指标树调用 |
| R6 | 模糊搜索仍对 `Dimension` 发全量下拉，且没有任何维度树调用 |
| R7 | `Ontology-EntityDescribe` 没有发出 `BusinessAttribute` + `LEContainATT` 查询（0 次） |
| R8 | 同上，请求体形状无从断言 |
| R9 | 同上，没有分页 |
| R10 | 第 2 页的业务属性丢失（输出只有 `Attributes and relations: no related objects.`） |
| R11 | 图邻域为空时业务属性**全部丢失**（输出同上） |
| R12 | 属性查询失败路径不存在（不发查询），因此也没有降级说明 |

15 条绿色用例是护栏，**必须保持绿**：G1（权威命中时不发全量下拉/树查询）、
G2（指标关联维度仍走 `IndicatorIsDrilledByDimension`）、G3（对象徽标行不变）、
G4（全部不可用时不得伪造指标），以及 M1–M11 的 Mutation Guard（全量下拉、`EQ` 代替
`LIKE`、`LIKE` 打错属性、缺 `sorts`/`pagination`、`pageSize` 越界、只取第 1 页、
属性顶点写错、丢实体过滤、丢 `LEContainATT` 边、丢钻取关系）。

**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。

## 3. 实现要求

### 3.1 元数据树查询封装（新增，命名自由）

在 `bi_agent/tools/remote_ontology_tools.py` 新增共享函数（红测只按行为断言），
经 `RemoteOntologyClient.metadata_query(analysis_config, common_config)` 发出：

```
fetch_metadata_kind(client, *, kind, needle) -> list[dict]     # kind ∈ {Indicator, Dimension}
fetch_entity_attributes(client, *, entity_code) -> list[dict]  # BusinessAttribute + LEContainATT
```

契约：

1. **指标树**（`kind == "Indicator"`）：`vertex[0].type == "Indicator"`，`properties` 至少含
   `code` 与 `label`（或 `name`）；`commonConfig.filters` 对 `label`（或 `name`）做
   `LIKE %<needle>%`；带 `sorts`；带 `pagination`。
2. **维度树**：同上，顶点换 `Dimension`。
3. **业务属性**：`vertex[0].type == "BusinessAttribute"`；`filters` 用 `AND` 组合
   `{"type":"LogicalEntity","property":"code","operator":{"code":"EQ","type":"STRING"},"value":<实体编码>}`
   与 `{"type":"LEContainATT","sourceType":"LogicalEntity","targetType":"BusinessAttribute"}`；
   带 `sorts` 与 `pagination`。
4. **分页与翻页**：`pageNum ≥ 1`，`1 ≤ pageSize ≤ 500`；
   **第 1 页返回行数等于 `pageSize` 且尚未命中时，必须继续请求下一页**，直到命中或返回空页；
   翻页次数必须有上限（建议 ≤ 20 页），且不得无限循环。
5. 失败（`OntologyApiError`）→ 返回"不可用"标记，由调用方降级，**不得抛出**。

### 3.2 接线

1. `_make_metric`：权威确认不可用（`status == "unavailable"`）时的指标检索，改用指标树；
   权威命中时**不要**再多发树查询（G1 锁定）。
2. `_candidate_results`（模糊检索）：`Indicator` / `Dimension` 改为经树查询（带 `LIKE`），
   其余 11 个类型保持 `list_objects` 不变；返回形状 `(type_name, props)` 与排序规则不变。
3. `_make_describe`：属性来源改为文档查询；**关系**仍由既有 `find_related` 负责，
   两者不得互相顶替；对象徽标行与 `Attributes and relations` 段落仍可识别（G3 锁定）。
4. `_metric_dimensions`（指标关联维度）**完全不改**（G2 锁定）。

### 3.3 降级与说明

1. 树查询不可用 → 回退既有兜底（`_search_type` / `_candidate_results` / `find_related`）；
2. 降级必须**追加**一句如实说明（例如 `（指标树查询不可用，已回退到本地全量检索）`），
   不能把回退写成权威结论，也不能把异常抛给模型；
3. 全部路径都不可用 → 输出非空、不得伪造任何码值（G4）。

### 3.4 文档同步

更新 `API/系统接口调用与代码统计.md`：指标树 / 维度树 / 业务属性三个查询的调用点。

### 3.5 明确不做

* 不改 `bi_agent/tools/analysis_policy.py`、Prompt/SOP、评测集、前端 UI；
* 不消费 `Modifier`（无调用方）；不实现 `本体实例计算API-WIP.md`（`todo`）与
  `指标维度计算API-WIP.md`（只有图片）；
* 不做 X360 模型工具化、前端 `source` 消费、图谱检索增强；
* 不新增配置项、不新增鉴权头、不读取真实凭据、不部署。

## 4. 环境未确认项（不得假装已确认）

1. 各生产本体库是否都已支持 `Indicator` / `Dimension` 顶点 + `LIKE` 过滤（P1 期间发现过
   个别库的属性模型不一致）？若不支持，按 §3.3 降级并**在交付报告里如实列出**。
2. `LEContainATT` 边的方向（`sourceType=LogicalEntity → targetType=BusinessAttribute`）
   是否与所有库一致？
3. 服务端 `pageSize` 的真实上限（文档示例是 10）：实现取 500，如服务端拒绝则改小并在
   报告里写明实测值。

## 5. 完成前必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_ontology_metadata_query_consumption_red.py   # 目标：27 passed
.venv/bin/python -m pytest -q tests/test_ontology_object_resolution_red.py            # 24 passed 不得回退
.venv/bin/python -m pytest -q tests/test_ontology_mal_contract_red.py                 # ≥69 passed 不得劣化
.venv/bin/python -m pytest -q tests/
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
```

* 570 / P0 147 / known_gap 0 必须不变；全量 `pytest -q tests` 失败项不得多于改动前基线；
* 某项因缺少真实 Provider 而无法运行时，如实标 `not_measured`，**不得**写成 passed。

## 6. 交付报告（必须包含）

1. 修改文件清单与每个文件的改动要点；
2. 红测从 12 failed / 15 passed 到全绿的实际输出；
3. 检索请求数对比：改动前 `Ontology-SemanticQuery("采购金额下降的原因")` 发多少次
   `SELECT FROM … LIMIT 2000`、改动后发多少次树查询（贴数字）；
4. 翻页验证：目标对象在第 2 页时能取到（把日志或调用序列贴出来）；
5. P1 红测 24 条与 MAL 契约 70 条的回归结果；
6. 误伤验证：其余 11 个候选类型仍走 `list_objects`；指标关联维度查询未变；纯关键词搜索
   仍能命中模糊词；`Ontology-TermDisambiguate` / `ListBusinessObjects` / 图谱工具行为不变；
7. 评测门禁结果与 known gap 数量；
8. §4 未确认项的处理方式（哪些按默认实现、哪些按实测调整）；
9. 明确说明：未读取真实凭据、未跑 live、未部署、未创建 MR/tag/Release。
