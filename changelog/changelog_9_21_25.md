# eimosp-ontology-agentic-analytics 变更记录（2026-09-21 至 2026-09-25）

> 本文档记录 2026-09-21（周一）至 2026-09-25（周五）当周的最终变更，按周直接维护
> （2026-09-08 起 changelog 只按周维护，不再创建日报）。本文件于 2026-09-20（周日）
> 预建，当周发生实际修改后直接写入本文件并标注发生日期。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-09-21 · X360 流程定义接口接入：「行动 → 转督办」换真（已完成）

新增只读 X360 客户端，把「行动 → 转督办」的 `bpDefinitionId` 与责任人从 14 条硬编码
关键词表换成 X360 实时数据，并保留一键回退。

- **只读客户端**：新增 `bi_agent/x360/`（`__init__.py` + `client.py`），公开
  `X360ApiError` / `X360Activity` / `X360ProcessDefinition` /
  `X360ProcessDefinitionClient`。只有文档给出的两个 `GET`
  （`/api/gateway2/x360/v1/process-definitions/ai/key/{key}` 与 `.../ai/{id}`），
  无请求体、无任何写接口；ID 一律保持字符串；匹配分级「活动名 → 活动 code（大小写
  不敏感、ASCII 词边界）→ 任务名 → 任务 code」，任务命中返回其父活动、未命中返回
  `None`；`(base_url, selector)` TTL 缓存（`X360_CACHE_TTL_SECONDS`，0=每次回源）+
  失败冷却（`X360_FAILURE_COOLDOWN_SECONDS`）；所有失败（HTTP / 业务 / 非 JSON /
  超时 / 截断响应 / 结构异常）统一归一化成 `X360ApiError`，消息不含 token 与内部地址。
- **转督办解析**：`bi_agent/web/app.py` 新增 `_resolve_task_alert_target`，实现降级
  真值表全部 7 行；`bpDefinitionId` 来源只有三种——请求体显式传入 > X360 命中 > 遗留
  关键词表；响应新增 `source`（`request` / `x360` / `static_fallback` / `default`）、
  `activityName`、`bpDefinitionId`；责任人取命中活动的 `responsiblePerson`，为空才回落
  到 `TASK_ALERT_DEFAULT_ASSIGNEE`；非 `x360` 来源时活动字段一律为 `None`（不把关键词
  猜成活动名）；端点只解析一次，请求体字段集、422/409/502/504 与幂等行为全部不变。
- **口径**：按 API 文档默认取流程定义 ID（`data.id`），活动 ID 始终单独返回在
  `activityId`；`X360_BP_ID_LEVEL=activity` 一键切回活动 ID（纯配置，不需要改码或回滚
  发布）。
- **配置**：`X360_*` 十个变量进 `.env.example`、`Dockerfile`（非密默认值）与本地
  `.env`；`X360_AUTH_TOKEN` 属运行时密钥、`X360_BASE_URL` 属环境相关值，都不烤进镜像；
  默认值里不出现 mock 的 `MOCK_0728` / `2081949112647405570`。
- **文档**：`DEPLOYMENT.md`（task-alert 小节）、`API/智能分析Agent前端API.md` §11 与
  `API/系统接口调用与代码统计.md`（原「未接入 X360」结论作废）。
- **验收**：`tests/test_x360_process_definition_red.py` 由 32 failed / 3 passed 变为
  **35 passed**；`TaskAlertProxyTests` 20 条全绿（未配置 `X360_BASE_URL` 的用例走静态
  回退，行为与接入前逐字一致）；`test_ontology_mal_contract_red.py` 保持 69 passed /
  1 pre-existing failure 不变；评测 `smoke` 140/140、`adversarial` 62/62、
  `recorded-provider` 122/122、`regression` 570/570（P0 147/147）、`all` 570/570，
  known gap 0/0 不变；全量 `pytest -q tests` = **1119 passed / 1 failed / 25 skipped /
  1036 subtests passed**（唯一失败是与本批无关的既有矛盾断言）。
- **红测文件回填 1 处（如实记录）**：`_Harness.setUp` 增加一行环境注入
  （`self.patch_env()`）。原因：生产客户端只从环境变量读 `X360_BASE_URL`，而该 harness
  从不注入，导致 9 条只调用 `from_env()` 的用例对**任何**正确实现都会因「未配置」
  （Spec §5.8 第一/二行）而失败；未改动任何断言、用例名、期望值或用例数量
  （sha256 `eef1105e…` → `3769c88a…`，diff 为纯新增 3 行）。
