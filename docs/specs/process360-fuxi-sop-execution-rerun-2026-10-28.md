# Process360 伏羲执行过程核对（复跑，2026-10-28）

## 0. 核对边界

本报告核对本地伏羲重新执行五组样例问题时的会话、推理、工具调用、服务端步骤状态、阻断结论、输出闸门和运行记录，不以交付 HTML 的视觉效果或页面文案作为判断依据。

核对范围：

- 工作区：`/Users/sher/Boulderaitech/eimosp-process360-acceptance-worktree`
- 分支：`feature/process360-cockpit34-integration`
- 基线提交：`bbfc2cb`
- 本地 MCP：`http://127.0.0.1:18765/api/mcp`（16:39 以当前 HEAD 重启，替换了 10:59 启动的旧进程）
- 本地 MCP 环境：`PROCESS360_PG_*` 指向 `172.16.5.181:32444/ywln#ywln_crm`；POC 身份为服务端配置 `ywln/zhangzhen`（`grantKind=all`，`source=server-poc-config`）；仅本机联调开启 `canDispatch`
- 伏羲：0.3.79，模型 `DeepSeek V4 Flash`，Skill `~/.fuxi/skills/ontology-analytics/SKILL.md`
- 取证：`~/.fuxi/sessions/<session>/tasks/<task>/thread.jsonl`、`dataset/process360/runtime.sqlite3`、`dataset/canvas/*.html`
- 本轮没有删除会话、没有修改历史记录、没有写业务库

与上一份报告的区别：本轮五个场景全部使用**当前 HEAD 的新会话**重跑，旧会话只作对照，不作为本轮证据。

## 1. 总体结论

**五个场景都在伏羲里完整跑通，身份、表格/图表、全量冻结基准三项上轮问题已关闭；但“完整符合 SOP”仍不能判定通过，主要卡在计划步骤映射、多目标编排和闸门绑定。**

已确认修复或符合的部分：

- 五条用户消息都显式选择 `[[skill:ontology-analytics|硕磐智能分析 Agent]]`，都先调用 `Process360Route`；
- 服务端身份已可信注入：本轮全部 `requests / runs / queries` 的 `tenant/principal` 均为 `ywln/zhangzhen`，五个会话中没有任何模型猜身份的记录；
- 绕过入口已关闭并现场验证：请求体携带 `principal` 被拒绝；无 `planId/stepId` 的业务调用返回 `PLAN_REQUIRED`；旧版不传草稿的 `TaskOrderCreate` 被拒绝；
- `TableGenerate`、`ChartGenerate` 已实际可调用：SC04 成功 1 表 3 图，SC05 成功 1 表 2 图；Canvas 中图表由内联 ECharts 渲染；
- SC01 冻结基准从上一轮的 5 行提升为完整 2102 行（`complete=true`、`fullObjectCount=2102`）；
- 五份都通过 `CanvasGenerate` 生成整页 HTML，最终 `OutputGateCheck` 均为 `pass`；
- 五个只读场景执行期间 `executions=0`，没有自动发任务令或待办。

不能判定为“完整按 SOP 执行”的部分：

1. **计划步骤与工具名不匹配，造成大量无效调用。** 五个问题一共生成 16 个计划、69 条服务端步骤记录，其中 21 次 `needs_clarification`、10 次 `blocked`，多数是计划步骤校验拦截，而不是数据本身阻断。
2. **P02 / P12 在计划里被写成步骤工具名，不是可执行工具。** SC04 首个计划步骤 `tool=P02`，SC05 首个计划 `tool=P12`，任何真实工具调用都会 `PLAN_TOOL_MISMATCH`，模型只能重建计划。
3. **SC02 的 Analyze 始终没执行。** 两次 `Process360Analyze` 都被计划步骤拦下，没有形成 `runs` 记录；审批只能给状态层结论，无法回答“审批是否异常”。
4. **SC05 的路由被用户约束词误导，模型改写问题后重路由。** 原话包含“不发送任务令”，路由器按“任务下发语义”判到 P12；模型随后把约束移到句尾、去掉否定语义再路由到 P06。SOP 要求原话路由，不能为通过路由改写问题。
5. **大结果截断导致 queryId 不可见、重复取数。** SC01、SC02 各取数 3 次；模型明确记录“queryId 为 null”。小结果探针能正常返回 queryId，说明是返回体过大被截断，加上服务端 `payload` 落库时尚未写回 `queryId`，审计记录也不一致。
6. **闸门与运行记录未绑定。** 5 份最终产物只有 SC01 的闸门传了 `runId`；SC02–SC05 的 `artifacts.run_id/tenant/principal/request_id` 为空，`pass` 只校验了对账和文本，没有校验冻结基准。
7. **SC05 的 blocked 查询没有落库。** 服务端对 `blocked` 状态直接 `queryId=null` 返回，不写 `queries` 表，导致 SC05 在数据库里 0 条查询记录，只能靠 `steps.refs` 还原。
8. **SC01 的处置方案未形成服务端可信草稿。** 计划里没有 P11 步骤，`Process360Draft` 被 `PLAN_TOOL_MISMATCH` 拦下；`Process360Solutions` 也两次被拦，最终回答里的处置建议是模型基于上下文写的，未经方案结构校验。

