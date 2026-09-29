# 本体元数据查询消费收口 Spec（分析 Agent P2 批）

> 依据：`API/本体元数据查询API-WIP.md`（2026-09-18 工作区版本）§获取指标树、
> §获取维度树、§获取指标关联的维度列表、§获取逻辑实体关联的业务属性
> 红测：`tests/test_ontology_metadata_query_consumption_red.py`
> 实现提示词：`docs/specs/ontology-metadata-query-consumption-implementation-prompt.md`
>
> 前置批次：`ontology-mal-contract-migration.md`（方言迁移，已落地）、
> `ontology-object-resolution-and-repository-detail.md`（P1 对象确权与库详情，已实现）。
> 本批**只做消费面收口**：把"取元数据"从"全量下拉"换成文档给出的分页树查询。不改分析策略、
> Prompt、评测集、图表与前端 UI。

---

## 0. 一句话结论

P1 之后，"这是哪个对象"已经由本体服务确权；但"**按名字检索元数据**"仍然是本地全量下拉：

* 指标：`SELECT FROM Indicator LIMIT 2000`（`remote.py::list_objects`）；
* 维度：`SELECT FROM Dimension LIMIT 2000`；
* 业务属性：`expand-ontology-context` + `depth=1`（图邻域遍历）。

而 `API/本体元数据查询API-WIP.md` 已经把三条分页查询写清楚了：
`POST /api/v1/analysis/meta/query` + `analysisConfig.vertex` + `commonConfig.filters`
（`label LIKE` / `LEContainATT` 边）+ `sorts` + `pagination`。

后果是**可观测的能力上限**：一次下拉最多 2000 行（`list_objects` 上限 5000），
单个本体库的指标/维度一旦超过这个数量，超出的对象**直接查不到**，且失败方式与
"这个指标不存在"无法区分；属性则被图邻域与 `depth` 双重限制。

本批要求：**指标/维度检索走文档的树查询（分页、可翻页）、逻辑实体的业务属性走文档的
`LEContainATT` 查询**，图邻域与全量下拉只作为降级兜底，且降级必须如实说明。

---

## 1. 范围与非目标

### 1.1 范围内

| 项 | 生产入口 |
| --- | --- |
| 指标检索走指标树查询 | `bi_agent/tools/remote_ontology_tools.py::_make_metric`（降级搜索路径） |
| 维度检索走维度树查询 | 同文件 `_candidate_results` / `_search_type`（模糊检索路径） |
| 业务属性走 `LEContainATT` 查询 | 同文件 `_make_describe` |
| 分页与单页上限 | 新增的元数据查询封装（命名自由） |
| 降级与说明 | 同上：查询失败 → 既有兜底路径 + 追加说明 |
| 文档 | `API/系统接口调用与代码统计.md`（指标树/维度树/属性查询的调用点） |

### 1.2 非目标（本批明确不做）

* 不改 `bi_agent/tools/analysis_policy.py`（路由、工具暴露、安全拒绝优先级一律不动）；
* 不改 Prompt / SOP；不改评测集（570 / P0 147 / P1 388 / P2 35 / known_gap 0 必须不变）；
* 不改 `ensure_object` / `repository_info` 的既有归一化行为（P1 硬约束）；
* 不消费 §获取修饰词（`Modifier`）：当前没有任何调用方，也没有产品场景，需先有产品决定；
* 不实现 `API/本体实例计算API-WIP.md`（内容为 `todo`）与
  `API/指标维度计算API-WIP.md`（内容只有图片）——**上游文档未完成，无法定义契约**；
* 不做 X360 模型工具化、前端消费 `source`、图谱检索增强、性能与索引优化；
* 不新增数据库能力、不读取真实凭据、不跑 live。

---

## 2. 批次定位：这里就是"消费面"的收口点

