# Process360 伏羲执行过程核对（2026-10-28）

## 0. 核对边界

本报告核对的是本地伏羲实际执行五组样例问题时的会话、推理、工具调用、工具返回状态、阻断结论、输出闸门和运行记录，不以交付 HTML 的视觉效果、卡片排版或页面文案作为判断依据。

核对范围：

- 工作区：`/Users/sher/Boulderaitech/eimosp-process360-acceptance-worktree`
- 分支：`feature/process360-v12-closed-loop`
- 基线提交：`9385a4968f21a2a8f4c58faf26798659c5e5a546`
- 本地 MCP：`http://127.0.0.1:18765/api/mcp`
- 已安装 Skill：`~/.fuxi/skills/ontology-analytics/SKILL.md`
- 伏羲连接器：`~/.fuxi/connectors/ontology-analytics-mcp/.fuxi-meta.json`

取证方法：

- 每个会话的用户消息、助手推理和工具卡片位于
  `~/.fuxi/sessions/<session>/tasks/<task>/thread.jsonl`；
- 其中 `message.updated.payload.message.activities` 保存本轮 `reasoning` 和 `tool` 活动；
- Process360 服务端运行记录位于当前工作区的
  `dataset/process360/runtime.sqlite3`；
- 本次只读查询运行记录、草稿和动作表，没有删除会话、没有调用删除接口、没有写业务库。

## 1. 总体结论

**五份最终样例都进入了 Process360 主流程，但不是五份都严格符合 SOP。**

可以说符合的部分：

- 五行用户消息都带有 `[[skill:ontology-analytics|硕磐智能分析 Agent]]`，说明五份最终样例都显式选择了技能；
- 五份都先调用了 `Process360Route`，再进行 `Process360Context` 和受控取数；
- 取到数据后都区分了 `ok / partial / blocked`，没有把 blocked 指标补成 0，也没有把候选原因包装成确认根因；
- 五份都调用了 `CanvasGenerate`，并且最终都执行过 `OutputGateCheck`；
- 五份都没有调用 `TaskOrderCreate`，没有发送真实待办；`runtime.sqlite3.executions` 当前为 0；
- 五份最终都生成了 Canvas Artifact，说明整页交付链路实际执行过。

不能判定为“完全按 SOP 执行”的部分：

1. **最严重的问题是 principal 不可信。** Skill 要求所有 Process360 业务工具使用宿主注入的 `principal`，缺失时停止业务取数。实际推理中模型明确写下“没有真实 host identity”或“没有宿主注入”，随后自行猜测 `tenantId/userId` 继续查询。运行记录显示不同场景使用了 `demo2/fuxi-readonly`、`default/fuxi-session`、`ywln/fuxi-local` 等不同身份，SC03 甚至没有形成可核对的 `runs` 记录。这个问题影响授权边界，不能用“结果是只读的”来抵消。
2. **SC05 的 `needs_clarification` 没有被遵守。** 第一次 `Process360Route` 给出 SC05/SC01 需要澄清的信号，模型自行根据“偏离日计划”固定为 SC05，没有先向用户提出 2–3 个选项并等待选择。
3. **SC04 的 SOP 路由与实际执行不一致。** 路由返回 SC04，但报告中的 SOP 为 P02；模型判断问题更像事实查询和异常分析，自行按 P03/P06 执行。这个判断可能合理，但没有先确认或记录“为什么覆盖路由结果”。
4. **`TableGenerate` 和 `ChartGenerate` 在声明中可见，实际直接调用却返回 `tool_not_available`。** SC03、SC05 都遇到该问题，最终靠 `CanvasGenerate` 内部渲染图表和表格降级完成。SC01、SC02、SC04 没有直接调用这两个工具，全部依赖 Canvas 内部块。
5. **最终闸门通过不等于一次通过。** SC01 和 SC04 都是第一次 `OutputGateCheck` 判 `reject`，修正对账口径后第二次才 `pass`。这是正确的闸门行为，但不能写成“全程无异常”。
6. **存在一次空参数工具调用和多次重复调用。** SC02 的 `CanvasGenerate` 第一次传空对象 `{}`，因缺少 `title`、`blocks` 失败后重试；SC01、SC02、SC04 在长结果被截断后重复调用了 Analyze，SC05 重复调用了 Route。最终结果没有丢，但执行效率和不必要性需要记录。