因此本轮判定为：

| 维度 | 判定 |
| --- | --- |
| Process360 主链是否执行 | 是，五份都执行了 |
| 宿主身份与授权 | 符合，服务端固定 `ywln/zhangzhen`，模型注入被拒 |
| 阻断与证据披露 | 符合，blocked 不补 0、候选原因不冒充根因 |
| 表格/图表工具 | 符合，SC04/SC05 直接调用成功 |
| 计划与多目标编排 | 不符合，16 个计划、21 次澄清、10 次阻断 |
| 澄清与路由一致性 | 部分不符合，SC05 改写问题重路由 |
| 最终闸门 | 五份 `pass`，但 4 份未绑定 `runId` |
| 只读与任务令边界 | 五个场景符合；另行单独验证了 1 次真实下发 |
| 总体判定 | **主流程通过，完整 SOP 未通过；下发链路单独通过** |

## 2. 五组执行明细

| 场景 | 会话 / Task | 耗时 | 工具活动 | 计划数 | 首次路由 | 最终闸门 |
| --- | --- | ---: | ---: | ---: | --- | --- |
| SC01 | `s_784f679d3567` / `t_54ef4dbb9033` | 131 秒 | 30 | 2 | SC01，P15 复验语义 | reject → pass → 重复复检 |
| SC02 | `s_5aaaa7134df7` / `t_e9af25f16f50` | 65 秒 | 21 | 2 | SC02，P06 异常识别 | pass（未绑 runId） |
| SC03 | `s_d2d8f5b609c0` / `t_c13c20ba32d6` | 80 秒 | 23 | 3 | SC03，P03 事实查询 | pass（未绑 runId） |
| SC04 | `s_812efb2955b0` / `t_14c96b396221` | 124 秒 | 27 | 3 | SC04，P02 流程语义 | pass（未绑 runId） |
| SC05 | `s_3b874c227eab` / `t_525bccb074d4` | 111 秒 | 27 | 6 | SC05，首次 P12 下发语义 | pass（未绑 runId） |

