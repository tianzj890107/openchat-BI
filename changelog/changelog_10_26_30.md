# eimosp-ontology-agentic-analytics 变更记录（2026-10-26 至 2026-10-30）

> 本文档记录 2026-10-26（周一）至 2026-10-30（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-10-29 19:20 · Cockpit 年度口径对齐、AI 卡片刷新兜底与首屏独立加载

- 用户可见变化：运营页右上角默认时间由 `2025年10月` 修正为 `2025`，与“年度”默认粒度及实际
  `2025-01-01～2025-12-31` 查询一致；切换筛选或刷新页面时，AI 插槽先展示上次已发布的默认
  口径卡片并明确标注口径差异，不再整批变成空白。AI 卡片读取不再等待布局配置、指标或 AP
  取数完成。
- 服务端：`/api/cockpit/ai-publications` 对非默认筛选保留默认口径卡片作为显示兜底，返回
  `scopeMatch=false`、`displayScope=default` 和逐插槽标记，不把旧卡片冒充当前筛选结果；
  相同 AP 查询的成功结果复用窗口由 45 秒延长到 5 分钟，普通刷新优先复用上次结果，后台
  继续按原周期复核。
- 组件适配：`runtime.py` 仅在宿主运行时把年度默认值规范为年份标签，不改上游组件结构、
  卡片位置或指标配置；运行时元数据重新生成。
- 验证：Python 1695 通过、37 跳过、1022 subtests 通过；Node 70 通过；`git diff --check`
  通过。部署后以真实浏览器复核两种角色 15/15 卡片。

### 2026-10-29 18:10 · Cockpit 节点切换保留看板缓存，缺失 AI 卡片立即预热

- 用户可见变化：运营页、穿透页切换头盔节点（如投标、报价、订单接收）不再清空数据客户端、
  重建整页看板或重新触发全部图表查询；已加载的指标图和表格继续显示，AI 插槽直接读取对应
  环节的已发布卡片。节点选择只改变当前展示节点，日期、粒度、客户等真实筛选变化仍会进入
  新的数据范围并保留旧内容直到新版本完成。
- 前端：`data-client.js` 将节点选择与业务筛选分开，节点调用仅记录用于视图回放，不进入数据
  scope；相同查询的五分钟缓存继续可复用，真正切换筛选时才 `clearScope`。清理范围时同步
  `AbortController` 中止在途请求并拒绝排队请求，避免旧节点任务继续占用 AP 队列。
- 服务端预热：`RefreshScheduler` 对没有可读卡片的已配置插槽立即登记并执行，不再统一等待
  `COCKPIT_REFRESH_INTERVAL_SECONDS`；已存在成功卡片的范围仍按原周期复核。某角色缺少查询
  计划时，可复用同一页面已保存的查询计划，但分析结果仍写入当前角色身份，不复用其他角色的
  证据或结论。
- 验证：Node `data-client` 30 项、Cockpit Python 29 项、全部 Cockpit Python 164 项通过；
  新增节点切换不触发 scope 变化/缓存保留、清理范围取消排队请求、其他角色查询计划预热等用例。

### 2026-10-29 11:40 · Cockpit AI 分析按环节隔离上游失败

- 用户可见变化：单个看板指标查询失败（如上游 `SQL 超时`、`系统繁忙`）不再让整页所有 AI
  插槽一起报错。已成功取数的环节照常生成原因与建议；本环节有指标失败时，卡片在限制中
  列明失败指标数量与名称，并声明结论不完整；本环节没有任何可用指标时交付限制卡片，不生成
  原因和建议，也不引用其他环节数据。
- 实现：`data-client.js` 新增 `scope({partial:true})` / `ready({partial:true})`，只把带服务端
  凭据的成功查询送入分析，并把失败查询作为缺口清单返回；`cockpit.js` 的分析请求携带
  `unavailableQueries`，整页发布和单卡刷新共用同一规则。`AnalysisRequest` 新增
  `unavailableQueries`（最多 80 条），服务端按 `STAGE_METRICS` 归属环节、清洗标签后写入
  `stageEvidence.failed/failedLabels`，并同步到分析提示、限制说明和本环节缺数卡片。
