# openchat-BI 变更记录（2026-08-25）

> 本文档只记录 2026-08-25 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-25

### 分析 SOP 拆分与循环进度

用户可见变化：

- 原六步线性 SOP 扩展为九个可观测阶段：识别意图、准备口径与上下文、
  规划取数方案、执行首轮查询、分析首轮结果、补充查询取数、验证与深挖、
  整理结论和图表、汇总交付；最后一步使用简洁的“汇总交付”名称，
  不再附加括号说明。
- 分析阶段支持真实回退循环：在“验证与深挖”或“整理结论和图表”之后
  再次执行 `SQLRun` 或 `MetricDataQuery`，进度会退回“补充查询取数”，
  新一轮查询完成后再前进到
  验证和结果整理，不再长时停在一个笼统的“深度分析”节点。
- 生成中间表格、图表或阶段性结论不会提前完成整轮 SOP，Agent 仍可继续
  取数、分析和验证。
- 只有 Agent 进入不再调用工具的最终回复时，“汇总交付”才显示为进行中；
  只有收到整轮终止 `done` 事件后，全部 SOP 才标绿。
- 历史会话中已保存的旧六步 SOP 在恢复时自动映射到新九步流程；已完成会话
  仍保持全部完成，不修改或覆盖任何历史会话数据。