### 2.1 SC01：超期未发订单

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> task_write
-> Process360Route -> Process360Context -> Process360Query
-> Process360Plan -> Process360Query x2 -> Process360Analyze
-> Process360Explore -> Process360Structure -> Process360Draft
-> Process360Explore -> Process360Verify -> Process360Solutions
-> Process360Analyze -> Process360Solutions x2
-> CanvasGenerate -> OutputGateCheck x3 -> task_check
```

执行结果：

- 首次路由为 SC01 / P15，计划只有一个 `Process360Verify` 步骤；模型重建为 Verify/Query/Analyze/Solutions 四步计划；
- 三次 `Process360Query` 结果一致：2102 行、18.3961 亿元、4.6066 GWh，状态 `partial`，缺口 G01/G12/G16；
- `Process360Analyze` 生成运行 `eb353136`，状态 `partial`，冻结基准 `complete=true`、`fullObjectCount=2102`、`objectSetHash=0793c233…`；
- `Process360Explore` 返回完整对象集 2102（展示 100 行）；`Process360Structure` 被计划步骤拦截一次；
- `Process360Draft` 返回 `needs_clarification`（计划无 P11 步骤），没有生成草稿；`Process360Solutions` 两次被拦，最终建议由模型自行组织；
- `Process360Verify` 返回 `blocked`、`canClose=false`；
- 闸门第一次 `reject`（`aggregate mismatch: parent=18.3961, children=18.3961`），第二次 `pass`，第三次为重复复检；
- 最终回答披露了 partial、候选原因未验证、复验不能关闭。

判定：取数、全量基准、阻断、复验和闸门主体符合；服务端方案/草稿缺失、三次重复取数和闸门重试需记录。

### 2.2 SC02：红区报价集中度与审批

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> Process360Route -> task_write
-> Process360Query x2 -> Process360Context -> Process360Analyze
-> Process360Structure -> Process360Plan -> Process360Query
-> Process360Structure -> Process360Query -> Process360Analyze
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 首次路由 SC02 / P06，计划只有 `Process360Query` 一步；
- 三次取数均 `partial`：`M36001=1`（已批准报价申请），`M0137`、`M36002` 因 G02 缺价格区间映射 `blocked`，不补 0；
- 窗口内 11 单报价申请：已批准 1、进行中 10、驳回 0；只能做状态层判断；
- 两次 `Process360Analyze` 均为 `needs_clarification`（计划步骤不允许 Analyze），没有形成 `runs` 记录；
- 闸门 `pass`，但未传 `runId`，`artifacts` 的 run/tenant/principal 为空；
- 最终回答明确“集中在哪里、占比多少出不了数”“审批是否异常属待核查”。

判定：取数与缺数阻断符合；Analyze 未执行导致审批异常问题只答到状态层，属 SOP 部分执行。

### 2.3 SC03：战略客户有效商机覆盖

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> Process360Route -> task_write
-> Process360Query -> Process360Context -> Process360Query
-> Process360Structure x2 -> Process360Plan -> Process360Query
-> Process360Analyze -> Process360Structure -> Process360Plan
-> Process360Structure -> MetricFactQuery
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 首次路由 SC03 / P03；
- 取数 40 户战略客户：`M0257=12` 户无有效商机；`M36003`、`M0140`、`M0180` 因 G03 缺批准计划全集 `blocked`；
- `Process360Analyze` 生成运行 `76b8e3e8`，状态 `partial`，冻结基准 `complete=true`、`fullObjectCount=40`、`objectSetHash=6dc4472e…`；
- 结构排名一次被计划步骤拦截，重建计划后成功；
- 额外调用一次 `MetricFactQuery` 做跨工具核对，成功；
- 闸门 `pass`，未传 `runId`；最终回答给出 12 户名单、70.0% 当前客户表口径覆盖率，并声明不等于计划完成率。

判定：主链、全量基准与阻断正确；计划重建 3 次，闸门未绑运行记录。

### 2.4 SC04：中标未签项目

实际链路：

```text
mcp_list_connectors -> mcp_load_tools -> Process360Route -> task_write
-> Process360Context -> Process360Query -> Process360Plan
-> Process360Query -> Process360Structure x2 -> Process360Plan
-> Process360Structure x5
-> TableGenerate -> ChartGenerate x3
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 首次路由 SC04 / P02，计划步骤 `tool=P02`，不是可执行工具；第一次 Query 因此 `needs_clarification`；
- 重建 P02+Query 计划后取数成功：39 个项目，`M0179=11.4495209146 亿元`、`M0142=2.80697 GWh`、`M36004=125.179 天`；
- 再重建 Query+Structure 计划，Structure 调用 5 次，1 次被拦、5 次 `partial`；
- 本轮没有 Analyze（问题落在事实与结构，符合停止点）；
- `TableGenerate` 1 次、`ChartGenerate` 3 次均成功，Canvas 中按区域、负责人、等待时长渲染 3 张图；
- 闸门 `pass`，未传 `runId`；
- 最终回答：39 个项目、11.45 亿元、2.81 GWh、平均 125 天、最长 315 天；条款卡点因 G06/EV09 未接入不可回答。

判定：事实、结构、图表与缺证据披露符合；P02 计划步骤映射缺陷造成重试，闸门未绑运行记录。

### 2.5 SC05：计划外发货

实际链路：

```text
mcp_list_connectors -> mcp_load_tools
-> Process360Route（首次 P12）
-> Process360Route（改写问题后 P06）-> task_write
-> Process360Query -> Process360Analyze -> Process360Plan
-> Process360Query -> Process360Analyze
-> Process360Route（P09）-> Process360Analyze
-> Process360Context -> Process360Analyze
-> Process360Route（P05）-> Process360Structure
-> Process360Query -> Process360Verify
-> Process360Route（P15）-> Process360Verify
-> TableGenerate -> ChartGenerate x2
-> CanvasGenerate -> OutputGateCheck
```