- 加载状态：取数阶段卡片显示“正在加载分析数据”，证据收集完成、真正提交模型后切换为
  “AI 正在分析”；`InsightLoading` 渲染 `progress`，整页发布和单卡刷新同步。
- 证据映射：商机白名单纳入客户规划与实际电量指标（`YWLN_M0075`、
  `YWLN_M_CUSTOMER_TARGET_ENERGY`、`YWLN_M_CUSTOMER_ACTUAL_ENERGY`）；`YWLN_` 前缀的
  自定义编码参与环节匹配，不再依赖纯数字正则。`vertex:[]` 且没有指标、维度配置的组件在
  宿主侧直接标记“看板组件未配置实体查询字段，已跳过空查询”，不再把空实体请求发往 AP。
- 验证：110 项 Cockpit Python 测试、29 项前端测试通过；新增失败查询归环、`partial`
  作用域、客户规划映射、空配置拦截和缺口披露用例。上游真实 SQL 超时仍如实展示，不补造数据。

### 2026-10-29 09:52 · Cockpit 验收收口：指标证据隔离、失败状态与直发标注

- 用户可见变化：看板 AI 插槽按业务环节隔离证据，商机卡只消费商机指标，报价、投标、订单、
  发货各自使用本环节指标；页面没有本环节指标时交付限制卡片并说明缺口，不再输出“0 项原因、
  0 项建议”冒充分析结论。采购、发货等其他环节数据不会再被商机卡引用。
- 头盔图兼容：删除旧的 `helmet_compat` 重写，停止把上游 `YWLN_D020/YWLN_M0022` 商机头盔
  改成旧 `D007/M00013` 发货口径，也不再移除报价、订单、发货节点配置。上游 repository 8 返回
  的 `YWLN_*` 配置原样渲染；本体未配置的指标继续由上游返回失败，宿主不补造。
- 失败状态：AP 上游返回 `success:false` 时保留清洗后的指标级原因（例如 SQL 超时及指标编码），
  页面显示“部分指标加载失败”，头盔节点在失败时以“—”替代可能的 `0.00`，长期 `loading`
  或“加载中”占位改为“加载失败”；失败组件的 KPI、周期、达成率和目标值整体显示“—”，
  失败组件内的 `0.00` 金额、电量、天数占位也改为“—”，真实非零值不受影响。
  失败后每 4 秒持续清理晚到的加载占位，并保留 6 秒宽限以免误伤仍在进行的查询；切换
  筛选时清空旧失败提示。不再展示全局失败横幅，完整指标和上游原因只保留在组件内错误与
  悬浮提示中，避免一条长红字覆盖页面。AI 插槽卡片按原型只展示风险、原因和建议，移除
  `shipment-task-order` 中未接线的“下发 N 条任务令”占位按钮。页面标题和“完整看板/更新时间”状态行改由看板组件
  Header 的 `title`/`description` 渲染，删除 cockpit 自定义状态行样式；状态行失败时只显示
  “部分数据加载失败”，不展开上游 SQL 错误。只对瞬时 504 做一次有界重试，确定性 502 不重试。
  真实零值和上游明确返回的 `0.00` 保持不变。
- 风险/待办直发：保留页面直接发送，服务端补建一次性草稿并继续校验身份、权限、接收人、幂等和
  回执；直发卡片标注“临时直发 / 未经验证分析”，正文追加“未经过服务端证据校验，不代表已验证
  根因或风险已解除”。Canvas 自带的 `verificationStatus=unverified` 标记可正常直发，会被强制
  归一化为未验证；调用方声明 `verified/true` 仍会阻断，嵌套元数据中的冒充字段也会清除；
  RISK/TODO 工具类型错配在调用 Fuxi 前阻断。
- 跳转与展示：跨 Tab 的 `switchTab + selectHelmet` 现在把 `node` 写入目标 URL，并在目标页按
  路由或 `activate-rules.json` 恢复节点；KPI 数值行不再被裁掉末位，超过 4 项的底层指标明细
  默认折叠；补充 favicon，消除 404。
