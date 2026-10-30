# Process360 V3.1 / V1.2 验收与未完成清单

验收日期：2026-10-28。首次验收基线：`feature/process360-ontology-closed-loop` 的 `a23f9c7`，
首次修复分支 `bugfix/process360-acceptance-hardening`。第二批补齐分支：
`feature/process360-v12-closed-loop`（基线 `f68b0b7`）。
两轮均没有部署、正式版本升级、真实任务下发或业务库写入。

> 阅读顺序：第 1-5 节保留首次验收记录；第 6 节是第二批补齐后的最终代码状态和剩余阻塞。

## 1. 验收结论

**首次验收为部分实现；第二批代码侧已补齐，但仍不能认定为真实 V1.2 端到端闭环通过。**

- 本地 V3.1 本体与 V1.2 SOP 来源正确；在临时目录从指定 Excel/Word 重建，除 `generatedAt` 外与已提交 catalog 完全一致。
- 已具备五场景的受控查询、静态语义上下文、候选原因、可信草稿、Fuxi 待办接口和受阻断复验计划。
- 第二批已实现身份交集、证据验证、冻结基准、单条行动消费、持久化幂等、多目标 DAG、S08 白名单探索，以及 P04/P05/P07/P14/P17/P18 的代码路径。
- 仍不能宣称真实闭环：业务批准口径、真实证据、Fuxi 宿主权限注入与人员解析、真实任务回执/处理进度、主服务对话入口和端到端页面点击均未完成联调。
- 不提交数据库凭据、业务明细、查询输出或用户提供的原始文件。本报告记录验证结论，不归档真实业务数据。

## 2. 来源及运行验证

| 项目 | 结果 |
| --- | --- |
| `亿纬锂能_流程360本体元模型_V3.1_新增数据表联动版.xlsx` | SHA256 `8ee68d1e357d55930b2c9292c20ad582e4ed10745367ebfba19ce232f4e4a344` |
| `流程360本体检索与闭环Skills设计方案_V1.2_问题分类SOP版.docx` | SHA256 `a00558c3ef270d8b65567bb34800955666e6931d48b6a2bc94d1eeb3a2265da2` |
| catalog 校验 | 206 指标、84 规则、5 场景、7 流程、26 活动、16 Action、8 方案、8 任务模板、14 证据模板、5 复验、18 SOP；引用校验无错误 |
| 真实库 | 用户指定连接可达；数据库 `ywln`、schema `ywln_crm`；事务只读，隔离级别 `repeatable read` |
| 五场景 | SQL 均可执行；SC01/02/03/04 为 `partial`，SC05 因未知/歧义计划分类为 `blocked`，正式指标为 null |
| 维度过滤 | 对五场景全部 9 个已支持的场景/维度组合检查无匹配 ID，均未扩大范围、无查询错误、无意外明细；不支持维度在访问数据库前阻断 |
| 上限一致性 | 五场景 `limit=1` 与默认上限的指标一致；明细截断有标记 |
| 阻断传递 | 真实 SC05 的 blocked 查询不会触发异常或输出可下发任务 |
| 写操作 | 未调用真实 Fuxi 创建、更新、通知、关闭接口；未创建数据库表或临时表 |

## 3. 已完成优化清单

