# eimosp-ontology-agentic-analytics 变更记录（2026-10-19 至 2026-10-23）

> 本文档记录 2026-10-19（周一）至 2026-10-23（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

### 2026-10-20 11:05 · 智能分析接入 Fuxi 远程 MCP

- 变化：主服务 `bi_agent.web` 新增 Streamable HTTP MCP 入口 `/api/mcp`，
  Fuxi 通过 `transport: http` 直接连接，不再在每个用户机器上启动 stdio MCP，
  也不要求用户填写 `.env`、App ID、Token 或输出目录。
- 工具面：向 Fuxi 暴露 16 个真实分析工具，包括 `AnalysisRoute`、
  `Ontology-SemanticQuery`、`MetricCalculation`、`MetricFactQuery`、
  `ChartGenerate`、`TableGenerate`、`CanvasGenerate`、`OutputGateCheck` 等；
  工具执行复用 Web 对话的 `build_source_executors`，不是另一套实现。
- 权限边界：硬性不暴露 `AnalysisRun`、`AskUser`、`TodoWrite`、
  `Ontology-FactQuery`、`ListTables`、`DescribeTable`；环境变量无法重新启用。
- 交付：`CanvasGenerate` 返回可通过 `/api/mcp/artifacts/<filename>` 下载的
  `Artifact URL`，不再使用 `run_scratch` / `promote_artifact` 或展示服务端暂存路径。
- 连接修复：本体客户端默认绕过开发机 `HTTP_PROXY` / `HTTPS_PROXY`，修复
  demo2 经本地代理访问时出现的 502 和 30 秒超时；语义检索优先走 metadata LIKE，
  Indicator 命中后停止继续扫描其他类型。
- 实测：本地 demo2 下 `Ontology-SemanticQuery` 从超过 120 秒降至约 0.86 秒，
  `MetricFactQuery` 全年取数约 0.98 秒，`MetricCalculation` 约 0.20 秒，
  `CanvasGenerate` 约 0.02 秒；生成的 HTML 经 Artifact URL 下载返回 200。
- 技能包：`ontology-analytics-skill` 改为远程 MCP 交付口径，保留纯规则
  `scripts/route.py`、`gates.py`、`selfcheck.py` 作为离线校验；删除技能内真实工具
  运行时，避免把服务、凭据和原始 SQL 工具随包分发。
- 涉及文件：`bi_agent/web/mcp_endpoint.py`、`bi_agent/web/app.py`、
  `bi_agent/ontology/remote.py`、`bi_agent/tools/remote_ontology_tools.py`、
  `ontology-analytics-mcp/`、`ontology-analytics-skill/`、`README.md`、
  `DEPLOYMENT.md`、`tests/test_mcp_endpoint_red.py`、
  `tests/test_remote_ontology_fast_path_red.py`。
- 验证：MCP 红测与本体契约测试共 106 项通过；技能自检 160/160 通过；
  `git diff --check` 通过。
- 边界：未部署、未重启服务器、未修改历史会话和用户数据。

### 2026-10-20 13:33 · 版本收口为 ontology-v0.1.3（PATCH）

- 变化：按用户明确指定，把远程 MCP 交付、demo2 兼容性修复和前端版本显示统一收口为
  `ontology-v0.1.3`；本版本在 `ontology-v0.1.2` 之后按 PATCH 推进。
- 产品能力：主服务内置 `/api/mcp`，Fuxi 通过 `transport: http` 直接连接，不再要求用户
  在本地启动服务、安装工具运行时或填写 `.env`；对外暴露 16 个受控分析工具，
  `CanvasGenerate` 通过 Artifact URL 交付整页 HTML。
- 权限与性能：硬性不暴露 `AnalysisRun`、`AskUser`、`TodoWrite`、`Ontology-FactQuery`、
  `ListTables`、`DescribeTable`；本体客户端绕过开发机代理修复 demo2 的 502/超时，语义检索
  优先走 metadata LIKE，Indicator 命中后停止扫描其他类型。
- 版本统一：`pyproject.toml`、`frontend/package.json`、`frontend/package-lock.json` 为
  `0.1.3`；`bi_agent/__init__.py`、`open_claude/__init__.py`、FastAPI `APP_VERSION`、
  前端 `PRODUCT_VERSION` 与首屏版本标签为 `ontology-v0.1.3`；前端构建产物同步重建。