- 数据口径：线上 9c906a9 静态包已使用 d01c08a 元数据；本轮浏览器复核经营看板各 KPI 为
  销售额 78.32 亿元、出货量 20.36 GWh、毛利率 18.20%、净利率 7.60%、应收周转 76 天，
  不再共用采购金额。部分运营指标（如订单接收电量、已中标未签单金额、中标率）上游仍返回
  502/504，页面按失败状态展示，需等上游补齐指标。
- Skill：更新风险卡、直发标注和环节证据规则，重新打包 24 文件，SHA256 为
  `e065e095caf65ee59441ecf40fe1f770a63a39aca6fd50eef44a9ad7a3f5dba1`；分发包不入库。
- 验证：全量 pytest 1632 passed、37 skipped、1022 subtests passed；Node 数据客户端 16 项、
  整页缓存 5 项、发布客户端 6 项通过；Skill 自检 160/160 通过。`git diff --check`、JS 语法
  检查与 Python 编译检查均通过。
- 涉及文件：`bi_agent/cockpit/dashboard_source.py`、`router.py`、`ap_gateway.py`、
  `main_service.py`、`bi_agent/web/app.py`、`bi_agent/process360/dispatch.py`、
  `bi_agent/web/mcp_endpoint.py`、`ontology-analytics-mcp/canvas_tool.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,data-client.js,index.html,cockpit.css}`、
  `insight-components/shared.js`、`ontology-analytics-skill/**` 及测试。
- 边界：未发送真实 Fuxi 风险/待办；上游尚未配置的指标仍保持明确失败，不视为业务数据完整。

### 2026-10-29 · Cockpit 适配 iba-demo 1021 单查接口、跳转规则与 12 个 AI 插槽

- 组件同步：按上游 `feature/demo_1021` 的 `d01c08a` 更新根组件、13 份模板、145 个组件配置、
  声明式插槽和 `activate-rules.json`；新版取消旧的三节点头盔覆盖，恢复交付四节点拓扑，并保留
  唯一缺失子组件 `share-bar-79fsomq9` 的空位与缺项报告。
- 数据请求：单查改用 `/x360/v1/ontology/data/query`，服务端固定发送
  `X-Ontology-Repository-Id: 8`（可由 `COCKPIT_AP_REPOSITORY_ID` 显式覆盖），兼容
  `success:true` 与 `code:200` 两种成功包装。页面只注入 `postAnalysisDataQuery`，不再注入批量
  适配器；批量接口仍请求本体且不可用，由新版 ProUI 自动并发单查，宿主不补空数据或部分结果。
- 页内跳转：接入 6 条 `activateRules`，把跨 Tab 的 `switchTab` 转换为主服务三页路由，并在目标
  页头盔图实际挂载后恢复 `selectHelmet` 节点；“查看销售额风险”和“查看出货风险”分别落到商机、
  发货节点。新增新版 SDK 销毁后 `fitView` 回调的空实例保护，避免切页时产生内部异常。
- 插槽验收：经营看板 0 个、运营页 4 个、穿透页 8 个，共 12 个 AI 插槽。浏览器逐节点验证
  `bid-status-note`、`quote-summary`、`bid-summary`、`order-sign-summary`、
  `sales-shipment-issues`、`opportunity-risk`、`opportunity-coverage-note`、
  `order-risk-summary`、`shipment-risk-summary`、`shipment-overdue-note`、
  `shipment-cause-breakdown`、`shipment-task-order` 均能挂载，无浏览器异常。
- 数据边界：34 已接入真实 AP 单查和 repository 8，但部分指标仍未配置完整；浏览器验收中
  7 次 `/api/cockpit/data/query` 返回上游 502，页面在原位置显示“未返回成功的数据结果”，
  不回退旧快照、旧原型或零值。业务数值完整性仍需等组件数据配完后复验。
