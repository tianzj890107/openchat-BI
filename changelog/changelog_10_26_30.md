# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更


### 2026-10-30 · 修正本体库编号与环境模板

- pdt-dev 当前目录已不存在本体库 `3`；ywln 目标改为 `14`（亿纬锂能开发本体库 /
  `ywln` / `ontology_ywln`），V2 为 `16`，demo2 仍为 `1`（ECore / `ontology_ecore`）。
- 同步修正 `.env.example`、`DEPLOYMENT.md` 和环境作用域说明，写清旧值会导致
  `configure()` 启动 fail-fast 与 Pod `CrashLoopBackOff`。为兼容尚未更新平台变量的
  pdt-dev 部署，增加窄口径 `3 → 14` 回退：只有目录中的 `14` 同时匹配命名空间 `ywln`
  和 Doris 库 `ontology_ywln` 时才启用并输出启动告警；`/api/sources` 显示实际编号；
  不匹配时仍保持 fail-fast，不自动选择其它业务库。平台变量仍建议改为 `14`。
- 同步修正 demo2 真实环境测试中的预期编号，并补充兼容回退的正向与数据库不匹配测试。
  涉及文件：`bi_agent/web/app.py`、`.env.example`、`DEPLOYMENT.md`、
  `docs/specs/environment-scoped-ontology-and-unused-session.md`、
  `tests/test_environment_scoped_ontology_and_unused_session.py`、
  `tests/test_pdt_pg_lake_improvements_red.py`。
- 验证：相关配置/回归测试 36 项通过（另 5 项按环境开关跳过）；用真实 pdt-dev 目录执行
  回退解析，选中 `14` 且对应 `亿纬锂能开发本体库 / ywln / ontology_ywln`，
  meta/knowledge 库也均存在；demo2 返回 `1`（ECore）；`git diff --check` 通过。

### 2026-10-28 · URL prompt 自动发起智能分析


### 2026-10-27（2026-10-28 验收修订）· Process360 五场景本体与受控分析：catalog、只读取数、候选草稿与复验计划

- 用户可见变化：分析 Agent 新增 Process360 闭环能力，覆盖 SC01 发货超期、SC02 红区报价、
  SC03 战略客户突破、SC04 中标未签、SC05 计划外发货偏差。问题先经 P01-P18/SC01-SC05
  确定性路由，再按用户目标选择阶段与停止点：问数在 S03 结束，分析在 S04 结束，明确要求才生成
  S05 草稿；S06 只接 Fuxi 待办，S07 目前仅复验计划。尚未完成 V1.2 全闭环；每个阶段返回统一 envelope 和
  `ok/partial/blocked/needs_clarification/not_applicable` 状态。
- 语义层：新增 `bi_agent/process360/catalog.py`、`scripts/build_process360_catalog.py` 和
  生成文件 `dataset/process360/ywln-v3.1/catalog.json`（206 指标、84 业务规则、5 场景、
  7 流程、26 活动、16 Action、8 任务模板、8 方案、14 证据模板、5 复验、18 SOP）。
  中文工作表映射为稳定英文 key；场景 bundle 只纳入本场景问题/方案/任务，修复了
  SC01 误带 SC05 `SL08` 的串场景问题；原始 `.xlsx/.docx` 不入仓，仅记录来源 SHA。
- 取数层：新增 `bi_agent/process360/db.py`/`queries.py`，只允许固定参数化 SELECT/CTE，
  read-only transaction + statement timeout；调用方不能传 SQL/DSN。SC01 当前快照返回
  13.26 亿元 / 3.33 GWh 超期未发（2026-10-27 实测），SC03 返回 12 户待突破战略客户，
  SC04 返回 39 个中标未签项目 / 11.45 亿元 / 平均等待 124 天；SC02 红区单数因缺价格区间
  映射 blocked，SC05 因同一订单行/产品/日期存在多计划版本而 blocked，均不补 0。
- 分析与执行：新增 `analysis.py`/`plans.py`/`execute.py`/`verify.py`/`service.py`；候选原因
  必须带证据模板且不得表述为已确认根因；任务草稿不含手机号，`canvasActions` 可直接作为
  `CanvasGenerate` 的 actions；S06 唯一出口为 Fuxi 待办（来源 `boulderai-anaylize-todo`），
  不调用 X360、不发送 IM、不伪造业务写操作；S07 缺冻结基准或批准 RF 目标时 `canClose=false`。
- 接入层：MCP 新增 `Process360Route`/`Process360Search`/`Process360Context`/`Process360Query`/
  `Process360Analyze`/`Process360Draft`/`Process360Verify` 七个只读工具；
  `TaskOrderCreate` 仍是唯一写工具。`CanvasGenerate` 的 actions 增加
  `source/scenario/task_template/category/metadata` 透传，供 Fuxi 宿主点击时创建待办。
  `ontology-analytics-skill/SKILL.md` 增加 Process360 场景闭环章节和 HTML actions 契约。
- 配置与文档：`pyproject.toml` 的 `web` extras 和 `open_claude/requirements.txt`
  增加 `psycopg[binary]>=3.1`；`.env.example` 增加 `PROCESS360_PG_*` 只读配置及
  `PROCESS360_CATALOG_PATH` 占位；README 增加 Process360 入口说明；新增
  `docs/specs/process360-closed-loop.md`，记录分层、五场景已实现/缺口、状态契约、
  执行边界和数据库/catalog 边界。
- 验证：`pytest -q tests/test_process360_catalog.py tests/test_process360_engine.py`
  17 passed；真实库只读校验五场景 SQL 均可执行（SC01/SC03/SC04 有数，SC02/SC05 按缺口
  blocked/partial）；`tests/test_fuxi_todo_actions.py`、`tests/test_mcp_endpoint_red.py`
  回归通过。未部署、未创建 MR/tag/Release；历史会话与用户数据未改动。

- 2026-10-28 验收修订：用指定 V3.1 Excel/V1.2 Word 在临时目录重建，catalog 除生成时间外完全一致；
  已逐项登记未实现的多目标计划、趋势/转化/排名/进度/预测、证据验证、S08 预算与恢复、问题持久化、
  批准目标和实际效果复验、用户权限及 Fuxi 端到端联调，不能以 18 类路由宣称完整实现。
- 范围与一致性：严格校验 Scope/MCP 参数，已支持维度全部落入汇总/明细 SQL；未映射维度先阻断；
  SC03 改全量聚合、所有明细披露截断，同场景共享只读 REPEATABLE READ 事务；当前存量不伪装历史，
  显式当前快照保留原请求，SC05 历史对账缺快照直接阻断。
- 指标与分析：保留未知金额/电量，移除价格单位默认 1 并安全处理非法值；SC05 先聚合实际发货，再按
  明确无计划或已对齐计划计算超发量、按数量比例分摊免税金额，未知分类不发布正式指标；blocked 数据
  不触发风险，不生成可下发草稿；SC01/SC04 未完成业务映射验收时保持 partial。
- 草稿与执行：校验场景/版本/方案归属，不借无关模板；补齐 P07/P13/P14 与设计例句路由并明确未实现
  SOP 停止点；草稿、MCP 下发与错误回执防手机号泄露，收件人迭代器只消费一次，有损幂等 ID 加摘要，
  空 Fuxi 回执不报成功；本地 RF 示例不作为已批准目标，复验顶层传播取数失败，始终不自动关闭。
- 主要文件：`bi_agent/process360/`、`bi_agent/integrations/fuxi_todo.py`、`bi_agent/web/mcp_endpoint.py`、
  `ontology-analytics-skill/SKILL.md`、`tests/test_process360_acceptance_red.py`、
  `tests/test_process360_sql_contract.py`、`tests/test_process360_engine.py`；详细优化 23 项与未完成 16 项见
  `docs/specs/process360-acceptance-2026-10-28.md`，实现 spec 同步修订。原始输入、凭据和业务输出不入仓。
- 最终验证（2026-10-28）：新增 71 项验收回归与 9 项显式 PostgreSQL 只读 SQL 合约用例；组合回归
  142 passed。真实库五场景、9 组维度过滤、明细上限不影响指标与 SC05 阻断传递全部通过；catalog
  引用校验、F 类静态检查、`git diff --check` 通过。未部署、未发送真实任务、未修改用户历史数据。

### 2026-10-28 · Process360 V1.2 第二批补齐：可信草稿、直接发待办、权限与高级 SOP

- 用户可见变化：Process360 建议卡现在可以“点击即发”Fuxi 待办。卡片只携带
  `draftId/draftHash/runId/actionId/scenario/approvalStatus/expiresAt/dispatchTool`；
  Fuxi 宿主补 `principal` 和当前用户/责任人手机号后调用 `TaskOrderCreate`，服务端从草稿
  回读标题、正文和场景，不采用调用方改写。待审批卡片显示“待审批”并禁用，过期草稿点击
  时要求重新生成。HTML 和行动条目不含手机号、连接串或凭据。
- 执行与幂等：新增 `bi_agent/process360/store.py`，持久化 runs/drafts/actions/
  action_consumptions/executions/receipts/plans/exploration_calls/evidence/approvals；
  单个建议按钮一次性消费，网络失败可用同一 `idempotency_key` 和 `retry=true` 重试，
  成功回执重放不重复创建。Fuxi 只使用 `POST /source/todo-batches` 和
  `POST /source/todo-status-events`，字段名严格按 `API/risk-todo-source-api.md`，
  没有进度查询接口；P14 只能读取本服务执行记录和 Fuxi 推送回执。
