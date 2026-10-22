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


### 2026-10-21 · V3 经营驾驶舱 POC 与主服务分析插槽

- 页面（2026-10-22 修订）：四个独立入口 `/cockpit/home`、`/cockpit/overview`、
  `/cockpit/operations`、`/cockpit/analysis`，`/cockpit` 与 `/` 直接返回总览页，首页保留但不默认打开。
  四页只渲染看板本体，顶部使用 ProUI `pro-tabs` 组件样式保留“首页”“全局经营看板”
  “运营 360 整体分析”“穿透式问题分析”四个视图 Tab；移除左侧工作区、会话区、宿主页面标题
  和外层筛选栏。`/cockpit/overview` 仍直接显示全局经营看板。
- 原生组件渲染（2026-10-22 修订）：撤回原型 DOM/CSS 快照方案，删除 `static/cockpit/layout/`
  和 `scripts/extract_cockpit_layout.mjs`。页面读取 `static/cockpit/metadata/runtime.json`，
  通过 `ProBiDashboard` 渲染原生 ProUI 卡片、图表、表格、分组、按钮组和模板容器；
  卡片标题、图例、工具栏、按钮和间距使用组件自身样式，不再追求与原型逐像素一致。
- 交付原样渲染（2026-10-22 修订）：同步 `iba-demo/feature/demo_1021` commit `7e45062`，
  新增交付 Tab“储能产品线整体经营分析”（模板 `2113106174095179778`），子模板 15 份、组件 139 个、
  分析插槽 17 个。`runtime.py` 直接输出交付模板，`position`／`parentId`／`children`／标题／样式不再改写，
  宿主只替换 `dataConfig` 和附加 `cockpitBindingKey`；四页组件与交付逐字段一致，106 个组件绑定演示数据。
- 缺失披露：不再过滤组件类型、不再合成模板或追加卡片；商机模板引用的
  `share-bar-79fsomq9` 缺少定义，分组内该位置保持空位。红区报价专项、
  毛利／净利／回款详情、图表下钻、客户操作列、运营周期对标和履约率第四卡仍缺组件或动作配置。
  运营页交付头盔的 `defaultActiveKey` 与节点 ID 不匹配，首屏模板区按交付留空，点击节点后再加载；
  页面底部列出运行包中的缺项，不用近似卡片冒充交付组件。
- 交互：经营指标卡可切换销售额／出货量模板；运营头盔图点击节点切换七个环节模板；
  穿透头盔图点击节点切换四类风险模板。页面之间仅保留这四个 Tab 和看板内可确认的组件交互。
- 身份：Fuxi 统一使用 `id` 查询参数，`1=总裁`、`2=分析员`；当前四页内容和功能对两个 `id`
  完全一致，两个人都可访问，`id` 仅作为将来差异化的预留标识。页面和 API 均不使用 `role`，
  所有 Tab 和页内跳转保留当前 `id`。
- 分析与任务：17 个交付 `insights` 按页面和 `embedPath` 传入 `ProBiDashboard`，由 `#insight-*`
  具名插槽调用 `POST /api/cockpit/analyses` 执行真实模型分析并轮询回填；同一环节的多个插槽复用一次结果，
  客户端限 3 并发并对 429 重试。模型失败或没有内容时显示空位／错误，不回退为预写结论。
  后端证据、报告和模拟任务接口保留，旧的分析、历史和任务抽屉不再渲染。
- 闭环：模拟任务令支持草稿编辑、下发、接收、反馈和验收关闭，当前只校验状态与 revision，
  不按 `id` 分配操作权限；幂等生成和 revision 防止重复创建及覆盖更新。SQLite 单独保存在
  gitignore 的 `dataset/cockpit/`，不删除原会话。