- 验证：与 Process360 基线合并后，Cockpit 相关 Python 106 项、数据客户端／整页缓存前端
  25 项通过；Process360／Fuxi／MCP 回归 230 项通过、9 项跳过。34 浏览器逐节点确认 12 个
  AI 插槽全部挂载，销售额风险与出货风险跳转正确，无 batch 请求、无 JavaScript 或控制台异常。
- 涉及文件：`bi_agent/cockpit/ap_gateway.py`、`runtime.py`、`metadata.py`、`prototype.py`、
  `cockpit.js`、`data-client.js`、`index.html`、`vendor/pro-bi-ui.min.js`、`vendor/resources.json`、
  `metadata/iba-demo-1021/*`、`.env.example`、`docs/specs/cockpit-analysis-engines.md` 及测试。
- 部署：将 Process360 运行基线 `b32449c` 与本次 `f68f0bd` 合并为部署提交
  `2b7ff72`，避免覆盖既有 Process360 能力。8765 新 release 为
  `process360-cockpit-2b7ff72-20261029-081724`，PID `1629274`；旧
  `process360-a5342cd-20261028-180448`（PID `2561043`）已优雅停止并完整保留。8876
  静态站更新到 `commit=2b7ff72`、`assetVersion=9c906a9a91660d3a9406`，128 项 manifest
  全部通过。部署前在 18765 预检 AP 单查、两套头盔流程、MCP 与 Cockpit 配置，预检进程及端口
  已关闭；未修改 nginx 配置、共享 `.env`、`.venv`、`dataset` 或历史会话。
- 边界：未发送真实 Fuxi 待办，未创建 MR、tag 或 Release，未升级正式版本。AP 上游 502 和
  Process360 当前 `blocked/G16` 均保留为明确业务／数据缺口，不据此判定业务效果完成。

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

### 2026-10-29 11:55 · AI 分析排队可见优先与数据库同口径补查

- 用户可见变化：分析执行槽位占满时不再出现“分析并发已满”，卡片保持加载并显示“排队中，
  等待分析资源”，槽位释放后自动开始。AI 插槽改为按真实视口排序：用户点击重试／确认最高，
  屏幕内卡片按页面位置排序，屏幕外卡片最后；滚动到某张卡片会把它排到待执行队首，已运行的
  任务不被抢占、也不重复提交。
- 服务端排队：`/api/cockpit/analyses` 与 `/api/cockpit/analyses/refresh` 不再返回 429，
  改为创建 `queued` 任务并等待共享执行槽位（最长 900 秒），超时才标记失败；排队期间前端
  持续轮询，不把等待显示成错误。
- 取数与执行解耦：页面 AP 取数在申请分析槽位之前完成，慢查询不再占住唯一分析名额，已就绪的
  可见卡片可以先行分析。
- 数据库补查：页面 AP 查询失败时，主服务按同一筛选口径从唯一 PG 来源
  （172.16.5.181:32444 / ywln / ywln_crm）只读补查，结果保存为独立的 `pg` 凭据并进入证据；
  同一计算范围只用一种来源，页面成功结果仍以 AP 为准，禁止混算。
- 口径边界：仅 `YWLN_M0036 发货金额` 通过核对并启用（2025 全年 AP 78.32 亿元、PG 79.16 亿元，
  差异约 1.1%，来自两份副本的装载时点）；`YWLN_M0024 商机数` 同口径对账相差约 4 倍
  （AP 338、PG 1374），保持 `RECONCILE_GAP` 阻断，不输出数字。维度、产品类型及其他未映射
  筛选一律阻断并返回原因代码，不换指标、不补 0。
- 缓存与披露：发布范围加入补查映射版本，映射变化不复用旧卡片；补查凭据带口径版本，版本不符
  要求重新分析。卡片限制固定披露“已从主库（PostgreSQL）补查：…”和未补查指标的原因代码。