- 版本文档：新增 `docs/versions/ontology-v0.1.3.md`，同步更新 `docs/versions/README.md`、
  `docs/versions/versioning-policy.md`、根 `README.md`、`AGENTS.md` 与历史版本状态。
- 验证：MCP 红测与本体契约测试共 106 项通过；前端 76 项 Node 测试通过；技能自检
  160/160；`npm run build` 成功；构建产物只包含 `ontology-v0.1.3`；`git diff --check` 通过。
- 边界：版本收口只准备 Merge Request；不自动合并、不创建 tag、不创建 GitLab Release、
  不部署，也不拉 `release/ontology-v0.1.3` 分支。


### 2026-10-22 · V3 经营驾驶舱交付看板（iba-demo demo_1021）

- 页面与路由（2026-10-22 18:30 修订）：三个独立入口 `/cockpit/overview`、`/cockpit/operations`、
  `/cockpit/analysis`；`/cockpit` 与 `/` 直接返回经营看板，`/cockpit/home` 保留为兼容地址（FastAPI 307、
  静态站客户端改写为 `overview`）。三页只挂载一个 `ProBiDashboard`，顶部筛选器和三个 Tab 均来自交付配置；路由只激活
  对应 Tab，并保留 Fuxi 的 `id=1|2`。不渲染工作区、会话区或第二套导航。
- 交付包（2026-10-22 18:30）：拉取 `iba-demo` 分支 `feature/demo_1021@37975c7`，导入 13 份模板、
  122 个组件、12 个插槽声明和 `insight-components/`；更新 `pro-bi-ui.min.js` 到
  `011269f8`，CSS 未变化，继续复用 `b1ee836d` 和 Vue 3.5.25。源 JSON 和 `insights.js` 保持原样，
  哈希、类型统计和缺项记录在 `source.json`。
- 原生组件渲染（2026-10-22 18:30）：撤回原型 DOM/CSS 快照方案，删除 `static/cockpit/layout/`
  和 `scripts/extract_cockpit_layout.mjs`。页面读取 `static/cockpit/metadata/runtime.json`，
  通过 `ProBiDashboard` 渲染原生 ProUI 卡片、图表、表格、分组、按钮组、流程弧形图和模板容器；
  卡片标题、图例、工具栏、按钮和间距使用组件自身样式。
- 数据回放（2026-10-22 18:30）：冻结 pdt 正式页的 39 个 AP 查询、3 个批量查询和 4 个头盔图请求到
  `data-snapshots.json`，浏览器通过 `ProUIBi.configureBi` 按请求键回放，不访问 AP、PDT 或生产接口。
  快照不包含 Cookie、Token、账号或用户身份；未捕获的查询在原卡片显示组件自带的
  “未找到该 AP 查询的发布快照”，宿主不补造数据。时间筛选切到 `2026-08-13 19:06:09`
  后无组件错误，销售额卡按交付绑定更新。
- 筛选联动：顶部“采购订单创建时间维度”按交付配置只绑定当前 Tab 的一个指标卡
  （经营看板绑“促进增长｜销售额”，运营 360 绑“保障交付｜出货量”），其余卡片不声明该维度绑定。
  该行为与交付配置一致，宿主不自行扩展联动范围。
- 智能分析插槽（2026-10-22 16:23 修订）：交付根配置没有 `insights` 字段，宿主从 `insights.json`
  补入 12 个插槽声明：经营看板 0 个、运营 360 4 个、穿透式问题分析 8 个。插槽位置按交付配置，
  内容改为调用主服务 `/api/cockpit/analyses` 的真实模型分析；页面加载后通过 `requestIdleCallback`
  （回退 800ms 定时）预取商机、报价、投标、订单、发货 5 个环节，每个环节只提交一次，前端最多
  3 个并发，其余排队。插槽挂载复用同一 Promise，点击头盔节点不重新分析，只有“重新分析”强制刷新。
  首次分析通常约 10–20 秒，已完成范围复用 SQLite 历史；失败时显示错误和重试。交付
  `insight-components/` 恢复为页面实际挂载的插槽组件，保留交付 DOM/CSS、组件名称和插入位置；
  组件内的原型演示数字改为消费同一份真实分析结果：阶段数字取 `evidence.facts`，记录级主因取
  `evidence.records`，风险/原因/建议取 `result.summary`、`result.causes`、`result.recommendations`
  和 `result.limitations`。缺失字段显示“未提供”，不再使用静态 mock 文案。新增
  `insight-components/shared.js` 统一取值和重试；插槽入口、内部 registry/shared、子组件和 CSS
  全部沿用同一 `cockpit-version` 查询串，避免部署后 HTML 已更新但仍命中旧子组件模块缓存。