| 编号 | 原问题 | 最终行为与主要文件 |
| --- | --- | --- |
| F01 | Scope 把字符串 `false` 当成真、上限隐式修正、ID 字符串当数组、日期截断、未知字段被忽略 | 严格类型/范围/别名冲突/日期一致性校验；非法范围不查库。`models.py` |
| F02 | 传入未映射维度后静默查询全量 | 按场景白名单在查库前返回 `needs_clarification` 与 `UNSUPPORTED_FILTER`。`queries.py` |
| F03 | SC02 客户/负责人、SC04 客户筛选没有落 SQL | 聚合与明细使用同一组参数化筛选；不把销售姓名或型号猜成负责人/产品 ID。`queries.py` |
| F04 | SC01 质量统计没有应用筛选，订单行关联与主查询不一致 | 补客户/负责人/产品过滤及订单/行号关联；产品过滤使用真实 CTE 别名。`queries.py` |
| F05 | SC03 使用有限明细的条数计算全量指标 | 独立全量 COUNT 聚合，明细上限只影响展示。`queries.py` |
| F06 | 多条 SQL 各开一个连接，汇总和明细可能跨数据版本 | 同场景共享只读 REPEATABLE READ 事务，结束统一 rollback/close；保留参数化、行数与超时限制。`db.py` |
| F07 | SC03/04 历史截止日被当作当前存量观察日；SC01 显式当前快照仍使用旧截止日 | 当前存量不能回填历史；显式选当前快照时变更实际观察日并保留 `requestedScope`；SC05 历史对账缺计划快照直接 blocked。`queries.py` |
| F08 | 缺金额/电量被转成 0；价格单位缺失默认 1；非法单位字符串导致整批失败 | 缺值保留 null，价格单位做安全数值判断，缺/零电量及缺价单列；空集合的确定零与未知值区分。`queries.py`、`analysis.py` |
| F09 | 明细 SQL LIMIT 后没有披露截断 | 与全量计数比较，SC01/02/03/04/05 均披露截断。`queries.py` |
| F10 | SC05 仅把未匹配记录填入正式计划外指标，漏算已对齐计划超发，且含税兜底免税金额 | 实际发货先按订单/行/产品/日期汇总：明确无日计划取实际量；有计划且已对齐取 max(实际-计划,0)；按数量比例分摊免税金额；没有可靠分类不发布正式指标。`queries.py` |
| F11 | SC05 blocked 指标仍可触发风险；SC02 批准报价数被当作红区异常 | 分析只消费可用指标；整体阻断时异常为 unverifiable、无确认风险或候选根因；SC02 红区缺映射不触发。`analysis.py` |
| F12 | 0 值被 `or` 回退覆盖；澄清状态进入分析后变成 blocked | 使用显式 None 判断；保持 `needs_clarification/not_applicable/blocked`。`analysis.py` |
| F13 | 缺 P07/P13/P14 的真实路由，P18/P04/P08/P17 的设计例句被其他模式截走 | 补齐路由及优先级、指标编码场景识别、allowed_scenarios 校验；覆盖设计文档例句。`router.py` |
| F14 | 路由成功后所有问题都走查询、诊断、任务草稿 | 问数到 S03 停止，诊断到 S04 停止，明确草稿才进入 S05；未实现 SOP 返回明确缺口，不伪装已完成。`service.py`、MCP 引导语、仓库 Skill |
| F15 | 缓存 catalog 返回内部可变字典，场景检索先 LIMIT 后过滤 | 公共返回防御拷贝；文件加载先校验引用；先按场景过滤再截断；相对路径按 cwd 解析。`catalog.py`、`context.py` |
| F16 | blocked 分析仍生成 ok 草稿、跨场景分析被接受、未知方案静默为空、缺任务映射借用其他模板 | 阻断草稿不返回可执行 actions；校验分析场景/本体版本和方案归属；不借用无关模板。`service.py`、`plans.py` |
| F17 | 手机号可从 owner/metadata 或错误回执进入页面和模型 | 草稿和下发前检查完整任务/元数据；错误不回显原始收件人，Fuxi 回执错误递归脱敏。`plans.py`、`execute.py`、`fuxi_todo.py`、MCP |
| F18 | 收件人迭代器发送后再次消费导致“成功写入却返回失败” | 下发前归一化一次，传输与回执计数复用同一列表。`execute.py` |
| F19 | 中文或超长 ID 归一化碰撞；无页面范围的 Process360 默认任务 ID 跨批次复用 | 有损转换追加稳定摘要；Process360 直接执行必须提供 canvas 或显式来源幂等键。`fuxi_todo.py`、`execute.py` |
| F20 | 空 Fuxi JSON 被误报成功 | 需有效 applied/skipped 回执且无 errors；真实下发仍未在本轮执行。`fuxi_todo.py` |
| F21 | RF03/RF06 非空示例值被当作已批准目标；复验未把数据库失败传播到顶层 | 本地 RF 保留为未批准设计参照；冻结基准检查场景/版本/对象/日期/窗口/指标；查询缺口上浮，永不自动关闭。`verify.py`、`service.py` |
| F22 | MCP 调用方忽略 JSON schema 时未知字段仍被接受，查询失败还被误报为配置不可用 | 七工具服务端校验参数类型、必填、枚举和上限；查询错误与连接不可用分开，异常不回显数据值。`tools.py`、`service.py`、`db.py` |
| F23 | 核心闭环测试固定历史日期，次日失败 | 冻结测试时钟，保留生产历史快照阻断规则。`tests/test_process360_engine.py` |

