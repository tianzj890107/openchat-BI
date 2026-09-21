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

### 2026-09-21 · 本体元数据查询消费：指标树/维度树/业务属性走文档分页查询（P2 批，已完成）

P1（对象确权 + 本体库详情）落地后，"按名字取元数据"仍然是本地全量下拉、业务属性仍靠
图邻域遍历；本轮把这两条接进文档给出的分页树查询，并修掉了可观测的能力上限。

- **缺口一（元数据检索没有分页能力）**：`MetricCalculation` 在权威确认不可用时不走树查询，
  而是 `_search_type` → `list_objects` → `SELECT FROM Indicator LIMIT 2000`；
  `Ontology-SemanticQuery` 的模糊检索经 `_candidate_results` 对 13 个候选类型各发一次
  `SELECT FROM <Type> LIMIT 2000`（其中就含文档已给出树查询的 `Indicator` / `Dimension`）。
  后果：单类型超过一次下拉上限（2000 行，`list_objects` 上限 5000）的对象**直接查不到**，
  且与"该对象不存在"不可区分。
- **缺口二（业务属性靠图邻域遍历）**：`Ontology-EntityDescribe` 用
  `expand-ontology-context` + `depth=1` 收集属性，而文档给的是 `BusinessAttribute` 顶点 +
  `LogicalEntity.code EQ` + `LEContainATT` 边的 TABLE 分页查询。后果：属性受图邻域与深度
  上限约束，图邻域为空时属性**全部丢失**。

- **实现**（`bi_agent/tools/remote_ontology_tools.py`）：
  - 新增分页树查询层 `_tree_name_search` / `_tree_attribute_search`：`POST /api/v1/analysis/meta/query`，
    `analysisConfig.vertex` + `filters`（`label LIKE %关键词%` / `LEContainATT` 边）+ `sorts` +
    `pagination`（`pageSize=200`，落在文档 1..500 内）；第 1 页返回行数等于 `pageSize` 且尚未
    命中时继续请求下一页，直到命中或空页，翻页上限 20 页、命中即停。
  - `MetricCalculation` 的降级检索改走**指标树**；`_candidate_results` 的 `Indicator` /
    `Dimension` 分支改走**指标树 / 维度树**，其余 11 个候选类型仍走 `list_objects`。
  - `Ontology-EntityDescribe` 的业务属性改走 **`BusinessAttribute` + `LEContainATT`** 查询；
    关系仍由既有 `find_related` 负责，两者不得互相顶替。
  - 树查询失败（`OntologyApiError`）时回退到既有全量下拉 / 图邻域，并**追加**如实说明
    （`（元数据树查询不可用，已回退到本地全量检索）` / `（业务属性查询不可用，已回退到图邻域）`），
    不把传输错误抛给模型；全部路径不可用时输出非空、不伪造码值。
- **文档**：`API/系统接口调用与代码统计.md` §四补上指标树 / 维度树 / 业务属性三条分页查询
  的调用点与请求要点。
- **测试**：`tests/test_ontology_metadata_query_consumption_red.py` 由 **12 failed / 15 passed**
  变为 **27 passed**（R1–R12 全部转绿；G1–G4 与 M1–M11 绿护栏保持）。
- **回归**：P1 红测 24 条保持全绿；MAL 契约保持 69 passed / 1 pre-existing failure；
  全量 `pytest -q tests` = **1170 passed / 1 failed / 25 skipped / 1036 subtests passed**
  （1 failed 是 HEAD 就存在的 MAL 契约自相矛盾断言，未修、未恶化）；评测 `smoke` 140/140、
  `adversarial` 62/62、`recorded-provider` 122/122、`regression` 570/570（P0 147/147）、
  `all` 570/570，known gap 0/0 不变。
- **未确认项（留给上游，Spec §4）**：各生产库是否都已支持 `Indicator` / `Dimension` 顶点 +
  `LIKE` 过滤；`LEContainATT` 边方向（`LogicalEntity → BusinessAttribute`）是否所有库一致；
  服务端 `pageSize` 的真实上限（文档示例是 10，实现取 200，如被拒则按 §4.3 降级并改小）。
- 未部署、未创建 MR/tag/Release、未改动版本号、未读取真实凭据、未跑 live。

### 2026-09-21 · 修正本体 MAL 契约测试里的自相矛盾断言（测试侧，无生产代码改动）

全量验收时唯一残留的红是 `tests/test_ontology_mal_contract_red.py` 里的
`test_list_repositories_uses_the_documented_context_endpoint`：同一文件 `:336` 要求目录列表
带上 `X-Ontology-Repository-Id`，而 `:344`、`:933` 与生产实现
（`bi_agent/ontology/remote.py:542,544` → `include_repository_header: False`）都要求**不带**。
该矛盾在 P1 之前就已存在，属测试侧写错，不是产品缺陷。