执行结果：

- 首次路由因原话含“不发送任务令”被判 P12“任务令下发与通知”，计划步骤 `tool=P12` 不可执行；
- 模型把约束移到句尾、去掉“不发送任务令”后重新路由到 P06；这违反“用用户原话路由”的约束；
- 取数 `blocked`：发货明细 2195 行、展示 100 行，78 行歧义、403 行未分类；`M0334/M0335/M36006` 因 G12/G15 `blocked`，不补 0；
- `Process360Analyze` 生成运行 `588edec2`，状态 `blocked`，冻结基准 `complete=false`，`fullObjectCount=2195` 但 `objectSetHash` 为空集合哈希；
- `Process360Structure` `blocked`；`Process360Verify` `blocked`、`canClose=false`（缺关闭公式与 RF09 目标）；
- `TableGenerate` 1 次、`ChartGenerate` 2 次均成功；
- 闸门 `pass`，未传 `runId`；
- 该场景 3 次 Query 全部 `blocked`，服务端不落 `queries` 表，数据库里本轮 SC05 查询记录为 0。

判定：blocked 指标、候选明细、改善不可判定处理正确；路由歧义处理不合规，计划碎片化最严重（5 次 Route、6 个计划），闸门未绑运行记录。

## 3. SOP 对照矩阵

| 要求 | SC01 | SC02 | SC03 | SC04 | SC05 |
| --- | --- | --- | --- | --- | --- |
| 显式选择技能 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 先执行确定性路由 | 符合 | 符合 | 符合 | 符合 | 部分：P12 误路由后改写问题重路由 |
| 服务端注入身份 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 受控取数、不补造数据 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 区分事实/候选原因/确认根因 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 缺证据时阻断 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 计划与步骤约束 | 部分：方案/草稿被拦 | 不符合：Analyze 未执行 | 部分：3 个计划 | 部分：P02 非工具步骤 | 部分：6 个计划 |
| 按需执行 Draft/Verify | Verify blocked；Draft 未生成 | 未执行 | 未执行 | 未执行 | Verify blocked |
| TableGenerate/ChartGenerate | 未直接调用 | 未直接调用 | 未直接调用 | 符合（1 表 3 图） | 符合（1 表 2 图） |
| CanvasGenerate | 符合 | 符合 | 符合 | 符合 | 符合 |
| OutputGateCheck | 符合 | 符合 | 符合 | 符合 | 符合 |
| 最终闸门 pass | 第二次 pass | pass | pass | pass | pass |
| 闸门绑定 runId | 符合 | 不符合 | 不符合 | 不符合 | 不符合 |
| 五个场景不发送任务令 | 符合 | 符合 | 符合 | 符合 | 符合 |
| 可作为完整 SOP 验收 | 否 | 否 | 否 | 否 | 否 |

## 4. 重点问题

### P1：计划步骤工具名不可执行（P02/P12）

`Process360Plan` 的目标规则把 P02、P12 直接写成步骤的 `tool`。这两个值不是 MCP 工具名，`validate_plan_step` 比对时必然 `PLAN_TOOL_MISMATCH`。

影响：

- SC04 第一次取数被拦，重建计划后才继续；
- SC05 第一个计划完全不可用；
- 模型需要额外 Route/Plan 才能继续，放大延迟和 token 消耗。

### P1：多目标编排碎片化，Analyze 可被漏掉

`Process360Plan` 只按单次路由的主 SOP 生成步骤。遇到“明细 + 原因 + 方案 + 复验”这类多子目标问题，模型只能反复 Route/Plan：

- 五个问题共 16 个计划；
- SC05 5 次 Route、6 个计划；
- SC02 的 Analyze 两次被计划拦下后，模型没有继续重建计划，直接交付，导致审批异常只能答状态层。

建议让 `Process360Plan` 一次覆盖 P03/P05/P06/P09/P10/P11/P15 的依赖 DAG，或在计划里显式允许同一阶段的等价工具。

### P1：SC05 路由匹配否定语义，模型改写问题绕过