兼容说明：普通 ASCII 短幂等 ID 保持原样；中文、特殊字符或超长 ID 的自动生成规则增加摘要。已有任务重试应显式沿用原 `source_todo_id`，避免被识别为新任务。SC05 诊断扩展字段使用 `outsidePowerGwh` 表达已分类超计划量；正式展示优先消费带状态的 `metrics[]`。

## 4. 未完成问题登记（不得记作验收通过）

P0 表示对正式经营结论/执行安全有影响，P1 表示 V1.2 核心能力缺失，P2 表示可用性/交付完善项。

| 编号/优先级 | 未完成内容 | 完成依赖及验收标准 |
| --- | --- | --- |
| U01 / P0 | SC01 订单行有效状态、完整版本映射未覆盖本体要求；G01/G12/G13/G16 未业务验收 | 补权威物理字段、主键唯一性和版本规则；校验订单行有效性、交期、价格单位、电量后与业务台账对账；当前值为暂定 partial |
| U02 / P0 | SC02 M0137/M36002 无红区价格区间和审批范围；G02、RF02/RF08 未批准 | 接报价明细、红区分界与授权制度，区分毛利红区阈值与报价占比提醒线；批准时间缺失需补齐 |
| U03 / P0 | SC03 M36003/M0140/M0180 缺批准计划客户全集与目标/商机完整映射 | 固定分母、期间、客户等级和值域；不能用当前客户表替代计划集合 |
| U04 / P0 | SC04 G04 项目/商机/正式订单关联和周期未验收 | 证明项目名称版本键可靠、关联覆盖完整、正式订单状态与周期起止可复算；RF04 的 30 天只是示例 |
| U05 / P0 | SC05 真实数据存在重复/未知计划分类，G12/G13/G15/G16 与 RF09 未完成 | 业务确认唯一行映射、计划版本、标记/对齐状态、批准例外、产品电量及后续窗口目标；不能凭代码替业务选择重复计划或把未匹配视为违规 |
| U06 / P0 | G06 原因证据未接入验证器、反证及证据版本 | CF/EV 目前为静态模板；接生产/质量/物流等证据后才能把候选原因升级为已验证原因 |
| U07 / P0 | G07 运行记录与实际效果复验未实现 | 持久化原问题/对象集合/价格与数量基准/执行回执；实现 M36005 净履约化解，剔除取消/移出等伪改善；接批准 RF/窗口/人工验收，才能判定允许关闭范围 |
| U08 / P0 | 用户/组织数据权限与审批不是由本模块完整执行 | 当前 Scope 是筛选，不能代替身份授权；需平台注入可信用户范围并在取数前强制过滤；Fuxi 点击授权、人员解析、审批/回执需端到端联调；本轮未用 postgres 账号验证用户级隔离 |
| U09 / P1 | S00 只有单 SOP/单场景选择，没有多目标 DAG、步骤/计划版本与恢复 | 已修复代码侧：`planner.py` 实现复合目标拆分、依赖校验、计划版本、共享预算和局部完成；真实复合问题仍需模型路由联调。 |
| U10 / P1 | P04 多期比较、P05 结构贡献/排名、P07 流程转化、P14 进度、P17 预测、P18 综合编排未实现 | 已修复代码侧：`advanced.py` 提供六个工具；P07 缺轨迹、P17 缺假设/目标时明确 blocked，P14 只读本服务回执。 |
| U11 / P1 | S01 关键词召回、S02 一次场景 bundle 与设计的受预算逐步骤装配仍有差距 | 部分修复：权限绑定、数据快照指纹和上下文过滤已实现；多指标意图拆分与逐步骤按需装配仍需继续。 |
| U12 / P1 | S08 自主探索与共享预算账本、去重恢复未实现 | 已修复代码侧：服务端工具白名单、task/plan/step 绑定、请求哈希去重、共享预算和 path_gap 回原步骤。 |
| U13 / P1 | S05 方案比较/约束验证未完成，草稿主要是模板映射 | 代码侧已补结构/约束校验和可信草稿；缺批准成本/周期/效果依据时不做量化评分。 |
| U14 / P1 | MCP `TaskOrderCreate` 与 Process360 执行辅助函数仍为不同入口 | 已修复：MCP 草稿模式回读服务端草稿，校验租户/用户/hash/action/审批/canDispatch；单条消费、持久化幂等和回执落库；旧通用入口保留兼容但禁止冒充 Process360 草稿。 |
| U15 / P2 | 原生主服务对话入口未完成专属工具注册/引导验收 | 仍未完成：本分支验证 MCP/Skill；主服务对话的真实工具注册、引导和展示链需另行联调。 |
| U16 / P2 | 浏览器/Fuxi 宿主真实点击、人员解析、进度回执、页面闭环尚未人工端到端验收 | 仍未完成：只做了 fake/模拟宿主契约测试；真实 Fuxi 测试任务、账号、人员范围和回执需用户授权后执行。 |