主要文件：`frontend/src/runtime.js`、`frontend/src/main.jsx`、
`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。

验证：`OfflineRegressionTests` 100 项通过，前端 Vite 生产构建通过。

发布：已同步到测试服务器 `f08a67b` release 并重启 ChatBI；`/healthz`、
`/workbench` 和线上 `workbench.js` 均验证通过。覆盖前代码备份为
`f08a67b-backup-20260825-165305-sop-loop`，未覆盖或清理会话、上传、图表、日志和数据库目录。

### ChatBI 第一阶段并发治理

用户可见变化：

- 同一会话（`session_id`）已有回答在生成时，再次发送问题或选择会立即得到
  `409 SESSION_BUSY`，页面提示“当前会话仍在生成，请等待完成或取消”，不再让两个
  turn 交叉写同一会话。
- reset / 恢复历史 / 激活报表 / 切换数据源后，**新问题可以立即开始回答**：即使旧
  turn 的 LLM / Doris / 本体调用尚未返回，新 turn 也不会再收到 `409 SESSION_BUSY`；
  旧 turn 稍后返回时既不会提交答案，也不会清除新 turn 的生成状态。
- 请求即使**还在 admission 排队等待**（已持有会话 lease、尚未获得全局 active slot）
  也会被 reset / 恢复历史 / 激活报表 / 切换数据源立即取消：排队请求不再滞留到容量
  释放后才退出，也不会在重置后短暂占用全局 active；取消路径返回 `429
  ADMISSION_CANCELLED`，若恰好已获批则返回 `409 TURN_SUPERSEDED`，两种情况都不执行
  LLM / Doris / 本体工具。
- 服务繁忙时返回 `429`（`GLOBAL_QUEUE_FULL` / `PRINCIPAL_CONCURRENCY_LIMIT` /
  `ADMISSION_TIMEOUT`）并带 `Retry-After`，页面显示繁忙提示；不同会话互不阻塞。
- reset / 恢复历史 / 切换数据源会终止旧回答：旧流收到 `session_superseded`，页面停止
  旧流更新并清掉生成光标，旧 turn 不会写入新会话，也不会把部分回复保存为已完成。
- 排队规则现在是严格 FIFO：先到的请求先获得执行权，新请求不能插队；同一身份并发达到
  上限时不会卡死队列中其他可运行的会话。下游资源（LLM / Doris / 本体）繁忙等待期间
  取消或超时会快速返回明确错误，不再把 worker 线程阻塞到 30 秒。
- 所有关键 SSE 事件带 `turn_id`（`done` 额外带 `generation`），浏览器只接受当前 turn
  的事件，旧流不会清掉新流的 busy 状态；前端构建产物 `workbench.js` 已同步更新。

后端能力：

- 新增 `bi_agent/concurrency.py`：`RequestPrincipal` 身份抽象（当前以 `session_id`
  作为 `quota_key`）、session slot 注册表（turn 互斥 + generation + cancel）、
  `TurnLease` 一次性 turn 所有权、有界 FIFO admission controller（active/queued/
  超时/取消）、LLM/Doris/本体三类下游信号量（协作取消 + 100ms 轮询 + 超时）、
  session TTL/LRU 惰性回收。
- `SessionSlot` 改为租约所有权模型：`try_acquire(cancel_event=...)` 返回一次性
  `TurnLease`（generation + 唯一 owner），并在持有 slot lock 时**原子绑定**该 turn
  唯一的 cancel event（busy / owner / lease / cancel 一次设置，不存在先建内部 event
  再替换的未挂载窗口）；`attach_cancel` / `release_turn` / `is_superseded` 全部校验
  owner；supersede（reset/restore/activate/数据源切换）提升 generation、触发旧
  cancel 并**立即释放槽位**。旧 turn 的 `finally` 只能释放自己的 lease，绝不会清除
  新 turn 的 busy/cancel/owner；恢复历史复用同一 session 对象时，turn 上下文
  （slot+lease+cancel）在 turn 开始时一次性捕获，旧 turn 不会误读新 turn 状态。
- `AdmissionController` 使用唯一排队 ticket 的有界 FIFO：只有队首且同时满足全局容量
  与身份上限时才放行，新请求不能绕过已排队请求；队首因身份并发上限暂时不可运行时
  跳过放行其后可运行的请求，取消/超时从队列准确移除 ticket。
- `app._begin_turn` 在 admission 获批后**二次检查 supersession**：排队期间发生
  reset/restore/activate/数据源切换时，即使恰好在放行瞬间，也会立即释放刚获得的
  admission ticket 与（已失效的）session lease，返回 `409 TURN_SUPERSEDED`，不创建
  SSE 流、不执行任何下游调用，active/waiting 计数准确恢复，无 ticket/lease 泄漏。
- `ResourceLimiter.acquire(timeout, cancel_event)`：等待期间按 100ms 轮询，取消事件
  触发立即抛 `ResourceCancelled`，总时长超限抛 `ResourceTimeout`；LLM 调用通过
  `stream_message(cancel_event=...)`、Doris/本体工具通过线程级 cancel 上下文传入当前
  turn 的取消事件；semaphore 获得后**再次检查 cancel**，若在获批瞬间已取消则立即归还
  信号量并抛 `ResourceCancelled`，取消请求不会到达 provider/executor；所有取消/超时/
  异常/断开的路径都保证 slot、admission ticket 与下游信号量不泄漏。
- `_ensure_session` 改为“检查-创建-写入”原子化（双层检查），并发首请求只产生一个
  `WebSession`；reset/restore/activate/数据源切换先提升 generation 并取消旧 turn。
- `app.py` 全部 chat/choice/报表端点接入 turn guard 与 admission；`save_conversation`
  携带 `turn_id`/`generation`，被 superseded 的保存返回 `409 TURN_SUPERSEDED`。
- 锁顺序契约写入模块文档：registry → slot → WebSession 内部 → conversation store，
  禁止持锁做网络或等待全局信号量。

配置（`CHATBI_*`，均可选）：`CHATBI_MAX_ACTIVE_TURNS=8`、
`CHATBI_MAX_ACTIVE_PER_PRINCIPAL=2`、`CHATBI_MAX_WAITING_TURNS=32`、
`CHATBI_ADMISSION_WAIT_SECONDS=2`、`CHATBI_LLM_CONCURRENCY=6`、
`CHATBI_DORIS_CONCURRENCY=12`、`CHATBI_ONTOLOGY_CONCURRENCY=12`、
`CHATBI_SESSION_IDLE_TTL_SECONDS=7200`、`CHATBI_MAX_IN_MEMORY_SESSIONS=500`。

部署约束：当前并发状态在进程内，**只能单 Uvicorn worker**，多 worker 需后续共享状态
方案；`.env.example` 与 `DEPLOYMENT.md` 已同步说明。

主要文件：`bi_agent/concurrency.py`、`bi_agent/web/app.py`、`bi_agent/web/session.py`、
`bi_agent/llm/provider.py`、`bi_agent/tools/__init__.py`、`frontend/src/runtime.js`、
`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_concurrency.py`、
`tests/test_regressions.py`、`.env.example`、`DEPLOYMENT.md`。

测试：`tests/test_concurrency.py` 39 项（同/异会话互斥、409/429 契约、superseded
隔离、断开与异常释放、下游并发上限、TTL 只回收内存对象、AskUser→choice、报表模式、
claims 去重不回归；新增 lease 所有权、reset/restore 后新 turn 立即启动且旧 turn
不能释放新 turn、finally 交错、等待 LLM 信号量时 reset 快速取消且 slot/admission/
LLM token 均不泄漏、**admission 排队期间 reset/restore 立即取消且不占用 active、
放行与 reset 竞态下 ticket/lease 无泄漏、semaphore 获批瞬间取消容量完全恢复**、
LLM/Doris 等待取消与超时容量恢复、FIFO 顺序、principal 上限不卡队列、排队取消移除
ticket 等）；`test_regressions` 159 项、`test_reliability` 25 项、全量 discovery
223 项通过。

### ChatBI 业务名称优先展示

用户可见变化：

- 面向用户的正文、结论、表格和图表不再直接展示裸编码：有业务名称时，名称是主要展示
  文本，编码只作为次要追溯信息（首次或需追溯时形如“采购金额（M0001）”，重复出现时
  只写“采购金额”）；无法解析名称时保留原编码，不猜测、不编造名称。
- `ChartGenerate` 的标题、`series[].name`、`x_axis`、饼图 `data[].name`、
  `y_axis_name` 以及 `ChartGenerateMultiDim` 的 `dimensions[].label`、
  `dimensions[].x_axis`、`dimensions[].series[].name`、饼图分类在存在可信名称映射时
  自动规范化为业务名称；`default_dim` 与维度 `key` 保持不变，`source_note` /
  `scope` / `semantic` 中的追溯编码不丢失。
- `MetricDataQuery` 的 analysis 请求 `alias` 优先使用稳定业务名称（如“采购金额”），
  不再默认使用裸编码 `M0001`；重名时加稳定后缀“名称（编码）”；结果 metadata 同时保留
  `code`、`display_name`、`alias`、`kind`，并新增 `metrics` / `dimensions_meta` /
  `metric_names` / `dimension_names`，旧字段（`metric_codes`、`dimensions`）保持兼容。
- `TableGenerate` 表头优先使用业务字段名称；同时存在 `supplier_code` 与
  `supplier_name` 时名称列排在编码列之前、编码列保留用于追溯；用户明确要求查看编码时
  原样展示，不做强制替换。
- SQL 提示与 Agent 指令要求按编码维度聚合展示时同时查询名称字段（如 `unit_code` +
  `unit_name`），`SQLRun` 结果 metadata 在可确定时增加 `code_name_pairs` 配对信息；
  未确认关联关系时禁止猜测 JOIN。
- 正文兜底优先依靠提示词与结构化工具参数，不做危险的正则全局替换：SQL 代码块、URL、
  JSON、`source_note` 不会被名称处理误改。

后端能力：

- 新增 `bi_agent/display_names.py` 统一确定性名称解析层：本体对象名称优先级（有效中文
  label > 有效中文 name > label > name > alias > code）、`display_text` 追溯格式、
  编码识别（本体编码 / 业务 code 字段 / 物理字段名）、`unique_aliases` 稳定去重、
  图表 / 多维图 / 表格参数规范化入口。
- `WebSession._execute_tool` 在渲染工具执行前按会话可信名称映射（最新查询结果
  metadata → 会话已见本体实体 → 本地本体库）规范化参数；远端会话不回退到无关的本地
  工作簿，避免错误解析。
- `remote_ontology_tools._resolve_display_names` 复用已取得本体信息与客户端缓存，仅对
  未解析编码做有界 `metadata_query` 查询，失败自动降级为原编码，不阻塞数据查询。

Agent 提示词：`.claude/agents/bi-analyst.md`、`report-analyst.md`、
`report-generator.md` 新增“业务名称优先展示”、图表 / 表格名称字段规则与 SQL
code/name 配对规则，保留编码证据追溯要求与既有 Level / 证据链 / 可靠性规则。

主要文件：`bi_agent/display_names.py`、`bi_agent/tools/remote_ontology_tools.py`、
`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、
`bi_agent/tools/table_tools.py`、`bi_agent/tools/sql_tools.py`、
`bi_agent/web/session.py`、`.claude/agents/bi-analyst.md`、
`.claude/agents/report-analyst.md`、`.claude/agents/report-generator.md`、
`tests/test_regressions.py`。

