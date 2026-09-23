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

### 2026-09-21 · 会话回收站（把「记忆管理」页做成删除会话的回收站）：Spec + 红测 + 生产实现

- 需求：把「记忆管理」按钮点进去的页面做成删除会话的回收站。此前三条"删掉就没了"的路径是：
  (1) 侧边栏「最近」的 `✕` → `DELETE /api/conversations/{cid}` → `ConversationStore.delete()`
  直接 `unlink`（硬删除、无二次确认、无撤销）；(2) 活跃会话超过 `MAX_CONVERSATIONS = 100` 时
  `_prune()` 自动物理删除最旧的；(3) 报表侧另有独立删除入口（本批不动）。本批把 (1)(2) 改为
  **先进回收站、保留期内可恢复**，并把回收站放进已有页面。
- 生产复现证据（临时目录，**未触碰任何真实用户会话**）：`GET /api/conversations/trash` → `405`
  （路径被 `DELETE /api/conversations/{cid}` 参数化路由占用）；`DELETE /api/conversations/trash?confirm=1`
  → `200 {"ok": false}`（被同一条参数化路由吃掉，是路由顺序陷阱）；`POST …/trash/{cid}/restore`
  → `404`；删除后快照文件直接消失、`trash/` 目录不存在；连续 `save` 102 条后活跃仅剩 100 条，
  被裁掉的 2 条物理消失且无法恢复。
- 生产实现（本轮落地）：
  - `bi_agent/web/conversations.py`：新增回收站分层——`delete()` 改为**软删除**（`os.replace`
    原子移入 `<root>/trash/<cid>.json`、写 `deleted_at`、从 `history_index.json` 移除；非法 id 与
    未知 id 仍返回 `False`、重复删除幂等返回 `True`）；新增 `trash_listing()` / `restore()` /
    `purge()` / `purge_all()` / `purge_expired()`；`_prune()` 的裁剪对象改为进回收站，
    并按 `(updated_at, 文件 mtime, id)` 排序（`updated_at` 只有秒级精度，同秒批量保存原本会
    退化成按随机 id 排序，导致"被裁掉的未必是最旧的"）；保留期 `CONVERSATION_TRASH_RETENTION_DAYS`
    默认 **30 天**（**严格小于**才清理、正好到期当天保留、`≤0` 表示永不自动清理、解析失败取默认）、
    上限 `MAX_TRASH = 500`（超出按最旧的先永久删除），store 打开时与列表请求时都会维护；
    恢复保持 `updated_at`、移除 `deleted_at`、同 id 冲突返回 `already_active` 且不覆盖不追加。
  - `bi_agent/web/app.py`：新增 4 个回收站接口（`GET /api/conversations/trash`、
    `POST …/trash/{cid}/restore`、`DELETE …/trash/{cid}`、`DELETE …/trash?confirm=1`），
    其中 `DELETE /api/conversations/trash` **声明在** `DELETE /api/conversations/{cid}` **之前**
    （否则 `trash` 被当作会话 id）；清空只接受 `1/true/yes`，其余按未确认返回 `400` 且不删任何条目；
    非法 id → `400`，不在回收站 → `404`（恢复）/ `{"ok": false}`（彻底删除）。
  - `frontend/src/shell.html` + `frontend/src/runtime.js`：「记忆管理」页新增回收站区块
    （计数 / 列表 / 行内「恢复」「彻底删除」/「清空回收站」/ 状态行，保留既有 `#btn-reset` 与
    `#memory-status`），新增 `openMemory()` 并挂到 `data-view="memory"` 导航；「彻底删除」与
    「清空回收站」走 `confirm()` 二次确认；侧边栏 `✕` 文案改为「移入回收站」并同步回收站计数；
    已重新执行 `npm run build` 并提交 `bi_agent/web/static/vendor/antd/workbench.js`。
- 安全边界（沿用批次 1）：回收站列表**只回元数据白名单**
  （`id`/`mode`/`title`/`first_user_question`/`created_at`/`updated_at`/`deleted_at`/`turn_count`/
  `message_count`/`expires_at`/`days_left`），不回 `messages`/`chat_html`/`source_config`/
  `recovery_state` 等正文与配置；软删除沿用 `sanitize_source_config`，凭据不落盘。回收站接口仍
  匿名（真正的鉴权属独立批次，Spec 已如实记录）。