- 交互：头盔图点击节点切换环节模板；运营页报价、投标、订单接收节点分别挂载 `quote-summary`、
  `bid-summary`、`order-sign-summary`；穿透页订单接收、发货节点分别挂载 `order-risk-summary`
  和 4 个发货插槽。页内 Tab 切换同步 URL 并保留 `id`。
- 流程与风险卡片（2026-10-22 17:28 修订）：穿透式问题分析的销售额口径头盔图移除“投标”，
  使用交付快照内已有的三节点响应（商机获取 → 订单接收 → 发货），标题同步；运营 360 的
  全流程仍保留投标。商机获取、订单接收、发货三类分析插槽统一使用共享
  `createStageRiskComponent`，按初期 mock 的轻量结构统一为概况、风险、原因、建议四段：13px／22px
  字号行高、8px 卡片间距、`14px 16px 12px` 内边距，概况事实使用普通文本行而非胶囊，原因使用
  “原因N”浅色标签，建议恢复为“正文 + 责任角色 + 期限 + 关闭”的单行组合；验收、补充说明、证据
  和限制收进折叠区。源 `template-registry.json`、`data-snapshots.json` 不改写，运行时仅对
  `SALES_CALIBER` 优先读取已捕获的三节点网关响应并裁剪分析模板规则。
- 紧凑分析输出（2026-10-22 17:28 修订）：分析结果契约升级为 `compact-v1`，缓存 scope 同步带版本号，
  避免继续复用旧长文本结果；模型输出限制为短摘要、短原因、50 字内措施、单一责任角色、
  `deadlineDays` 工作日和 50 字内验收，补充说明单独放入可选 `detail`。任务令优先使用
  `deadlineDays`，旧分析缺少该字段时回退 10 个工作日。三个风险插槽直接展示完整短摘要和原因行，
  责任角色与期限不再拆成三列元信息，验收、补充说明、证据和限制默认折叠，减少与 mock 的视觉差异。
- 自适应高度（2026-10-22 16:59）：含内嵌分析插槽的 ProUI 卡片为图表/KPI 内容保留
  `clamp(112px, 46%, 260px)` 的自适应最小高度，分析插槽占用剩余空间并在内部滚动；修复运营页
  和穿透页 KPI 子卡被压到 8px 的问题，实测恢复为约 118–120px。1280、1440、1920 三档视口下
  三个路由均无页面横向溢出；分析卡片在 1440px 和 390px 视口下均无内部横向溢出。真实模型返回的
  原因和建议条数仍可能多于 mock，卡片按内容自适应高度，不用静态条数或假数据补齐。
- 身份：Fuxi 统一使用 `id` 查询参数，`1=总裁`、`2=分析员`；当前三页内容和功能对两个 `id`
  完全一致，两个人都可访问，`id` 仅作为将来差异化的预留标识。页面和 API 均不使用 `role`。
- 已知差异：商机模板 `2112062888320483329` 的 `group-9ypz7vwt` 引用 `share-bar-79fsomq9`，
  交付缺少该子组件定义，运行包保留空位；五个进度卡同值、销售标题绑定采购指标等现象来自交付
  AP 配置本身，页面保留原值。详细清单见 `docs/specs/cockpit-v3-metadata-gaps.md`。
