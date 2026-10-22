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

- 页面（2026-10-22 修订）：新增三个独立入口 `/cockpit/overview`、`/cockpit/operations`、
  `/cockpit/analysis`，`/cockpit` 以307跳转总览。三页只渲染看板本体，顶部仅保留四个驾驶舱
  视图 Tab；移除左侧工作区、会话区、宿主页面标题和外层筛选栏；旧工作台和旧 BI 静态包保留。
- 布局与元数据（2026-10-22 修订）：交付元数据缺少原型布局、卡片几何和部分组件，因此新增
  `static/cockpit/layout/` 原型DOM/CSS快照作为逐项布局基线；`iba-demo/feature/demo_1021`
  commit `17152091` 的模板注册表、16个声明式插槽和100项显式绑定继续用于覆盖判断和差异披露。
  交付共130个组件配置，源配置为AP 100项／mock 30项。提取脚本保留来源哈希；未复制示例鉴权代码，
  未用近似图表填充缺项。
- 顶部导航与 ProUI 挂载（2026-10-22）：看板顶部新增“首页”“全局经营看板”“运营 360 整体分析”
  “穿透式问题分析”四个 Tab，三个独立路由和所有 Tab／页内跳转均保留 Fuxi 的 `id=1|2`。
  新增 `bi_agent/cockpit/runtime.py` 与 `scripts/export_cockpit_runtime.py`，从元数据编译结果导出
  `static/cockpit/metadata/runtime.json`（7个组件、19个挂载点）；纯静态8876页面不依赖
  `/api/cockpit/metadata`。年度图挂载 `ProBarChart`／`ProDualAxisChart`，运营与穿透头盔图挂载
  `ProMiniCpGraph`，节点点击可切换环节。没有对应组件或配置的风险卡、节点入口卡、AI卡片、
  周期对标、履约率第四卡和专项分析区继续按原型尺寸留空。
- 组件资源（2026-10-22 修订）：从同一 `iba-demo` commit 同步新版 `pro-bi-ui.min.js`
  与 `pro-ui.min.css`，更新内容哈希缓存参数并保留原许可声明；Vue 仍复用 3.5.25。
  `insights.js` 原样冻结并生成运行时 `insights.json`。组件包更新本身不改变当前原型静态
  DOM/CSS 渲染路径，年度图、头盔图和缺失卡片仍需后续接入 ProBI 或补充元数据。
- 组件包验证（2026-10-22）：本地浏览器加载新 UMD 后暴露90个导出；年度图已用
  `ProBarChart`／`ProDualAxisChart` 生成 canvas，运营和穿透头盔图已用 `ProMiniCpGraph`
  生成 canvas/SVG。首页无直接 ProUI 映射的 11 个风险／流程位，运营各环节 9 个入口／对标位，
  穿透各环节 1–8 个 AI／专项位继续留空。
- 数据与展示：100项显式绑定原型事实；原型10条超期订单共24.3亿元与AI证据一致，
  保留原型7条风险、订单结构、待签清单、出货目标／实绩／预测及产品部月度演示分配规则。
  页面仅开放原型固定期间／全产品部；旧DemoSource接口、分析历史与任务保持保留并以source隔离。
- 差异披露：15个原型视图原始标记119个候选空位；其中19个年度图／头盔图挂载点已由 ProUI 填充，
  其余按原型宽高清空，页面底部只汇总当前视图仍留空的项，不显示固定AI结论替代交付组件。
  商机缺少的 `share-bar-79fsomq9` 及原型多时点／金额口径冲突、头盔像素级几何、
  周期对标、发货第四卡片、专项模板和下钻动作等继续在文档中列明。
- 交互：看板内保留指标年度销售／出货切换、首页八节点进入运营环节、运营标题跳转和明确的无配置提示；
  缺失按钮不再以近似动作冒充。纯看板页面不渲染旧角色切换、分析历史或任务抽屉。
- 身份与穿透入口（2026-10-22 修订）：Fuxi 统一使用 `id` 查询参数，`1=总裁`、`2=分析员`；
  当前原型三页的内容、按钮和交互对两个 `id` 完全一致，两个人都可访问，`id` 仅作为将来差异化的预留标识。
  页面和 API 均移除 `role` 身份参数，不维护两套身份地址；`/cockpit` 总入口和页内跳转均保留当前 `id`
  及视图参数。首页重点风险卡组件缺失时仍保留“查看三级穿透”“AI 改善建议”按钮，分别进入发货分析和
  带 `focus=advice` 的分析页。
- 分析与任务：后端证据、受控模型分析、报告和模拟任务接口保留；模型失败不回退为预写结论。
  当前三页不自动发起模型分析，缺失的AI卡片按原型尺寸留空；后续补交付插槽配置后再接入。
- 闭环：模拟任务令支持草稿编辑、下发、接收、反馈和验收关闭，当前只校验状态与 revision，
  不按 `id` 分配操作权限；幂等生成和 revision 防止重复创建及覆盖更新。SQLite 单独保存在
  gitignore 的 `dataset/cockpit/`，不删除原会话。
- 预测：展示演示业务已有预测；发货页提供明确假设下的金额化解测算，不声称已实现统计预测。
- 主要文件：`bi_agent/cockpit/`、`bi_agent/web/static/cockpit/`（含 `layout/`）、
  `scripts/extract_cockpit_layout.mjs`、`bi_agent/web/app.py`、`tests/test_cockpit_poc.py`、
  `tests/test_cockpit_resource_contract.py`、`tests/test_cockpit_metadata.py`、
  `docs/specs/cockpit-v3-poc.md`、`docs/specs/cockpit-v3-metadata-gaps.md`、`README.md`、
  `DEPLOYMENT.md`、`.env.example`、`.gitignore`、`.gitattributes`。
- 验证（2026-10-22）：驾驶舱契约测试36项通过；JavaScript及提取脚本语法通过，`git diff --check`通过。
  浏览器验证四个Tab、`id=2`保留、销售／出货视图、运营和穿透头盔图，年度图与头盔图分别生成
  canvas／SVG；“查看三级穿透”“AI 改善建议”、销售额指标和环节跳转通过；关键缺失区尺寸与原型捕获值一致。
- 部署（2026-10-22 10:54）：三个看板页已作为纯静态站更新到
  `http://172.16.10.34:8876/cockpit/{overview,operations,analysis}`，由独立
  `eimosp-cockpit-8876` nginx 容器承载。发布内容为 commit `4583b43`，包含四个顶部 Tab、
  新版 ProUI `c38cbf36` 和静态 `runtime.json`，旧站备份在
  `backups/site-20261022-105409`。未部署第二套后端、未修改或重启 `8765` 主服务、
  未复制运行数据；`8765/healthz` 和 `/workbench` 均保持 200。
  远程 1440px 已验证年度图、头盔图和 `id` 参数保留，页面无运行时错误或横向溢出。
- 边界：真实业务数据源尚未映射，Fuxi 宿主尚未联调；POC 执行器按单进程运行。
  未创建 tag／Release／MR，未修改用户历史数据。