因此，五份结果应判定为：

| 维度 | 判定 |
| --- | --- |
| Process360 主链是否执行 | 是，五份都执行了 |
| 阻断和证据披露 | 基本符合 |
| 最终交付闸门 | 五份最终 `pass`，其中两份先 `reject` |
| 只读和任务令边界 | 符合，未发现写业务或发待办 |
| 宿主身份授权 | 不符合，不能判定为可信执行 |
| 澄清和路由一致性 | 部分不符合，至少 SC04、SC05 有问题 |
| 表格/图表工具可达性 | 不符合声明，实际依赖 Canvas 降级 |
| 总体判定 | **主流程基本执行，但不能判定为完整符合 SOP；需先修复身份注入和路由澄清** |

## 2. 五组最终样例的执行明细

五组最终会话如下。均是最终版本；早期试验会话不作为本次验收依据。

| 场景 | 会话 / Task | 耗时 | 工具活动数 | 最终路由 | 最终闸门 |
| --- | --- | ---: | ---: | --- | --- |
| SC01 | `s_e30b6d1da560` / `t_2006383cdcb1` | 104 秒 | 21 | SC01，P15 复验语义 | 第一次 reject，第二次 pass |
| SC02 | `s_8fa1c7375a32` / `t_394e709f1abc` | 90 秒 | 23 | SC02，P06 异常识别 | pass |
| SC03 | `s_1b003ba2cd97` / `t_4c3f5fd4f651` | 66 秒 | 18 | SC03，P03 事实查询 | pass |
| SC04 | `s_b1acfcbc453e` / `t_e9c4ce81a173` | 72 秒 | 21 | SC04，路由返回 P02，模型按 P03/P06 执行 | 第一次 reject，第二次 pass |
| SC05 | `s_49e2fa5d3802` / `t_ae602c3050ee` | 94 秒 | 21 | 第一次 SC05/SC01 歧义，第二次固定 SC05 | pass |