- 红测实测：**24 passed**（实现前 14 红 / 10 绿；pytest 汇总行因 R9 的 3 个子断言分别计票显示为
  `15 failed, 11 passed`）。护栏 G13–G18 与 M1–M4 Mutation Guard 全部保持绿。
- 红测的一处**断言代理修正（必须知悉）**：R8 原先断言 `rows[0]["title"] == "新快照"`，但
  `save()` **从不可信客户端传入的 `title`**（该契约由既有绿灯用例
  `tests/test_regressions.py::test_title_algorithm_skips_internal_messages_and_index_version`
  锁定：`title="错误标题"` 会被首问覆盖），所以那个期望值在任何实现下都不可达。已把该行改为
  断言同 ID 活跃记录的 `first_user_question == "新的问题"`（同样的"活跃记录不得被回收站旧快照
  覆盖"意图），并**新增** `already_active` 必须为真的断言（§2.3 第 3 条）。断言强度只增不减，
  其余 23 条红测一字未动；生产实现没有为此放宽标题清洗规则。
- 回归：全量 `pytest -q tests` **1224 passed / 8 failed / 25 skipped / 1042 subtests passed**，
  8 条 failed 全部来自并行新增的另一批红测 `tests/test_pdt_pg_lake_flow_red.py`，本批文件之外
  **0 failed**；`test_regressions.py` + `test_concurrency.py` +
  `test_environment_scoped_ontology_and_unused_session.py` + `test_container_port_contract.py` +
  `test_application_base_path.py` 共 **282 passed / 1 skipped / 30 subtests passed**。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号、未读取真实凭据、未跑 live、
  未对真实用户会话执行删除或恢复（全部验证都在 `TemporaryDirectory()` 内）。

### 2026-09-22 · PDT 本体服务数据湖切换 PG 引擎：连接影响分析记录（本轮只记录，未改代码）

- 背景：pdt-dev 本体服务的数据湖由 Doris 切换为 PostgreSQL，钱江本体库（id 12）进入调试。
  本轮按要求**只做只读实测与记录**，不修改任何生产代码、配置、部署文档与前端，不创建红测。
- 实测结论（2026-09-22，只读）：数据湖为 **PostgreSQL 17.7**；`current_database()=ontology`、
  `current_schema()=public`；**一个 PG 库承载多个本体库，每个本体库对应一个 schema**
  （`ontology_qianjiang` / `ontology_wtttest` / …），本体库 schema 内是视图，业务数据在
  `po` / `ods` / `item` / `mit_base` / `bdm_customer`。
- 目录变化：pdt-dev 目录 `total=4`（12 钱江本体库-勿动 / 8 导入工具自测 / 6 测试导入 /
  5 开发本体库-PG），字段只返回 `currentDatabase`；**旧的 `ONTOLOGY_REPOSITORY_ID=3` 已不存在**，
  继续用 pdt-dev 重启会在启动校验处直接 `RuntimeError: 远程本体库 3 不在可用目录中`。
- 影响：连接方式（HTTP 网关、双请求体、双响应形态、`dorisDatabase`/`currentDatabase` 目录字段兼容）
  不需要改；直接失效项是 `ListTables`（依赖 `information_schema.tables.table_rows`）与
  `DescribeTable`（依赖 `information_schema.columns.column_key`）必然 500、FactQuery 提示词仍在
  教 MySQL 方言（反引号 / `LIMIT a,b` / `IFNULL`）、直连分支只支持 `jdbc:mysql://` + `pymysql`；
  另有语义变化：表/视图名全部小写、必须始终 schema 限定、视图无法用 `pg_class.reltuples` 估行。
  网关只放行 `SELECT`/`MATCH`，而本地 `_ALLOWED_LEAD` 放行 `WITH`/`EXPLAIN`/`PRAGMA`，会出现
  "本地能过、线上 400"。