P13 发运/签单/调价业务写操作被当前产品边界有意排除，不作为默认待补接口；需要另行确定产品范围和授权。

## 5. RED → GREEN 证据与复现

- 原基线组合测试：1 failed / 31 passed；失败来自固定日期进入历史快照阻断。
- 第一组新增回归：36 failed / 1 passed，证明范围、统计、状态、隐私、草稿及 RF 边界问题存在。
- 后续补充 RED：设计例句/未实现 SOP/参数校验/幂等/空回执出现 13 个失败；另行确认事实停止点、历史 SC05、隐私回执与实际 MCP 下发路径的失败，再修复。
- 最终新增 `tests/test_process360_acceptance_red.py` 71 项；`tests/test_process360_sql_contract.py` 9 项。
- PostgreSQL SQL 合约用 `SELECT/VALUES/generate_series` 合成数据，不创建表、不读取业务表；覆盖先聚合再求超发、明确无日计划、未知标记/未对齐/无计划/缺计划量、重复计划、免税金额不兜底及事务属性。
- 默认回归不隐式连真实数据库；SQL 合约测试必须显式设置 `PROCESS360_ACCEPTANCE_DSN`，本轮已用用户授权连接执行通过。
- 最终组合回归 **142 passed**，其中包括显式连接 PostgreSQL 的 9 项 SQL 合约测试；五场景真实数据只读查询、9 组筛选和上限不变性检查全部通过。
- `ruff check --select F` 与 `git diff --check` 通过；原始业务输出仅临时检查，不进入仓库。

```bash
python -m pytest -q tests/test_process360_catalog.py tests/test_process360_engine.py \
  tests/test_process360_acceptance_red.py tests/test_process360_sql_contract.py \
  tests/test_fuxi_todo_actions.py tests/test_mcp_endpoint_red.py \
  tests/test_ontology_metadata_query_consumption_red.py tests/test_remote_ontology_fast_path_red.py
# 无显式数据库配置时，9 项 PostgreSQL 合约用例按设计跳过；单独配置后执行全部 9 项。
```


## 6. 第二批补齐（2026-10-28，`feature/process360-v12-closed-loop`）

### 6.1 代码侧已完成

| 能力 | 实现 | 验证 |
| --- | --- | --- |
| 运行记录 | `store.py` SQLite：runs/drafts/actions/action_consumptions/executions/receipts/plans/exploration_calls/evidence/approvals；支持导出 | `test_process360_store.py` |
| 身份权限 | `identity.py`：tenant/user 必填；org/role 范围与查询筛选取交集，交集为空拒绝 | `test_process360_identity.py` |
| 证据验证 | `evidence.py`：来源、哈希、对象、期间、规则、必需内容、反证分别校验；哈希正确不等同根因成立 | `test_process360_evidence.py` |
| 冻结闭合 | `closure.py`：只使用服务端冻结 baseline、批准目标和交付证据；取消/移出对象不自动算改善；SC05 无批准公式时 blocked | `test_process360_closure.py` |
| 可信草稿与下发 | `service.py`：草稿落库；`TaskOrderCreate` 回读；租户/用户/hash/action/审批/canDispatch 校验；单条行动一次性消费；持久化幂等；Fuxi 回执落库 | `test_process360_execution.py`、`test_process360_mcp_contract.py` |
| 建议卡 | `CanvasGenerate` 透传 `draftId/draftHash/runId/actionId/approvalStatus/expiresAt/dispatchTool`；待审批/过期阻止；拒绝行动条目中的手机号 | `test_fuxi_todo_actions.py` |
| P04/P05 | 多期同口径比较、结构汇总/排名/占比 | `test_process360_advanced.py` |
| P07 | 按 objectKey/batchKey 计算节点转化和停留；缺轨迹 blocked，不用节点总数相除 | `test_process360_advanced.py` |
| P14 | 只读当前用户在本服务的执行记录和 Fuxi 推送回执 | `test_process360_advanced.py`、`test_process360_execution.py` |
| P17/P18 | 显式假设下的规则推算；多子目标综合，局部 blocked 不伪装完成 | `test_process360_advanced.py` |
| 多目标与探索 | 多目标 DAG、依赖、计划版本、共享预算；探索工具白名单、请求哈希去重、path_gap | `test_process360_plan.py` |

