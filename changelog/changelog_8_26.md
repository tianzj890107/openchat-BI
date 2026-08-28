# openchat-BI 变更记录（2026-08-26）

> 本文档只记录 2026-08-26 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-26

### 业务名称优先展示规则（Agent 提示词加强）

用户可见变化：
- BI 分析、报表分析、报表生成三类 Agent 的正文结论、图表（标题、图例、坐标轴、饼图分类）和表格表头强制优先展示业务名称；编码只允许出现在名称后的括号或来源追溯中，不再允许用裸编码代替已知名称。
- 新增完整“业务名称优先展示规则（最高优先级）”约束段，包含名称映射可信来源优先级、图表/表格/SQL 输出规则、输出前强制自检和最终服从强化句。
- 无可信名称映射时保留原编码，禁止猜测或编造名称；SQL、JSON、URL、API 参数、物理字段和 `source_note`/`scope`/`semantic` 中的追溯编码保持原样。

影响范围：
- ChatBI 数据分析会话、报表问答与报表生成流程的所有面向用户输出。
- 仅修改提示词，不改变接口协议、SSE 事件类型和既有并发/校验逻辑。

主要文件：
- `.claude/agents/bi-analyst.md`
- `.claude/agents/report-analyst.md`
- `.claude/agents/report-generator.md`

### 根因分析与行动建议卡片只保留在对话区

用户可见变化：
- 看板只保留：用户问题、结论卡片、TableGenerate 表格、ChartGenerate 图表、
  ChartGenerateMultiDim 多维图表。
- 根因分析、根因证据链、行动建议、管理建议、后端 `action_recommendations` 结构化
  行动卡片以及导出/执行/转督办等交互卡片只显示在对话区，不再追加到看板。
- 结论卡片仍在对话区和看板同时展示；表格、普通图表和多维图表照常进入看板。
- 恢复旧历史会话时，旧快照看板中的 `dash-rootcause`、`dash-actions`、
  `dash-export` 继续迁移到对话区并从看板移除。
- 根因分析与行动建议的交付要求未变，未删除正文章节，未收紧输出门禁。

根因：`action_recommendations` SSE 分支对同一卡片依次调用
`appendChatActionCard(card)` 与 `appendDashboardCard(card)`，DOM 节点不能同时存在
于两个父节点，第二次追加会把卡片从对话区移动到看板；修复后结构化行动卡片只追加到
对话区。

主要文件：`frontend/src/runtime.js`、`bi_agent/web/static/vendor/antd/workbench.js`、
`tests/test_regressions.py`。

测试：新增卡片展示位置回归覆盖（根因/行动/结构化行动不进入看板、结论与图表表格仍
进入看板、旧看板行动卡片迁移到对话区、正文提取与卡片渲染保留）；`OfflineRegressionTests`
104 项通过。
### 分析 SOP 重构为五步状态机（支持回退与查询循环）

用户可见变化：
- 分析 SOP 由九步精简为固定五步：01 语义理解&元数据匹配、02 业务上下文注入、
  03 深度思考&分析规划、04 SQL 执行&数据获取、05 结果分析&可视化输出，编号 01–05。
- 每个主步骤固定不变，SOP 面板只显示五步名称与状态（已完成/进行中/未开始），不再
  显示“正在进行：…”的具体动作行；步骤推进与回退仍由真实执行事件驱动，不使用
  定时器伪造进度。
- 支持真实回退与循环：第 5 步后再次取数会回退到第 3 步“根据分析结果重新规划”，
  查询失败会回到第 3 步“根据查询错误调整方案”；回退后第 4、5 步恢复“未开始”，
  不会保留绿色完成态；3→4→5→3→4→5 可无限循环。
- 同一时刻最多一个“进行中”步骤；只有后端终止事件 `done` 才允许五步全部变绿，
  `error`、`session_superseded`、`awaiting_user_choice`、图表/表格/结论文本、
  `action_recommendations` 等都不会把整轮标记完成。
- 后端新增结构化 SSE 事件 `sop_progress`（step/detail/allow_backward/turn_id），
  前端优先按真实阶段推进，工具与正文映射仅作兼容兜底；旧 turn 的 SOP 事件不能污染
  新 turn。