- 修正：`:336` 改为断言该请求头**不出现**（与另外两条同契约用例一致），并补一行英文注释
  说明"目录列表是跨库的，仓库头只属于单库请求（详情/数据查询）"；未改动用例名、数量与其他断言。
- 验证：`tests/test_ontology_mal_contract_red.py` 由 69 passed / 1 failed 变为 **70 passed**；
  全量 `pytest -q tests` **1171 passed / 0 failed / 25 skipped / 1036 subtests passed**（首次全绿）；
  评测 `all` 570/570（P0 147/147）、known gap 0/0 不变。

### 2026-09-21 · 匿名读取面收敛（线上验收批次 1）：Spec + 红测 + 生产实现

PDT / demo2 只读验收暴露的问题划分成三批后，本批完成**批次 1**的契约与实现：让
`GET /api/sources`、`GET /api/system-prompt`、会话系统提示、`GET /healthz` 不再把内网物理
标识（host:port、连接串、账号）、机器主机名和绝对工作目录交给匿名调用方。批次 2 为工具链
重复调用与耗时（demo2 一次提问 16 次调用 / 80.5s）；批次 3 为发布上线与线上复验（两环境仍
停在 0.1.7，仓库 0.1.9 之后的 P1/P3 修复尚未上线）——**本批不部署**。

- 复现结论（走真实生产入口，不是 evaluator/fixture 造成的假象）：
  - `GET /api/sources` 的 `doris` 块原样返回连接真值：内网 host:port、
    `jdbc:mysql://172.16.6.163:9030/…`、数据库账号（线上为 `admin`）。口令为空，
    因此没有凭据泄露，但匿名调用方拿到了内网 host:port + 账号 + 库名。
  - 会话系统提示的 `# Environment` 块含 `- Working directory: <绝对路径>`（取自进程 cwd，
    容器内即 `/app`），而 `GET /api/system-prompt` 未做收敛就回吐整段提示，模型因此把 `/app`
    抄给用户；同一段提示也发给模型。
  - 本轮新确认：`GET /healthz` 回吐机器主机名（`"host": socket.gethostname()`），是同类
    匿名可读的内网指纹；`port` 字段另有既有契约（必须反映实际监听端口），本批不动。
- 契约与红测（`5eaa678` 先落）：新增 `docs/specs/anonymous-read-surface-hardening.md`
  与 `docs/specs/anonymous-read-surface-hardening-implementation-prompt.md`；新增
  `tests/test_anonymous_read_surface_red.py`（25 条，离线 `TestClient(app)` + 伪造 STATE，
  不读凭据、不跑 live、**不调用任何删除/重置接口**），交付时实测 11 红 / 14 绿。
- 生产实现（本批完成）：
  - `bi_agent/web/app.py`：新增 `SOURCES_REDACTED_PLACEHOLDER` 与
    `_redacted_source_field` / `_unredact_source_field`。`GET /api/sources` 的
    `jdbc_url` / `api_url` / `username` 改为返回占位符（未配置返回空串），并新增
    `jdbc_configured` / `api_url_configured` / `username_configured` 三个布尔标志；
    `password` 仍为 `""`，`driver` / `database` / `value` / `active` 等逻辑标识不变。
    `PUT /api/sources` 在**任何校验之前**把占位符归一化为"未提供"，因此设置页原样回填保存
    无副作用、不误清空、不报 400。`GET /healthz` 删除 `host` 字段（不再回吐主机名），
    `port` 与未就绪 503 语义不变。
  - `open_claude/prompt.py`：`# Environment` 块收敛为只剩 `- Date:`，删掉
    `Working directory:` / `Platform:` / `OS:` / `Git repo:` / `Shell:` 行；其余段落与工具
    清单不变，`WebSession.cwd` 与工具执行 cwd 仍是真实工作目录。
  - 额外发现并一并收口（同族匿名读取面）：`PUT /api/sources` 的**写响应**此前会回显真实
    `doris_jdbc_url`，即匿名空 `PUT {}` 就能拿回 `GET` 刚收敛掉的内网连接串 —— 现改为返回
    同一占位符（前端只消费 `changed` 与逻辑标识，不受影响）。
- 验收：`tests/test_anonymous_read_surface_red.py` **25 passed**（实现前 11 红）；
  `test_container_port_contract.py` + `test_application_base_path.py` + `test_concurrency.py`
  **83 passed / 17 subtests passed**；`test_regressions.py` **219 passed / 12 subtests
  passed**；全量 `pytest -q tests` **1196 passed / 0 failed / 25 skipped / 1039 subtests
  passed**。评测 `smoke` 140/140、`adversarial` 62/62、`recorded-provider` 122/122、
  `regression` 570/570（P0 147/147）、`all` 570/570，known gap 0/0 不变。
- 未确认项按 Spec 默认值实现并在 Spec §4 记录（逻辑库名继续可见、占位符文案、`# Environment`
  只留日期、`/healthz` 删除 `host`、远程 `base_url` 保留）。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号、未读取真实凭据、未跑 live。