- 验证：新增 9 项补查测试与 2 项前端排队测试；看板聚焦回归 119 项 Python、31 项 JS 通过。
- 部署与线上验证：8765 新增 release
  `process360-cockpit-fe154e9-20261029-1150`（提交 `fe154e9`，PID `2496079`），旧
  `process360-cockpit-552e5a6-20261029-1129`（PID `2402427`）停止后完整保留；同提交实例
  先在 `127.0.0.1:18765` 预检通过再切换，`dataset` 以当前运行副本合并、历史
  `history.sqlite3` 保留。8876 静态站 `commit=fe154e9`、
  `assetVersion=ad7a02148ca32ce8b2ec`，manifest 128 项通过，三页 `id=1|2` 均 200，
  `cockpit.js` gzip 后 13.6 KB；部署前站点备份
  `backups/site-fe154e9-20261029-115307`。线上真实复现：发货金额 AP 返回 504 时，
  分析上下文为 `dataSource=ap+pg`、`pgReceiptIds=1`、
  `fallback.metrics=[YWLN_M0036]`、`stageEvidence.failed=0`；验证后即取消该分析任务，
  未生成卡片、未写业务数据、未发送 Fuxi 待办。

### 2026-10-29 13:20 · 对齐 AP 三分钟预算与筛选口径切换保留旧卡片

- 用户可见变化：AP 后端把 SQL 时限放到 3 分钟后，Cockpit 不再在 10 秒或 35 秒提前放弃。
  主服务对 AP 的单次预算可配置到 240 秒（线上 180 秒），排队等待与上游执行共用同一期限，
  不会先排 180 秒再等 180 秒；浏览器单请求超时 200 秒、取数就绪等待 220 秒，均大于上游预算。
  已经花掉长预算的 504 不再自动重试，只有快速失败才重试一次，避免等待翻倍。
- 用户可见变化：切换时间等筛选口径后不再清空卡片。旧卡片继续展示并标注“筛选口径已切换
  （时间：…），正在加载新数据；以下仍为上次分析”；新口径分析完整交付后一次性替换该环节的
  风险、原因和建议并清除提示；新口径失败时保留旧卡片并写明“新口径分析未完成”，可重试。
- 修复筛选漏触发：首次筛选变化不再被当成默认口径吞掉；页面仍在加载时提交的筛选变化会保留
  最新一次，就绪后补触发；连续切换只允许最新范围回填。
- 修复失效边界：陈旧卡片不会被当作新口径版本发布；没有组件发起取数时，就绪等待 3 秒后结束，
  不会空等 220 秒。
- 主要文件：`bi_agent/cockpit/ap_gateway.py`、`bi_agent/web/static/cockpit/data-client.js`、
  `publication-client.js`、`cockpit.js`、`insight-components/shared.js`、`cockpit.css`。
- 验证：看板聚焦回归 121 项 Python、40 项 JS 通过（新增 AP 预算/排队共期限、长超时不重试、
  筛选变化不被吞、加载中筛选补触发、旧卡片保留与失败提示等用例）。本地浏览器复验：
  点击“月度”后旧卡片保留并出现“筛选口径已切换，正在加载新数据；以下仍为上次分析”，
  新口径分析完成后提示自动消失；同一脚本在改动前提交上也会停在首个“完整看板”断言，
  属于本地 fixture 既有的发布失败，不是本次回归。
- 部署与线上验证：8765 新增 release `process360-cockpit-bf34362-20261029-1330`
  （提交 `bf34362`，PID `2541175`），旧 `process360-cockpit-fe154e9-20261029-1150`
  （PID `2496079`）停止后完整保留；新实例先在 `127.0.0.1:18765` 预检再切换。
  `runtime-env.json` 更新为 `COCKPIT_AP_TIMEOUT_SECONDS=180`，并同步 `PYTHONPATH`、`PWD`、
  `RELEASE_COMMIT`、`PROCESS360_CATALOG_PATH`；`dataset` 以当前运行副本合并，历史
  `history.sqlite3` 保留。8876 静态站 `commit=bf34362`、
  `assetVersion=c2bff4a1bc1a9c973257`，manifest 129 项通过，三页 `id=1|2` 均 200；
  部署前站点备份 `backups/site-bf34362-20261029-120325`。线上 `M0036` 2025 全年查询
  `/api/cockpit/data/query` 返回 200（约 0.34 秒），`startup` 200，日志无 Traceback；
  nginx `/api/cockpit/` 仍为 `proxy_read_timeout 300s`，覆盖 180 秒预算。