### 6.2 建议卡到 Fuxi 待办

```text
Process360Draft
  → CanvasGenerate kind=actions
  → 用户点击“发送任务令”
  → Fuxi 宿主补 principal + recipients_raw
  → TaskOrderCreate(draft_id, draft_hash, action_id)
  → 服务端回读可信草稿
  → 单条 action 消费 + persistent idempotency
  → POST /source/todo-batches (boulderai-anaylize-todo)
  → 保存 applied/skipped/errors 回执
```

- 按钮 payload 只含不透明草稿引用和展示字段，不含手机号、连接串、SQL 或凭据。
- 旧通用 `TaskOrderCreate` 仍可用于非 Process360 场景；一旦带 Process360 标记但没有
  草稿，直接拒绝，不能绕过草稿/审批校验。
- Fuxi 只有 `POST /source/todo-batches` 和 `POST /source/todo-status-events`，
  没有单条查询或执行进度接口；P14 的“已处理完成”必须等 Fuxi 回传状态事件，
  当前只能证明“已推送并收到回执”。

### 6.3 仍然阻塞

- 真实业务负责人尚未批准成本/周期/效果依据，方案量化比较和 SC05 关闭公式保持 blocked。
- 真实证据（生产/质量/物流等）未接入，候选原因不能升级为已验证根因。
- Fuxi 宿主尚未提供真实测试账号、人员和任务范围；真实点击、人员解析、进度回执未联调。
- 原生主服务对话入口的工具注册/引导/展示链未验收。
- 本轮未部署、未发送真实任务、未创建 MR/tag/Release。

### 6.4 回归结果

```bash
pytest -q tests/test_process360_*.py tests/test_fuxi_todo_actions.py tests/test_mcp_endpoint_red.py
# 136 passed, 9 skipped（9 项 PostgreSQL 合约需 PROCESS360_ACCEPTANCE_DSN）
```

全量 `pytest -q tests`：1514 passed、37 skipped、1 failed。唯一失败是 worktree 缺少
`frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题，与本轮
Process360 改动无关，未修改该前端依赖或断言。

### 6.5 第三轮收口（统一请求、计划、产物与下发）

本轮在现有实现上收口，不换框架、不另开服务。目标是让一次用户请求沿
“可信身份 → 受控范围 → 同源数据 → 有约束的计划 → 可追溯分析 → 可信草稿 →
幂等下发 → 真实回执 → 绑定产物”完整追踪。

| 能力 | 最终行为 | 主要文件/测试 |
| --- | --- | --- |
| 统一请求上下文 | MCP、页面下发和审计共用 `principalId/tenantId/grantKind/grantScope/ authorizationVersion/conversationId/requestId/surface`；模型或页面提交身份字段直接拒绝 | `request_context.py`、`mcp_endpoint.py`、`test_process360_request_context_red.py` |
| 权限显式化 | 缺 `grantKind` 不再默认全量；POC 默认只读，下发由 `PROCESS360_POC_DISPATCH` 单独开启；撤权、换授权版本后旧 query/publication 不再可读 | `identity.py`、`test_process360_authorization_red.py` |
| 查询结果契约 | `queryId` 绑定来源连接、规范范围、catalog/模板版本、授权指纹、有效期、完整性、结果哈希和完整行；Query/Analyze/Draft/Structure/Verify 可复用；换范围或撤权明确 blocked | `service.py`、`store.py`、`test_process360_query_contract_red.py`、`test_process360_query_reuse.py` |
| 计划强制 | 公共 MCP 业务工具必须 `planId + stepId`；校验步骤工具、依赖、场景、范围、澄清项；计划步骤结果单独落库，修订保留原计划 | `service.py`、`store.py`、`test_process360_sop_enforcement_red.py` |
| 产物闸门 | 正式报告必须带 `canvasId/artifactHash`，缺省 `deliveryKind=analysis_report`；缺失直接 reject；通过/失败都登记 append-only artifact，并绑定 request/plan/query/run | `mcp_endpoint.py`、`store.py`、`test_process360_artifact_and_dispatch_failure_red.py` |
| 可信批准 | Verify 从 `approvalRef` 读取目标、方向、最低分母和有效期；模型自填目标不能代替批准，缺记录/过期/冲突均 blocked | `service.py`、`test_process360_trusted_approval_red.py` |
| 统一下发 | 页面和 MCP 共用执行服务；稳定幂等键 `tenant:draftId:actionId`；发送前原子 claim；状态区分 `queued/sending/succeeded/blocked/rejected/unknown`；登记失败绝不调用 Fuxi | `dispatch.py`、`service.py`、`store.py`、`test_process360_dispatch_unified_red.py` |
| Canvas 状态机 | 空回执、缺 `sourceTodoId`、`accepted!=true` 不显示成功；`blocked/rejected` 优先；HTTP 超时不自动切宿主；父窗口来源、ack/result、刷新恢复和草稿过期分别处理 | `ontology-analytics-mcp/canvas_tool.py`、`test_process360_canvas_state_red.py` |
| 驾驶舱来源 | 整页与 AI 卡片显式绑定 `dataSource/dataIdentity/dataFingerprint/chartQueries`；来源不同的 AI 结果不能覆盖 AP 页面；页面和卡片缓存按来源隔离 | `cockpit/page_cache.py`、`cockpit/publications.py`、`test_cockpit_page_cache.py` |

验证：

```bash
pytest -q tests/test_process360_*.py tests/test_fuxi_todo_actions.py \
  tests/test_mcp_endpoint_red.py tests/test_cockpit_page_cache.py \
  tests/test_cockpit_main_service.py tests/test_cockpit_publications.py \
  tests/test_cockpit_card_delivery.py