| 批次 | 内容 | 状态 |
| --- | --- | --- |
| P0 · 安全拒绝 / 行动建议 / 元数据路由 / 预测 / 真实性 / 稳定性 | 六批已落地，known gap 0 | 完成 |
| P0 · X360 第一批 | 转督办按 X360 流程定义换真 | 完成（`923283c`） |
| P0 · 建模侧跨 Schema | `qualifiedTables` / `search_path` | 在建模仓库 |
| P1 · 对象确权 + 库详情 + `cdcTopicPrefix` | Spec/红测已交付，实现已落地 | 完成 |
| **P2 · 本批** | 元数据检索走文档树查询 + 业务属性走文档查询 | 本文档 |
| P2 · 剩余项 | 见 §10：全部属于**外部阻塞**（上游文档未完成）或**需产品/新授权**，不是本仓库可独立收口的代码缺口 | 挂起 |

本批是分析 Agent"远程本体消费面"的最后一批可独立收口的代码缺口。

---

## 3. 当前行为（生产复现）

真实入口：`remote_specs(client)` 产出的 `MetricCalculation` / `Ontology-SemanticQuery` /
`Ontology-EntityDescribe` 执行器；离线 loopback 复现见红测文件。

### 3.1 指标检索：降级路径仍然全量下拉

```
MetricCalculation(metric="采购金额")
  → confirm_object(...)                       # P1：权威确权（命中即用权威行）
  → status == unavailable → _search_type(client, "Indicator", "采购金额", limit=20)
    → client.list_objects("Indicator")        # SELECT FROM Indicator LIMIT 2000
```

文档给的是：

```json
{"analysisConfig": {"vertex": [{"type": "Indicator", "properties": [
    {"name": "code"}, {"name": "label"}, {"name": "indicatorType"}]}]},
 "commonConfig": {"filters": {"type": "Indicator", "property": "label",
                              "operator": {"code": "LIKE", "type": "STRING"},
                              "value": "%采购金额%"},
                  "sorts": [{"type": "Indicator", "property": "code", "order": "ASC"}],
                  "pagination": {"pageNum": 1, "pageSize": 10}}}
```

### 3.2 模糊检索：13 个类型逐个全量下拉

`Ontology-SemanticQuery("采购金额下降的原因")`（含查询标记 → 不确权）→
`_candidate_results` → 对 `_CANDIDATE_TYPES` 的 **13** 个类型各发一次
`SELECT FROM <Type> LIMIT 2000`，其中 `Indicator` / `Dimension` 正是文档已给出
树查询的两个类型。

### 3.3 业务属性：图邻域代替属性查询

```
Ontology-EntityDescribe(entity="LE000001")
  → confirm_object → hit(LogicalEntity/LE000001)     # P1
  → client.find_related("LogicalEntity", "LE000001", depth=1)
    → GET expand-ontology-context?type=…&code=…&depth=1
```

文档给的是 `BusinessAttribute` 顶点 + `filters.children = [LogicalEntity.code EQ,
{LEContainATT, sourceType: LogicalEntity, targetType: BusinessAttribute}]` + `sorts` +
`pagination` 的 TABLE 查询（只返回属性、分页）。

**实测（2026-09-21，P1 已实现的工作区）**：`tests/test_ontology_metadata_query_consumption_red.py`
= **12 failed / 15 passed**；见 §6。

---

## 4. 目标设计

### 4.1 指标树 / 维度树检索

1. 按名字检索 `Indicator` / `Dimension` 时，**必须**经 `POST /api/v1/analysis/meta/query`，
   `analysisConfig.vertex[0].type` 为对应类型，`commonConfig.filters` 对该类型的
   `label`（或 `name`）做 `LIKE %<关键词>%`，并带 `sorts`。
2. `commonConfig.pagination` 必须存在：`pageNum ≥ 1`，`1 ≤ pageSize ≤ 500`。
3. **第 1 页返回行数等于 `pageSize` 且尚未命中时，必须继续请求下一页**，直到命中或返回
   空页（翻页上限由实现自定，但必须有限）。禁止把单页截断当作"没有这个对象"。
4. 命中后沿用既有渲染（`_format_metric` / `_format_object`），输出形状与首行标识不变。
5. 检索路径不再对 `Indicator` / `Dimension` 发 `SELECT FROM <Type> LIMIT …`。

### 4.2 逻辑实体关联的业务属性

