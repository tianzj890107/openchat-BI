# 变更记录（2026-11-23 至 2026-11-27）

按自然周维护。

> 2026-11-24 建立本周记录。

### 2026-11-24 分析 Agent 重试 DeepSeek 推理字段协议错误

- Team 网关和直连 DeepSeek 遇到要求回传 `reasoning_content` 的 HTTP 400 时，在收到首个流式数据块前最多重试 5 次。首次重试沿用历史工具结果的兼容转换，后续重试只重发当前模型请求。已完成的查询、会话历史及工具结果保留，流开始后按原错误结束。
- 本地相关回归 38 项通过，覆盖第五次重试成功、次数耗尽、首块前后报错和其他错误保持原行为。

### 2026-11-24 本体消费展示工作台规格

- 明确由分析仓交付 `/workbench-agentkit`，按固定提交从 GitLab 提取 AgentKit UI 组件并持有依赖锁，分析对话继续接本仓执行与会话接口。
- 规定独立展示与 V6.1 风险卡接入共用对话、看板、证据和本体子图，以 PACK 商机覆盖作为首期验收场景。
- 规格与首期验收记录见 [本体消费展示工作台规格](../docs/specs/workbench-agentkit-ontology-consumption.md)。

### 2026-11-24 实施：AgentKit 工作台首期骨架（红测驱动）

- 新入口 `GET /workbench-agentkit`：沿用 `APP_ROOT_PATH`（如 `/api/ontology-agentic-analytics/workbench-agentkit`），无前缀与配置前缀都能打开；返回 `Cache-Control: no-store`，静态资源按文件 mtime 注入 `?v=`，不再使用写死版本号。首期用独立入口验收；25 日切换默认入口的最终行为见本周后续条目。
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
- 历史恢复：`hydrateTurns()` 从 `/api/conversations/*/record` 的存储消息重建轮次（用户文本、工具调用、连续 assistant 记录合并为同一气泡），切换会话即回看该轮答复与工具过程；状态测试锁定该行为。
- 宿主交接示例：新增 `docs/examples/agentkit-host-handoff.html`（V6.1 风格风险卡 → `/workbench-agentkit?...`），并新增 `tests/workbench_agentkit_host.test.mjs` 在 jsdom 中点击卡片后校验 URL 前缀与 `parseHandoff` 往返（来源、锚点、期间、筛选、证据、交接号），宿主与本页参数不会各写一套。
- 依赖锁：`frontend/package.json` / `package-lock.json` 新增 `@assistant-ui/react@0.14.14`、`@radix-ui/react-collapsible@1.1.12`、`lucide-react@0.468.0`、`class-variance-authority@0.7.1`，`jsdom@26.1.0` 为 devDependency。
- 首屏冒烟：`tests/workbench_agentkit_dom.test.mjs` 用 jsdom 执行已提交的构建产物与页面模板，验证页面挂载、输入框、空态、V6.1 交接横幅和会话列表请求。真机浏览器点击结果见下方验收结论。
- 测试：先写红测再实现——`tests/test_workbench_agentkit_route.py`（4 项，路由未实现时为 404，现全部通过）、`tests/workbench_agentkit_state.test.mjs`（11 项状态投影与交接 URL）、`tests/workbench_agentkit_results.test.mjs`（7 项结果/证据/子图请求适配）、`tests/workbench_agentkit_shell.test.mjs`（7 项页面壳/右栏/主题作用域/构建配置/上游记录）。AgentKit 相关 Node 25 项通过；`test_direct_root_workbench_entry.py`、`test_application_base_path.py`（10 项）与 `test_anonymous_read_surface_red.py`、`test_cockpit_main_service.py`（40 项）通过。
- 首期验收基线 `2f64cdd` **未通过**。33 项前端和 26 项后端专项测试通过，路由、构建产物与上游 10 个文件校验通过。真机浏览器使用本地模拟 SSE 复现首次发送白屏和宿主范围未进入请求，按实际接口回放确认澄清续流被丢弃。历史正文可恢复，历史上下文接续和看板恢复待完善。真实 PACK 销售取数、看板与子图端到端验证仍待复验。复现条件和通过标准已写入规格 §6.1。

### 2026-11-24 验收阻断项修复：发送、交接范围、澄清续流、历史恢复