- 历史兼容：旧六步、旧九步已完成快照恢复为五步全完成；未完成快照映射到最接近的新
  步骤；转换只在内存完成，不重写历史 JSON，不批量迁移。
- 根因/行动建议仍只留在对话区，结论/表格/图表仍进看板；SOP 事件缺失不影响最终回答
  输出，未新增任何回答门禁。

主要文件：`frontend/src/sopMachine.js`（新增，纯函数状态机）、
`frontend/src/runtime.js`、`frontend/src/main.jsx`、`frontend/src/workbench.css`、
`bi_agent/web/session.py`、`bi_agent/web/app.py`、
`bi_agent/web/static/vendor/antd/workbench.js`、
`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`、`tests/test_regressions.py`。

测试：新增纯函数状态机测试（node 执行真实转换：前进/回退/循环/单一进行中）、六步/
九步/五步快照迁移测试、后端 `sop_progress` 事件顺序测试（首查 03→04→05、重查
05→03→04、无工具交付）、SSE 透传测试；全量 discovery 233 项通过。

### Team 模型 thinking 能力按实测结果标记

用户可见变化：
- 对 Team/LiteLLM 网关当前 24 个模型逐一发起最小真实请求，并分别验证开启、关闭参数；
  `supports_thinking` 改为本地实测能力表，不再把所有 Team 模型统一标记为 false。
- 已标记支持：`qwen3.5-397b-a17b`、`qwen3.7-plus`、`qwen3-vl-plus`、
  `qwen3.5-122b-a10b`、`qwen3-vl-flash`、`qwen3.8-2.4t-a95b`、
  `qwen3.8-27b`、豆包 2.1 Turbo/Pro，以及三个 DeepSeek V4 路由；这些模型在
  模型选择器中显示 thinking 开关。
- `Qwen/Qwen3-80B-AWQ` 实测开启参数后仍不产生 reasoning，Kimi 同样未产生 reasoning；
  GLM、Mimo、豆包 2.0 等路由会拒绝所测 thinking 参数，因此继续标记为 false，避免展示
  无效开关或触发 400，而不是盲目全部标记为 true。
- Qwen、豆包 2.1、DeepSeek 分别按实测兼容的参数格式路由；
  `qwen3.8-2.4t-a95b` 关闭时省略其会拒绝的 false 参数。可通过
  `TEAM_THINKING_MODELS` 覆盖完整能力表，显式空值才表示全部关闭。
- thinking 关闭时，上游即使仍返回 reasoning，也不会向用户展示思考过程；内部仍保留该段
  供工具调用上下文使用，最终正文照常输出，未新增或收紧任何输出门禁。

主要文件：`bi_agent/llm/registry.py`、`bi_agent/llm/provider_team.py`、`.env.example`、
`DEPLOYMENT.md`、`tests/test_regressions.py`。

测试：Team thinking 路由与能力表定向回归 24 项通过；全量 discovery 244 项通过。

### 可见思考中文约束与 turn 级自动 fallback

用户可见变化：
- 用户开启 thinking 且当前模型 `supports_thinking=true` 时，系统提示会注入简体中文
  可见思考约束：面向用户的思考摘要必须使用简体中文、简短概括，不得暴露逐 token 推理、
  隐藏指令、内部系统提示词或完整思维链；语言要求通过提示词约束模型原生输出，后端不做
  机械翻译，也不调用其他模型翻译。
- thinking 关闭时，会话层对 `thinking_delta` 增加兜底门禁：即使上游意外返回
  reasoning，也不会向用户转发任何思考内容，最终正文与工具调用照常输出，不新增门禁。
- 自动配额 fallback 改为仅当前 turn 生效：同一 turn 后续工具迭代复用临时 fallback
  模型，但不再改写用户已保存的模型选择、全局模型配置或默认模型；下一轮新请求仍从用户
  显式选择的原模型开始，只有设置界面显式保存才会永久修改模型选择。fallback 提示文案
  明确标注为“本次请求临时切换”。