测试：`test_regressions` 新增 18 项（名称优先级与降级、MetricDataQuery alias/metadata、
柱状图 / 饼图 / 多维图名称规范化、表格表头与 code/name 顺序、显式编码不强制替换、无
可信名称不猜测、SQL / JSON / URL 不被误改、claims / scope 与图表校验不回归），
`test_regressions` 159 项、`test_reliability` 25 项、`test_concurrency` 39 项、
全量 discovery 223 项通过。

### Evidence Consistency Guard 与非空回答兜底

用户可见变化：

- Doris / 本体数据接口把数值返回为字符串（例如 `"500"`）时，系统仍能生成对应 FACT
  Claim，不再因为传输类型差异误报 `unsupported numeric fact: 500`；嵌套在
  `data.result.rows` 中的结构化结果同样支持。
- 数字已完全退出最终回答门禁：任意数字格式、舍入、元/万元/亿元等单位换算、百分比、
  差额、占比和同比/环比均不会触发 `REJECT`、重写、`answer_blocked` 或证据兜底；例如
  `67745.47 元` 写成 `6.77 万元` 可直接正常输出。数字可靠性改由取数口径、来源说明和
  Agent 提示约束保障，不再使用数字 token 与 Claim allow-list 比对。
- Claim 从“全部叙述的主门禁”降级为证据一致性护栏：合理推断和建议允许超出 Claim
  字面内容；已知冲突未披露、代理指标冒充真实指标仍是硬问题。关联冒充因果、推断写成
  已确认等软风险只局部弱化措辞并补充证据限制，不再整段重写或阻断。