- 首次发送白屏：assistant 消息补齐 `status`（`running` / `complete`），修复 assistant-ui 读取 `status.type` 时的 `Cannot read properties of undefined (reading 'type')`；jsdom 测试改为真实输入并点击发送，覆盖逐帧正文与 `done` 后恢复发送键，另加慢流停止用例（停止后保留部分正文并提示「本轮已停止」）。
- V6.1 交接范围：`/api/chat` 新增 `scope`（`source/anchor/period/filters/evidence/handoff_id`），后端校验锚点与期间后拼入模型提示词，`visible_user_text` 仍是用户问题；前端 `scopeFromHandoff()` 只在交接可用时携带，`buildChatBody()` 组装请求体。同一交接的会话 ID 存 sessionStorage（按交接号），刷新复用；新建会话会更新该记录。
- 澄清续流：新增 `resumeTurn()`，提交 `/api/choice` 前释放旧 turn id（后端为续流分配新请求 id），续流正文与 `done` 归入原问题；提交失败后可从原澄清卡重试，并保留已填选项和手工输入。jsdom 用两个不同 turn id 回放验证。
- 历史恢复：`activate` 按传入 `session_id` 建立/命中会话并回传 `session_id`、`messages` 与 `agentkit` 快照；快照（轮次、工具过程、表格/图表、证据、本体命中）随保存写入会话记录，保留所有轮次；超出单条 16 MB 容量时提示失败并保留已保存的记录；前端结合结构化快照、旧消息与旧版已保存资产回看，追问继续使用激活会话；每轮完成/失败/中断后自动保存（内容指纹去重）。
- 本机真实服务复验（未改线上）：带 `scope` 的 `/api/chat` 返回 124 个 SSE 事件，`user_message` 事件中可见「[来源卡带入的分析范围]…锚点=PACK_OPP_COVERAGE；期间=2026Q3…」，随后因采购域无商机数据进入澄清；缺锚点的 `scope` 返回 400「交接范围缺少风险或指标锚点」。保存会话后带新 `session_id` 调 `activate`，回传该 `session_id`、20 条消息和含表格的 `agentkit` 快照，确认保存/恢复契约生效。
- 验证：Node 165 项通过（含 6 项 jsdom 端到端：挂载、发送、停止、交接范围与刷新会话、历史恢复、澄清续流）；后端专项 21 项通过（路由、范围校验、历史存取、入口/base-path），会话存储回归 24 项通过。产物约 721 KB（gzip 210 KB）。
- 主要文件：`frontend/agentkit/{App.jsx,api.js,state.js,messageAdapter.js}`、`bi_agent/web/{app.py,conversations.py}`、`tests/workbench_agentkit_{dom,api,state}.test.mjs`、`tests/test_workbench_agentkit_{scope,history,route}.py`。

### 2026-11-25 验收阻断项修复：历史覆盖、恢复后追问、按轮看板与交接范围确认

- 打开旧会话不再写入：自动保存只在页面真的产生新一轮后触发；`/api/conversations/save` 的 AgentKit 保存只写结构化轮次，服务端保留原有 `chat_html`/`dashboard_html`/`ontology_html`/`tools_html`/`llm_html`、`sop_steps` 与消息，不再清空旧快照（`preserve_legacy`）。
- 恢复后追问白屏：新增 `nextTurnId()`，新轮次在历史轮次之后继续编号（`turn-1`/`turn-2` → `turn-3`），避免 React key 与 assistant-ui 消息 ID 重复；jsdom 覆盖「恢复后追问」不报错且历史与新轮次同存。
- 看板按轮分组：右栏改为「分析结果 · 按轮」，每轮的表格和图表独立成组。工具过程和本体命中可在对话中的对应调用查看。每轮完成后刷新左栏会话列表，无需手动刷新。
- 缺失值不再显示为 0：图表数值保留 `null`（柱状显示「—」且不画条、饼图图例「—」、折线跳过缺失点），避免把缺失误读为 0。
- 交接范围：`scope` 校验加强（锚点编码、期间格式、筛选项与证据引用的类型和数量上限）；`/api/chat` 首帧新增 `scope_accepted`，页面在横幅显示「分析服务已核对范围：锚点…期间…」。同一卡片的会话记录存入 sessionStorage，刷新自动重开该会话（打开不写入）。
- 验证：Node 171 项通过（8 项 jsdom 端到端：挂载、发送、停止、范围与刷新会话、恢复、澄清续流、按轮看板、卡片刷新重开）；后端专项 47 项通过（路由、范围、历史、入口/base-path、会话存储）。产物约 723 KB（gzip 211 KB）。
- 未闭环：PACK 销售本体的真实取证出表出图与 V6.1 真机宿主联调仍需目标环境；工作区的 V6.1 原型为仓外文件，本次未改动。