主要文件：`bi_agent/web/session.py`、`DEPLOYMENT.md`、`tests/test_regressions.py`。

测试：新增会话级回归（中文约束仅在 thinking 开启且模型支持时注入、thinking 关闭不
转发 `thinking_delta`、fallback 不持久化且下一轮恢复原模型、同一 turn 工具迭代复用
fallback 模型、完整 12 个已验证模型能力表）；全量 discovery 244 项通过。

### 部署：今日功能同步生产环境

- 将今日已完成的功能同步到生产 release 目录
  `/home/data/zhangzhen_home/zhangzhen/openchat-BI-releases/f08a67b`：五步分析 SOP
  状态机（含 `sopMachine.js` 与前端构建产物）、Team thinking 能力表与参数路由、
  可见思考中文约束、turn 级自动 fallback、业务名称优先展示、并发治理与看板卡片
  展示位置修复。
- 部署前先备份原 release 源码到
  `f08a67b-backup-20260826-110556-thinking-sop`（排除 dataset 与运行数据），同步
  仅覆盖源码，未触碰 `.env`、`dataset/`、上传、图表与日志。
- 服务已按当前生产启动参数重启（`python -m bi_agent.web --host 0.0.0.0 --port
  8765 --db doris`），健康检查 `healthz=200`、`/workbench=200`；生产 API 确认
  `Qwen/Qwen3-80B-AWQ` 等未验证模型 `supports_thinking=false`，12 个已验证模型为
  `true`；运行日志无错误。
- 下午再次发布 SOP 五步名称显示调整（四个“与”改为半角 `&`）与团队默认模型切换
  （`direct-deepseek-v4-flash`）：部署前备份到
  `f08a67b-backup-20260826-133555-sop-ampersand`，仅同步源码与构建产物，重启后
  `healthz=200`、线上 `workbench.js` 已使用新名称；随后定点修改生产 `.env` 的
  `TEAM_MODEL`（修改前已备份 `.env`）并再次重启，`/api/config` 确认默认模型为
  `direct-deepseek-v4-flash`。全程未触碰 `.env` 其他配置、`dataset/`、上传、图表
  与日志。
- SOP 面板移除“正在进行：…”动作行展示（只显示五步名称与状态）也已同步生产：备份
  `f08a67b-backup-20260826-142610-sop-detail-off`，重启后线上 `workbench.js` 不再
  包含 detail 渲染，`/workbench=200`、`healthz=200`；旧进程在优雅关停期间因悬挂的
  LLM 网关请求未退出，按 uvicorn 提示以 SIGINT 强制结束后确认单进程运行，`.env`、
  `dataset/`、会话、上传、图表与日志均未受影响。

### 团队默认模型切换为 DeepSeek V4 Flash

用户可见变化：
- 团队网关默认模型由 `Qwen/Qwen3-80B-AWQ` 切换为 `direct-deepseek-v4-flash`，新
  会话默认模型选择同步更新；该模型位于已验证 thinking 能力表内，可见思考开关保持可用。
- 代码内置默认值（`TEAM_MODEL` 未设置时的回退）、`.env.example`、部署文档示例与
  生产 `.env` 的 `TEAM_MODEL` 全部同步为 `direct-deepseek-v4-flash`；`TEAM_MODELS`
  能力表未缩减，其他模型仍可选。

主要文件：`bi_agent/llm/registry.py`、`.env.example`、`DEPLOYMENT.md`、
`changelog/changelog_8_26.md`。

测试：registry 默认模型与 thinking 标记定向验证通过；`OfflineRegressionTests` 115 项、
`test_reliability` 25 项、`test_concurrency` 39 项全部通过。

### 行动章节边界修复与 Claim 候选稿只展示最终版本

用户可见变化：
- “行动建议”章节提取器新增扩展边界标题：`口径说明与限制披露`、`限制披露`、`冲突披露`、
  `数据限制`、`证据限制`、`风险与限制`；遇到这些标题（允许带 Markdown 标题符号、加粗、
  中文/英文冒号与括号说明）时行动章节立即结束。指标口径、物理表与关联键、可比样本范围、
  冲突披露、关系缺口、指标规格限制、样本量限制、数据异常、时间字段覆盖和结尾引导语不再
  被错误解析成行动条目。