- 钱江现状：`ontology_qianjiang` schema **0 表 0 视图**，对 repo 12 的 `meta/query` 返回 500，
  即数据与元数据都未落地，语义检索 / 元数据 / 指标 / FactQuery 全部无数据可查。
- 交付物：`docs/specs/pdt-data-lake-pg-migration-impact.md`（实测证据 + 逐项影响 +
  P0/P1/P2 待改项登记 + 未决风险 + 可复现的只读探针命令）。本轮只登记，不改代码。
- 未确认项：数据面无 repository 隔离（带 repo 12 仍可读其他 schema 的表）、钱江元数据库 500 的
  根因、旧 `/agent/doris/query` 出口与 `API/本体MAL层API.md` 的去留。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号、未读取真实凭据、未改生产代码、
  未跑 live；实测全程只读（目录 `GET` + 只读 `SELECT`）。

### 2026-09-23 · PDT 数据湖切 PG 后：端到端流程走查 + Spec、红测与生产修复

- 要求：按"用户可以执行的方式"把「打开数据源设置 → 选钱江 → 提问 → 语义检索 → 指标查询 →
  回退手写 SQL → 列表/结构 → 出图」整条链路用**生产代码**实测一遍，找出流程与逻辑问题，
  写成 Spec + 红测，并把红测修绿。
- 走查方式（全程只读）：走 `GET/PUT /api/sources`、`build_cognitive_policy_decision`、
  `build_source_executors` 装配出的工具执行器、`configure()` 启动校验；对 PDT 只做目录 `GET`
  与只读 `SELECT`，未写入、未删除、未重置、未读取真实凭据、未部署、未重启服务。当天
  `pdt-dev.eimos.com` 在本机解析失败（NXDOMAIN），改用返回相同数据的内部地址
  `172.16.5.181:30834`（同一后端）。
- 结论：链路上半段（设置页、本体库/数据库原子切换、策略路由、目录归一化）正常；问题集中在
  "最后一段"——数据面与元数据面已在 PG 引擎上，而 Agent 侧仍按 Doris/MySQL 说话，且**传输
  故障被写成业务否定**（"本体库里没有这个对象"），网关错误正文又被丢弃，用户既拿不到数据也
  拿不到可判断的原因。
- 登记问题 F1–F8（P0 三条 / P1 三条 / 环境两条）：
  - F1 元数据 SQL 仍是 MySQL 方言——`ListTables` 发 `information_schema.tables.table_rows`、
    `DescribeTable` 发 `information_schema.columns.column_key`，PG 网关上必然 500，自助取数
    环节被整体掐断；
  - F2 假否定——`remote_ontology_tools.py` 用 `except OntologyApiError: continue` 静默吞掉逐类型
    检索失败，上层在结果为空时直接断言 `no remote matches / no remote match / no remote anchor`，
    且不带降级说明；
  - F3 网关错误正文被丢弃——`sql_tools.py` 只留 `HTTP Error 500: Server Error`，PG 的真实报错
    （如 `relation "x" does not exist`）到不了模型与用户；
  - F4 手写 SQL 的工具描述仍在教 MySQL 方言（反引号 / `LIMIT a,b` / `IFNULL`）；
  - F5 本地 `_ALLOWED_LEAD` 放行 `WITH|PRAGMA|EXPLAIN`，网关只接受 `SELECT|MATCH`，出现
    "本地校验通过、线上必失败"；
  - F6 直连分支只认 `jdbc:mysql://` + `pymysql`，PG 直连不可用（当前主链路走 HTTP 网关，故非 P0）；
  - F7 PDT 本体库 ID 由 3 改为 12，旧值会 fail-fast（`RuntimeError: 远程本体库 3 不在可用目录中`）；
  - F8 `ontology_qianjiang` 当前 0 表 0 视图、repo 12 的 `meta/query` 500，即 F1/F2 修好也暂无数据可查。
- 交付物一：`docs/specs/pdt-pg-lake-end-to-end-flow.md`——13 步逐环节实录（每步标明生产入口、
  实测结果与真实产出）、F1–F8、目标契约 R1–R7、守卫 G1/G2/G2b、范围与非目标、验收、风险与
  回滚、残留观察（数据面未按 repository 隔离、旧 `/agent/doris/query` 命名与文档不一致等）。