- 边界：上游 SQL 别名错误、空 vertex 配置不会因为延长超时而消失；超时只解决“等得不够久”，
  不改变失败口径，也不引入第二数据源。

### 2026-10-29 14:10 · 数据库补查接入真实页面契约

- 用户可见变化：页面部分指标 AP 失败时，AI 卡片可以真正接入主库补查结果，不再报“结果凭据
  与页面查询范围不一致”；页面全部 AP 查询失败、但失败指标在已登记口径内时，也可以只凭补查
  数据交付受限卡片，并明确标注来源为主库。
- 范围契约：`chartQueries` 只表示页面成功展示的 AP 查询，`unavailableQueries` 表示页面失败
  待补查的查询。AP 凭据必须与该成功集合完全一致，PG 凭据只能来自失败集合且不得与成功集合
  重叠；两个集合互斥，任一不一致都拒绝回填。前后端沿用同一契约，未放宽筛选一致性校验。
- 纯补查路径：允许 `apReceiptIds` 与 `chartQueries` 同时为空；补查后仍无任何可用结果时返回
  明确错误“页面取数全部失败，且没有任何已登记口径可供补查”，不生成空卡片。
- 筛选语义：日期筛选必须是 `BETWEEN + DATE + ABSOLUTE`，其他操作符（如 `NOT_BETWEEN`）直接
  阻断；只接受扁平的 AND 条件，OR 混排、嵌套条件和重复日期条件一律返回
  `FILTER_UNSUPPORTED`，不再把不支持的操作符编译成区间查询。
- 补查额度：先按当前环节筛选，再对未映射/不可执行查询返回原因码，最后才对可执行查询计数，
  无效请求不会占用额度；非本环节查询不进入候选。
- 修复参数错位：重复日期条件此前会折叠成一段 SQL 却保留两对参数，现直接阻断，避免执行失败。
- 主要文件：`bi_agent/cockpit/pg_fallback.py`、`bi_agent/cockpit/dashboard_source.py`、
  `bi_agent/web/app.py`、`bi_agent/cockpit/main_service.py`、
  `bi_agent/web/static/cockpit/data-client.js`。
- 验证：看板聚焦回归 129 项 Python、41 项 JS 通过；新增用例覆盖真实前后端契约下的补查接入、
  全部失败仅补查、操作符/逻辑/嵌套拒绝、重复日期条件、额度顺序与环节过滤。

### 2026-10-29 14:58 · 看板分析改为服务端定时刷新与页面订阅

- 用户可见变化：刷新页面或重新进入看板时直接显示服务端上次完成的卡片和“分析更新于 …”，
  不再每次打开都重新取数并触发一轮模型分析；后台更新期间保留旧卡片并提示“正在后台更新”，
  新版本完整交付后一次性替换。状态行不再出现“主服务：路由、取证与交付校验中”等内部步骤，
  只在没有历史结果时显示首次加载。
- 服务端调度：新增 `bi_agent/cockpit/refresh.py`。`RefreshScheduler` 常驻线程按
  `page_refresh` 表扫描到期的范围，`RefreshManager` 重新执行原查询、计算证据指纹，数据、
  来源或交付契约未变化时只更新检查时间，不调用模型；变化时创建分析任务，等待完整卡片契约后
  发布。每次扫描显式登记两种身份 × 三个默认页面，不要求先存在整页快照；有整页版本的范围复核
  整页，没有整页版本但已发布环节卡片的运营页/穿透页复核卡片。新登记范围首次检查延后一个周期，
  部署或重启不会立刻重跑全部默认页面；没有查询计划的范围标记 `awaiting-plan`，不再显示为
  `idle` 或持续 `waiting`。
- 统一证据解析：整页与环节卡片复核都调用 `dashboard_source.page_analysis_context`，与 HTTP
  分析入口共享 `snapshotId`、`dataFingerprint`、来源披露和环节覆盖；helmet 图只用于整页渲染，
  不再被当作业务分析凭据，修复“头盔图凭据被校验拒绝”和“快照标识与真实指纹不一致”。
