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

- 页面：新增独立 `/cockpit` 入口，包含全局经营看板、运营 360 整体分析、穿透式问题分析；
  采用新版 ProUI 看板、KPI、头盔图、表格及智能分析插槽，旧工作台和旧 BI 静态包保留。
- 组件交付同步（2026-10-21 修订）：重新下载发布的 BI UMD 和配套基础 CSS，记录 SHA-256 并更新
  资源缓存参数；Vue版本及文件哈希不变，继续复用现有运行时。导入 `iba-demo/feature/demo_1021`
  commit `55842efc` 的根组件、14份子模板（共130个组件配置）和3个分析插槽声明，保存为参考元数据；
  记录商机模板的一处缺失子组件引用，不复制示例鉴权代码，不直接替换当前POC页面或连接AP接口。
- 角色与交互：固定总裁／分析员视角，URL 可指定角色；总裁通过按钮看分析和确认任务，
  分析员使用 Fuxi 对话，页面提供上下文复制，不重建聊天、不自动向 Fuxi 发送消息。
- 数据：新增隔离演示源和未来本体／数据库适配边界；期间、产品部和环节共享快照。
  订未发统一为订单接收减已发货、由正常与超期组成；超期金额和四类主因由逐单记录汇总；
  报价、商机、投标、订单变更各自使用独立记录，月度目标、实绩与业务预测可对账。
- 分析：前两页直接取数，第三页由主服务调用既有模型适配器，先用受控工具取证再填充风险／
  原因／建议。限制工具、并发和轮次，校验证据引用、结构与原因—建议关系；
  失败明确展示，不用固定结论冒充成功。支持取消、重试、缓存、范围隔离和转义 HTML 报告。
- 闭环：模拟任务令支持草稿编辑、总裁下发、分析员接收／反馈、总裁验收；幂等生成和 revision
  防止重复创建及覆盖更新。SQLite 单独保存在 gitignore 的 `dataset/cockpit/`，不删除原会话。
- 预测：展示演示业务已有预测；发货页提供明确假设下的金额化解测算，不声称已实现统计预测。
- 主要文件：`bi_agent/cockpit/`、`bi_agent/web/static/cockpit/`、`bi_agent/web/app.py`、
  `tests/test_cockpit_poc.py`、`docs/specs/cockpit-v3-poc.md`、`README.md`、`.env.example`、`.gitignore`、`.gitattributes`。
- 验证：相关后端测试 101 项通过、1 项既有条件跳过、11 子测试通过；前端回归 76 项通过；
  JavaScript 语法及 `git diff --check` 通过。独立本地浏览器验证三个页面、真实模型发货／报价／
  商机分析、范围切换、分析恢复及模拟任务完整流转。本次资源／元数据修订相关测试 27 项通过，
  新资源下看板图表、运营头盔和明细表浏览器复查正常。
- 边界：真实业务数据源尚未映射，Fuxi 宿主尚未联调；POC 执行器按单进程运行。
  本轮仅本地实现与 GitLab 分支交付，未部署、未创建 tag／Release／MR，未修改用户历史数据。