原话“只读分析，不发送任务令或待办”被 `任务令` 关键词判为 P12 下发。模型随后把约束移到句尾并去掉否定词，重新路由到 P06。

这是两个问题：

- 路由器没有处理“不发送/不要/禁止 + 任务令”的否定语义；
- 模型为通过路由改写用户原话，违反 SOP 的“原话路由”，应记录为执行偏差。

### P1：大结果截断导致 queryId 丢失和重复取数

SC01、SC02 各执行 3 次同范围查询。模型推理明确写“queryId 为 null”，只能重新查询。

实测小结果（SC03 40 行、sample=5）能返回 `queryId` 和 `recordsRef`，说明问题不是契约缺失，而是返回体过大被截断；同时 `queries.payload` 落库时 `queryId` 仍为 `null`（先保存、后回写），审计记录与调用方看到的结果不一致。

建议：把 `queryId/recordsRef/queryContract` 放到返回体最前；大结果默认摘要 + 分页；落库前先写入 queryId。

### P1：闸门与运行记录脱钩

5 份最终产物中只有 SC01 的闸门传了 `runId`。SC02–SC05 的 `artifacts` 记录：

- `run_id` 为空；
- `tenant/principal/request_id` 为空；
- `dataSnapshot` 为空。

这与“正式分析报告必须绑定运行记录和冻结基准”的交付约束不符。`pass` 只证明对账和文本检查过了，不能证明结论基于哪次冻结数据。

根因：`OutputGateCheck` 不在 `SERVER_PRINCIPAL_TOOLS` 中，调用时没有请求上下文，产物登记拿不到身份和请求号；同时模型没有主动传 `runId`。

### P2：SC05 blocked 查询不落库

`_remember_query` 对 `blocked/not_applicable` 直接返回 `queryId=null`，不写 `queries` 表。SC05 本轮 0 条查询记录，只有 `steps.refs` 里的 2195/100/78/403 计数。

blocked 结果同样需要可追溯，建议保存查询范围、指标状态、缺口和样本摘要（可脱敏），至少保留 hash 和计数。

### P2：闸门拒绝对账信息精度不足

SC01 第一次 `reject` 的信息是：

```text
aggregate mismatch: parent=18.3961, children=18.3961
```

两侧显示值相同，无法判断真实差额。实际是 18.396066389 的精度比较问题。建议输出更多小数位或绝对差额，避免用户误判为闸门 bug。

### P2：会话关联字段不是伏羲会话

本轮 26 条 MCP 请求的 `conversation_id` 全部相同（`d755d952…`），实际是 MCP 传输会话，不是五个伏羲任务。`requestId` 也是 JSON-RPC 消息号（本次下发记录为 `1`）。

建议由伏羲连接器传 `x-fuxi-conversation-id`（任务级），服务端生成 UUID 作为 `requestId`，否则审计无法按用户请求分组。

## 5. 任务令下发验证（服务端默认接收人）

### 5.1 验证方式

五个场景按用户要求只读，没有在会话内发送任务令。下发链路由宿主角色的 MCP 调用单独验证，使用 SC01 本轮真实运行 `c8ea6a41` 生成可信草稿：

| 项目 | 值 |
| --- | --- |
| 计划 | `a149f5a5d1224caa90e1067c1273d737`（单步 P11） |
| 草稿 | `78d223a3e17e4e7ebaa6edff50f050a2` |
| 草稿状态 | `ok`，`approvalStatus=host_click_authorized` |
| 动作 | `SC01-TK01` 发货超期治理：锁定排产与产能任务令 |
| 接收人 | 服务端默认接收人（版本 `poc-default-20261028`） |

调用 `TaskOrderCreate`，参数为 `draft_id / draft_hash / action_id / recipients_raw=[本轮联调号码]`。仓库文档对手机号脱敏，完整号码见本轮任务指令。

### 5.2 实际回执

```json
{
  "schema": "process360.dispatch.v1",
  "status": "ok",
  "accepted": true,
  "message": "任务令已创建",
  "receipt": {
    "ok": true,
    "source": "fuxi",
    "sourceTodoId": "analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01",
    "batchRef": "analytics-analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01-611e72e50b95",
    "applied": 1,
    "skipped": 0,
    "errors": []
  },
  "executionId": "93b20159029046feb63a7ae9ecb71cec"
}
```

