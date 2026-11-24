# 本体消费展示工作台 AgentKit UI 复用规格

> 2026-11-24 · 首期验收未通过 · 验收基线 `2f64cdd` · 面向分析 Agent 独立展示和 V6.1 总裁驾驶舱接入

## 1. 目标和交付范围

分析仓交付一套完整的本体消费展示工作台。前端使用 AgentKit 的组件和交互规范，构建、路由、会话与分析执行由本仓负责。用户能从一个经营问题追到分析结论、指标口径、查询证据和命中的本体关系，并在同一会话继续追问。

首期使用 **PACK 未签单商机／商机覆盖**。独立入口支持自由提问，宿主入口支持从 V6.1 风险卡带入分析上下文。两种入口使用同一页面、同一结果结构和同一套本体消费逻辑。

首期交付包括会话列表、消息流、输入与停止、工具过程、澄清、结果看板、证据详情及本体子图。V6.1 首期验证风险卡打开分析、带入范围和定位结果。整舱视觉改造、五类风险和七张穿透卡的逐项覆盖、待办审批与任务令下发按后续场景实施。

## 2. 页面和模块归属

| 区域 | 实现与归属 |
| --- | --- |
| 入口和页面壳 | 在当前分析仓的 `frontend/` 实现新入口 `GET /workbench-agentkit`。沿用 `APP_ROOT_PATH`，例如通过 `/api/ontology-agentic-analytics/workbench-agentkit` 访问。同一入口可独立打开，也可由驾驶舱托管。现有应用根路径和 `/workbench` 继续作为兼容入口及回归对照。 |
| 左侧会话列表 | 使用 AgentKit 会话列表的视觉和交互，接分析仓的会话列表与恢复。支持新建、切换和打开历史。可用动作以本仓会话接口为准。 |
| 中间对话区 | 使用 AgentKit 的 Thread、Composer、Markdown、工具分组、状态和澄清卡。用户可发送、停止、补充条件和追问。助手正文与工具过程按事件顺序呈现，发出的建议问题计入当前会话。 |
| 右侧分析区 | 复用分析仓的图表、表格和证据展示能力，按问题展示结果。点击历史问题或结果引用时定位其看板内容。图表和表格在右栏呈现一次。窄屏允许在对话和结果之间切换。 |
| 本体内容 | 复用 `@boulderaitech/ontology-graph` 和现有子图交互。命中列表与图节点都能查看定义和关联。图概览展示当前可见结果命中的节点及真实直接关系，详情可从选中节点展开上下文。 |
| 会话与执行 | 继续使用分析仓的会话、SSE、SOP、本体查询、取数和证据判定。基于 AgentKit 的前端装配运行在分析仓的构建与服务入口。 |

### 2.1 AgentKit 组件获取和升级