- 主要文件：`bi_agent/cockpit/metadata.py`、`bi_agent/cockpit/runtime.py`、`bi_agent/web/app.py`、
  `bi_agent/web/static/cockpit/{cockpit.js,cockpit.css,index.html}`、
  `bi_agent/web/static/cockpit/insight-components/`、
  `bi_agent/web/static/cockpit/metadata/{runtime.json,iba-demo-1021/}`、
  `tests/test_cockpit_poc.py`、`tests/test_cockpit_resource_contract.py`、
  `tests/test_cockpit_metadata.py`、`docs/specs/cockpit-v3-poc.md`、
  `docs/specs/cockpit-v3-metadata-gaps.md`、`README.md`、`DEPLOYMENT.md`。
- 验证（2026-10-22 17:15）：驾驶舱契约测试 41 项通过；`node --check` 和 `git diff --check` 通过。
  浏览器验证三个路由在 `id=1|2` 下激活正确 Tab，页面只有一个 `ProBiDashboard`；
  运营页加载后后台出现尚未显示环节的分析任务，证明空闲预取生效；点击头盔节点后
  报价、投标、订单签单、订单风险及 4 个发货插槽均直接显示已完成结果，无组件错误；另以真实
  已完成分析逐一挂载 12 个交付插槽组件，全部通过渲染、无横向溢出，主因拆解按记录聚合显示
  4 类主因和逐单金额/超期天数。
- 浏览器补充（2026-10-22 17:28 修订）：穿透页头盔图实际节点为商机获取、订单接收、发货三个；
  依次点击三个节点后均挂载 `.stage-risk-analysis`，旧 `.opportunity-risk` /
  `.order-risk-summary` / `.shipment-risk-summary` 独立结构数量为 0。计算样式确认卡片为
  13px／22px、8px 间距、`14px 16px 12px` 内边距；事实块无背景胶囊，原因标签、建议责任人、
  期限和关闭按钮均按 mock 结构渲染，1440px 与 390px 视口下卡片内部无横向溢出。
- 部署（2026-10-22 17:38 修订）：`172.16.10.34:8876` 静态站更新到
  `feature/cockpit-v3-poc@74d642d`，HTML与插槽模块使用同一版本串；62个发布文件中manifest列出的
  61个文件哈希全部通过，三个页面、bootstrap与版本化模块返回200。8877旁路API同步到同一提交，
  `compact-v1`、期限字段和缓存契约版本生效；独立代码目录 `api-74d642d`，健康检查正常。
  原16条完成分析和原始数据目录保留，旧站／SQLite一致备份／回滚环境保存在
  `backups/deploy-20261022-173750-pre-74d642d`；8765主服务和用户历史会话未修改。
  浏览器加载及41项相关测试通过；真实模型验收被网关预算阻塞：HTTP400 `budget_exceeded`，
  费用约30.52／额度30.00，新分析如实显示失败，未替换账号或用固定分析冒充成功。
  历史发布 `b6eaaca` 的静态旧缓存修复保留，旧站回滚副本仍在。
- 部署（2026-10-22 16:13，历史）：`172.16.10.34:8876` 曾更新到 `feature/cockpit-v3-poc@38ad4f0`，
  HTML 版本串为 `38ad4f0`，发布目录 38 个文件且 `manifest.sha256` 全部通过。线上三条路由、
  `/cockpit/home` 改写、`id=1|2`、Tab 同步和头盔节点插槽均已验证。使用 `id=2` 冷启动运营页时，
  后端在空闲阶段新建报价、订单两个环节分析任务，证明 5 个环节预取生效；点击节点后插槽直接显示
  真实模型结果。部署前旧站备份为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/backups/site-20261022-161324-pre-a438fcd`，
  暂存目录为 `site-next-38ad4f0`。未重启 8877 API、未修改 8765 主服务、`dataset/` 和用户历史数据。
- 部署（2026-10-22 15:53，历史）：`172.16.10.34:8876` 曾更新到
  `feature/cockpit-v3-poc@a438fcd`（静态插槽版本），备份为
  `backups/site-20261022-155309-pre-2b828a5`。
- 部署（2026-10-22 14:49，历史）：`172.16.10.34:8876` 曾更新到
  `feature/cockpit-v3-poc@2b828a5`，旧站备份为 `backups/site-20261022-144900-pre-5501d6f`。
- 代理与旁路 API（2026-10-22 12:00，历史）：nginx 的 `location /api/cockpit/` 转发到
  `172.16.10.34:8877` 的 `eimosp-cockpit-api`；服务目录为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/api-017d65f`，数据独立写入
  `api-data/`。本轮不重启 API、不修改 8765 主服务和用户历史数据。