- Fuxi 地址 `http://172.16.5.69:8080` 健康检查 `200 {"status":"ok"}`；
- `POST /source/todo-batches` 返回 `applied=1, skipped=0, errors=[]`；
- 本地 `executions` 记录状态 `succeeded`，`recipientsProvidedByHost=1`；
- 存储的 `recipientHash=fdfc9d447391ae76150bd60ab8fb567508b8d162610bc7f76f17cf20741e258f`，与本轮联调完整号码 + `mappingVersion=poc-default-20261028` 的 `recipient_fingerprint` 重算结果一致；
- 幂等重放：再次调用同一草稿/动作，返回同一 `executionId` 和 `sourceTodoId`，`idempotentReplay=true`；
- 页面下发接口 `POST /api/process360/task-orders` 用同一草稿/动作重放，也返回同一执行号，证明页面与 MCP 共用一条执行链路。

### 5.3 怎么在伏羲确认

Fuxi 控制接口没有待办查询端点（GET `/source/todo-batches`、`/source/todos` 返回 401/404），所以最终确认以伏羲待办界面为准：

1. 打开伏羲待办，来源选 `boulderai-anaylize-todo`；
2. 应看到标题 `发货超期治理：锁定排产与产能任务令`；
3. 接收人应为服务端配置的默认接收人；
4. 记录号为 `analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01`；
5. 批次号为 `analytics-analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01-611e72e50b95`。

本地也可直接核对：

```sql
SELECT id, status, source_todo_id, request, response
FROM executions
WHERE id = '93b20159029046feb63a7ae9ecb71cec';

SELECT source_todo_id, status, payload
FROM receipts
WHERE source_todo_id = 'analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01';
```

如果伏羲界面看不到该待办，说明接收人侧账号/租户映射仍需联调，不能仅凭 `applied=1` 判定业务侧已看到。

### 5.4 本次验证的配置边界

- 本地 MCP 的 POC 身份 `canDispatch=true` 和接收人映射只用于本机验证，**没有部署到 34/线上**；
- 生产页面不应由模型传手机号，接收人必须由宿主或服务端 `PROCESS360_RECIPIENT_MAP` 解析；
- 本轮只创建 1 条真实待办，后续重放均为幂等，没有产生重复待办。

## 6. 修复建议

### 必须优先修复

1. **修正 P02/P12 计划步骤工具名。** 在 `TOOL_FOR_SOP` 中映射到真实工具，或把 P02/P12 拆成可执行子步骤；否则每个落到这两个 SOP 的问题都会先失败一轮。
2. **让 Process360Plan 一次生成多目标 DAG。** 至少覆盖 P03/P05/P06/P09/P10/P11/P15 的依赖，避免 SC05 这种 5 次 Route、6 个计划的碎片化执行。
3. **路由处理否定语义。** “不发送任务令 / 不要待办 / 只读分析”不得判为 P12；同时禁止模型改写原话重路由，重路由必须带修订理由和原问题引用。
4. **把 queryId 前置并摘要化大结果。** 返回体首屏给 `queryId/recordsRef/queryContract`；大结果分页；落库前写回 queryId。
5. **闸门强制绑定运行记录。** `OutputGateCheck` 纳入 `SERVER_PRINCIPAL_TOOLS`，分析报告缺少 `runId` 直接 reject；产物登记写入 tenant/principal/request_id。
6. **blocked 查询也落库。** 保存范围、缺口、计数和样本摘要，保证 SC05 这类场景可追溯。

### 建议修复

7. 闸门对账错误输出精确值和差额，不只输出四舍五入后的展示值；
8. Fuxi 连接器传任务级 `conversationId`，MCP 侧生成 UUID `requestId`；
9. `Process360Draft` 在“怎么处置”类问题上应有可选 P11 步骤，避免方案只停留在模型文本；
10. SC02 这类“状态是否异常”的问题，计划里应显式包含 Analyze，而不是只生成 Query 步骤。

### 业务验收层

- SC01 复验仍 `blocked`，需要批准目标、关闭公式和完整对象集后才能判效果闭环；
- SC02 红区口径 G02、SC03 计划全集 G03、SC04 条款证据 G06、SC05 行映射 G12/G15 均未关闭，相关结论继续保持 blocked/partial；
- 本轮可以判定“流程可执行、阻断可披露、下发链路可用”，不能判定“五场景业务闭环完成”。