- AP 失败补查：单条业务查询失败不再中止整轮复核。失败查询按同一环节与筛选交给已登记
  PostgreSQL 补查，所有环节先合并补查凭据再分析，保证一份页面只有一个证据指纹；页面条目与
  凭据记录 `kind=pg`，来源标注 `ap+pg`/`pg`，`dataIdentity=postgres`。AP 恢复后优先重新使用
  AP 结果，补查凭据不会伪装成 AP。
- 持久与去重：`page_refresh` 记录状态、尝试次数、下次检查时间、租约和错误；`claim_refresh`
  用 `BEGIN IMMEDIATE` 加租约保证同一范围只有一个工作线程。新增 `refresh_plans` 保存手工刷新
  的查询计划；`Store.request_refresh` 只把范围置为 `waiting`，不会清除运行中任务的租约。
  没有查询计划的范围返回 409，不再创建随后被调度器置为 `idle` 的空任务。
- 快照不膨胀：复核结果的页面版本与当前发布版本相同时只更新检查时间，不追加快照，避免每
  15 分钟写入一份内容相同的历史副本。
- 接口：新增 `GET /api/cockpit/publications/status`（版本、数据时间、分析时间、更新状态、
  下次检查时间与 `cardsVersion`）、`GET /api/cockpit/publications/cards`（环节卡片）和
  `POST /api/cockpit/publications/refresh`（手工刷新）。`GET /api/cockpit/startup` 返回快照、
  卡片与分析状态，不再因为打开页面启动分析；`POST /api/cockpit/page/lookup` 增加
  `displaySnapshot`/`displayStale`，配置版本轮换后旧版本只作展示。
- 前端：`cockpit.js` 用 `publication-poll.js` 单一状态轮询替代浏览器定时发布：探测异常继续
  重试，页面卸载后停止，标签页隐藏时降频，重新可见时立即检查；发现新整页版本才拉取替换，
  没有整页快照的页面按 `cardsVersion` 原位替换环节卡片。旧卡片不会覆盖更新时间更新的卡片；
  配置版本轮换后仍以 `displayOnly` 展示上次分析并提示“后台正在更新”，避免部署后瞬间清空卡片；
  缓存命中与新版本应用共用同一入口，统一清理 `stale`、`scopeNotice`、`progress`、`error`、
  `refreshing`；`page-client.js` 增加 `status()`、`cards()`。
- 每环节只维护最新卡片键：组件/配置轮换后，旧 `publication_views` 键只保留为历史，不再被调度；
  避免同一环节每 15 分钟因“旧键 → 新键”反复调用模型。整页复核同时回读历史失败查询，AP 恢复
  后可以替换旧的补查/部分证据。
- 运营页和穿透页没有整页快照时，状态接口聚合当前环节卡片的刷新状态；后台定时检查显示为
  `scheduled`，手工刷新显示 `waiting`/`running`，卡片发布后恢复 `published`，不会再永久显示
  “正在后台更新”。
- 数据读取：`latest_page` 与调度扫描改为 SQL 侧按 `json_extract` 过滤，只加载需要处理的
  页面正文，避免每次轮询都解析全部历史快照。
- 主要文件：`bi_agent/cockpit/refresh.py`、`store.py`、`router.py`、`page_cache.py`、
  `dashboard_source.py`、`bi_agent/web/app.py`、`bi_agent/web/static/cockpit/cockpit.js`、
  `page-client.js`、`publication-client.js`、`publication-poll.js`、
  `tests/test_cockpit_refresh.py`、`tests/cockpit_publication_poll.test.mjs`。
- 验证：Cockpit 聚焦回归 158 项 Python、48 项 JS 通过；新增用例覆盖真实共享证据解析、
  PostgreSQL 补查整页发布、无整页快照的卡片维护、手工刷新租约去重、自定义范围实际执行、
  轮询失败续跑、卡片版本原位替换、旧视图键去重和卡片状态聚合（2026-10-29 15:05）。