- 权限与证据：新增 `identity.py`，强制宿主注入 tenant/user，权限范围与查询筛选取交集，
  交集为空拒绝业务取数；新增 `evidence.py`，来源、哈希、对象、期间、规则、必需内容和
  反证分别校验，哈希正确不等于根因已验证；新增 `closure.py`，只使用冻结 baseline、
  批准目标和交付证据，样例数字不生效，SC05 无批准关闭公式时 blocked。
- 高级 SOP：新增 `advanced.py` 与对应 MCP 工具 `Process360Compare`（P04）、
  `Process360Structure`（P05）、`Process360ProcessFlow`（P07）、`Process360Progress`
  （P14）、`Process360Forecast`（P17）、`Process360Solutions`（P18）。P07 缺阶段轨迹
  时 blocked，不用节点总数相除；P17 无目标/假设时 blocked，有显式假设才输出“规则推算”；
  P18 局部 blocked 不伪装整体完成。
- 多目标与探索：新增 `planner.py` 和 `Process360Plan`/`Process360Explore`，实现多目标
  DAG、依赖、计划版本、共享预算、探索工具白名单、请求哈希去重和 path_gap 回原步骤。
- 接入层：`Process360Query/Analyze/Draft/Verify` 等业务工具统一要求 `principal`；
  `TaskOrderCreate` 新增 `draft_id/draft_hash/idempotency_key/retry/principal`；
  `CanvasGenerate` 的 actions 透传草稿引用并拒绝手机号。Skill 文档同步更新工具表、
  点击下发、幂等重试、Fuxi 字段和停止条件。
- 涉及文件：`bi_agent/process360/{store,identity,evidence,closure,advanced,planner,service,tools}.py`、
  `bi_agent/web/mcp_endpoint.py`、`ontology-analytics-mcp/canvas_tool.py`、
  `ontology-analytics-skill/SKILL.md`、`ontology-analytics-skill/README.md`、
  `ontology-analytics-skill/references/08-tools-and-sources.md`、
  `docs/specs/process360-closed-loop.md`、`docs/specs/process360-acceptance-2026-10-28.md`
  及新增测试。
- 验证：`pytest -q tests/test_process360_*.py tests/test_fuxi_todo_actions.py
  tests/test_mcp_endpoint_red.py` 为 136 passed / 9 skipped；9 项 PostgreSQL 合约测试
  需显式设置 `PROCESS360_ACCEPTANCE_DSN`。全量 `pytest -q tests` 为 1514 passed / 37 skipped /
  1 failed，唯一失败是 worktree 缺少 `frontend/node_modules/@boulderaitech/ontology-graph/
  src/layout.js` 的环境问题，与本轮 Process360 改动无关。
- 边界：本轮未部署、未发送真实 Fuxi 任务、未创建 MR/tag/Release；业务批准口径、真实
  证据、宿主权限注入、真实点击与回执、主服务对话入口仍需联调。

### 2026-10-28 Process360 身份、全量基准、查询复用与任务令回执加固

- 身份改为服务端解析：MCP 网关为每次 Process360/TaskOrderCreate 调用注入可信
  `principal`（contextvar），工具公共 schema 不再暴露 `principal`，入参携带会被拒绝。
  新增 `grantKind=none|restricted|all`，空授权列表不再等于“不限制”；POC 默认使用
  服务端配置的只读全量身份 `PROCESS360_POC_PRINCIPAL`。
- 全量冻结基准：`build_baseline` 接收服务端独立重取的完整对象集，记录
  `fullObjectCount/frozenObjectCount/complete/objectSetHash`；展示 `limit` 不再污染基准，
  `complete=false` 时 S07 直接 blocked，复验的当期对象集同样取全量。
- 查询复用与紧凑返回：`Process360Query` 返回 `queryId` + `recordsRef` + 最多 5 条样本，
  明细与证据记录不再回传全量；`Analyze/Structure/Verify` 接受 `queryId` 复用同一结果，
  按 tenant/principal/catalogVersion/scenario 隔离；Analyze 的 `metricCatalog` 只保留本轮指标。
- 渲染工具注册修复：`ChartGenerate/ChartGenerateMultiDim/TableGenerate` 注册为不依赖数据源
  的能力，`CanvasGenerate` 在真实源路径下同样进入 source-free 集合；`/api/mcp/health`
  暴露 `missingExecutors`，声明未实现的工具会被记录。
- 任务令下发链路：新增 `POST/GET /api/process360/task-orders`，页面只提交
  `draftId/draftHash/actionId/requestId`，服务端解析身份与接收人映射
  （`PROCESS360_RECIPIENT_MAP`）并回读草稿。统一回执 `process360.dispatch.v1`，
  只有 `status=ok` 且 Fuxi 回执证明 `applied+skipped>0` 才显示成功。
- Canvas 行动卡状态机：六项草稿字段缺失即判定旧版并禁用（“旧版建议，请重新生成任务草稿”）；
  增加 `requestId`、宿主 `fuxi:task-order-result` 回执监听、25 秒超时和“结果待确认”状态，
  `blocked` 不再显示为成功。
- 涉及文件：`bi_agent/process360/{identity,service,closure,store,tools,dispatch}.py`、
  `bi_agent/process360/queries.py`、`bi_agent/web/mcp_endpoint.py`、
  `ontology-analytics-mcp/canvas_tool.py`、`ontology-analytics-skill/SKILL.md`、
  `ontology-analytics-skill/references/08-tools-and-sources.md`、
  `docs/specs/process360-closed-loop.md` 及新增/更新测试。
- 验证：`pytest -q tests/test_process360_*.py tests/test_fuxi_todo_actions.py` 为
  142 passed / 9 skipped；全量 `pytest -q tests` 为 1528 passed / 37 skipped，唯一失败仍是
  worktree 缺少 `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js`。
  用 32444 只读库实测：`limit=5` 的 SC01 查询返回 5 条样本但冻结基准为 2102/2102、
  `complete=true`；`queryId` 复用的 Analyze 约 2.1 秒，返回 5 条样本与 4 条指标定义。
- 边界：未部署、未发送真实 Fuxi 任务；接收人映射与页面下发地址需按环境配置后才可点击下发。

### 2026-10-28 Process360 计划校验、执行轨迹与闸门绑定

- 路由计划：`Process360Route` 落库并返回 `planId`/`revision`，`Query/Analyze` 传 `planId`
  时校验存在性、归属和场景一致；不一致返回 `PLAN_SCENARIO_MISMATCH`。改判走
  `Route(planId, reviseReason)` 生成修订记录，原计划保留，避免无记录绕过路由。
- 执行轨迹：新增 `requests`/`steps` 表与 `bi_agent/process360/audit.py`，每个 Process360
  工具调用（含只问数的 Query）记录工具、状态、入参哈希、耗时、行数与
  `queryId/runId/planId/draftId` 引用；`GET /api/process360/requests/{id}` 可读。
- 闸门绑定：`CanvasGenerate` spec 输出 `canvasId`/`artifactHash`（页面 SHA-256），
  `OutputGateCheck` 校验文件存在与哈希一致，并可用 `runId` 绑定冻结基准；
  缺失/不符/基准不完整均判 reject。
- 未实现（需业务口径）：按指标父子结构自动生成对账数据。父项与子项集合属于场景口径，
  仓库里没有批准定义，继续由 `CLOSURE_FORMULA_MISSING` 显式阻断，不臆造层级。
- 验证：`pytest -q tests` 为 1534 passed / 37 skipped，唯一失败仍是 worktree 缺
  `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js`。
- 边界：未部署、未发送真实 Fuxi 任务、未创建 MR。

### 2026-10-28 Process360 统一请求、查询复用、计划约束、产物与下发收口

- 统一请求上下文：MCP、页面下发和审计共用服务端解析的
  `principalId/tenantId/grantKind/grantScope/authorizationVersion/conversationId/requestId/surface`；
  模型或页面提交身份、租户、下发权限字段会被拒绝。POC 默认只读，下发由
  `PROCESS360_POC_DISPATCH` 单独开启。
- 查询结果改为 v2 契约：`queryId` 绑定来源连接、规范范围、授权版本/指纹、catalog 和查询
  模板版本、有效期、完整性、结果哈希及完整行；Query/Analyze/Draft/Structure/Verify 可复用，
  换范围、撤权、换场景或过期时明确阻断。Process360 查询结果显式返回
  `dataSource=process360-postgres` 和 `sourceConnection`。
- 公共 MCP 的 Process360 业务工具强制 `planId + stepId`，校验步骤工具、前置依赖、场景、
  范围和待澄清项；计划步骤结果与服务端请求轨迹分别落库，一个伏羲会话可包含多个 requestId。
- `OutputGateCheck` 对正式分析报告强制绑定 `canvasId/artifactHash`，缺省
  `deliveryKind=analysis_report`，缺失产物直接 reject；产物按 request/plan/query/run
  append-only 登记，页面变化后必须重过闸门。`Process360Verify` 从服务端 `approvalRef`
  读取批准目标、方向和有效期，模型自填目标不能代替审批。
