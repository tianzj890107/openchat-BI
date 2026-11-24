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
- 构建：新增 `frontend/vite.agentkit.config.js`（独立 IIFE + 独立样式表，`publicDir: false`，不把 Vue/Pro UI 公共库带进产物），日常构建只读本仓文件；产物约 532 KB（gzip 152 KB），含 assistant-ui 运行时与本体图渲染。
- assistant-ui 运行时：`frontend/agentkit/runtime.js` 用 `useExternalStoreRuntime` 把会话状态投影成消息（工具过程放消息 metadata），`AssistantRuntimeProvider` 提供运行时，`ComposerPrimitive` 接管输入、发送与停止；运行时标识写入根节点 `data-agentkit-runtime="agentkit-runtime:assistant-ui"`。依赖固定 `@assistant-ui/react@0.14.14`（与仓库既有 `@assistant-ui/store`/`tap` 锁定版本兼容），`frontend/package.json` 与 `package-lock.json` 同步。
- 上游组件适配：`frontend/agentkit/adapters/ToolGroup.jsx` 按固定提交的 `tool-group.aui.tsx` 实现，保留 Root/Trigger/Content、`data-slot` 与上游计数文案（`toolGroupCountLabel` 直接复用 `tool-display-label.ts`），交互用 Radix Collapsible + lucide 图标 + assistant-ui `useScrollLock`；Tailwind 类换成本页 `ak-tools` 样式，因此不需要引入 Tailwind 管线。上游导入清单增至 10 个文件，来源与落点见 `frontend/agentkit/UPSTREAM.md`。
- 真实链路验证（本机 2026-11-24，未改线上）：`GET /workbench-agentkit` 200 且资源按 mtime 版本化（`?v=1795505450`）；`POST /api/chat` 返回 192 个 SSE 事件（18 次工具调用、5 次带 `ontology_entities`、共 24 个本体命中），因本机本体是采购域（ecore）缺商机/销售对象而进入澄清（3 个选项）；随后 `POST /api/choice` 恢复同一轮并 `done`，返回 1705 字口径说明。此轮无表格/图表，属数据源域不匹配，不是渲染缺陷；PACK 明细与图表需在有销售本体与数据的已核准环境复验。同一实例改用采购域可回答的问题（按供应商统计采购订单金额 Top5）复验了结果渲染：18 次工具调用中返回 1 张表格（列标签＋明细行）和 1 张 `horizontal_bar` 图，经状态投影得到 2 张看板卡片、18 条证据、109 个本体命中，`done` 后状态回到 idle，说明右栏能直读真实后端契约。
- 助手正文 Markdown：新增 `frontend/agentkit/adapters/MarkdownText.jsx`（`react-markdown` + `remark-gfm`，不启用原始 HTML），标题、列表、表格、代码块按本页样式渲染，不再把 `##`、`**` 原样显示；`markdown-text.tsx` 的上游落点同步写入 `UPSTREAM.md`。产物增至约 719 KB（gzip 209 KB）。
- 宿主交接示例：新增 `docs/examples/agentkit-host-handoff.html`（V6.1 风格风险卡 → `/workbench-agentkit?...`），并新增 `tests/workbench_agentkit_host.test.mjs` 在 jsdom 中点击卡片后校验 URL 前缀与 `parseHandoff` 往返（来源、锚点、期间、筛选、证据、交接号），宿主与本页参数不会各写一套。
- 依赖锁：`frontend/package.json` / `package-lock.json` 新增 `@assistant-ui/react@0.14.14`、`@radix-ui/react-collapsible@1.1.12`、`lucide-react@0.468.0`、`class-variance-authority@0.7.1`，`jsdom@26.1.0` 为 devDependency。
- 浏览器级验收（可复现）：新增 `tests/workbench_agentkit_dom.test.mjs`，用 jsdom 执行**已提交的构建产物**与页面模板，断言 shell 挂载、assistant-ui 输入框、空态文案、V6.1 交接横幅、会话列表请求，且无脚本错误；这不是真机浏览器点击，部署后仍需人工过一遍。风险：`tests/` 侧通过 `createRequire` 从 `frontend/` 解析 jsdom，避免在仓库根重复安装。
- 测试：先写红测再实现——`tests/test_workbench_agentkit_route.py`（4 项，路由未实现时为 404，现全部通过）、`tests/workbench_agentkit_state.test.mjs`（11 项状态投影与交接 URL）、`tests/workbench_agentkit_results.test.mjs`（7 项结果/证据/子图请求适配）、`tests/workbench_agentkit_shell.test.mjs`（7 项页面壳/右栏/主题作用域/构建配置/上游记录）。AgentKit 相关 Node 25 项通过；`test_direct_root_workbench_entry.py`、`test_application_base_path.py`（10 项）与 `test_anonymous_read_surface_red.py`、`test_cockpit_main_service.py`（40 项）通过。
- 未完成（不在本次范围）：其余上游 TSX 的逐项移植（Thread/列表/附件等仍需 Tailwind 与别名管线；已移植的工具折叠组见对照表）、PACK 销售数据的成功取数复验（本机为采购域）、V6.1 真机宿主联调与真机浏览器实点验收。主要文件：`bi_agent/web/app.py`、`bi_agent/web/static/agentkit/index.html`、`bi_agent/web/static/vendor/agentkit/`、`frontend/agentkit/`、`frontend/vite.agentkit.config.js`、`scripts/import_agentkit_upstream.py`。