- **未结清（上线前必须结清，Spec §10）**：`bpDefinitionId` 到底要哪一级 ID 的上游书面
  确认、鉴权方式、生产流程定义 KEY/ID、`responsiblePerson` 取值域、是否需要任务级督办、
  `履约单` 的真实归属。未结清前生产保持现状（`X360_BASE_URL` 留空 = 未接入，或已接入时
  `X360_BP_ID_LEVEL=activity`）。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动 v0.1.9 与版本号、未读取真实凭据；
  live / live-canary 未运行。

### 2026-09-21 · 本体对象消歧走权威接口 + 本体库详情收口（P1 批，已完成）

核验出分析 Agent 本体消费面有两处「接口已就绪、但没有任何调用方」的缺陷，现已接进真实链路。

- **缺陷一（对象消歧靠本地猜）**：`RemoteOntologyClient.ensure_object()`
  （`bi_agent/ontology/remote.py:239`）与 `repository_info()`（同文件 `:516`）已实现并已按新
  方言归一化，但 `grep -rn "ensure_object\|repository_info" bi_agent/` 只命中定义本身。
  实测 `Ontology-TermDisambiguate("prHeader")` 只发 1 次 `SELECT FROM Term LIMIT 2000`，
  输出 `[T0001] 采购申请头 (Term)`；`Ontology-EntityDescribe("prHeader")` 对 13 个候选类型
  各发一次全量下拉后再用本地 `_rank_row` 定类型；权威接口回答的是 `LogicalEntity / LE000009`。
  即多类型同名对象的**确权口径由本地排序决定，而不是由本体服务判定**。
- **缺陷二（本体库详情零调用）**：`_remote_repository_catalog()` 只翻列表分页，详情接口
  `GET /api/v1/analysis/context/ontology-repository/{id}` 调用 0 次，`cdcTopicPrefix`
  没有任何出口（判断"这个库的数据是不是最新"唯一可用线索）。
- **实现（`bi_agent/tools/remote_ontology_tools.py`）**：新增权威确认层
  `confirm_object()` / `confirmation_candidates()`。只在**单个对象名/编码**（无空格、无比较词、
  ≤64 字符）时调用 `POST /api/v1/analysis/context/resolve-ontology-object`，请求体逐字为
  `{"analysisConfig": {"name", "candidateTypes"}, "commonConfig": {}}`；`candidateTypes`
  非空、首项是该工具的权威类型（TermDisambiguate→Term、MetricCalculation→Indicator、
  EntityDescribe/SemanticQuery→BusinessObject），其余为文档枚举回退项且顺序稳定。
  命中时**只按接口给出的 `typeName` 与展开属性作答**（不再由本地 `_rank_row` 定类型），
  `Ontology-EntityDescribe` 的 `expand-ontology-context` 也用权威 type/code；未命中给出
  "本体库中没有该名字的对象/术语（已由本体服务确认）"，不用本地近似候选冒名；确认接口失败
  则降级到既有候选/搜索路径并追加「（本体确认接口不可用，已回退到本地候选）」，不抛错给模型。
  四个工具（`Ontology-TermDisambiguate` / `Ontology-EntityDescribe` /
  `Ontology-SemanticQuery` / `MetricCalculation`）接线后首行标识与既有输出形状不变；
  模糊/多词输入（含空格或比较词，如"采购金额下降的原因"、"华东 逾期 订单"）**不发**确认请求，
  仍走既有搜索路径。
- **实现（`bi_agent/web/app.py`）**：`_remote_repository_catalog()` 在列表阶段之后对
  **当前激活本体库**调用**一次** `repository_info()`，用详情行补齐该条目（新增
  `cdcTopicPrefix`，未配置为空串；列表已有则用列表值），其余条目保持列表值；详情失败只保留
  列表值并记 warning，`remote_status.available` / `message` 不被详情失败污染。
  `GET /api/sources` 的 `ontology.remote_repositories[]` 与 `database.remote_databases[]`
  两个出口一致携带该字段，`username` / `password` 仍未出现。
- **文档**：`docs/analysis-agent-data-source-and-ontology-consumption.md` §4.4/§7（两个方法
  不再标"当前无调用方"；`qualifiedTables` 更正为只属智能建模任务上下文）、
  `API/系统接口调用与代码统计.md` §四（详情接口已有调用方）。
- **验收**：`tests/test_ontology_object_resolution_red.py` 由 **15 failed / 9 passed** 变为
  **24 passed**；命中路径不再出现任何 `SELECT FROM <Type> LIMIT …` 全量下拉（改动前
  `Ontology-EntityDescribe` 需要拉 13 次）；`tests/test_ontology_mal_contract_red.py` 保持
  69 passed / 1 pre-existing failure；全量 `pytest -q tests` = **1143 passed / 1 failed /
  25 skipped / 1036 subtests passed**；评测 `smoke` 140/140、`adversarial` 62/62、
  `recorded-provider` 122/122、`regression` 570/570（P0 147/147）、`all` 570/570，
  known gap 0/0 不变。