- 边界：真实业务数据源尚未映射，Fuxi 宿主尚未联调；POC 执行器按单进程运行。8877 旁路 API
  当前由 `setsid nohup` 启动，没有 systemd 自动拉起，服务器重启后需要重新启动。

### 2026-10-23 11:55 · 预收口 ontology-v0.1.4（PATCH）

- 变化：按用户明确指定，把 `feature/cockpit-v3-poc` 上的 V3 经营驾驶舱交付预收口为
  `ontology-v0.1.4`，版本位次为 PATCH；本版本范围仅包含该分支的驾驶舱能力，不包含同期
  工作区中的其它并行修改。
- 产品能力：三个独立看板路由、交付 ProUI 元数据与模板、三节点穿透式分析头盔图、空闲预取
  的真实模型分析插槽、交付快照回放，以及按早期 mock 结构收口的阶段风险卡片。
- 版本统一：`pyproject.toml`、`frontend/package.json`、`frontend/package-lock.json` 更新为
  `0.1.4`；Python 包、FastAPI、前端 `PRODUCT_VERSION`、首屏版本标签统一为
  `ontology-v0.1.4`；前端构建产物 `bi_agent/web/static/vendor/antd/workbench.js` 同步重建。
- 文档与测试：新增 `docs/versions/ontology-v0.1.4.md`，同步版本索引、版本规范、根 README、
  `AGENTS.md`、部署示例和版本契约测试；现行索引同时修正为 `ontology-v0.1.3` 已于 2026-10-20
  发布、tag 指向 `a805a66` 的事实，已发布的 `ontology-v0.1.3.md` 保持历史原貌。
- 验证：版本契约、驾驶舱元数据、资源契约和 POC 测试在提交前执行；前端 `npm run build` 成功；
  `git diff --check` 通过。
- 边界：只准备并推送临时分支、创建到 `master` 的 Merge Request；不自动合并、不创建 tag、
  不创建 GitLab Release、不部署，也不拉 `release/ontology-v0.1.4` 分支。tag 与 Release 等
  用户确认 MR 合入后另行授权。

### 2026-10-23 · Cockpit主服务分析路线与联调收口

- 插槽默认main路线，直接复用现有WebSession的意图路由、数据源工具、准入／租约／取消及交付校验，
  与聊天SSE共享执行生命周期；独立路线仅作为联调对照，禁止失败后静默降级。
- 同一页面全部插槽使用同一engine；支持生产全站锁定，选型后不维持两套并行分析服务。main按需串行执行，
  不再空闲预取五个环节；主服务正文直接呈现，不为卡片追加模型改写。
- 主服务支持受限交付、待确认口径、补充后重新分析及执行轨迹；不完整或未经提交的候选正文不回填。
  临时分析会话只回收内存，不影响用户聊天与历史数据；main源指纹不冒充数据库快照，不复用旧完成结果。
- 独立路线可读取同身份、同范围main任务的服务端冻结证据，保留哈希与基线ID；原始查询行不能仅凭引用
  被标为已验证根因。无证据基线不能用于生成独立根因。图表快照与实时分析尚未同源对账，页面明确披露。
- 本地真实主服务调用约32.8秒、9轮模型响应、10次工具调用；本体／数据网关域名解析失败，最终受限交付，
  未生成虚构根因。这是执行链验证，不代表真实业务效果已经验收。
- 主要文件：`bi_agent/cockpit/main_service.py`、`router.py`、`agent.py`、`store.py`、`bi_agent/web/app.py`、
  cockpit JS/CSS、`.env.example`、`tests/test_cockpit_main_service.py`、`docs/specs/cockpit-analysis-engines.md`。
- 验证：相关测试123项通过、1项既有条件跳过、34个子测试通过；JS语法和diff空白检查通过。
- 本轮仅本地实现与分支交付，不部署、不修改8765／8877服务器或用户历史会话。