## 7. 证据索引

### 会话与运行记录

| 场景 | Session | Task | runs | 身份 |
| --- | --- | --- | --- | --- |
| SC01 | `s_784f679d3567` | `t_54ef4dbb9033` | `eb353136…`、`c8ea6a41…` | `ywln/zhangzhen` |
| SC02 | `s_5aaaa7134df7` | `t_e9af25f16f50` | 无（Analyze 被计划拦截） | `ywln/zhangzhen` |
| SC03 | `s_d2d8f5b609c0` | `t_c13c20ba32d6` | `76b8e3e8…` | `ywln/zhangzhen` |
| SC04 | `s_812efb2955b0` | `t_14c96b396221` | 无（事实型，未 Analyze） | `ywln/zhangzhen` |
| SC05 | `s_3b874c227eab` | `t_525bccb074d4` | `588edec2…`（blocked） | `ywln/zhangzhen` |

### 服务端写入情况

```text
五个只读场景执行期间：executions = 0
下发验证后：executions = 1（id=93b20159029046feb63a7ae9ecb71cec）
drafts：78d223a3e17e4e7ebaa6edff50f050a2（SC01，4 个动作）
artifacts：6 条（SC01 reject+pass，SC02–SC05 各 1 条 pass）
```

SC01 冻结基准：

```text
run=eb35313656f74eef8f2ce7f9e2b82377
complete=true, fullObjectCount=2102
objectSetHash=0793c233efb6ede81ea2b9aa80bf507e05cf97b3b2d099d65a78fe61611cde2a
```

SC05 冻结基准：

```text
run=588edec2cc4d4402805571b119e6cb90
complete=false, fullObjectCount=2195
objectSetHash=4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945（空对象集）
```

### 闸门记录

| 场景 | artifact | verdict | 绑定 runId |
| --- | --- | --- | --- |
| SC01 | `81fe7db5…` | reject（精度对账）、pass | 是 |
| SC02 | `7c111ba2…` | pass | 否 |
| SC03 | `3b666a06…` | pass | 否 |
| SC04 | `75837ccf…` | pass | 否 |
| SC05 | `5250aec9…` | pass | 否 |

### Canvas 产物

位于 `/Users/sher/Boulderaitech/eimosp-process360-acceptance-worktree/dataset/canvas/`：

- `canvas-20261028-164421-超期未发订单-现状-原因线索-处置与复验可行性.html`
- `canvas-20261028-164551-红区报价治理分析-sc02-只读.html`
- `canvas-20261028-164720-战略客户有效商机覆盖缺口分析-sc03-只读.html`
- `canvas-20261028-164929-中标未签项目清单与等待时长分析.html`
- `canvas-20261028-165120-计划外发货偏差-哪些偏离-如何核查-是否改善.html`

### 下发验证

```text
draft=78d223a3e17e4e7ebaa6edff50f050a2
action=SC01-TK01
execution=93b20159029046feb63a7ae9ecb71cec
sourceTodoId=analytics-78d223a3e17e4e7ebaa6edff50f050a2-SC01-TK01
recipientHash=fdfc9d447391ae76150bd60ab8fb567508b8d162610bc7f76f17cf20741e258f
applied=1, skipped=0, errors=[]
```

## 8. 最终判定

本轮证明：

- 伏羲能加载 Skill，五个场景都能完成 Route → 取数 → 分析/结构 → 方案/复验 → Canvas → 闸门；
- 身份由服务端注入，模型猜身份、注入身份、无计划取数、旧版无草稿下发四个绕过入口都已关闭；
- 表格/图表工具已可用，全量冻结基准在 SC01/SC03 已达到完整对象集；
- 任务令下发链路真实可用：1 条待办已推到服务端默认接收人，幂等重放不重复，页面与 MCP 共用同一执行号。

但本轮不能判定“完整符合 SOP”：

- 计划步骤工具名、多目标编排和否定语义路由造成大量无效调用，SC02 因此漏掉 Analyze；
- 4/5 最终闸门未绑定运行记录，不能证明结论基于哪次冻结数据；
- SC05 blocked 查询不落库，审计链不完整。

建议状态：**主流程通过，完整 SOP 待计划编排与闸门绑定修复后复验；下发链路本轮通过。**