- **既有测试回填 1 处（如实记录）**：`tests/test_ontology_mal_contract_red.py` 的
  `test_list_repositories_stops_paginating_on_the_last_page` 原断言 `len(self.fake.calls) == 1`
  （用"HTTP 总调用数"代理"不翻下一页"），与本批"目录必须对激活库请求一次详情"直接冲突；
  改为 `self.fake.paths().count(REPO_LIST_NEW) == 1` —— **意图不变，仍是"只发一次列表请求"**，
  未删用例、未降低其它断言、未把失败改成 skip（sha256 `a094f585…` → `790adba6…`）。
  同文件 `test_list_repositories_uses_the_documented_context_endpoint` 是 HEAD 就存在的
  自相矛盾断言，未修、未恶化。
- **未确认项（留给上游）**：`cdcTopicPrefix` 的产品口径（本批只透传展示，不做语义推断）；
  `resolve-ontology-object` 返回空 `rows` 时"没有该对象"与"该部署不支持精确确认"是否要区分
  （本批按前者处理）；EntityDescribe/SemanticQuery 的权威类型取 `BusinessObject` 是否与上游
  一致（如需调整只改 `candidateTypes` 顺序）；确认接口的超时/并发预算。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号、未读取真实凭据；未跑 live。

### 2026-09-21 · 本体元数据查询消费：Spec + 红测（P2 批，本批未改生产实现）

P1（对象确权 + 本体库详情）落地后，"按名字取元数据"仍然是本地全量下拉；本轮核验出两处
缺口并交付 Spec、红测与实现提示词（本轮只做交付物，没有改生产实现）。

- **缺口一（元数据检索没有分页能力）**：`MetricCalculation` 在权威确认不可用时仍走
  `_search_type` → `list_objects` → `SELECT FROM Indicator LIMIT 2000`；
  `Ontology-SemanticQuery` 的模糊检索经 `_candidate_results` 对 13 个候选类型各发一次
  `SELECT FROM <Type> LIMIT 2000`（其中就含文档已给出树查询的 `Indicator` / `Dimension`）。
  而 `API/本体元数据查询API-WIP.md` 已给出 `meta/query` 的指标树 / 维度树分页查询
  （`label LIKE` + `sorts` + `pagination`）。后果：单类型超过一次下拉上限（2000 行，
  `list_objects` 上限 5000）的对象**直接查不到**，且与"该对象不存在"不可区分。
- **缺口二（业务属性靠图邻域遍历）**：`Ontology-EntityDescribe` 用
  `expand-ontology-context` + `depth=1` 收集属性，而文档给的是 `BusinessAttribute` 顶点 +
  `LogicalEntity.code EQ` + `LEContainATT` 边的 TABLE 分页查询。后果：属性受图邻域与深度
  上限约束，图邻域为空时属性**全部丢失**。
- **Spec**：`docs/specs/ontology-metadata-query-consumption.md`（含 P2 之后仍不做项与
  外部阻塞清单：指标维度计算/本体实例计算 WIP 文档未完成、`Modifier` 无产品场景、
  X360 模型工具化与前端 `source` 属新批次、live 需真实 Provider Key、跨 Schema 属建模侧）。
- **红测**：`tests/test_ontology_metadata_query_consumption_red.py`（27 条，离线 loopback，
  无凭据、无 LLM、不碰用户数据）。实测 **12 failed / 15 passed**：R1–R12 红；
  G1–G4 与 M1–M11 为绿护栏（权威命中不多发检索、指标关联维度钻取关系、对象徽标形状、
  不可用时不伪造指标、以及全量下拉/EQ 代替 LIKE/LIKE 打错属性/缺 sorts 或 pagination/
  pageSize 越界/只取第 1 页/属性顶点写错/丢实体过滤/丢 LEContainATT 边/丢钻取关系）。
- **实现提示词**：`docs/specs/ontology-metadata-query-consumption-implementation-prompt.md`。
- **回归**：P1 红测 24 条保持全绿；MAL 契约保持 69 passed / 1 pre-existing failure；
  全量 `pytest -q tests` = 1158 passed / 13 failed / 25 skipped / 1036 subtests passed
  （13 = 本批 12 条红测 + 1 条既有矛盾断言）；评测 `smoke` 140/140、`adversarial` 62/62、
  `regression` 570/570（P0 147/147）、`all` 570/570，known gap 0/0 不变。
- 未修改生产实现、未部署、未读取真实凭据、未跑 live。