### 2026-11-25 AgentKit 工作台预览反馈

- 对话区单独滚动，输入框与发送、停止按钮留在底部。对话中的每条工具调用可展开查看入参、返回、状态、耗时、错误和此次命中的本体。结果看板按轮保留表格和图表。
- 点击单条本体命中，以其编码、类型、库和分析会话查询子图。「关系扩散」沿用同一锚点向本体平台查询，展示对应接口返回的关系，可切回初始子图。
- 导航底部「数据源」提供本体库、配对业务数据源、检索模式与本地图库。数据源保存后开启使用新绑定的会话，历史按原绑定恢复。输入框内的模型简称打开模型参数，沿用分析服务的全局配置。
- 工作台从页顶分为导航、对话和宽看板三栏。品牌和应用版本位于导航左上，输入框统一包住模型入口、快捷键与发送或停止。对话顶部的可折叠 SOP 显示实际进度，结束后工具调用自动收起。看板沿用工作台的 Pro BI 图表组件，散点图继续使用 ECharts。（2026-11-25）
- 规格和验收条件见 [本体消费展示工作台规格](../docs/specs/workbench-agentkit-ontology-consumption.md)。主要变更在 `frontend/agentkit/`、`bi_agent/web/app.py` 及 AgentKit 回归测试。

### 2026-11-25 AgentKit 工作台预览实例更新到 5dc0e5d（8766）

- 按用户当次授权，只更新 172.16.10.34 的 8766 AgentKit 预览实例：`git archive 5dc0e5d` 到
  `agentkit-5dc0e5d-20261125-1101`，复用既有 `.env`/`.venv` 软链，`dataset` 指向原预览
  `dataset-preview`，未触碰 8765 冻结驾驶舱。
- 验证：`/healthz`、`/workbench-agentkit`、`/static/vendor/agentkit/*`、`/api/conversations` 均 200；
  旧进程已停止，新 PID 1767209。
- 主要文件：`DEPLOYMENT.md`（§9 发布记录）。

### 2026-11-25 8766 预览补齐 Workbench 本地 Excel + PG 数据源

- `.env.example` 增补 `WORKBENCH_PG_*` 与 `WORKBENCH_LOCAL_ONTOLOGY_PATH` 说明（独立只读账号、独立 workbook，
  不继承 Process360 凭据）；补上后 `/api/sources` 会把该 workbook 列为可选源。
- `DEPLOYMENT.md` §9 记录预览实例的独立 `preview.env` 与回滚方式，未改动 8765 共用 `.env`。

### 2026-11-25 8766 预览更新到 dcc3dff

- 按用户当次授权，只更新 172.16.10.34 的 8766 预览：`git archive dcc3dff`（含 8f24dfe 的 AgentKit
  布局与分析进度优化）到 `agentkit-dcc3dff-20261125-1345`，复用 `preview.env`、`dataset-local` 本体与旧
  `dataset-preview`；未触碰 8765。
- 验证：`/healthz`、`/workbench-agentkit`、`workbench-agentkit.js`、`/api/sources` 均 200；新 PID 2396451。
- 主要文件：`DEPLOYMENT.md`（§9 发布记录）。

### 2026-11-25 AgentKit 工作台：模型名、关闭按钮与阶段提示

- 模型列表标签改为真实模型名（`bi_agent/llm/registry.py` 去掉“团队 API · …”前缀），AgentKit 与工作台设置都显示实际模型 id。
- 设置弹窗的关闭按钮由“关闭模型 / 关闭数据源”文字改为叉号（带 `aria-label`）；入口与弹窗标题的“数据源”改为
  “切换本体库/数据源”，保存按钮改为“保存本体库与数据源”。
