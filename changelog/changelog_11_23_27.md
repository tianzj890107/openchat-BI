# 变更记录（2026-11-23 至 2026-11-27）

按自然周维护。

> 2026-11-24 建立本周记录。

### 2026-11-24 分析 Agent 重试 DeepSeek 推理字段协议错误

- Team 网关和直连 DeepSeek 遇到要求回传 `reasoning_content` 的 HTTP 400 时，在收到首个流式数据块前最多重试 5 次。首次重试沿用历史工具结果的兼容转换，后续重试只重发当前模型请求。已完成的查询、会话历史及工具结果保留，流开始后按原错误结束。
- 本地相关回归 38 项通过，覆盖第五次重试成功、次数耗尽、首块前后报错和其他错误保持原行为。

### 2026-11-24 本体消费展示工作台规格

- 明确由分析仓交付 `/workbench-agentkit`，按固定提交从 GitLab 提取 AgentKit UI 组件并持有依赖锁，分析对话继续接本仓执行与会话接口。
- 规定独立展示与 V6.1 风险卡接入共用对话、看板、证据和本体子图，以 PACK 商机覆盖作为首期验收场景。
- 本次交付为设计规格，入口、接口和浏览器验收列入实施阶段。主要文件为 [本体消费展示工作台规格](../docs/specs/workbench-agentkit-ontology-consumption.md)。

### 2026-11-24 实施：AgentKit 工作台首期骨架（红测驱动）

- 新入口 `GET /workbench-agentkit`：沿用 `APP_ROOT_PATH`（如 `/api/ontology-agentic-analytics/workbench-agentkit`），无前缀与配置前缀都能打开；返回 `Cache-Control: no-store`，静态资源按文件 mtime 注入 `?v=`，不再使用写死版本号。`/` 与 `/workbench` 继续返回原 Pro UI 页面，与新入口互不影响。
- 页面壳由 `bi_agent/web/static/agentkit/index.html` 提供首屏骨架（顶部交接区、左会话列表、中对话、右结果看板、窄屏切换按钮），React 挂载后接管；产物为 `bi_agent/web/static/vendor/agentkit/workbench-agentkit.{js,css}`（约 162 KB / 10 KB），与 Pro UI 的 `vendor/antd` 完全分开。
- 前端源码在 `frontend/agentkit/`：`state.js` 把 `/api/chat`、`/api/choice` 的 SSE 投影成单一会话状态（正文增量合并、`tool_start`/`tool_input`/`tool_result` 合并到原调用并保留 `ontology_entities`、澄清暂停、迟到/旧轮次事件丢弃、`done` 终态幂等、停止保留已得结论）；`api.js` 负责带 `APP_ROOT_PATH` 的请求与 SSE 解析；组件 `SessionList/Thread/Composer/Board/HandoffBanner` 覆盖会话新建与切换、工具过程、澄清多选提交（与 AskUser 一致）、停止与重试、结果表/图/指标。
- 右栏按后端真实 `tool_result` 契约渲染（`table` / `chart` / `multi_chart` / `ontology_entities` / `duration_ms` / `error_code`）：`results.js` 负责把表格列标签、ECharts 系列、饼图切片、多图拆成看板卡片，并输出证据行与去重后的本体命中（同一编码在不同本体库分别计）；图表支持柱状、折线、饼图三类；`ChartGenerateMultiDim` 的 `multi_chart`（单对象 + `dimensions`）渲染为一张可切维度的卡片；证据区展示工具、耗时、命中数与错误码。
- 本体子图：命中项可打开 `OntologyGraph`，经 `POST /api/ontology/subgraph`（`strategy=context`，带 `repository_id`）取数，复用 `@boulderaitech/ontology-graph` 与 `frontend/src/ontologyGraphModel.js` 渲染，点击节点看定义；编码不合法时不发请求，空子图与渲染失败分别降级提示。
- V6.1 交接：从 `source/anchor/period/filters/evidence/handoff` 查询参数读取卡片上下文并显示「按此范围继续」横幅；缺锚点时显示不可用反馈并提供「返回来源卡」「重新发起分析」两个出口，不再静默丢弃。新增 `buildHandoffUrl()`，宿主侧用同一函数拼 `/workbench-agentkit?...`，并有往返用例锁定契约。
- AgentKit 上游按固定提交 `b8df86dfa3c30de6676cd1d768cda504bf3c3338` 按文件导入：新增 `scripts/import_agentkit_upstream.py`（`git archive --remote` + `get-tar-commit-id` 校验，`--check` 只校验；`dev` 前进即报错），导入 `aui-thread.json`、`aui-thread-list.json`、`confirm-dialog.json`、`registry.json` 与 `thread.aui.tsx`、`thread-list.aui.tsx`、`tool-group.aui.tsx`、`tool-call.tsx`、`markdown-text.tsx` 到 `frontend/agentkit/upstream/`，来源与本地落点记在 `frontend/agentkit/UPSTREAM.md`。
- 构建：新增 `frontend/vite.agentkit.config.js`（独立 IIFE + 独立样式表，`publicDir: false`，不把 Vue/Pro UI 公共库带进产物），日常构建只读本仓文件。
- 测试：先写红测再实现——`tests/test_workbench_agentkit_route.py`（4 项，路由未实现时为 404，现全部通过）、`tests/workbench_agentkit_state.test.mjs`（11 项状态投影与交接 URL）、`tests/workbench_agentkit_results.test.mjs`（7 项结果/证据/子图请求适配）、`tests/workbench_agentkit_shell.test.mjs`（7 项页面壳/右栏/主题作用域/构建配置/上游记录）。AgentKit 相关 Node 25 项通过；`test_direct_root_workbench_entry.py`、`test_application_base_path.py`（10 项）与 `test_anonymous_read_surface_red.py`、`test_cockpit_main_service.py`（40 项）通过。
- 未完成（不在本次范围）：assistant-ui 运行时与上游 TSX 的逐项适配、真实 PACK 数据链路与 V6.1 宿主联调、浏览器实点验收。主要文件：`bi_agent/web/app.py`、`bi_agent/web/static/agentkit/index.html`、`bi_agent/web/static/vendor/agentkit/`、`frontend/agentkit/`、`frontend/vite.agentkit.config.js`、`scripts/import_agentkit_upstream.py`。