- 有 Claim 的首个合格候选直接交付，不再为了注入 Claim 上下文无条件丢弃并生成第二稿；
  只有硬事实问题才隐藏候选并要求一次针对性修正，重复硬失败才输出确定性的证据兜底。
- 证据校验器自身异常时 fail-open：记录 `answer_validation` warning 并保留候选答案，
  不把校验器可用性变成回答可用性。最终 Narrative 连续两次硬校验失败时，也不会吞掉
  所有正文、只留下 ontology 工具操作和 `answer_blocked`，而会输出并保存“已确认
  Claims + 缺失证据 + 后续处理”的安全回答。
- 模型耗尽执行轮次仍只有本体/schema 工具调用时，系统会明确说明已确认内容、缺失的
  数据查询或物理映射，不再把本体操作本身当作最终业务答案。
- BI Agent 增加本体检索停止条件：唯一锚点和可执行映射确定后必须进入
  `MetricDataQuery` / `SQLRun`；映射持续缺失时停止同义反复检索并交付限制说明。

主要文件：`bi_agent/reliability.py`、`bi_agent/web/session.py`、
`.claude/agents/bi-analyst.md`、`tests/test_reliability.py`、
`tests/test_regressions.py`。

测试：新增数值字符串、嵌套结果、查询技术参数排除、确定性差额/增幅派生、合理建议软
风险、因果措辞局部降调、校验器异常仍交付、连续硬校验失败安全回答、本体工具耗尽轮次
仍有用户交付等回归覆盖；`test_regressions` 159 项、`test_reliability` 25 项、
`test_concurrency` 39 项、全量 discovery 223 项通过。