- 预测：展示演示业务已有预测；发货页提供明确假设下的金额化解测算，不声称已实现统计预测。
- 组件资源：`pro-bi-ui.min.js`（`c38cbf36`）与 `pro-ui.min.css`（`b1ee836d`）与本次交付 commit
  哈希一致，无需重复下载；Vue 仍复用 3.5.25。冻结 `components.json`、`template-registry.json`、
  `insights.js` 并派生 `insights.json`，源 JSON 不改写。
- 主要文件：`bi_agent/cockpit/runtime.py`、`bi_agent/web/static/cockpit/{cockpit.js,cockpit.css,index.html}`、
  `bi_agent/web/static/cockpit/metadata/runtime.json`、`scripts/export_cockpit_runtime.py`、
  `tests/test_cockpit_poc.py`、`tests/test_cockpit_resource_contract.py`、
  `tests/test_cockpit_metadata.py`、`docs/specs/cockpit-v3-poc.md`、
  `docs/specs/cockpit-v3-metadata-gaps.md`、`README.md`、`DEPLOYMENT.md`。
- 验证（2026-10-22）：驾驶舱契约测试 37 项通过，其中新增“页面组件与交付模板逐字段一致”断言；
  `node --check` 通过；浏览器验证四个路由、四个 Tab、`id=1|2`、首页指标＋头盔＋风险插槽、
  运营和穿透头盔图、表格和 KPI；真实模型已完成首页 `focus-risks` 与穿透页 `sales-shipment-issues`
  分析并返回原因和证据数量；1440px 与 480px 无横向溢出。
- 首页与顶部组件化（2026-10-22）：`/cockpit/home` 直接挂载交付新增的首页模板，
  不再由宿主从其他两页挑组件拼装；顶部四个 Tab 改用 ProUI `pro-tabs` 结构和活动下划线，
  窄屏自动把当前 Tab 滚入可视区，缓存参数升至 `proui-dashboard-v4`。
  `/cockpit` 直接返回 `overview`，首页保留但不是默认路由。本地浏览器验证四个路由、
  `id=1|2`、活动条定位和 1440px／480px 布局。
- 部署（2026-10-22 12:00）：`172.16.10.34:8876` 已切换到 `feature/cockpit-v3-poc` commit
  `017d65f` 的交付原样渲染版本，发布目录共 9 个文件并通过 `manifest.sha256` 校验；`home`、
  `overview`、`operations`、`analysis` 和四个 ProUI Tab 均正常返回，运行时缓存版本为
  `proui-dashboard-v4`。远程浏览器验证 `id=1|2` 传播、活动下划线、首页和穿透页模型分析插槽、
  KPI／图表／表格渲染；1440px 与 480px 无横向溢出，窄屏活动 Tab 自动滚入可视区，无 JS 异常，
  网络请求无 4xx／5xx，ProUI 仍有非致命的 Vue 属性透传警告。
- 代理与旁路 API（2026-10-22 12:00）：nginx 新增 `location /api/cockpit/`，转发到独立
  `172.16.10.34:8877` 的 `eimosp-cockpit-api`；服务目录为
  `/home/data/zhangzhen_home/zhangzhen/eimosp-cockpit-8876/api-017d65f`，PID 在 `app.pid`，
  日志在 `api.log`，数据独立写入 `api-data/`。`bootstrap`、`metadata` 经 8876 代理返回 200，
  其他 `/api/*` 仍返回 404。经代理发起的真实模型分析 `50074713092e444ab9f4918ee8c02a34`
  已完成发货环节分析，结果为 `completed`。站点备份为
  `backups/site-20261022-115417-pre-017d65f`，nginx 配置备份为
  `backups/conf-20261022-115417-pre-proxy/default.conf`。未修改或重启 8765 主服务，未复制运行数据，
  未创建 tag／Release／MR，未修改用户历史数据。
- 边界：真实业务数据源尚未映射，Fuxi 宿主尚未联调；POC 执行器按单进程运行。8877 旁路 API
  当前由 `setsid nohup` 启动，没有 systemd 自动拉起，服务器重启后需要重新启动。