- 有 Structured Claims 时，无工具调用的最终叙述先在后端缓冲；候选稿通过 Claim 校验前不
  发送用户可见 `text_delta`、不提交可见 assistant 消息、不进入 `chat_html`、不生成行动
  卡片。被拒绝的候选稿（如 `unsupported numeric fact: 65`）只作为内部修复上下文，最终只
  展示并保存通过校验的一份回答；同一轮 `action_recommendations` 结构化事件只发送一次，且
  只基于最终通过的 Narrative 提取。
- 校验器异常时保留可用候选并给出安全兜底，不返回空白、不无限重写、不重复执行
  SQL/图表/表格工具，也不新增任何输出门禁。

主要文件：`bi_agent/tools/analysis_policy.py`、`frontend/src/runtime.js`、
`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。

测试：新增行动章节扩展边界、会话最终稿只提取两条真实行动（BFHC 交付延迟、VEND001 内部
验收延迟）、限制/冲突/口径/样本量/数据异常不成为行动、Claim 拒绝不重跑工具、候选稿不展示
且最终稿只出现一次、行动事件只发一次等回归；全量 discovery 249 项通过。

### 指定历史会话 f8cf8d06 定点修复

用户可见变化：
- 本地历史会话 `dataset/conversations/f8cf8d06.json`（“到货周期拉长的原因是什么”轮次）按
  用户授权定点修复：移除迭代 18、19 两份被拒绝候选 Narrative 及其内部 claim 注入/拒绝提醒
  消息，正常对话区只保留最终通过校验的有效回答（无被拒的 `65%` 表述，冲突与限制独立披露）。
- 同步重建 `chat_html`：移除候选稿渲染块与“最终回答被阻止”系统提示，最终回答块内结构化
  行动卡片只保留两条真实行动（BFHC 交付延迟、VEND001 内部验收延迟），限制/口径项不再作为
  行动卡条目。
- `dashboard_html` 保持原样（无根因/行动/导出卡，1 张结论卡、4 张表格、6 张图表保留），
  `tools_html`、`ontology_html`、`llm_html`（调试区）与全部工具证据未删除；`message_count`
  80、`turn_count` 5、`updated_at` 等派生字段与 messages 一致。
- 修复前已在项目外备份目录
  `/Users/sher/Desktop/Boulderaitech/openchat-BI-backups/f8cf8d06-20260826-113130.json`
  保留原始文件（SHA-256 `8e281f…`），可随时回滚；未调用任何会话删除/reset 接口，未改动
  其他历史会话。

### 部署：行动解析与会话修复同步生产环境

- 生产 release `f08a67b` 代码备份到
  `f08a67b-backup-20260826-113643-action-claim-session`（排除 dataset 与运行数据）；
  同步仅覆盖源码与已构建静态资源（`analysis_policy.py`、`runtime.js`、`workbench.js`、
  `tests/test_regressions.py`、`changelog_8_26.md` 等），未触碰服务器 `.env`、`.venv`、
  `dataset/`、上传、图表与日志。
- 指定会话 `f8cf8d06.json` 已同步到服务器（与本地 SHA 一致），`history_index.json` 仅定点
  更新该会话单条索引项（备份 `.bak-20260826-113643`），未覆盖其他索引项。
- 服务按生产启动参数重启（`python -m bi_agent.web --host 0.0.0.0 --port 8765 --db doris`），
  `healthz=200`、`/workbench=200`；服务器会话恢复验收通过：仅一份最终回答、行动卡两条、
  无候选稿/拒绝提示、看板无根因/行动卡、图表表格保留，运行日志无错误。

### 全局本体子图卡片（GraphContext / GraphExpand）

用户可见变化：
- 工具调用后的“命中的本体”标签与“本体内容”页面的实体卡统一支持点击弹出本体子图；
  两个入口复用同一个弹窗、同一套数据接口和 ontology-agent 的网络图视觉语言。
- 点击绑定采用容器级事件委托，覆盖实时生成、历史会话恢复和后续动态插入的“命中本体”标签
  与“本体内容”卡片；静态 JS/CSS 资源版本同步递增，避免代理或浏览器继续使用部署前缓存而
  出现接口已上线但点击无响应。
- 弹窗默认展示 GraphContext 上下文子图，当前点击节点以描边高亮；点击“展开上下游”后在
  同一弹窗加载 GraphExpand 扩散图，支持拖动、缩放和相邻关系高亮。
- 可视化改为直接适配 ontology-agent 的 Sigma + Graphology + ForceAtlas2 实现：沿用其
  ForceAtlas2 参数、语义初始布局、重叠消解、标签阈值、相邻节点选择和“重新布局”交互；
  弹窗不再依赖 ECharts，也不会再调用未定义的 `loadEcharts`。
- 指标和业务对象可直接作为锚点；术语、业务属性、维度、逻辑实体等类型会沿已建模关系解析
  最近的指标或业务对象锚点，同时保留原节点为视觉焦点。例如 T000113 可回挂关联指标，
  AT0000347 可回挂所属业务对象。
- 子图查询是独立只读接口，按 `session_id` 使用当前会话本体源并校验远程 repository；不依赖
  semantic/graph 检索模式，不调用 LLM、不执行 SQL、不写入聊天历史、不推进 SOP。
- 本地 Excel 本体与远程生产本体共用统一 nodes/links 返回契约；关系边不可用或达到节点上限
  时在弹窗明确提示，不把合成邻接关系冒充权威方向证据。
- 兼容本体管理服务遍历物理表节点时返回“未知本体类型: TableNode”的已知缺陷：仅在命中该
  特定错误时自动改用只读 OpenCypher 获取同深度、同上限的节点与关系，其他鉴权、配置和
  服务异常仍原样失败，不被降级逻辑掩盖。

主要文件：`bi_agent/ontology/remote_retriever.py`、`bi_agent/web/app.py`、
`frontend/src/runtime.js`、`frontend/src/ontologySigmaGraph.js`、`frontend/src/workbench.css`、
`frontend/package.json`、`frontend/package-lock.json`、
`bi_agent/web/static/vendor/antd/workbench.js`、
`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`、`tests/test_regressions.py`、
`DEPLOYMENT.md`。

测试：真实远程本体联调通过（M0011、T000113、AT0000347 的 GraphContext 及 M0011 的
GraphExpand 均返回节点与关系）；前端生产构建成功；全量 discovery 253 项通过；
`git diff --check` 通过。

### 部署：全局本体子图卡片同步生产环境

- 生产 release `f08a67b` 的相关源码与静态资源已备份到
  `f08a67b-backup-20260826-152652-ontology-subgraph`；发布只同步本体子图后端、共享弹窗前端、
  构建产物、测试与文档，未覆盖 `.env`、`.venv`、`dataset/`、上传、图表或日志。
- 服务按生产参数重启，进程 PID `4138960`，`healthz` 与 `/workbench` 均返回 200；服务器实际
  静态资源已包含全局子图接口、共享弹窗和五步 SOP 的 `&` 文案。
- 生产真实本体验收通过：M0011 GraphContext 为 260 节点/351 关系，T000113 正确回挂 M0011，
  AT0000347 正确回挂 BO0005，M0011 GraphExpand 为 260 节点/352 关系；服务日志无异常。
- 首次发布后补充修复前端资源缓存版本与历史/动态节点点击委托，并重新同步生产静态资源；
  后续根据验收反馈将错误的 ECharts 渲染替换为 ontology-agent 同源的 ForceAtlas2 实现，
  并通过真实 Chrome 点击验证弹窗生成 7 层 Sigma canvas、无渲染错误；最终入口引用
  `workbench.js?v=161`、CSS `v=126`，无需改动或重启后端数据服务。
- 部署前后历史会话文件数均为 69，指定会话 `f8cf8d06.json` 的 SHA-256 均为
  `a7be1343995e3cd8be9a7d44567085681d99abd124a9777d810f49603326e88c`，历史数据未变化。