- 页面与 MCP 下发收口到同一执行服务，幂等键固定为 `tenant:draftId:actionId`，发送前原子
  claim，状态区分 `queued/sending/succeeded/blocked/rejected/unknown`；执行登记失败不会调用
  Fuxi。Canvas 按钮按完整回执显示状态，超时不自动切宿主，支持状态刷新、父窗口来源校验和
  接收人映射版本阻断。
- 驾驶舱整页显式记录并校验 `dataSource/dataIdentity/dataFingerprint`；AP 图表与 AI 卡片
  必须同源同版本才能发布，PG 查询结果和旧 AP 快照不能仅因标题相同就混用；页面与卡片缓存
  key 同步加入数据来源。
- 文档同步更新：`ontology-analytics-skill/SKILL.md`、
  `ontology-analytics-skill/references/{07-output-gates,08-tools-and-sources}.md`、
  `docs/specs/process360-closed-loop.md`、`docs/specs/process360-acceptance-2026-10-28.md`、
  `.env.example`。新增/更新的关键文件还包括
  `bi_agent/process360/{request_context,service,dispatch,store,identity,audit}.py`、
  `bi_agent/web/{mcp_endpoint,app}.py`、`bi_agent/cockpit/{page_cache,publications,router}.py`、
  `ontology-analytics-mcp/canvas_tool.py`。
- 验证：Process360、Fuxi、MCP 与 Cockpit 相关组合测试为 230 passed / 9 skipped（9 项
  PostgreSQL 合约需 `PROCESS360_ACCEPTANCE_DSN`）；全量 `pytest -q tests` 为
  1578 passed / 37 skipped / 1 failed，唯一失败是 worktree 缺少
  `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题；`git diff --check` 通过。
- 边界：未部署、未发送真实 Fuxi 待办、未创建 MR/tag/Release、未升级正式版本；真实业务批准、
  外部证据和 Fuxi 端到端联调仍需业务条件。

### 2026-10-28 Process360 下发兼容入口、回执恢复与来源校验收口

- `TaskOrderCreate` 的权限检查前置到全部发送分支：Process360 草稿、旧版普通行动和重试都必须
  使用服务端解析身份并满足 `canDispatch`，无权限时不创建或调用 Fuxi 客户端。
- Canvas 成功条件收紧为 `status=ok + accepted=true + receipt.ok=true + applied+skipped>0`；
  仅带 `sourceTodoId`、零处理条数或 `receipt.ok=false` 均显示待确认。HTTP 超时覆盖响应体读取；
  页面持久化待确认行动，刷新后自动恢复并短时轮询，`unknown` 可用同一草稿显式安全重试。
- 页面下发接口接受 `retry=true` 并复用原幂等键；状态接口返回 `retryable/retryHint`。
- `queryId` 复用新增当前 `sourceConnection` 校验，切换数据库连接后返回
  `QUERY_SOURCE_CONNECTION_CHANGED`；被阻断的 PostgreSQL 查询仍保留
  `dataSource/sourceConnection/scope`。
- 计划步骤状态区分 `completed/skipped/needs_input/blocked`；`not_applicable` 记为 `skipped`，
  不再放行依赖步骤。
- 验证：Process360、Fuxi、MCP 与 Cockpit 相关组合测试 `240 passed / 9 skipped`，Cockpit
  JavaScript 测试 `21 passed`，Canvas 生成脚本通过 `node --check`，`git diff --check` 通过。
  全量 `pytest -q tests` 为 `1588 passed / 37 skipped / 1 failed`，唯一失败仍是 worktree
  缺少 `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题。
- 边界：未部署、未发送真实 Fuxi 待办、未创建 MR/tag/Release、未升级正式版本。

### 2026-10-28 · 驾驶舱头盔图 AP 字段兼容修复

- 用户可见变化：运营页和穿透页的头盔图不再显示“AP请求失败；未切换到本体、
  数据库或旧快照”，AP 请求全部恢复 200。
- 原因：X360 流程配置把商机获取/报价/订单接收/发货节点改为引用
  `D020/M0023`、`D021/M0031`、`D016/M0033`、`D024/M0036`；当前 AP 分析模型
  未发布这些字段，单独查询也返回 500“系统繁忙”。2026-10-22 参考发布使用
  `D007/M00013` 且其余节点无数据配置，实测查询正常。
- 修复：新增 `bi_agent/cockpit/helmet_compat.py`，在读取头盔配置时把商机获取
  恢复为 `D007/M00013` + 参考状态映射，并移除报价/订单接收/发货三处不可用的
  `helmetConfig`；其他节点、流程和已修正配置原样透传，不新建指标、不补 0、
  不切换数据源。
- 验证：新增兼容与代理链路回归测试；全量 1394 passed、28 skipped。34 线上
  `id=1|2` 三页 AP 请求全部 200，整页快照继续发布。
- 边界：这是 X360 字段发布前的临时兼容映射，上游修正后应删除并复验。

### 2026-10-28 · 驾驶舱AP并发排队替代429

- 用户可见变化：经营看板、运营360和穿透分析不再显示“Cockpit AP查询并发已满，请稍后重试”；
  AP槽位占满时请求在自身超时内排队，正常加载、多标签和多身份同时访问继续返回数据。
- 原因：AP传输层在共享并发信号量被占满时使用非阻塞获取并直接返回429；一个页面会并行发起多条
  AP查询，两个身份或多个标签同时打开即可触发。34旧release日志确认只有 `/api/cockpit/data/query`
  返回过429，`/analyses` 没有。
- 修复：`bi_agent/cockpit/ap_gateway.py` 改为按请求剩余超时等待槽位，等待超时返回504排队超时，
  不静默降级、不切换数据源；默认 `COCKPIT_AP_CONCURRENCY` 由2调整为4；
  `bi_agent/web/static/cockpit/data-client.js` 对429和排队超时504做短暂重试。
- 涉及文件：`bi_agent/cockpit/ap_gateway.py`、`bi_agent/web/static/cockpit/data-client.js`、
  `.env.example`、`tests/test_cockpit_ap_gateway.py`、`tests/cockpit_data_client.test.mjs`、
  `DEPLOYMENT.md`。
- 验证：全量Python测试1395 passed、28 skipped；前端Node测试22项通过；
  34线上24／48／64并发AP查询全部200（最大约1.8秒），新release日志429和5xx均为0；
  `id=1|2` 三个页面共6个路由浏览器验收全部AP 200，无错误文案、无JavaScript异常。
- 部署：后端 `cockpit-main-15d31e0-20261028-0817`（PID 158559，8765），
  静态站 `assetVersion=4da3f092598bd18dde3b`；旧release和旧静态资源保留可回滚。

### 2026-10-28 · Cockpit 历史缓存来源域兼容

- 用户可见变化：升级到带 `dataSource` 来源域的版本后，已有经营看板、运营360和穿透分析
  不再因缓存 key 变化而丢失上次成功卡片或整页快照；旧历史内容在首次打开时继续可回放。
- 修复：新写入仍使用包含数据来源的新 scope；仅在实时 AP 模式且同一身份、页面、筛选范围、
  AP 连接与配置版本一致时，新 scope 未命中后只读回退旧 scope。PostgreSQL、演示和交付快照
  结果不会命中 AP 旧 key，历史 SQLite 不做搬迁、覆盖或重新生成。旧 AP 卡片与最新 AP
  查询重新组成整页时，只有同时保留 `snapshotId=ap-*` 和主服务 AP 会话来源的记录可以复用；
  缺少来源标记或来自 PostgreSQL／演示的历史卡片仍严格阻断。
- 涉及文件：`bi_agent/cockpit/publications.py`、`bi_agent/cockpit/page_cache.py`、
  `bi_agent/cockpit/router.py`、`tests/test_cockpit_publications.py`。