- 交付物二：`tests/test_pdt_pg_lake_flow_red.py`——自带 loopback 假 PG 网关（对 MySQL-only 构造
  回真实网关的 `code 500 系统繁忙`），12 条用例全部跑**生产代码**：R1/R2 方言、R3–R5 假否定、
  R6a/R6b 错误正文、R7/R7 续 工具说明、G1 目录守卫、G2/G2b 正常路径守卫。
- 生产修复（只动 Spec §4 范围内的两个文件，未改网关、路由、SOP、评测集与前端）：
  - `bi_agent/tools/sql_tools.py`——
    - `ListTables` 不再选 `information_schema.tables.table_rows`，改为只取 `table_name`：PG 的
      `information_schema.tables` 没有该列，行数估算直接省略，列表只回 `database.table` 名；
    - `DescribeTable` 不再选 `information_schema.columns.column_key`，改为
      `column_name, data_type, is_nullable`，并去掉 `[PK]` 标记：PG 判定主键要 join
      `table_constraints` / `key_column_usage`，宁可少报也不误报；两处工具说明同步去掉
      "行数/主键"承诺；
    - `_doris_query` 的 HTTP 分支新增 `HTTPError` 捕获：读取非 2xx 响应正文并用新增的
      `_gateway_error_message` 取 `msg`（非 JSON 时回退原始正文），把真实 PG 报错
      （`relation "..." does not exist`）与网关校验文案（`仅允许以 SELECT 或 MATCH 开头…`）
      带进工具输出，不再只剩 `HTTP Error 500: Server Error`；2xx + `success:false` 的既有失败
      路径与 `DorisApiError` 语义不变（`test_regressions` 的既有断言保持通过）；
    - `SQL_RUN_SCHEMA` 描述改为声明实际引擎为 PostgreSQL（PG）方言，去掉 MySQL/ANSI 类表述。
  - `bi_agent/tools/remote_ontology_tools.py`——`_candidate_results` 与
    `_graph_anchor_candidates` 记录每个类型的探针失败，**全部探针失败且没有任何结果**时向上抛
    `OntologyApiError`，由既有 `except` 分支输出 `… remote error: …`；不再把"后端 500"写成
    "本体库里没有"。`_candidate_results` 内层 tree→local 回退失败也计入探针失败；权威确认层失败
    仍保留既有的"降级到本地候选 + 降级说明"，"后端正常但确实没有该对象"仍回业务否定。
- 红测实测：以本 Spec 定稿时的生产代码（`d67a723`）用 `git worktree` 独立检出后运行为
  **8 failed / 4 passed**（红：R1、R2、R3、R4、R5、R6a、R6b、R7；绿：G1、G2、G2b 与 R7 的元数据条）。
- 实现后实测：`tests/test_pdt_pg_lake_flow_red.py` **12 passed**；全量 `pytest -q tests`
  **1232 passed / 0 failed / 25 skipped / 1042 subtests passed**（改动前基线 1224 passed /
  8 failed，8 条即本红测）；评测 smoke 140/140、adversarial 62/62、recorded-provider 122/122、
  regression 570/570（P0 147/147）、all 570/570，known_gap 0/0、known_gap_ratchet PASS。
- 非目标（保持登记，本轮不做）：本地 `_ALLOWED_LEAD` 与网关白名单的差异（F5）、直连 JDBC 分支
  仍只认 MySQL（F6）、PDT 本体库 ID 与 `ontology_qianjiang` 暂无数据（F7/F8，属环境/本体侧）、
  遗留 `Doris*` 命名清理（保留兼容，只在 R7 收敛模型可见文案）。
- 未部署、未重启服务、未创建 MR/tag/Release、未改动版本号、未跑 live、未读取真实凭据、
  未对真实会话或用户数据执行任何删除/恢复，全部验证都在 loopback 假网关内。
- 2026-09-23 修订：Spec §5 的验收口径由"当前 8 failed / 4 passed"改为"定稿时
  8 failed / 4 passed"，并注明其后由 `689a152` 把 R1–R7 转绿（现为 12 passed），
  避免实现完成后回读 Spec 时把历史红态误当成当前状态。