- 会话区新增阶段提示：本轮执行中显示当前 SOP 阶段或“正在调用 <工具>”，并可在“思考过程”里展开模型 thinking；
  工具调用开始后不再是无输出的空白等待。
- 重新构建 `static/vendor/agentkit/workbench-agentkit.{js,css}`；`tests/workbench_agentkit_dom.test.mjs` 同步新文案，
  Node 套件 177 项通过。

### 2026-11-25 8766 预览更新到 4c90a1d

- 按用户当次授权把模型名、叉号关闭按钮、阶段提示三项改动部署到 172.16.10.34 的 8766 预览：
  release `agentkit-4c90a1d-20261125-1410`，复用 preview.env 与 dataset-local 本体，未触碰 8765。
- 验证：`/healthz` 200、页面 200、bundle 含 `ak-stage`、`/api/config` 返回真实模型名、`/api/sources` 源不变。
- 主要文件：`DEPLOYMENT.md`（§9 发布记录）。

### 2026-11-25 分析 Agent 默认工作台切换到 AgentKit

- 应用根路径、`/workbench` 和 `/workbench-agentkit` 直达同一页面。带网关前缀的旧链接、一次性 `?prompt=` 和 V6.1 来源卡交接继续使用；`/workbench-legacy` 可打开旧工作台。
- 智能分析使用统一会话列表。报表从输入框左侧「＋」添加，支持 PDF／DOCX、最近报表多选、按需数据库对账及标准报表生成。添加或移除附件后可在原会话继续，保持草稿、往轮结果和记录 ID。重新打开历史会恢复活动附件和对账设置，旧快照中的文字、明细、图表、SOP 及可关联到原工具的本体命中在新版回看。
- 对话支持建议问题填入、手工澄清、原卡重试及已确认选项。看板按问题展示结论、根因、建议和证据产物，点问题回到对话对应位置，支持每轮 HTML、Word 与嵌入时的主页同步。
- 增加会话搜索、刷新和回收站入口，导航与内容栏宽可拖动并记住。高级本体和 Doris 配置集中在数据源设置，称呼、主题、角色与回答风格集中在模型设置。实现与验收范围见 [切换规格](../docs/specs/workbench-agentkit-ontology-consumption.md#66-替换原工作台的用户功能2026-11-25)及[统一附件入口](../docs/specs/workbench-agentkit-ontology-consumption.md#67-智能分析中的附件2026-11-25)。

### 2026-11-25 8766 预览更新到 3c9a100

- 推送 GitHub 缺失提交（`b8ce31e`、`3c9a100`），并把 8766 预览更新到 `agentkit-3c9a100-20261125-1546`：
  统一入口切到 AgentKit、报告附件分析、历史对齐；复用 preview.env 与 dataset-local 本体，未触碰 8765。
- 验证：`/healthz`、`/workbench-agentkit` 200；bundle 与本地一致；`/api/sources` 源不变；Node 184 项通过。
- 主要文件：`DEPLOYMENT.md`（§9）。

### 2026-11-25 恢复 demo2 旧版工作台到 /workbench-legacy

- demo2 当前 `/workbench` 的构建确认仍为 `07ac670`（2026-09-30）：`workbench.js` md5 `e0a0f53e…`、CSS md5 `592a4a68…`，与仓库历史一致，无需重建。
- 从该提交恢复旧版页面到独立目录：模板 `bi_agent/web/static/workbench-legacy/index.html`，资源 `static/vendor/antd-legacy/{workbench-legacy.js,workbench-legacy.css,lib/vue.global.js,lib/pro-bi-ui.min.js}`；`/workbench-legacy` 改由 `_legacy_workbench_response()` 渲染，保留 `APP_ROOT_PATH` 和固定的历史版本串（`?v=127/162`）。
- 入口关系：`/`、`/workbench`、`/workbench-agentkit` 均为 AgentKit 新版；`/workbench-legacy` 为 demo2 旧版。原 Pro UI 页面不再占用该兼容入口（其资源保留在 `vendor/antd`）。
- 验证：路由测试断言旧页资源路径、标题「硕磐智能分析 Agent · 本体工作台」以及 JS/CSS 的 md5 与 demo2 构建一致；新增 jsdom 冒烟用例，三份旧脚本可在 DOM 中启动并渲染导航（“新对话”“智能分析”）。