- 验证：Cockpit Python 聚焦测试 31 项通过，前端 Node 测试 22 项通过；全量 Python 为
  1598 passed / 37 skipped / 1 failed，唯一失败仍是 worktree 缺少
  `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题；
  `git diff --check` 通过。
- 部署：后端 release `process360-a23ba77-20261028-160256`（PID 1999223，8765）；
  旧 `process360-eb0b119-20261028-155839` 与 `cockpit-main-15d31e0-20261028-0817`
  完整保留回滚。8765真实重放 `overview/operations/analysis` 的 AP 取数和整页发布均为
  200，历史快照与卡片保持可读；Process360 真实只读查询为 SC01 partial，来源仍为
  172.16.5.181:32444/ywln#ywln_crm。8876静态站与 nginx 不改，18765已关闭，未发送真实
  Fuxi 待办。

### 2026-10-28 · 同步 pdt 最新发布看板

- 用户可见变化：经营看板、运营360和穿透分析改为渲染 `pdt-dev` 看板
  `2109836674373566465`（根配置 2026-10-28 14:07:56）的最新发布配置；经营看板指标从采购口径
  切换为 `YWLN_*` 销售口径，卡片右上新增“查看销售额风险／查看出货风险”入口；运营页新增
  “订单履约率”KPI、五环节分段条（商机获取／报价／投标／订单接收／发货）及对应进度卡。
- 数据规模：13 份模板、142 个组件配置（此前 135 个），其中 AP 103 个、mock 39 个；
  12 个分析插槽锚点全部仍有效，商机模板 `share-bar-79fsomq9` 子组件缺失保持不变并在缺项报告中列明。
- 导入方式：新增 `scripts/import_cockpit_publish.py`，把拉取到的 `dashboard.json` 与
  `templates/*.json` 转换为 `components.json`、`template-registry.json`，并重写
  `source.json` 的发布信息、哈希、类型统计、锚点与适配记录；不再手工拷贝文件。
- 宿主适配：发布配置把 `activateRules` 放在仪表盘根级，导入时回填到
  `tab-container-zm9eyxne`；新规则的 `actions` 数组改写为 ProUI 的 `tab`/`helmet` 结构，
  1 条 `titleText` 表面规则无法表达，记入 `source.json.unsupportedRules`。
- 交互修复：卡片 `headerActions` 触发的切换 Tab／选中头盔节点此前只改 SDK 内部状态，页面
  路由和数据不跟随；`data-client.js` 的 `observeRuntimeFilters` 增加 `onTabChange`／
  `onHelmetSelect` 钩子，`cockpit.js` 据此跳转到目标页面并保留 `id` 与 `node` 参数，
  跳转后按 `node` 恢复头盔图选中节点。
- 涉及文件：`scripts/import_cockpit_publish.py`、`bi_agent/cockpit/runtime.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,data-client.js}`、
  `bi_agent/web/static/cockpit/metadata/iba-demo-1021/{components.json,template-registry.json,source.json,README.md}`、
  `bi_agent/web/static/cockpit/metadata/runtime.json`、`tests/test_cockpit_metadata.py`、
  `tests/cockpit_data_client.test.mjs`。
- 验证：Cockpit Python 聚焦测试 106 项通过（含 `test_cockpit_metadata.py`、
  `test_cockpit_resource_contract.py`），前端 Node 测试 23 项通过；本地隔离浏览器验收
  8 项通过（首屏、AP 失败保留、筛选切换、整页发布、overview/operations 全页）；
  点击“查看销售额风险／查看出货风险”跳转到穿透页并带 `node`，头盔图选中对应节点；无 JavaScript 异常。
- 部署：本轮未部署。旧 release 与 `pdt-release-2109836674373566465` 冻结快照保持不变。

### 2026-10-28 16:47 · Process360 线上下发联调配置与 Skill 包更新

- 更新最新 Skill 分发包，24 文件与源码逐项一致、ZIP 完整性校验通过。
- 按当次明确授权，34 的 8765 主服务开启 POC 下发权限及页面下发；只配置沈康责任人映射，
  不配置张真或全局默认接收人。草稿以 `owner_ref=shenkang` 指定联调接收人，未知责任人阻断。
- 环境文件备份后重启既有 release；未修改 Cockpit 静态站、未覆盖历史数据、未新增发送待办。
  线上健康、状态接口及权限／接收人解析验证通过，完整 HTML 点击链路仍待联调。
- 部署及回退记录见 `DEPLOYMENT.md`；手机号等个人配置未入库。

### 2026-10-28 17:05 · Process360 五场景伏羲 SOP 复跑与任务令下发验证

- 以当前 HEAD 重启本地 MCP，用新会话重跑 SC01–SC05，全部完成 Route → 受控取数 →
  分析/结构 → Canvas → 闸门；五场景执行期间不发送任务令。
- 身份改为服务端注入 `ywln/zhangzhen`；模型注入 principal、无计划业务调用、旧版无草稿
  下发三个绕过入口现场验证均被拒绝。
- SC01/SC03 冻结基准达到完整对象集（2102 / 40）；SC04、SC05 的 TableGenerate 与
  ChartGenerate 直接调用成功。
- 单独验证下发链路：用 SC01 真实运行生成可信草稿，经 `TaskOrderCreate` 向沈康
  `159****7656` 创建 1 条 Fuxi 待办，`applied=1/skipped=0/errors=[]`；MCP 与页面接口
  重放均返回同一 executionId，未产生重复待办。
- 记录仍未关闭的问题：P02 计划步骤不是可执行工具（P12 已改为 Analyze+Draft 可执行步骤）、
  多目标计划碎片化、SC05 否定语义误路由、大结果截断导致 queryId 丢失、4/5 闸门未绑定
  runId、SC05 blocked 查询未落库。
- 完整核对见 `docs/specs/process360-fuxi-sop-execution-rerun-2026-10-28.md`。

### 2026-10-28 17:06 · 34 线上 Process360 接入真实 PostgreSQL

- 用户可见变化：34 线上 MCP 的 Process360 受控取数恢复为真实 PostgreSQL 来源
  `172.16.5.181:32444/ywln#ywln_crm`，不再返回 `DATABASE_UNAVAILABLE`；经营看板等
  Cockpit 页面恢复可访问，但 AP 业务数据接通仍属已知未完成项。
- 部署：新 release `process360-a6239d4-20261028-170622`（提交 `a6239d4`，PID 2321809，
  8765），通过 release 内 `runtime-env.json` 显式注入 PG、Catalog 与 Cockpit 变量；
  旧 release、历史数据目录和共享环境备份均保留。回退方式见 `DEPLOYMENT.md`。
- 验证：健康检查、MCP 健康（32 工具、`missingExecutors=[]`）、Cockpit 配置/引擎/整页发布
  接口均 200；`Process360Query`（SC01）返回 `partial`、来源
  `process360-postgres`、18.3961 亿元 / 4.6066 GWh，并披露 G01/G12/G16；日志无
  Traceback 与 5xx。
- 边界：本轮只补充真实数据库连接与部署，未改变五场景口径，SC02–SC05 业务闭环和效果
  复验仍不能据此判为完成；未创建 MR、tag 或 Release。


### 2026-10-28 17:50 · 行动交付卡与可信草稿闸门

- 用户可见变化：要求改善建议、处置方案、任务草稿或下发的分析，HTML 现在必须包含结构化
  行动卡和“发送任务令”按钮；不再只输出一段文字建议。草稿因证据、权限或责任人不足时，
  页面显示“尚不能生成可下发任务”及具体缺口，不伪造草稿，也不让按钮无声消失。
- Skill：新增交付类型判定（事实／分析／行动）和固定顺序 Analyze → Process360Draft →
  CanvasGenerate → OutputGateCheck；明确生成草稿不等于发送，发送仍等用户点击。更新
  P10/P11/P12 停止点、行动卡字段和闸门说明。
- MCP：Process360Route/Plan 保存 `actionDeliveryRequired` 并为 P10/P11/P12 生成可执行的
  Analyze+Draft 步骤；Process360Draft 返回 `canvasActionBlock`；OutputGateCheck 校验行动卡
  是否存在、草稿是否存在/哈希一致/action 归属一致/runId 属于本轮计划，草稿 blocked 时必须
  有 Draft 尝试记录和明确原因。
- Canvas：actions 块支持空的阻断占位（`items=[]` + `reason/gaps`），输出机器可读
  `canvas-actions` 元数据；有效卡片继续复用原有按钮、审批/过期禁用和统一下发状态机。
- Canvas 状态修正：未携带任何服务端草稿引用的建议卡不再误显示“缺少草稿字段”。严格模式
  （`PROCESS360_CANVAS_DISPATCH_MODE=trusted`）下它们显示“分析建议”且不出现发送按钮；
  当前临时 POC 模式（默认 `all`）下所有有正文的行动卡显示“发送任务令”和“临时直发”，
  点击后由主服务按卡片内容即时创建一次性草稿，再复用身份、手机号检查、幂等和 Fuxi 回执
  链路。部分草稿字段、待审批或过期状态不改写为可信卡；临时模式只负责补建本次草稿。
- 接收人：临时直发由服务端从 `PROCESS360_RECIPIENT_MAP` 选取唯一接收人（可用
  `PROCESS360_CANVAS_RECIPIENT` 指定键），当前环境统一落到沈康；页面和 HTML 不包含
  手机号，也不能提交接收人或身份字段。切回 `trusted` 即恢复严格草稿按钮规则。
- 验证：行动交付、临时直发、接收人和 HTTP 安全边界相关测试 57 项通过；
  Process360/Canvas/MCP 聚焦测试 151 项通过；全量 Python `1620 passed / 37 skipped`，
  仅保留 worktree 缺少前端
  `frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的既有环境失败。
- 部署与线上验证（18:14）：新增 8765 release
  `process360-a5342cd-20261028-180448`（提交 `a5342cd`，PID 2561043），旧 release
  和 PID 2321809 完整保留；先经 18765 同提交预检后切换。健康检查、MCP 健康
  （`missingExecutors=[]`）、Cockpit 配置/引擎/已发布分析均 200；线上生成的 Canvas
  行动卡 `temporaryDispatch=true`，HTML 含“临时直发”“发送任务令”，页面不传手机号。
  真实 SC01 只读查询仍为 `partial`、来源 `process360-postgres`、18.3961 亿元 /
  4.6066 GWh，并披露 G01/G12/G16；8765 日志无 Traceback 与 5xx。8876 未改动。
- Skill：交付包重建为 24 文件并逐项校验，SHA256 为
  `297911caba6a992560b6c0aee66be5bb38a59cf02522a2c65fd2a83247cb3d84`。
- 边界：旧 HTML 不会自动补按钮，需要重新生成；本轮未创建真实 Fuxi 待办，真实点击回执
  和业务效果需在伏羲人工验收；未创建 MR/tag/Release，未升级正式版本。

### 2026-10-28 18:36 · 风险卡与风险下发通道

- 用户可见变化：Process360Draft 现在同时生成“风险卡”和“处置待办卡”。风险卡展示风险标题、
  已观察事实、影响、等级依据、业务范围、证据和责任人，候选原因明确标为“待验证，不是已确认
  根因”；按钮为“推送风险”。处置待办继续显示“发送任务令”，两类卡片可关联但不会互相替代。
- Fuxi 下发：新增 MCP 写工具 `RiskItemCreate`，按 Fuxi 契约发送 `itemType=RISK`；待办仍由
  `TaskOrderCreate` 发送 `itemType=TODO`。两类条目使用不同 `sourceTodoId`
  （风险为 `analytics-risk-*`）和不同幂等键；重复点击只重放原执行，工具与卡片类型不匹配时
  在调用 Fuxi 前阻断。推送风险成功只表示 Fuxi 已接收，不代表风险解除。
- Canvas 与闸门：actions 元数据新增 `itemType`，风险按钮和待办按钮分别显示并复用身份、
  接收人、审批、过期、超时和安全重试状态机。OutputGateCheck 现在接受
  `RISK + RiskItemCreate` 与 `TODO + TaskOrderCreate` 两种可信组合，并拒绝类型错配。
- Skill/文档：更新 `ontology-analytics-skill/SKILL.md`、工具与闸门参考、README 和
  Process360 closed-loop spec，明确风险卡只推送有证据的已观察事实，风险与待办独立幂等。
- 验证：新增风险 Fuxi payload、双类型草稿、独立幂等键、类型错配阻断、Canvas 双按钮和
  交付闸门测试 7 项通过；Process360/Fuxi/Canvas/MCP 聚焦回归 229 项通过、9 项跳过。
- 边界：本轮未部署、未创建真实 Fuxi 风险/待办、未创建 MR/tag/Release、未升级正式版本。

### 2026-10-29 · 智能分析与 360 智能分析拆分为两个 Skill，360 强制走 ywln 链路

- 用户可见变化：`智能分析` 与 `360智能分析` 现在是两个独立技能。
  `ontology-analytics-skill` 只覆盖通用经营/财务分析（18 个通用工具，demo2 本体 + Doris）；
  新增 `process360-analytics-skill` 只覆盖 SC01-SC05，第一步必须调用 `Process360Route`，
  数据只取 `process360-postgres` 的 `ywln_crm`，明确禁止用 `AnalysisRoute`、
  `MetricFactQuery`、`ListBusinessObjects` 或采购域 Doris 兜底。
- 连接级隔离：MCP 的 `tools/call` 不携带技能 ID，服务端改为按连接区分技能与数据源。
  新增 `/api/mcp/general`（通用白名单）和 `/api/mcp/process360`（仅 `Process360*` +
  `CanvasGenerate`/`RiskItemCreate`/`TaskOrderCreate`/`OutputGateCheck`）；
  `ONTOLOGY_MCP_TOOL_PROFILE=general|process360` 作为默认白名单，`/api/mcp` 保持旧行为。
  越权工具返回 `tool_not_allowed`，连接器里看不到入口工具即说明接错连接。
- 服务端强约束：即使走全量 `/api/mcp`，`AnalysisRoute` 对明确的 SC01-SC05 问题返回
  `mode=PROCESS360_REQUIRED`、`next_step=PROCESS360_ROUTE`、
  `required_tools=["Process360Route"]`，不再给出 `QUERY_DORIS`；连接器未暴露
  `Process360Route` 时返回 `next_step=SWITCH_CONNECTOR` 并要求改用 360 连接器。
  弱关键词（例如“本月发货金额”）仍按通用事实查询处理。
- 风险与待办：新增“发风险/推送风险/风险卡/待办卡/风险和待办”等下发语义，路由落 P11 并
  置 `actionDeliveryRequired=true`；计划自动追加 P09 + P11，先 `Process360Draft` 再
  `CanvasGenerate` 行动卡，用户点击后才走 `RiskItemCreate`/`TaskOrderCreate`。
  此前“计划外发货偏差分析…发风险和待办”被识别成 P06、`actionRequired=false`，现已修正。
- 涉及文件：`process360-analytics-skill/`（新增 SKILL.md、README、4 个 references）、
  `ontology-analytics-skill/SKILL.md`、`README.md`、`references/07-output-gates.md`、
  `references/08-tools-and-sources.md`、`bi_agent/process360/router.py`、
  `bi_agent/web/mcp_endpoint.py`、`.env.example`、`DEPLOYMENT.md`、
  `tests/test_process360_skill_split_red.py`。
- 验证：新增 10 项拆分与拦截测试通过；Process360 全量 229 passed / 9 skipped；
  MCP、路由与安全聚焦回归 124 passed / 49 subtests passed。
- 边界：本轮未部署、未在伏羲重新安装技能、未创建真实风险/待办、未创建 MR/tag/Release、
  未升级正式版本；伏羲侧仍需发布 `process360-analytics` 技能并给 360 Agent 绑定
  `process360` 连接器。

## 2026-10-30 Analytics 统一服务整合

- 在同一仓库的 `feature/analytics-unified-service` 分支整合 cockpit、工作台 URL 入口、PDT 本体 fallback、本地 Excel 文档与 Process360 skill 分离。
- 保留通用分析和 Process360 两类 MCP 工具配置；不引入 LangGraph 实验引擎。
- 第一轮定向验证：Python 32 项、URL 入口 Node 5 项通过；未部署、未清理原工作区。

### 2026-10-30 共享执行模块

- 将现有执行循环提取到 `bi_agent.runtime.session.AgentSession`，工作台和 Cockpit main 路线使用同一实现；旧 WebSession 导入保持模块级兼容。
- 纳入 Process360 接收人配置说明和测试示例匿名化；保留原主目录独有资料，管理清单记录文件指纹。
- 新增隔离运行时 spec，明确 MCP 基础工具与未来委托任务入口的边界。

### 2026-10-30 MCP 委托任务接入共享 Runtime

- 新增 `/api/mcp/tasks` 的提交、分页查询和协作取消工具，复用工作台 AgentSession、数据源装配、全局 admission 与 turn 生命周期。
- 有界任务队列、SQLite 状态与事件、私有任务 token、单进程存储所有权及重启中断标记；取消保留结果，不自动重放。
- 后台任务禁用派发和任意 Shell/文件写工具，服务端校验白名单；需要澄清时返回 needs_input，保留既有浏览器会话。
- 基础工具 MCP 与 Cockpit 调度发布保持原接口；未启动、重启或退役任何现有服务。


### 2026-10-29 14:40 · Cockpit 同步 iba-demo 97f4e28 与新版 ProUI

- 用户可见变化：看板 ProUI 运行包与看板/子模板配置同步到 `iba-demo feature/demo_1021`
  `97f4e28`（上一版为 `d01c08a`）。组件数量与类型保持 2 个根组件、13 个模板、145 个组件，
  AI 插槽仍为 12 个；筛选标签由“时间”改为上游的“日期”，其余布局与交互按上游配置渲染。
- 运行包：`vendor/pro-bi-ui.min.js` 更新为上游新 UMD（6,197,235 字节，sha256 `fc21219c…`），
  `index.html` 的缓存参数同步改为 `?v=fc21219c`；上游仍未包含头盔图销毁后 `fitView` 的
  空实例保护，同步后重新补回这一行守卫。`pro-ui.min.css` 与 Vue 运行时未变化。
- 配置同步：`metadata/iba-demo-1021/components.json`、`template-registry.json` 按上游原样更新，
  并重新生成 `metadata/runtime.json`；`activate-rules.json`、`insights.js` 与
  `insight-components/` 上游未变，保留现有的宿主适配（例如任务令按钮的调整）。
- 宿主适配：组合筛选器默认期间继续保留 `YWLN_D044=2025-10`。上游把该默认值清空，若直接跟随会让
  看板默认查询失去期间约束，与页面范围和已发布卡片不一致，因此在同步后重新写回并记录在
  `source.json`、`vendor/resources.json`。
- 主要文件：`bi_agent/web/static/cockpit/vendor/pro-bi-ui.min.js`、`vendor/resources.json`、
  `index.html`、`metadata/iba-demo-1021/{components,template-registry,source}.json`、
  `metadata/runtime.json`、`tests/test_cockpit_metadata.py`、`tests/test_cockpit_resource_contract.py`。
- 验证：Cockpit 聚焦 137 项 Python、41 项 JS 测试通过；UMD `node --check` 通过；资源清单
  哈希、metadata 文件哈希与 `source.json` 一致；静态站资源版本由 `3abcfd47…` 变为
  `bc0eb9fd3a578bb113eb`。

### 2026-10-29 17:00 · Cockpit 全槽位预热、Tab 常驻与 AP 慢查询调度收口

- 用户可见变化：三个页面配置的 12 个 AI 插槽会按业务环节在服务端预热并保存；运营页和
  穿透页即使没有整页快照，也会进入维护队列。打开或刷新页面直接返回全部已保存卡片，未访问过
  的 Tab 也能立即展示已有结果，不再依赖浏览器先打开一次。
- 启动与切换：`/api/cockpit/startup` 增加 `cardsByPage`、并集 `cards` 和 `cardsVersion`；
  三个顶部 Tab 改为组件内 `setActiveTab` 加 `history.pushState`/`popstate`，只切换当前页面、
  卡片元数据和轮询范围，不重建 SDK、数据客户端或已加载的看板实例。
- AP 调度：前端 AP 并发从 2 调到 3，按 `IntersectionObserver` 的真实可见环节优先，重查询最多
  占 2 个槽位，轻查询始终保留一个执行位；同一环节的卡片共享查询，不因多个 AI 插槽重复取数。
- AI 等待：分析等待从“整页 AP 全部结束”收敛为当前业务环节的查询；一个无关图表失败或变慢，
  不再阻断已有足够证据的可见卡片。后台刷新只回读当前环节的查询，避免历史上下文带入同页其他环节。
- 查询复用与超时：页面请求和后台刷新统一经过 `query_receipt` 的共享 AP 缓存/合并层，缓存键
  包含身份、连接、查询和存储；共享查询的跟随者等待预算由网关超时加余量决定，不再固定 35 秒。
  后台调度保持单工作线程，页面并发预算仍可用满；后台沿用同一结果，不再走独立的 AP 快路径。
- 计时：单条 AP 请求记录前端排队 `clientQueueMs`、服务端排队 `backendQueueMs`、上游执行
  `upstreamMs`、响应处理 `clientResponseMs`，并在 `/data/query` 返回 `receiptWaitMs` 与
  `serverTotalMs`，可在浏览器调试日志中按查询环节定位慢点。
- 主要文件：`bi_agent/cockpit/targets.py`、`refresh.py`、`router.py`、`store.py`、
  `page_cache.py`、`ap_gateway.py`、`bi_agent/web/static/cockpit/cockpit.js`、
  `data-client.js`、`tests/test_cockpit_card_preheat.py`、`test_cockpit_page_cache.py`、
  `cockpit_data_client.test.mjs`、`cockpit_tab_navigation.test.mjs`。
- 验证：Cockpit 聚焦回归 165 项 Python（含 14 个子用例）、53 项 JS 通过；`node --check`
  与 `git diff --check` 通过。覆盖全部插槽映射、无整页快照预热、启动返回跨页卡片、未变化不重复
  调用模型、Tab 原地切换、可见环节插队、重查询隔离、当前环节等待和共享跟随者长超时。
- 边界：本轮只提交并推送临时分支，未部署、未创建正式版本；上游慢 SQL、未登记指标口径和真实
  伏羲任务联调仍按原范围单独验收。

### 2026-10-29 17:06 · Cockpit 首屏骨架与启动依赖解耦

- 用户可见变化：首屏不再同时出现静态“正在加载经营看板”和 Vue 白框。Vue 接管前只显示一层
  按 KPI、图表区域排布的统一骨架；Vue 挂载后立即移除静态骨架，不再等全部初始化结束。
- 启动拆分：布局配置只并行读取 `runtime.json`、`GET /engines` 和 `GET /data/config`，不再等待
  `/startup`。真实看板布局取得配置后立即挂载，图表继续使用组件原有 loading，AI 插槽使用现有
  分析骨架；历史卡片由挂载后的 `GET /publications/cards` 独立刷新，页面快照与更新状态由
  发布轮询独立补充，任一历史请求变慢都不会挡住整张看板。
- Tab 数据：切换 Tab 时只读取目标页已保存卡片，不再等待完整 `/startup`；页面快照和更新状态
  在后台由发布轮询补充，均不阻塞布局。
- 错误与重试：配置、Vue 或 ProUI 资源加载失败时显示明确错误和“重新加载”按钮，不再无限显示
  loading；`GET /publications/cards` 同时返回 `cardsVersion`，前端命中后不再重复拉取相同卡片。
- 主要文件：`bi_agent/web/static/cockpit/index.html`、`cockpit.css`、`cockpit.js`、
  `bi_agent/cockpit/router.py`、`tests/cockpit_loading_shell.test.mjs`、
  `tests/cockpit_tab_navigation.test.mjs`、`tests/test_cockpit_card_preheat.py`。
- 验证：Cockpit 聚焦回归 165 项 Python（含 14 个子用例）、58 项 JS 通过；`node --check`
  与 `git diff --check` 通过。新增用例覆盖单一首屏骨架、配置不等 `/startup`、静态骨架及时移除、
  挂载后独立加载历史卡片与状态、失败重试和卡片版本返回。
- 边界：本轮只提交并推送临时分支，未部署；上游 SQL、指标口径和真实业务数据仍需单独验收。

### 2026-10-29 17:23（2026-10-31 10:20 更新）· Cockpit 同步 iba-demo UMD 与三张订单 DataTable

- 用户可见变化：同步最新 ProUI/看板配置后，订单接收节点新增「明星产品订单电量及占比」
  与「受影响订单清单」，发货节点新增「客户与超期订单」。三张表复用上游 `ProDataTable`
  的布局、列宽和分页，不再在宿主另写表格样式。经营看板和运营页四处置顶跳转入口不再固定
  显示“3项风险”或“查看风险”，而是读取对应穿透页 `opportunity-risk`、
  `shipment-risk-summary` 已发布卡片中实际交付的 `causes` 条数，显示为 `N条风险`；
  分析尚未取得时显示“风险分析中”。入口计数与点击后看到的风险条目使用同一份详情卡片，
  不会把证据数、记录数或建议数当成风险数。
- 组件同步：看板模板、激活规则、报价图和商机搜索配置来自 `iba-demo feature/demo_1021`
  `cd8d71f`，组件数保持 142，AI 插槽保持 15 个；其中 103 个组件声明 AP、39 个保留上游
  mock。UMD 另同步到 `ebe55d0`，新增 `createBiRuntime({runtimeKey})`、
  `setTemplateRegistry` 和 `updateComponentMeta`，当前资源哈希为 `10f624d9...`。宿主使用
  固定 runtime key 注册全部模板，在首个 Tab 即可覆盖隐藏的运营页入口，不需要先切 Tab，
  并在看板重建后重新应用；新版 UMD 继续保留本地头盔图 `fitView` 空实例保护。
- 风险入口映射：概览页 `progress-y5dumxio`、`progress-91j3rt9a` 分别读取
  `opportunity-risk`、`shipment-risk-summary`；运营页 `progress-ynh9zsng`、
  `progress-zl0egumz` 使用相同详情来源。覆盖路径统一为 `headerActions[0].label`，
  AI 发布结果更新后原地重算，不触发整页重建。
- 订单表格：明星产品表对齐新版 AP 字段，展示系列、去年参考电量、订单接收电量、占全部订单
  电量和已登记口径；受影响订单表展示 AP 事实及原因、责任动作，并固定筛选变更/取消订单；
  超期订单表展示 AP 事实及主因和具体根因，并固定筛选超期天数大于 0 的订单。口径由服务端
  按已登记系列映射生成，不让模型临场编造指标定义。
- 数据链路：上游三张表的 `/api/mock/star-product-scope`、`/api/mock/affected-order-extra`、
  `/api/mock/overdue-order-root-cause` 不进入交付包，统一改走
  `POST /api/cockpit/ai-tables/{tableKey}/query`。主服务按固定字段白名单生成 AP 单查，
  在服务端再次合并两张表各自的固定预过滤条件，前端漏传也不会扩大数据范围；事实列直接
  使用 AP 返回，原因、责任动作和根因只从当前范围已发布且通过交付校验的环节卡片中，按
  `evidenceIds` 对应记录里实际出现的订单号合并。表格映射版本升级为 `ai-tables-v3`。
- 证据边界：筛选项只允许 `AND`，字段和分页有白名单及上限；未匹配到订单证据时显示
  “证据不足，未确认根因”或“待核实原因后明确责任动作”，不借用其他订单结论，也不把
  页面文字或模型猜测包装成已验证根因。
- 已知缺口：商机模板原有的 `share-bar-79fsomq9` 子组件缺项仍保留为空位并记录
  `CHILD_DEFINITION_MISSING`；三张订单表的插槽落点均已命中。
- 主要文件：`bi_agent/cockpit/ai_tables.py`、`router.py`、`targets.py`、
  `bi_agent/web/static/cockpit/cockpit.js`、`insight-components/table-runtime.js`、
  三张订单表插槽目录、`metadata/iba-demo-1021/*`、`metadata/runtime.json`、
  `index.html`、`vendor/{pro-bi-ui.min.js,resources.json}`、
  `tests/test_cockpit_ai_tables.py`、`tests/cockpit_ai_tables.test.mjs`。
- 验证：Cockpit 相关 Python 220 项、Node 看板测试 82 项全部通过；`node --check`、资源清单
  哈希与 `git diff --check` 通过。覆盖证据关联合并、未知订单不借用原因、明星产品口径、
  未审核字段和 `OR` 筛选阻断、固定预过滤、字段哈希与 runtime 可复现、三张表不引用 mock
  路径，以及四个风险入口到详情插槽的动态 `N条风险` 计数和 `updateComponentMeta` 调用。
- 边界：本轮完成代码与静态配置验证，未部署，未用真实业务数据验收三张表的 AP 返回、分页、
  排序或页面视觉效果，也未发送风险/待办。

### 2026-10-29 17:55 · 修复 AI 插槽渲染作用域与后台刷新抢占首屏 AP

- 用户可见变化：修复新版页面中 AI 插槽只显示空占位、模块未完成加载的问题。根因是
  `CockpitInsight` 在渲染时读取了外层应用 setup 的 `page` 变量，实际作用域内不存在，
  触发 `ReferenceError: page is not defined`。当前页面现通过显式 `page` prop 传入，三个
  Tab 的插槽都能继续加载 registry、shared 和各自组件，不再因组件异常停在空占位。
- 首屏 AP：后台定时刷新默认从 3 个范围并行收敛为 1 个。此前三个后台范围可同时占用三个
  上游 AP 槽位，用户打开页面时 26 个图表查询只剩一个槽位可用，表现为整页长时间 loading。
  现在后台最多占一个槽位，至少保留三个槽位给页面请求；预热心跳仍按 15 分钟间隔执行。
- 配置：新增 `COCKPIT_REFRESH_SCOPE_LIMIT`，默认 `1`；需要更高预热吞吐时可显式调大，
  但会与页面 AP 查询共享 `COCKPIT_AP_CONCURRENCY=4` 的槽位。
- 主要文件：`bi_agent/web/static/cockpit/cockpit.js`、`index.html`、
  `bi_agent/cockpit/refresh.py`、`router.py`、`tests/cockpit_insight_runtime.test.mjs`、
  `tests/test_cockpit_refresh.py`。
- 验证：Cockpit 聚焦回归 170 项 Python（含 14 个子用例）、62 项 JS 通过；`node --check`
  与 `git diff --check` 通过。新增用例锁住插槽 page prop 传递和后台单范围默认值。

### 2026-10-29 18:29 · Cockpit 15 个 AI 插槽独立发布与稳定读取

- 用户可见变化：Cockpit 启动后单独读取全部 15 个 AI 插槽的已发布结果，不再等待指标、
  图表或 AP 查询。已有结果的插槽直接展示；没有结果的插槽明确标记为 `missing`，不会用
  空内容冒充完成。切换三个 Tab、切换运营节点、图表/AP 失败或后台刷新期间，已加载卡片
  保持可见，不再退回 loading。
- 固定注册表：以 `insights.json` 的 15 个实际 `slotId` 为准，统一登记
  `slotId/page/stage/outputType/contractVersion`。读取接口、预热调度和验收测试共用同一张
  注册表；同一业务环节仍只分析一次，订单接收等跨页共享环节不会重复调用模型。
- 独立读取接口：新增 `GET /api/cockpit/ai-publications?id=1&uiScope=default`，只访问持久化
  发布记录，不触发 AP、`ensureAnalysis()` 或页面取数。响应返回
  `expectedCount/readyCount/missingCount/updatingCount`、固定 slot 映射、每个插槽的
  `status/generatedAt/dataAsOf/refreshStatus/payload`，并按内容生成轮询版本。
- 服务端预热：缺失插槽立即登记补齐任务；无历史访问计划时，从交付包内的组件查询快照
  生成对应环节查询计划，再重新取数、执行分析与卡片契约校验。成功结果持久化，失败只更新
  错误状态并保留上一版；只有通过 `cockpit-cards-v1` 和摘要/原因/建议/限制结构校验的卡片
  才能计为 ready。
- 前端状态：新增 `ai-publication-client.js` 与页面外层 `aiPublicationStore`，在启动阶段
  并行读取全部 slot，组件挂载后按 `slotId` 获取结果；命中已发布卡片时跳过
  `ensureAnalysis()`。筛选口径真实变化时保留旧卡片并标注“以下仍为上次分析”，只允许最新
  范围结果替换展示内容；后台新版本由轻量轮询自动回填，不重建看板。
- 主要文件：`bi_agent/cockpit/targets.py`、`cards.py`、`refresh.py`、`router.py`、
  `bi_agent/web/static/cockpit/ai-publication-client.js`、`cockpit.js`、`index.html`、
  `tests/test_cockpit_slot_publications.py`、`tests/cockpit_ai_publications.test.mjs`。
- 验证：Cockpit 聚焦回归 169 项 Python、67 项 Node 测试通过；`node --check` 与
  `git diff --check` 通过。覆盖 15 slot 注册表、全部 ready/missing 计数、无 AP/模型读取、
  旧卡片保留、缺失不冒充完成、共享环节只预热一次及真实查询计划补位。
- 边界：本轮只提交并推送临时分支，未部署；线上已有卡片是否全部可读需部署后按两个角色、
  三个页面复核，缺失项由服务端预热继续补齐。

### 2026-10-29 18:48 · 修复 Cockpit 初始化筛选触发重复 loading

- 用户可见变化：修复打开页面或切换节点后看板反复重建、图表长期停在 loading 的问题。
  ProUI 初始化时自动写入的“年度/月度”等默认筛选不再被宿主误判为用户切换口径，不会因此
  清空数据客户端并重新挂载整张看板；只有筛选控件上的真实用户操作才会触发新范围取数。
- 幂等保护：同一页面、同一范围、同一完整快照版本重复返回时不再重装客户端或增加
  `boardRevision`；快照缺失回调在同范围 30 秒内最多触发一次恢复，避免缺失查询形成自循环。
  Tab 切回已加载页面继续复用原 SDK、数据客户端和缓存。
- 加载终态：共享取数客户端明确失败时转为可重试的组件错误态，不再无限保留组件自身
  `loading`；服务端尚未生成 AI 结果时，对应插槽显示“正在补充当前口径数据”并可重试，不再
  永久显示 AI 分析骨架。
- 主要文件：`bi_agent/web/static/cockpit/cockpit.js`、
  `bi_agent/web/static/cockpit/data-client.js`、`tests/cockpit_data_client.test.mjs`、
  `tests/cockpit_loading_shell.test.mjs`、`tests/cockpit_performance_preview.py`。
- 验证：Cockpit 回归 169 项 Python、69 项 Node 测试通过；`node --check` 与
  `git diff --check` 通过。隔离浏览器复测中，首屏稳定后 12 秒内无新增 AP 请求；切换
  “月度”只触发一次范围更新；经营看板与运营页 Tab 往返无整页刷新、无残留 loading、无
  JavaScript 异常。
- 边界：本轮只修复宿主调度与加载状态，不修改上游 SQL、指标口径或 AP 数据；真实业务数据
  仍需在上线后按三个页面和两种角色复核。

### 2026-10-29 19:25 · 页面快照缺项改为静默实时取数

- 用户可见变化：看板组件不再显示宿主产生的“当前范围没有完整缓存，正在重新取数”。页面快照
  只作为加载快路径；某个组件查询不在快照内时，该查询直接走真实 AP 取数，组件继续使用自身
  的加载与错误展示，不触发整页重建，也不向组件注入 Cockpit 自绘缓存错误。
- 兼容边界：快照中已有的查询仍按原逻辑回放；缺少的查询独立实时读取，不改变当前筛选、指标
  或结果凭据校验。
- 主要文件：`bi_agent/web/static/cockpit/data-client.js`、`cockpit.js`、
  `tests/cockpit_data_client.test.mjs`。
- 验证：`node --test tests/cockpit_data_client.test.mjs` 31 项通过。

### 2026-10-30 · 销售额与出货量共同分析独立取证

- 共同问题插槽独立绑定 `combined`，不再展示发货卡片的同一分析。使用主服务原有路由、取证工具与交付校验，联合已保存的商机、订单、发货查询；匹配明确日期范围、角色、部门和连接，不额外调用 AP/PG，不改写凭据取数时间。
- 增加默认范围显式预热入口 `/api/cockpit/combined/preheat`；仅启动共同分析，至少两个环节才生成。其他环节结果保留，共同分析不进入普通 SQL 预热队列；缺失证据继续披露，不将跨环节关联称为已确认根因。
- 涉及 `combined.py`、查询投影、插槽注册与主服务提示；新增同口径合并、跨期间排除和身份隔离测试。
- 上线验证：34 的 8765/8876 已部署 `c087a0c`；仅主动预热两个角色的共同分析插槽，分别为 117/118 条证据，其他卡片未清空或手动重算。两角色均 15 个插槽可渲染；浏览器拦截 AP 后共同分析显示正常、无 AI loading。58 项 Python、7 项前端测试通过。

### 2026-10-30 · 报价 AI 插槽对齐运营头盔图状态

- 报价概况仅消费 `YWLN_D021` 报价办理状态与 `YWLN_M0031` 报价电量，排除经营看板的红区报价单数与电芯占比；头盔图、组件包、元数据均未修改。
- 展示由同源结构化查询记录聚合已完成、未完成及各状态电量，不再按 claim 标签或缺失 unit 推测；正常完成、逾期完成分列，缺失状态标为“未返回”，合法零值保留。
- 增加只读冻结凭据的报价专用预热入口，仅更新两个角色的报价分析，不额外查询 AP/PG。56 项相关 Python、5 项前端验证通过。
- 上线补齐报价发布压缩响应的状态/电量原始行；只保留该插槽需要的两个字段，避免发布结果缺少可聚合状态。两个角色仅报价分析 ID 更新，其他卡片及共同分析均保留；正式代码 `919c392`。补充 22 项凭据与压缩契约测试通过。

### 2026-10-30 · 关闭已完成 AP 响应复用（默认不缓存）

- 用户可见变化：同一查询再次发起时不再回放上一次已完成的 AP 响应，每次都重新向上游取数并生成新凭据；同一时刻重叠发出的相同查询仍合并为一次上游调用，避免重复 SQL，但不再有“上次结果”复用窗口。
- 配置与实现：后端 `COCKPIT_AP_REUSE_SECONDS` 默认值由 `300` 改为 `0`，允许显式设置 `0`；前端 `DATA_REUSE_WINDOW_MS` 由 `5 * 60 * 1000` 改为 `0`。AI 发布卡片、历史快照与在途请求合并逻辑保持不变。
- 主要文件：`bi_agent/cockpit/router.py`、`bi_agent/web/static/cockpit/data-client.js`、`tests/cockpit_data_client.test.mjs`、`tests/test_cockpit_ap_gateway.py`；提交 `37476f2`。
- 验证：Python 42 项、Node 看板测试 82 项通过，`node --check`、`py_compile`、`git diff --check` 通过。线上 `8765` 连续两次相同查询 receipt `aed6f8e82312`／`524fe7cd7eec`，两次均 `cacheHit=false`、`follower=false`。
- 上线：`8765` release `process360-cockpit-37476f2-20261030-no-ap-cache`，PID `3852987`，`/healthz` 200；`8876` assetVersion `b6628694318ccccd18f1`，`release.json` 指向提交 `37476f2`。`8876` 的 nginx 容器以 bind mount 解析 `site` 软链，切换软链后需重启容器（`10de73310da9`），已在重启后确认 HTTP 同时返回新 assetVersion 与 `DATA_REUSE_WINDOW_MS = 0`。
- 回退：`8765` 旧 release `process360-cockpit-919c392-20261030-quote`；`8876` 备份 `backups/site-919c392-20261030-105250-pre`。历史 release、`.env`、`.venv`、共享 `dataset`、会话与用户数据均未覆盖或删除。

### 2026-10-30 · 图表默认不再回放整页快照

- 用户可见变化：打开或刷新看板时，图表数据默认逐条实时查询 AP，不再从服务端保存的整页快照直接回填；需要旧快路径时可显式使用 `?cache=1`。AI 已发布卡片与分析时间提示仍从发布结果读取，不走 AP。
- 实现：`install()` 仅在 URL 带 `cache=1` 时把快照交给数据客户端，否则传 `null` 触发实时查询；`DATA_REUSE_WINDOW_MS=0` 与后端 `COCKPIT_AP_REUSE_SECONDS=0` 保持不变，重叠在途请求仍合并。
- 主要文件：`bi_agent/web/static/cockpit/cockpit.js`；提交 `4c933e4`。
- 验证：Node 看板测试全通过，`node --check` 通过；线上入口返回 `assetVersion=4dc6e0a2dda046f2c5bd`，`cockpit.js` 含 `cache=1` 分支。
- 上线：`8876` 资源版本 `4dc6e0a2dda046f2c5bd`（`commit=4c933e4`），`site` 指向 `site-next-4c933e4-20261030-115044`，容器 `10de73310da9` 重启后生效；`8765` 后端代码未变（`37476f2`），`/healthz` 200。
- 回退：`8876` 将 `site` 指回 `site-next-37476f2-20261030-105008` 并重启容器；更早版本备份 `backups/site-919c392-20261030-105250-pre`。历史 release、共享 `dataset` 与用户数据未改动。

### 2026-10-30 · AI 插槽交付契约与推理校验

- 新增逐插槽交付契约 `cockpit-delivery-v2`：同一环节分析按插槽问题分别适配，不再把通用摘要直接投放到所有位置。报价只交付状态概况；投标交付异常表现与排查方向；商机、订单交付结构定位；共同分析作为管理总览；超期与原因拆解在缺少逐单状态时只交付数据缺口与核查动作。
- 新增并收紧推理校验：金额与电量混用比较、未验证的“取消/变更＋中标未签”集合相加、把异常表现/结构定位/数据缺口写成原因、目标口径冲突只藏在限制说明、验收写成“缺口不再扩大”，都会在交付时被拒绝并要求修正。交付投影会直接删除跨单位推断及由同一推断衍生的“取消变更量级有限”子句，不再只补免责声明；删除原因后引用它的建议同步剔除，避免悬空 `causeIds`。
- 原因按 `[异常表现]`/`[结构定位]`/`[数据缺口]`/`[待验证假设]`/`[记录支持]` 标注并分层排序；建议统一为“建议措施”，责任角色标注待确认，期限标注建议值，验收补齐可检查的清单/对账要求。
- 任务草稿、受影响订单/超期订单表格同步使用上述标注；发货状态缺失时不再复用出货目标缺口分析，订单接收卡在缺结构证据时明确披露“不能解释签单结构”。
- 前端插槽优先使用服务端按插槽投影的卡片，文案与同一环节其他插槽分开；共享样式按 `kind` 展示原因层级。
- 逐插槽完整性按职责验收：报价、投标状态、订单接收、表格和超期说明不强制要求原因或措施，报价概况不再因 `CAUSES_EMPTY`／`ACTION_EMPTY` 被判为内容不完整；证据条数按 id 去重，同一事实、记录和证据引用不重复计数。
- 主要文件：`bi_agent/cockpit/delivery.py`、`cards.py`、`router.py`、`store.py`、`ai_tables.py`、`agent.py`、`main_service.py`、`cockpit.js`、`insight-components/shared.js`；新增 `tests/test_cockpit_delivery_contract.py`。
- 验证：Cockpit 相关 Python 219 项、Node 看板测试 82 项通过，`git diff --check` 通过；使用线上已保存插槽重放，两个角色的共同分析均不再出现“难以解释”“不足以解释”“金额占比不足”“订单取消变更量级有限”和悬空 `signed-unsigned-scope`。
- 上线：交付契约提交序列为 `012fd2a`、`d611a72`、`71a4da6`（分支 `bugfix/cockpit-disable-ap-reuse-cache`）。34 的 `8765` release `process360-cockpit-71a4da6-20261030-151759`（PID `763133`），`8876` assetVersion `f4b2cb70ffa2f8e87c77`、`commit=71a4da6`。两个角色均 15/15 插槽 ready，报价 `contentGaps` 仅 `ANALYSIS_LIMITED`，共同分析证据去重后为 117/118 条；总裁共同分析保留 5 条有依据的原因，分析员保留口径冲突、商机覆盖、客户结构 3 条。回滚使用 `process360-cockpit-d611a72-20261030-151355` 与 `site-next-012fd2a-20261030-151130`。

### 2026-10-30 单主服务部署约定

- 纳入整合后新增的五个 Cockpit 修正提交，避免遗漏推断与表格筛选修复。
- 提供按环境隔离的单应用 Compose 与单前缀网关转发模板，统一工作台、Cockpit、MCP 入口，保留全部运行数据卷。
- 模板默认主分析路线；实际切换必须先完成候选实例真实环境验收，旧实例不自动退役。

### 2026-10-31 · AI 插槽文案、分类与发布体积优化

- 修复摘要补充说明重复句号，过滤“短摘要不含业务数字”等生成说明；不再用替换因果词片段的方式破坏“尚不能归因为”等原句。口径冲突与证据缺口优先归为数据缺口。
- AI 发布接口保留既有字段结构，仅裁剪前端不使用的查询计划、凭据 ID 与事实完整 provenance；完整证据与历史分析仍保存在原处，报价原始状态行保留。该修改只影响发布读取，不触发 AP、模型重算或部署。
- 31 项交付与插槽接口测试通过，覆盖句子完整性、分类、零值、报价记录保留及历史对象不变。
- 2026-10-31 上线复验：8765 已发布 `8e1c888`，正式前缀路由保持不变；两角色15个插槽均可读，报价状态行保留，发布体积约362/625 KB。重复句号、生成说明和分类修复生效，无建议原因引用断裂；未触发手动取数或分析。

### 2026-11-01 · Cockpit 黄金评测集与红测诊断

- 新增 40 条合成业务评测（10 推理、6 分类、4 文案、15 插槽投影、5 范围），包含独立业务预期、理由、优先级、schema 与 SHA256 manifest；无客户数据和运行凭据。
- 新增离线运行器及 JSON 明细报告、数据与运行器完整性测试、非阻断 CI 观察任务。严格运行失败退出，不把已知 P0 缺口当作通过；报告不入库，不连接 AP/PG、模型或 Fuxi。
- master `4c63e4d` 首次结果为35/40通过，5条红测保留：跨单位推证、英文推断、变更即损失、口径冲突分类、生成说明清理。诊断和后续建议记录于 `docs/specs/cockpit-eval-findings-2026-11-01.md`。当前不是模型端到端评测，不宣称验证真实SQL或任务下发。