### 2.1 SC01：超期未发订单

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> task_write
-> Process360Route -> Process360Context -> Process360Query
-> Process360Structure -> Process360Analyze x3
-> Process360Draft -> Process360Verify -> Process360Compare
-> CanvasGenerate -> OutputGateCheck x2
```

执行结果：

- 路由为 SC01，涉及 P15 复验语义；
- 取数返回 `partial`：2102 行、18.3961 亿元、4.6066 GWh；
- `Process360Structure` 使用 500 行样本得到 12.27 亿元，和全量 18.40 亿元不同，模型在回答中披露了截断；
- `Process360Draft` 生成 SC01-TK01 至 SC01-TK04 四条处置草稿；
- `Process360Verify` 返回 `blocked`、`canClose=false`，缺批准目标和交付证据；
- 第一次闸门因把 500 行样本与全量金额直接加总对账而 `reject`，修正为“样本不与全量做加总对账”后第二次 `pass`；
- 冻结基准只含 5 个订单行，正式复验前需要完整对象集重跑，最终回答已经披露。

判定：

- 主链、草稿、复验阻断和闸门修正符合 SOP；
- 但 principal 是模型猜测的 `demo2/fuxi-readonly`，不符合“宿主注入”要求；
- 只能判定为“业务流程执行成功、授权身份不可信、复验仍未闭环”。

### 2.2 SC02：红区报价集中度与审批

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> task_write
-> Process360Route -> Process360Context
-> Process360Query x2 -> Process360Structure -> Process360Analyze x3
-> Process360Structure x2
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 路由为 SC02、P06；
- `M0137` 红区报价单数处于“停用取数”，`M36002` 依赖它，均正确返回 `blocked`，没有补 0；
- 可核实事实为 2026-01-01 至 2026-10-28 已批准报价 38 单，近三个月 12 单；审批中 13 单、驳回 4 单；
- 审批时长中位 2.1 天、均值 2.4 天、最长约 6 天；
- 红区审批是否走正确授权无法判定，因为缺 OA 审批链路和授权版本 `G07`；
- 第一次 `CanvasGenerate` 以空参数 `{}` 调用，缺少 `title` 和 `blocks`，参数校验失败；随后重试成功；
- 最终 `OutputGateCheck` `pass`。

判定：

- 阻断和缺数披露符合 SOP；
- 模型调用稳定性有一次失败；
- principal 是模型构造的 `default/fuxi-session`，不符合宿主身份要求；
- 没有生成任务令，符合“本轮只读”的用户约束。

### 2.3 SC03：战略客户有效商机覆盖

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> task_write
-> Process360Route -> Process360Context -> Process360Query
-> Process360Structure
-> TableGenerate x2（失败）-> ChartGenerate（失败）
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 路由为 SC03、P03；
- 取数得到 40 户战略客户，12 户没有有效商机，28 户有商机；
- 当前客户主数据覆盖率 70.0%（28/40），但官方 `M36003` 因缺 `G03` 批准计划全集被阻断；
- `M0140`、`M0180` 同样被阻断，没有补 0；
- 建档年份分布 2024 年 5 户、2025 年 6 户、2026 年 1 户；
- 回答把企业名称关键词归类为业务方向，并明确标注为辅助性启发式，不是主数据行业字段；
- `TableGenerate` 两次、`ChartGenerate` 一次均返回 `LookupError: tool_not_available`；
- 随后用 `CanvasGenerate` 内部表格和图表块完成交付，最终 `OutputGateCheck` `pass`；
- `runtime.sqlite3` 没有对应的 `runs` 记录，因为该轮没有调用 `Process360Analyze` 等会落运行记录的工具；trace 中模型使用的是猜测的 `ywln/fuxi_local_user` 一类 principal，无法用服务端记录独立复核。

判定：

- 数据阻断和启发式说明符合 SOP；
- 表格/图表工具声明和实际可达性不一致；
- principal 不可信；
- 由于没有 Analyze 运行记录，不能把这一轮当作完整的服务端可审计执行。

### 2.4 SC04：中标未签项目

实际链路：

```text
mcp_list_connectors -> mcp_load_tools
-> Process360Route -> task_write -> Process360Context
-> Process360Query -> Process360Structure -> Process360Analyze
-> Process360Query -> Process360Analyze x2
-> CanvasGenerate -> OutputGateCheck x2
```

执行结果：

- 路由返回 SC04，但 SOP 为 P02；模型认为问题更接近事实查询和异常分析，主动按 P03/P06 执行；
- 取数得到 39 个中标未签项目，11.45 亿元、2.81 GWh；平均等待 125 天、最长 315 天；
- 区域和负责人排名完成，区域分项与总额一致；
- “卡在什么条款”无法逐项回答：缺合同、条款差异清单、会审记录，`EV09` 标注合同/CLM 接口未提供，`G06` 阻断；
- 能定位活动 `AC0401 发起条款会审与签单申请`，候选原因 `CF09 商务条款会审未完成`，但明确为候选原因；
- 第一次 `OutputGateCheck` 因四舍五入导致对账不平 `reject`，第二次传全精度值后 `pass`；
- 本轮没有调用 `Process360Draft`、`Process360Verify` 或 `TaskOrderCreate`；问题是事实、等待时长和条款证据，未要求处置或复验，这一部分不能单独判为漏做，但路由覆盖需要记录。

判定：

- 取数、阻断和候选原因披露符合要求；
- 路由 SOP 与实际执行不一致，属于需要确认的流程偏差；
- principal 是模型猜测的 `demo2/fuxi-analyst`；
- 闸门首次拒绝后修正，不能称为一次通过。

### 2.5 SC05：计划外发货

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> task_write
-> Process360Route（第一次）
-> Process360Route（第二次，固定 SC05）-> Process360Context
-> Process360Query -> Process360Analyze -> Process360Query
-> Process360Compare -> Process360Verify
-> TableGenerate（失败）-> ChartGenerate（失败）
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 第一次路由返回 SC05 与 SC01 需要澄清；模型根据“偏离日计划”自行固定为 SC05；
- 正式指标 `M0334`、`M0335`、`M36006` 全部 `blocked/null`，原因是计划分类不完整：403 行未知、78 行映射存疑；
- 当期实际发货约 4.8739 GWh；
- 可交付的是 9 条 `outside_candidate` 待核候选，约 2,858.39 万元、0.0755 GWh；明确不是正式计划外汇总；
- `Process360Compare` 表明上一同长度窗口同样 blocked，不能判断改善；
- `Process360Verify` 返回 `canClose=false`，缺批准关闭公式、目标 `RF09` 和冻结基准；
- `TableGenerate`、`ChartGenerate` 同样 `tool_not_available`，由 `CanvasGenerate` 内部渲染；
- 最终 `OutputGateCheck` `pass`；
- 最终回答披露使用了 `ywln/fuxi-local` 的猜测身份。

判定：

- blocked 指标、候选明细、改善不可判定均处理正确；
- 路由歧义没有先澄清，是明确的 SOP 偏差；
- 重复调用 Route、表格/图表工具失败、principal 猜测三项均需记录；
- 不能把本轮称为“完整按 SOP 执行”。

## 3. SOP 对照矩阵

| 要求 | SC01 | SC02 | SC03 | SC04 | SC05 |
| --- | --- | --- | --- | --- | --- |
| 显式选择技能 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 先执行确定性路由 | 符合 | 符合 | 符合 | 部分：路由 P02，实际 P03/P06 | 部分：歧义未澄清 |
| 使用宿主注入 principal | 不符合 | 不符合 | 不符合 | 不符合 | 不符合 |
| 受控取数、不补造数据 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 区分事实/候选原因/确认根因 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 缺证据时阻断 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 需要时执行 Draft/Verify | Draft/Verify 已执行，Verify blocked | 未执行；本轮主要是事实核查 | 未执行 | 未执行；本轮为事实与证据核查 | Verify 已执行并 blocked |
| 调用 CanvasGenerate | 符合 | 符合 | 符合 | 符合 | 符合 |
| 调用 OutputGateCheck | 符合 | 符合 | 符合 | 符合 | 符合 |
| 最终闸门 pass | 第二次 pass | pass | pass | 第二次 pass | pass |
| 不发送任务令/不写业务 | 符合 | 符合 | 符合 | 符合 | 符合 |
| TableGenerate/ChartGenerate 实际可用 | 未直接调用，依赖 Canvas | 未直接调用，依赖 Canvas | 直接调用失败 | 未直接调用，依赖 Canvas | 直接调用失败 |
| 可作为完整 SOP 验收 | 否 | 否 | 否 | 否 | 否 |

## 4. 重点问题

### P0：principal 没有可信宿主注入

Skill 的硬约束是：

> 所有 Process360 业务工具都需要宿主注入 `principal`；缺失身份时，业务取数必须停止。

实际 trace 中五个场景都出现了类似的自我推理：

- SC01：“没有真实 host identity，尝试一个合理的 principal”；
- SC02：“没有 explicit host-provided principal，尝试 generic principal”；
- SC03：“tenantId/userId must be injected by host，I don't have it”，随后尝试 `ywln/fuxi_local_user`；
- SC04：“fabricating principal is bad”，随后使用 `demo2/fuxi-analyst`；
- SC05：“host-injected principal not provided”，随后使用 `ywln/fuxi-local`。

服务端 `runs` 表能核对的最终身份如下：

| 场景 | tenant | principal |
| --- | --- | --- |
| SC01 | `demo2` | `fuxi-readonly` |
| SC02 | `default` | `fuxi-session` |
| SC03 | 无运行记录 | 无服务端记录；trace 中为猜测值 |
| SC04 | `demo2` | `fuxi-analyst` |
| SC05 | `ywln` | `fuxi-local` |

这说明当前不是“宿主注入身份”，而是“模型为了继续执行而构造身份”。即使本轮全是只读查询，也不能认为授权边界满足 SOP。该问题优先于页面内容和业务结论。

### P1：路由澄清被绕过

SC05 第一次路由明确需要澄清，模型为了让任务继续而自行选择 SC05。SOP 要求有多个口径且上下文不能唯一确定时，在回答中提出 2–3 个明确选项并等待用户选择，不能默默挑一个。

SC04 则是另一种情况：路由返回 SC04/P02，模型基于问题语义改用 P03/P06。该判断未必错误，但应留下“为什么要覆盖工具路由”的明确说明，不能把工具路由当成可随手改写的建议。

### P1：工具声明与实际可达性不一致

`tools/list` 能看到 `TableGenerate` 和 `ChartGenerate`，但实际调用 SC03、SC05 时服务端返回：

```text
LookupError: tool_not_available: TableGenerate
LookupError: tool_not_available: ChartGenerate
```

而 `CanvasGenerate` 内部可以正常渲染表格和图表。这说明当前交付实际使用了一条未在工具契约中明确写出的降级路径。需要二选一：

- 修复这两个工具在伏羲环境中的实际调用；或
- 明确 Skill 在该环境统一使用 `CanvasGenerate` 内部块，减少无效失败和上下文消耗。

### P2：首次闸门拒绝和重试必须保留在验收记录中

- SC01：第一次 reject 的原因是 500 行样本合计 12.27 亿元与全量 18.40 亿元不等；第二次改为披露样本截断、取消不成立的全量分解后通过。
- SC04：第一次 reject 的原因是区域分项四舍五入与总额差异；第二次使用全精度值后通过。

闸门最终通过说明系统没有放行错误对账，但不能把过程写成“五份全部一次通过”。

### P2：重复调用和上下文截断

- SC01 调用了三次 `Process360Analyze`，其中第一次被重新路由到 P15 并返回 `not_applicable`，随后调整参数重试；中间还因返回内容截断重试。
- SC02 调用两次 Query、三次 Analyze、三次 Structure，主要是长结果截断和补维度导致。
- SC04 调用两次 Query、三次 Analyze。
- SC05 调用了两次 `Process360Route`。

这些不构成业务错误，但会放大延迟和 token 消耗，也说明当前 MCP 返回体对伏羲上下文过大，模型只能通过“缩小参数再试”恢复。

### P2：SC01 的复验基准不完整

`Process360Verify` 返回 `blocked`、`canClose=false`，冻结基准 objectCount 为 5，而全量对象集为 2102 行。模型在最终回答中已经披露“正式复验前应使用完整对象集重跑并重新冻结”，这是正确行为；但这也意味着 SC01 不能算效果验收完成，只能算部分流程验证。

## 5. 修复建议

### 必须由伏羲宿主或网关完成

1. **服务端注入 principal。** 从会话、连接器或宿主身份中注入可信 `tenantId/userId/canDispatch`；模型输入中出现 principal 时应由服务端覆盖或拒绝，不能让模型自行构造。
2. **身份缺失时硬失败。** 不能接受空值、猜测值或 `source: host` 自证；应明确返回“缺少宿主身份，业务取数停止”。
3. **为五场景增加带身份的运行级回归。** 验收不只看最终 HTML，还要核对 `runs.tenant/principal` 与宿主会话一致。

### 由 Skill 和路由层完成

1. 路由返回 `needs_clarification` 时，必须停在对话层，不允许模型自行选场景；至少要在最终回答中明确写出“本轮按某个假设执行，若不符合请纠正”。
2. `Process360Route` 的 SOP 与执行模式必须保持一致；模型要覆盖路由结果时，记录覆盖理由并重新路由，而不是直接改走 P03/P06。
3. 对同一轮重复的等价 Query/Analyze/Structure 增加去重或结果摘要，避免被截断后反复全量取数。

### 由工具层完成

1. 修复 `TableGenerate`、`ChartGenerate` 在伏羲模式下的实际可调用性；如果当前部署确实不可用，应从 `tools/list` 中移除，或在 Skill 中明确 `CanvasGenerate` 是唯一交付路径。
2. 为 `CanvasGenerate` 增加更明确的参数提示和必填字段错误示例，避免模型传 `{}` 后才被 schema 拒绝。
3. 对长结果提供分页/摘要模式，至少让 `Process360Analyze` 和 `Process360Query` 在伏羲上下文内返回可操作的关键字段，而不是让模型依赖截断后的首尾文本推断。

### 业务验收层

1. SC01 的正式复验必须使用完整对象集和批准目标后重跑，不能把 5 行冻结基准当效果验收。
2. SC02、SC03、SC04、SC05 的 blocked 结论应保持现状，直到 G02、G03、G06、G07、G12 等缺口补齐；不能为了“有建议”而补造数字。
3. 五份样例可以继续作为“流程可运行、阻断可披露”的证据，但总体状态应写成“部分通过，待身份和路由修复后复验”，不能写成“完整闭环完成”。

## 6. 证据索引

### 会话与运行记录

| 场景 | Session | Task | 关键运行记录 |
| --- | --- | --- | --- |
| SC01 | `s_e30b6d1da560` | `t_2006383cdcb1` | `85d09f4c...`、`d22736c...`，均为 `demo2/fuxi-readonly` |
| SC02 | `s_8fa1c7375a32` | `t_394e709f1abc` | `1ee93ae0...`、`f43fa22f...`、`13b190f8...`，均为 `default/fuxi-session` |
| SC03 | `s_1b003ba2cd97` | `t_4c3f5fd4f651` | 无 `runs` 记录；trace 中为猜测 principal |
| SC04 | `s_b1acfcbc453e` | `t_e9c4ce81a173` | `d9f66f86...`、`25d967d2...`，均为 `demo2/fuxi-analyst` |
| SC05 | `s_49e2fa5d3802` | `t_ae602c3050ee` | `0eff55e0...`，`ywln/fuxi-local` |

### 服务端写入情况

```text
runtime.sqlite3.executions = 0
```

SC01 存在服务端草稿：

```text
draft_id = 3bdde22a417e46cfbe9c13207af6e435
run_id   = d22736c615674812b7659708c12b133e
actions  = SC01-TK01 / SC01-TK02 / SC01-TK03 / SC01-TK04
status   = pending
```

没有 `TaskOrderCreate` 执行记录，符合用户“只读分析、不发送任务令或待办”的要求。

### Canvas 产物（只作为执行证据，不核对页面内容）

五个最终 Canvas 文件位于
`/Users/sher/Boulderaitech/eimosp-process360-acceptance-worktree/dataset/canvas/`：

- `canvas-20261028-111821-sc01-发货超期治理-超期未发订单识别-候选原因-处置与复验.html`
- `canvas-20261028-112023-红区报价治理-sc02-集中度与审批核查.html`
- `canvas-20261028-112142-战略客户有效商机覆盖缺口分析-sc03.html`
- `canvas-20261028-112315-中标未签项目清单与等待时长分析-截至-2026-10-28.html`
- `canvas-20261028-112502-计划外发货偏差核查与改善判定-sc05-只读.html`

## 7. 最终判定

五份最终样例证明：

- 伏羲能够加载新 Skill；
- MCP 工具族可以被发现和调用；
- 受控取数、缺数阻断、候选原因、草稿/复验和最终闸门链条能够跑通；
- 当前没有发生业务写入或任务令外发。

但本次执行不能作为“完整符合 SOP”的验收通过。必须先修复宿主 principal 注入，并处理 SC05 的澄清绕过、SC04 的路由覆盖、Table/Chart 工具不可达问题；之后用同一五组问题重新跑一轮，才能把状态改为“完整 SOP 通过”。