- 部署：8765 新 release
  `process360-cockpit-6351b2a-20261029-1512`，PID `3280546`；旧
  `process360-cockpit-43ecb5a-20261029-1455`（PID `3238409`）停止后完整保留，`dataset` 与
  `history.sqlite3` 从旧实例复制，未删除或覆盖历史数据。8876 继续使用内容未变的静态资源
  `assetVersion=f4befdeda1752ad6b6c6`，三页和 `/api/cockpit/*` 代理均 200。
- 线上复核：手工刷新穿透页时状态由 `waiting` 正常回到 `published`，分析总数保持 34（未因
  旧卡片键产生重复模型调用）；真实浏览器连续轮询 2 次无 `ReferenceError`、无新增
  `/analyses/refresh`，页面不再显示“正在后台更新”，继续展示已发布卡片（2026-10-29 15:09）。
- 边界：默认范围由服务端维护，自定义筛选仍按访问触发；调度器只复核原页面查询，不修复上游
  SQL 错误，也不改变指标口径。

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

### 2026-10-29 17:23 · Cockpit 同步 iba-demo 00be09f 与三张订单 DataTable

- 用户可见变化：同步最新 ProUI/看板配置后，订单接收节点新增「明星产品订单电量及占比」
  与「受影响订单清单」，发货节点新增「客户与超期订单」。三张表复用上游 `ProDataTable`
  的布局、列宽和分页，不再在宿主另写表格样式。
- 组件同步：`iba-demo feature/demo_1021` 更新到 `00be09f`，组件数由 145 变为 142，
  AI 插槽由 12 个变为 15 个；其中 103 个组件声明 AP、39 个保留上游 mock。运营页插槽数
  变为 5，穿透页变为 10。`activate-rules.json`、UMD 与 CSS 未产生内容变化，UMD 继续保留
  头盔图 `fitView` 空实例保护。
- 订单表格：明星产品表展示系列、2025 年出货参考、推算订单电量、占比和已登记口径；
  受影响订单表展示 AP 事实及原因、责任动作；超期订单表展示 AP 事实及主因和具体根因。
  口径由服务端按已登记系列映射生成，不让模型临场编造指标定义。
- 数据链路：上游三张表的 `/api/mock/star-product-scope`、`/api/mock/affected-order-extra`、
  `/api/mock/overdue-order-root-cause` 不进入交付包，统一改走
  `POST /api/cockpit/ai-tables/{tableKey}/query`。主服务按固定字段白名单生成 AP 单查，
  事实列直接使用 AP 返回；原因、责任动作和根因只从当前范围已发布且通过交付校验的环节
  卡片中，按 `evidenceIds` 对应记录里实际出现的订单号合并。
- 证据边界：筛选项只允许 `AND`，字段和分页有白名单及上限；未匹配到订单证据时显示
  “证据不足，未确认根因”或“待核实原因后明确责任动作”，不借用其他订单结论，也不把
  页面文字或模型猜测包装成已验证根因。
- 已知缺口：上游旧插槽 `shipment-task-order` 仍引用不存在的 `table-md1iftaj`，运行包记录
  `INSIGHT_ANCHOR_MISSING` 并保留原状；本次没有改第四张表或迁移该插槽。商机模板原有的
  `share-bar-79fsomq9` 缺项仍在。
- 主要文件：`bi_agent/cockpit/ai_tables.py`、`router.py`、`targets.py`、
  `bi_agent/web/static/cockpit/cockpit.js`、`insight-components/table-runtime.js`、
  三张订单表插槽目录、`metadata/iba-demo-1021/*`、`metadata/runtime.json`、
  `vendor/resources.json`、`tests/test_cockpit_ai_tables.py`、`tests/cockpit_ai_tables.test.mjs`。
- 验证：Cockpit 聚焦回归 169 项 Python（含 14 个子用例）、60 项 JS 通过；`node --check`
  与 `git diff --check` 通过。覆盖证据关联合并、未知订单不借用原因、明星产品口径、
  未审核字段和 `OR` 筛选阻断、字段哈希与 runtime 可复现、三张表不引用 mock 路径。
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