1. `Ontology-EntityDescribe` 取属性时**必须**发文档的 TABLE 查询：
   `analysisConfig.vertex[0].type == "BusinessAttribute"`，
   `commonConfig.filters` 含 `LogicalEntity.code EQ <实体编码>` 与 `LEContainATT`
   （`sourceType: LogicalEntity`，`targetType: BusinessAttribute`）。
2. 分页契约同 §4.1：`pagination` 必须存在、`pageSize ∈ [1, 500]`、第 1 页满则继续翻页，
   不得静默丢属性。
3. 属性是**属性的来源**；关系仍由既有的 `find_related` / 图工具负责，两者不得互相顶替。
4. 输出形状：对象徽标行不变（`[<code>] <label> (<typeName>)`），属性/关系段落仍可识别。

### 4.3 降级与说明

1. 树查询失败（`OntologyApiError`）→ 回退到既有兜底路径（`_search_type` / `_candidate_results` /
   `find_related`），**不得**把异常抛给模型、不得返回空结果冒充"没有"。
2. 降级必须**如实说明**（例如 `（指标树查询不可用，已回退到本地全量检索）`），
   只能**追加**在既有文案之后。
3. 全部路径都不可用时：输出必须非空、不得伪造任何码值（红测 G4 锁定）。

### 4.4 安全与凭据

* 全部请求沿用既有鉴权（`X-Ontology-Repository-Id` / `X-App-Id` / 可选 `Authorization`），
  本批不新增任何头、不新增配置、不引入新的凭据来源；
* 错误文案不得回显 base URL、token 或内部绝对路径；
* 不改 `/api/sources` 的字段集（P1 已收口 `cdcTopicPrefix`）。

---

## 5. 兼容性与误伤控制

| 既有契约 | 要求 |
| --- | --- |
| P1 红测（24 条，已全绿） | 确权口径、`candidateTypes`、降级说明、库详情字段一律不得回退 |
| `tests/test_ontology_mal_contract_red.py`（70 条，69 passed / 1 pre-existing failure） | 不得变差 |
| 指标关联维度（`IndicatorIsDrilledByDimension`） | **保持**（红测 G2 锁定），不得被本批顺手改掉 |
| `_candidate_results` 对其余 11 个类型的行为 | `Indicator` / `Dimension` 之外的候选类型不得被改写或减少 |
| 评测集 | `smoke` / `regression` / `all` 570 / P0 147 / known_gap 0 不变；`ontology` 套件 46 条不变 |
| 前端 | 本批不改前端；工具输出字段只增不减 |

误伤控制（明确不做）：

* 不把"模糊关键词搜索"改成"精确树查询"（搜索仍要能命中模糊词）；
* 不引入同义词表或前缀规则；
* 不因新增查询而删掉 `list_objects` / `find_related`（它们仍是降级与图谱能力的基座）；
* 不对每个候选类型都发树查询（只对文档已给出树查询、且数量可能超限的 `Indicator` /
  `Dimension`）。

---

## 6. Red Test 对照表

文件：`tests/test_ontology_metadata_query_consumption_red.py`（离线 loopback，假 MAL 服务，
无凭据、无 LLM、不碰用户数据）。断言全部打真实生产入口：`remote_specs()` 产出的执行器。

| 编号 | 覆盖 | 期望今天为红 |
| --- | --- | --- |
| R1 | 确认不可用时指标检索走文档指标树 | 红 |
| R2 | 指标树请求体形状（顶点/属性/LIKE/sorts/pagination） | 红 |
| R3 | 指标树分页在 1..500 内 | 红 |
| R4 | 指标在第 2 页时仍能取到（不得把截断当"不存在"） | 红 |
| R5 | 模糊搜索不再对 `Indicator` 全量下拉，且改用指标树 | 红 |
| R6 | 模糊搜索不再对 `Dimension` 全量下拉，且改用维度树 | 红 |
| R7 | `EntityDescribe` 发文档的业务属性查询 | 红 |
| R8 | 属性查询请求体形状（顶点/实体过滤/`LEContainATT`/分页） | 红 |
| R9 | 属性查询分页在 1..500 内 | 红 |
| R10 | 属性在第 2 页时仍被返回 | 红 |
| R11 | 属性来自文档查询（图邻域为空也必须有属性） | 红 |
| R12 | 属性查询失败 → 图邻域降级 + 说明、不报错 | 红 |
| G1 | 权威命中时不发全量下拉/树查询 | 绿（护栏） |
| G2 | 指标关联维度仍走文档钻取关系 | 绿（护栏） |
| G3 | 对象徽标行与输出形状不变 | 绿（护栏） |
| G4 | 全部不可用时不得伪造指标 | 绿（护栏） |
| M1–M11 | Mutation Guards（见 §7） | 绿 |