**采用固定提交的源码导入。** AgentKit 上游是 GitLab `ai-team/spzn-agentkit`，首期固定到 `b8df86dfa3c30de6676cd1d768cda504bf3c3338`，目前对应 `dev`。仓库的 `agentkit-ui` 是应用源码，供跨仓使用的入口是 shadcn Registry。实施时按文件取用，导入的组件、适配代码和 npm 锁文件由分析仓维护。日常构建读本仓文件，升级时再从 GitLab 提取明确选定的组件。 [上游 Registry 使用说明](http://gitlab.boulderaitech.com/ai-team/spzn-agentkit/-/blob/b8df86df/agentkit-ui/docs/registry.md)

| 取用对象 | 操作 |
| --- | --- |
| 可独立安装的 Registry 组件 | 从 `agentkit-ui/public/r/` 提取选定 JSON，例如 `confirm-dialog.json`。在分析仓 `frontend/` 配好组件别名、TSX、Tailwind 和主题变量后，先用 shadcn `--dry-run` 检查文件落点、npm 依赖和递归 Registry 依赖，再安装确认过的条目。 |
| 对话和会话列表 | 以 `aui-thread.json`、`aui-thread-list.json` 作文件清单，同时对照固定提交中的 `src/components/assistant-ui/elements/`。选择 Thread、Composer、Markdown、工具分组和列表所需的组件及辅助文件。AgentKit 的产物、工作区、模型设置等内部引用由分析仓的接口适配和组件插槽承接。 |
| Registry 外的组件 | 按需提取对应 TSX 和它确实使用的辅助文件，例如 `approval-card.tsx` 或选项组件，连同上游来源和许可信息记录在分析仓。 |

在分析仓根目录可按以下方式获取和预览单个条目。预览步骤在分析仓 `frontend/components.json` 及别名配置就绪后执行。

```bash
(
  set -e
  agentkit_source_commit=b8df86dfa3c30de6676cd1d768cda504bf3c3338
  agentkit_registry_path=agentkit-ui/public/r/confirm-dialog.json
  agentkit_import_dir="$(mktemp -d "${TMPDIR:-/tmp}/agentkit-registry.XXXXXX")"
  git archive --remote=git@gitlab.boulderaitech.com:ai-team/spzn-agentkit.git \
    dev "$agentkit_registry_path" > "$agentkit_import_dir/upstream.tar"
  actual_commit="$(git get-tar-commit-id < "$agentkit_import_dir/upstream.tar")"
  if [ "$actual_commit" != "$agentkit_source_commit" ]; then
    printf 'AgentKit source commit mismatch: %s\n' "$actual_commit" >&2
    exit 1
  fi
  tar -xOf "$agentkit_import_dir/upstream.tar" "$agentkit_registry_path" \
    > "$agentkit_import_dir/confirm-dialog.json"
  cd frontend
  npx --yes shadcn@4.21.0 add "$agentkit_import_dir/confirm-dialog.json" --dry-run
)
```

GitLab SSH 的 `git archive` 使用分支或标签引用，归档头部的提交必须等于固定 SHA。若 `dev` 已前进，从 GitLab 的固定提交视图获取同一文件，或使用仍指向该提交的归档引用。预览通过后，去掉 `--dry-run` 导入已审阅的组件，提交导入源码和依赖锁。保留一份简短的上游记录，列出固定提交、取用路径与本地适配。升级时对照新旧上游源码并保留本地适配，再验证分析仓构建、消息流和历史恢复。

新入口采用一套对话依赖与主题，校验 React、assistant-ui、Radix 和 Tailwind 的版本组合及 CSS 作用域。复用既有 API 客户端、状态推导和结果渲染，由新页面的 React 组件读取状态。

## 3. 两条用户路径

### 3.1 独立展示

1. 用户打开 `/workbench-agentkit`，新建会话并发送「PACK 未签单商机主要涉及哪些客户和产品部？缺口怎么算出来的？」
2. 分析后端基于环境允许的本体和数据范围执行。如果统计期间、客户范围或「未签单」口径不明确，展示澄清卡。用户提交后继续原轮次。
3. 对话展示结论和证据引用，右栏展示该轮的客户与产品部明细、口径和缺口。用户可点本体标签查看对应指标、实体和关系。
4. 用户在同一会话追问，前一轮的看板和本体命中仍可回看。用户切换统计期间时，新轮次按新期间重新取证。

### 3.2 V6.1 风险卡进入

1. V6.1 从「商机覆盖风险」或等价 PACK 风险卡打开 `/workbench-agentkit`，传入来源、风险或指标锚点、当前期间及筛选。有已登记的证据时传证据引用。
2. 分析服务校验交接范围，工作台显示带入的来源、口径和过滤条件。用户可确认或补充。相同交接的页面刷新复用已建立的会话，避免重复执行首轮。
3. 结果从同一展示组件渲染。宿主如需定位原卡或打开结果，只读取已确认的结果标识及视图提示。新增风险卡通过业务映射接入同一流程。

交接的卡片事实作为来源上下文，由分析服务重新核对当前期间和指标口径。无法匹配本体编码时展示候选或待核实。交接不存在、失效或不可访问时显示明确反馈，提供返回来源卡或重新发起分析的入口。用户切换卡片或会话后，迟到结果只归属其原会话和轮次。

### 3.3 宿主接入片段

宿主只需带上下文打开入口，会话建立、校验与降级都由本页负责：

```js
// 记录在 frontend/agentkit/state.js: buildHandoffUrl(card, basePath)
const url = buildHandoffUrl({
  source: 'v61-cockpit',
  anchor: 'PACK_OPP_COVERAGE',   // 风险或指标锚点，缺省即视为不可用交接
  period: '2026Q3',
  filters: {customer: '宁德时代', region: '华东'},
  evidence: ['ev-11', 'ev-12'],
  handoffId: 'h-7',
}, '/api/ontology-agentic-analytics');
window.open(url, '_blank');
```

`parseHandoff()` 与 `buildHandoffUrl()` 互为往返，渲染侧不再手拼参数；锚点缺失时页面显示不可用反馈而不是空页。可运行的宿主示例见 `docs/examples/agentkit-host-handoff.html`（`tests/workbench_agentkit_host.test.mjs` 校验其参数往返）。

## 4. 接口和状态

### 4.1 对话对接

| 操作 | 对接方式 |
| --- | --- |
| 自由提问 | 复用当前分析后端的 `POST /api/chat`、`POST /api/choice` 或目标环境采用的同类会话接口。若选用 360 能力且它要求先有条款交接，则为自由提问补会话初始化，由分析后端装配对应的本体和能力。 |
| 条款交接 | 参考已有 `/api/analysis360/handoff`、`/api/analysis360/chat` 和 `/api/analysis360/choice`。这些接口目前来自分析功能分支，实施前确认可采用的代码基线和目标环境。 |
| 会话与子图 | 历史沿用 `/api/conversations/*` 能力及既有权限边界。关系图继续消费现有的本体子图合同，`/api/ontology/subgraph` 适用于其已配置的本体源。360 条款模式的图数据必须来自该轮实际使用的本体，可通过对应的子图工具或服务端适配取得。 |

PACK 对照验收时，两种入口使用同一个已核准的本体库和版本、数据源及指标口径。验证结果中记录的实际来源，并对齐两种入口的期间和筛选后再比较。

前端把 SSE 投影到单一会话状态，可使用 assistant-ui 的 `useExternalStoreRuntime` 或等价组件绑定。保留分析服务的 `session_id`、`turn_id`、`generation` 和工具 ID。正文增量追加到原消息，工具开始与结果合并到原调用，SOP 按轮记录。澄清沿用原会话和页面中的问题轮次。`/api/chat` 与 `/api/choice` 的 SSE 各有自己的请求 `turn_id`，前端在接纳当前续流的同时仍须隔离旧请求的事件。澄清提交失败后可重试。停止、中断、失效和失败分别反馈，重复或迟到的终态不能触发第二次成功或覆盖当前结果。

### 4.2 结构化结果

先从现有工具事件、结果数据和持久化记录提取可用字段。缺字段时由分析后端扩展结果投影，使聊天区、看板和宿主共享一次分析的产出。下表是首期须对齐的逻辑字段，沿用实现中可用的命名与标识。

| 内容 | 首期合同 |
| --- | --- |
| 身份与范围 | 可稳定读取的分析结果标识，关联会话与轮次。包含本体库、版本、分析锚点、统计期间和有效筛选。 |
| 结论与证据 | 结论、指标值、单位、口径和证据引用。部分数据、待核实项和来源缺口可见。缺失值保留缺失状态，避免渲染为零。 |
| 看板结果 | 每个表格或图表具备稳定标识、所属轮次、结构化数据和证据链接。重复事件只更新同一结果。 |
| 本体命中 | 至少包含本体库、类型和稳定编码，关联所属结果以及可查的子图锚点。不同本体库的同编码节点分别处理。 |

独立展示和 V6.1 对同一结果使用同一份结构化数据。结果读取和子图展开均按分析服务当前身份与本体访问范围校验。宿主提供的筛选及证据引用由后端复核。首期沿用已有可用的结果传输方式，只有跨页读取确实缺少合同才新增读接口。

## 5. 兼容与演进

| 层级 | 影响与处理 |
| --- | --- |
| 一阶【确定】 | 新页面和现有页面走独立入口，使用现有分析服务。独立页加载、取数或子图可分别反馈失败，正文与其余可用结果继续显示。发布首期入口可按路由回退。 |
| 二阶【需验证】 | 新旧页面的当前会话和结果读取同源。用历史样本验证重新打开、继续追问和结果关联。只含旧 HTML 的历史可通过原工作台查看，已有内容保持原样。对同一问题从独立页和 V6.1 分别进入，核对期间、权限、结果格式和本体来源。 |
| 三阶【推测】 | 同一展示入口和结果合同可让后续风险卡主要增加业务映射。以接入第二张风险卡验证共用程度，确认它只复用一套对话、看板和子图。旧工作台退役等首期和存量兼容验收后另行安排。 |

## 6. 实施顺序和验收

1. **页面和状态适配。** 验证 AgentKit 导入清单、固定提交、依赖锁和前端构建。无前缀与配置 `APP_ROOT_PATH` 时，`/workbench-agentkit` 都能返回新页面并加载资源。接通一个新会话的发送、停止、工具事件和澄清。用回放夹具验证同轮更新、迟到事件、提交失败和中断。
2. **PACK 主链路。** 使用受控的真实本体和已登记的查询。能对比客户与产品部，结果展示期间、单位、口径和可追溯证据。本体详情可由命中节点打开，子图只包含真实关系。数据不足或图服务不可用时对应区域正确降级。
3. **恢复与追问。** 打开该会话历史，按轮恢复答复、看板及命中图，再发一条追问。切换到另一会话后旧流不会覆盖当前界面。抽查旧工作台入口及旧历史仍可查看。
4. **V6.1 宿主验证。** 从一张 PACK／商机覆盖风险卡带入期间和对象，核对这轮查询范围和右栏定位。验证重复打开或刷新、交接失效、切换风险卡和窄屏使用。先验收这张卡，再推进第二张卡和其他场景。

### 6.1 2026-11-24 验收记录

验收基线为 `2f64cdd`。后端路由以本仓测试验证。浏览器使用该提交的构建产物、V6.1 宿主示例和本地模拟 SSE，覆盖独立页面和带前缀的宿主入口。续流和跨轮恢复另按后端实际接口行为回放。

| 验收项 | 观察结果 | 修复后的通过条件 |
| --- | --- | --- |
| 首次发送 | 独立入口和宿主示例都能打开，实际点「发送」后出现 `Cannot read properties of undefined (reading 'type')`，工作台内容消失。现有 jsdom 测试覆盖首屏挂载。 [运行时绑定](../../frontend/agentkit/runtime.js#L19) · [首屏测试](../../tests/workbench_agentkit_dom.test.mjs#L89) | 两种入口都能在真实浏览器发送并显示逐帧正文、工具状态和完成结果。慢流期间停止后保留已显示内容，页面可继续使用。 |
| V6.1 交接 | 示例风险卡正确打开页面并显示锚点、期间、筛选和证据。点「按此范围继续」后，抓到的 `/api/chat` 请求只有问题文本和会话 ID，分析后端未收到交接范围。刷新为同一交接重新生成会话 ID。 [交接和会话](../../frontend/agentkit/App.jsx#L21) · [请求体](../../frontend/agentkit/api.js#L97) | 后端收到并校验交接号及范围，实际分析和结果反馈使用该范围。同一交接刷新恢复已建立的会话，失效时提供重新发起入口。 |
| 澄清续流 | 后端为 `/api/choice` 分配新的请求 `turn_id`，前端按旧 ID 丢弃新流。用两个请求 ID 回放后，回答为空，状态停在 `streaming`。 [后端续流](../../bi_agent/web/app.py#L3148) · [前端事件过滤](../../frontend/agentkit/state.js#L228) | 以首次提问和澄清续流使用不同请求 ID 为测试条件，用户提交后在原问题下看到结论和看板。验证旧流迟到和澄清提交失败重试。 |
| 历史恢复与追问 | 打开旧记录可恢复文字和工具名称。激活请求缺少明确的 `session_id`，后续请求回退到历史记录 ID，无法对应到激活的分析上下文。现有恢复只处理消息，按轮看板、证据和本体命中缺少恢复，新增会话缺少保存调用。 [激活请求](../../frontend/agentkit/api.js#L30) · [历史投影](../../frontend/agentkit/state.js#L129) | 新会话完成后可保存并重新打开。追问复用激活时的分析会话和数据源。恢复时能够按轮回看图表、证据和本体命中。 |

**已通过。** 有无网关前缀的路由与资源检查、旧工作台路由回归、GitLab 固定提交的 10 个文件来源校验、构建产物字节比对、33 项前端测试及 26 项后端专项测试。浏览器验证了 390 像素下的对话／看板切换、缺锚点提示以及历史正文显示。


### 6.2 2026-11-24 阻断项修复记录

修复在 `feature/agentkit-ontology-workbench-spec` 上完成；四条阻断项均先补可复现测试再修复。

| 阻断项 | 修复 | 测试 |
| --- | --- | --- |
| 首次发送白屏 | assistant 消息补齐 `status`，assistant-ui 不再读空 `status.type`；发送与停止期间工作台保持挂载 | jsdom：真实输入 + 点击发送、逐帧正文、`done` 恢复发送键；慢流停止保留正文 |
| V6.1 交接范围未进入请求 | `/api/chat` 支持 `scope`，后端校验锚点/期间后拼入提示词，`visible_user_text` 不变；同一交接的会话 ID 存 sessionStorage，刷新复用 | 后端范围文本与拒绝路径、请求体形状、DOM 断言 `scope` 字段与刷新后 `session_id` 相同 |
| 澄清续流被丢弃 | `resumeTurn()` 在提交选择前释放旧 turn id，续流按新请求 id 归入原问题；失败可重试 | 状态测试（两个 turn id、失败态）+ DOM（点选澄清后显示续流结论、无 stuck streaming） |
| 历史恢复不完整 | activate 携带并回传 `session_id`/`messages`/`agentkit` 快照；保存写入结构化轮次（200 KB/40 轮上限），恢复优先快照；每轮完成自动保存 | 存储与 activate 测试、API 测试、DOM（恢复表格/工具/命中后追问复用激活会话） |

**本机服务复验。** 带 `scope` 的 `/api/chat` 把「[来源卡带入的分析范围]…锚点/期间/筛选/证据」写入本轮 `user_message`，缺锚点返回 400；保存会话后以新 `session_id` 调 `activate`，回传同一 `session_id`、消息与含表格的 `agentkit` 快照。

**仍未闭环。** 使用已核准 PACK 销售本体与数据的真实取证、出表出图，以及 V6.1 真机宿主联调，需要在目标环境执行；本机为采购域数据，只完成协议与页面链路验证。

**待端到端复验。** 修复表中阻断项后，使用已核准的 PACK 销售本体和数据，从独立页和 V6.1 实际宿主分别完成一次真实取证、澄清、出表和出图。本体命中能展开真实关系并查看定义，证据可追溯，刷新后仍能回看结果并继续追问。首期通过须以这两条浏览器链路的结果为准。其余上游组件的适配进度见 [AgentKit 来源与适配清单](../../frontend/agentkit/UPSTREAM.md)。

## 参考

- [现有工作台对话事件与组件](workbench-pro-ui-agent-conversation.md)
- [每轮 SOP 和连续工具记录](workbench-turn-sop-and-tool-runs.md)
- [对话正文和右侧结果](workbench-flat-transcript-and-board.md)
- [命中本体子图](workbench-ontology-hits-graph.md)
- [既有根入口和网关前缀](direct-root-workbench-entry.md)
- [分析仓功能分支的 360 深度分析](http://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/blob/39a1bcacc1c1c5f232f6beab78d02732ed18e05b/docs/analysis360.md)
- [AgentKit UI Registry](http://gitlab.boulderaitech.com/ai-team/spzn-agentkit/-/blob/b8df86df/agentkit-ui/registry.json)
- [AgentKit Thread 插槽](http://gitlab.boulderaitech.com/ai-team/spzn-agentkit/-/blob/b8df86df/agentkit-ui/src/components/assistant-ui/elements/thread.aui.tsx#L175)
- [assistant-ui 外部状态适配](http://gitlab.boulderaitech.com/ai-team/spzn-agentkit/-/blob/b8df86df/.agents/skills/runtime/references/external-store.md)
- V6.1 设计输入为 `V6.1-总裁驾驶舱(1).html` 中的经营看板、储小策和商机覆盖入口。