# 230 passed, 9 skipped（9 项 PostgreSQL 合约需 PROCESS360_ACCEPTANCE_DSN）
git diff --check
```

全量 `pytest -q tests` 为 1578 passed / 37 skipped / 1 failed；唯一失败仍是 worktree 缺少
`frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js`，与本轮 Process360、
MCP、Canvas 和 Cockpit 改动无关。

仍需业务或宿主条件才能关闭：

- 真实业务批准记录、生产/质量/物流等外部证据尚未接入；候选原因不能升级为已验证根因。
- 真实 Fuxi 测试账号、人员、任务范围和真实点击/回执未联调；本轮未发送真实待办。
- 驾驶舱目前显式来源为 AP；尚未把看板图表切换到 Process360 PostgreSQL 查询。切换前必须
  保持 `dataSource` 分离，不能把两套结果混成一份证据。
- 本轮未部署、未创建 MR/tag/Release、未升级正式版本、未写业务库。

### 6.6 第四轮下发与恢复收口（基线 `47a4e83`）

| 问题 | 修复结果 | 验证 |
| --- | --- | --- |
| 旧版 `TaskOrderCreate` 绕过下发权限 | 权限检查前置到所有发送分支；无 `canDispatch` 时不创建 Fuxi 客户端、不调用发送 | `test_process360_dispatch_recovery_red.py` |
| Canvas 回执判断偏宽 | 成功必须同时满足 `status=ok`、`accepted=true`、`receipt.ok=true`、`applied+skipped>0`；`sourceTodoId` 本身不再足以判成功 | `test_process360_canvas_state_red.py` |
| 查询复用未校验来源连接 | `queryId` 复用比较当前 `sourceConnection`，变化返回 `QUERY_SOURCE_CONNECTION_CHANGED` | `test_process360_query_reuse.py` |
| 超时恢复未闭环 | 超时覆盖响应体读取；页面持久化待确认行动、刷新恢复并轮询；HTTP 接受显式 `retry=true`，状态接口返回 `retryable` | `test_process360_canvas_state_red.py`、`test_process360_request_context_red.py` |
| `not_applicable` 被记为完成 | 计划步骤区分 `completed/skipped/needs_input/blocked`；`not_applicable` 为 `skipped`，不能解锁依赖 | `test_process360_dispatch_recovery_red.py` |
| 阻断结果缺来源 | PG 查询即使 blocked 也保留 `dataSource/sourceConnection/scope` | `test_process360_dispatch_recovery_red.py` |

验证：Process360、Fuxi、MCP 与 Cockpit 相关组合测试为 `240 passed / 9 skipped`；Cockpit
JavaScript 测试为 `21 passed`；Canvas 生成脚本通过 `node --check`。9 项跳过仍为需要
`PROCESS360_ACCEPTANCE_DSN` 的 PostgreSQL 合约测试。全量 `pytest -q tests` 为
`1588 passed / 37 skipped / 1 failed`，唯一失败仍是 worktree 缺少
`frontend/node_modules/@boulderaitech/ontology-graph/src/layout.js` 的环境问题。
未部署、未发送真实 Fuxi 待办、未创建 MR/tag/Release。