**基线（2026-09-21，P1 已实现的工作区）**：R1–R12 红，G1–G4 与 M1–M11 绿，
合计 **12 failed / 15 passed**。

---

## 7. Mutation 方案

| 变异 | 会被杀死的用例 |
| --- | --- |
| 树查询继续用 `SELECT FROM … LIMIT` 全量下拉 | R1、R5、R6、M2 |
| 用 `EQ` 精确匹配代替 `LIKE` | R2、M4 |
| `LIKE` 打到错误属性（如 `description`） | R2、M5 |
| 去掉 `sorts` 或 `pagination` | R2、R3、R9、M6 |
| `pageSize` 取 2000 / 0（越界） | R3、R9、M7 |
| 只取第 1 页就返回 | R4、R10 |
| 属性查询把顶点换成 `LogicalEntity` | R8、M8 |
| 丢掉 `LogicalEntity.code` 过滤或 `LEContainATT` 边 | R7、R8、M9、M10 |
| 丢掉指标关联维度钻取关系 | G2、M11 |
| 树查询失败时报错或返回空 | R12、G4 |
| 降级不加说明 | R12 |

---

## 8. 实现验收清单

1. 指标/维度检索按 §4.1 走文档树查询，含分页与翻页；
2. `EntityDescribe` 属性按 §4.2 走文档查询，含分页与翻页；
3. 降级路径与说明符合 §4.3；全部不可用时不伪造（G4）；
4. 红测 `tests/test_ontology_metadata_query_consumption_red.py` 全绿（27 条）；
5. P1 红测 24 条保持全绿；`tests/test_ontology_mal_contract_red.py` 不劣化（≥69 passed）；
6. 指标关联维度查询保持（G2）；
7. `--suite smoke/adversarial/regression/all` 全绿，570 / P0 147 / known_gap 0 不变；
8. 全量 `pytest -q tests` 失败项不多于基线；
9. `API/系统接口调用与代码统计.md` 更新（指标树/维度树/属性查询的调用点）；
10. 未部署、未读取真实凭据、未改动路由与评测集。

---

## 9. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 树查询在某些本体库上未实现对某个顶点类型（返回 400/404） | 降级到既有全量兜底并说明（§4.3），红测 R12 锁定属性侧；指标侧沿用同一契约 |
| 翻页让单次工具调用变慢 | 页大小上限 500、翻页上限有限；命中即停 |
| 本批与 P1 交叉 | P1 的候选/确权逻辑不动；本批只替换"检索"与"属性来源"两步 |
| 回滚 | 还原 `remote_ontology_tools.py` 的检索与属性路径；红测文件保留为回归 |

---

## 10. 本批之后仍不做（外部阻塞，不是本仓库缺口）

| 项 | 阻塞原因 |
| --- | --- |
| 指标维度计算（`API/指标维度计算API-WIP.md`） | 文档目前只有截图，没有可实现的契约 |
| 本体实例计算（`API/本体实例计算API-WIP.md`） | 文档内容为 `todo` |
| 修饰词（`Modifier`）消费 | 无调用方、无产品场景，需产品决定 |
| X360 模型工具化 | 需要产品决定 + 工具白名单/策略变更，属新批次 |
| 前端消费 X360 `source` | 前端 UI 批次 |
| live 套件的真实 Provider 测量 | 需要真实 Provider Key 的独立外部测量；离线门禁不依赖它 |
| 跨 Schema 表范围（`qualifiedTables` / `search_path`） | 建模侧仓库 |
