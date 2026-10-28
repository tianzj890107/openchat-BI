# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-10-27 · Cockpit 首屏加载与整页数据版本优化

- 首屏与资源：Cockpit 改用生产版 Vue，组件脚本和静态资源支持 gzip 预压缩；目标页面在挂载前
  确定，配置、运行模块和已发布卡片并行初始化；AI 插槽组件按当前页实际出现的模块加载，不再在
  每个页面启动时加载全部 12 个插槽。新增 `scripts/build_cockpit_site.py`，按内容哈希生成可并存的
  release 静态目录、`release.json` 和 `manifest.sha256`；新增 `deploy/cockpit-nginx.conf` 作为
  独立静态站的缓存与代理模板，保留旧 release 目录。
- 整页完整版本：新增 `/api/cockpit/page`、`/page/lookup` 和 `/startup` 及前端 `page-client.js`。
  页面打开时先回放服务器上次通过校验的完整版本，包含图表数据、筛选范围、AI 卡片和数据时间；
  后台再取新 AP 数据并更新卡片，全部图表与可见 AI 插槽属于同一数据版本后才原子发布新页面。
  更新失败、页面数据不完整或筛选已变化时保留上次完整内容并显示更新时间／失败原因，不回填旧请求，
  也不接受缺项或跨版本结果。页面版本追加保存，不覆盖历史。
- AP 取数：新增按连接、认证配置和完整查询条件隔离的短时结果复用及并发合并；相同查询在同一时刻
  只访问上游一次，仍按身份和有效期校验。新增 `COCKPIT_AP_BATCH_MODE=individual`，把批量查询按原
  顺序拆成同一组 AP 单项请求，全部成功才交付；用于避开线上批量接口“本地查询组合未配置／未启用”
  导致的整批失败。`native` 模式保留供批量接口修复后联调，未以空数据或静默降级掩盖失败。
- 数据一致性：图表查询、AI 结果和页面缓存使用同一 AP 数据指纹、认证范围、连接身份和配置版本；
  AI 结果首屏改为紧凑返回，仅携带卡片所需摘要、建议、限制和证据，完整来源仍保留在分析记录中。
- 涉及文件：`bi_agent/cockpit/page_cache.py`、`ap_gateway.py`、`router.py`、`store.py`、
  `bi_agent/web/static/cockpit/page-client.js`、`cockpit.js`、`data-client.js`、
  `publication-client.js`、`insight-components/index.js`、`index.html`、`cockpit.css`、
  `bi_agent/web/static/cockpit/vendor/vue.global.prod.js`、`bi_agent/web/static/cockpit/vendor/resources.json`、
  `scripts/build_cockpit_site.py`、`deploy/cockpit-nginx.conf`、`.env.example` 及对应测试。
- 验证：Cockpit 相关 Python 测试 94 项通过；整页缓存、数据客户端和卡片发布前端测试 21 项通过；
  本地浏览器验收覆盖缓存首屏、后台替换、AP 失败保留、筛选切换和三个页面初始路由，全部通过。
  静态站构建生成 127 个文件（含 62 个 gzip 文件）并通过 manifest 校验；`git diff --check` 通过。
- 边界：本轮只完成本地实现、测试和分支交付；未部署，未修改 34 服务器或用户历史会话。

### 2026-10-27 · 收口 ontology-v0.1.5（加载性能 PATCH）

- 按用户明确指定，把驾驶舱整页缓存、后台更新、AP 短时复用与 individual 拆批、生产版 Vue、
  gzip/内容哈希静态资源、AI 插槽按页加载和初始化并行化收口为 `ontology-v0.1.5`。
- `ontology-v0.1.4` 保持为加载优化前的定版，annotated tag 指向 `3287c91`；`ontology-v0.1.5`
  的 tag 与 GitLab Release 在版本收口提交上创建。
- 同步更新 README、版本索引、新增 `docs/versions/ontology-v0.1.5.md`、版本规范、版本契约测试
  和前端/包管理清单版本号。
- 边界：不部署、不修改服务器或用户历史会话；tag、Release 与 MR 合并按独立授权执行。

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
