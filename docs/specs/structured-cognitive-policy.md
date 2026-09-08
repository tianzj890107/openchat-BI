# 分析 Agent 轻量结构化 Cognitive Policy Spec

## 1. 目标

分析 Agent 在每个新用户轮次开始时，基于用户问题、现有确定性意图分类和该会话实际可用的工具，生成一个可测试、可观测的内部决策快照。快照用于说明“这一轮为什么走这条路线”，并为路由统计、故障定位和 Recovery 后续衔接提供稳定字段。

本改造只增加轻量决策记录，不取代六步 SOP、LLM 推理、本体检索、Tool Runtime、Recovery 或 Evidence Gate，也不承诺提升模型本身的推理能力。

## 2. 范围

### 2.1 本期包含

- 在 `bi_agent.tools.analysis_policy` 中提供纯函数 `build_cognitive_policy_decision(question, allowed_tools)`；
- 每个新用户轮次只生成一次决策；
- WebSession 保存最近一次决策的防御性快照；
- 在首次 `llm_request` 之前发出 `cognitive_policy` SSE 事件；
- Web 层为该事件附加当前 `turn_id`；
- 决策只能推荐当前会话允许的工具；
- 决策只保存输入摘要，不保存原始问题、SQL、工具结果或密钥。

### 2.2 本期不包含

- 不新增 LLM 分类调用；
- 不把 `required_tools` 变成工具硬白名单；
- 不阻断模型根据后续证据调整路线；
- 不实现策略配置后台、数据库持久化、跨会话统计平台或前端展示；
- 不重做现有 `classify_intent`、六步 SOP、Tool Runtime 或 Recovery 状态机。

## 3. 决策契约

`build_cognitive_policy_decision` 返回 JSON 可序列化字典，至少包含以下字段：

```json
{
  "policy_version": 1,
  "mode": "FACT_QUERY",
  "reason_code": "FACT_REQUEST_RESOLVED",
  "next_step": "QUERY_DORIS",
  "required_tools": ["Ontology-FactQuery"],
  "evidence_required": true,
  "needs_human": false,
  "input_digest": "sha256:..."
}
```

字段约束：

- `policy_version`：当前固定为整数 `1`；
- `mode`：稳定枚举，见第 4 节；
- `reason_code`：稳定、机器可统计的英文大写枚举，不放自由文本原因；
- `next_step`：稳定枚举，见第 4 节；
- `required_tools`：有序、去重，且必须是 `allowed_tools` 的子集；它表示预期首选路线，不是执行白名单；
- `evidence_required`：最终回答是否必须经过已有证据链；
- `needs_human`：当前是否必须通过 `AskUser` 获取用户选择；
- `input_digest`：规范化问题的 SHA-256 摘要，格式 `sha256:<64 个小写十六进制字符>`。

同一规范化问题和同一工具集合必须得到相同的所有决策字段；工具输入顺序不得改变语义结果。

## 4. 最小路由表

| 场景 | mode | reason_code | next_step | required_tools | evidence_required | needs_human |
|---|---|---|---|---|---:|---:|
| 已明确的事实、指标、列表或趋势查询，且有数据查询能力 | `FACT_QUERY` | `FACT_REQUEST_RESOLVED` | `QUERY_DORIS` | 优先 `Ontology-MetricQuery`，否则 `Ontology-FactQuery` | true | false |
| 明确要求异常、原因、根因、行动分析，且有数据查询能力 | `DIAGNOSTIC_ANALYSIS` | `DIAGNOSTIC_REQUEST` | `QUERY_DORIS` | 优先 `Ontology-MetricQuery`，否则 `Ontology-FactQuery` | true | false |
| 查询术语定义、本体对象或关系，且有本体查询能力 | `ONTOLOGY_LOOKUP` | `ONTOLOGY_LOOKUP_REQUEST` | `QUERY_ONTOLOGY` | 优先 `Ontology-SemanticQuery` | true | false |
| 问题为空或只有“看看/分析一下”等无法确定对象与目标的信息，且 `AskUser` 可用 | `CLARIFICATION` | `AMBIGUOUS_REQUEST` | `ASK_USER` | `AskUser` | false | true |
| 需要数据或本体能力，但会话没有对应工具 | `CAPABILITY_LIMITATION` | `QUERY_CAPABILITY_UNAVAILABLE` | `DELIVER_LIMITATION` | 空数组 | false | false |

补充规则：

- 诊断意图优先于普通事实查询；
- 明确的“定义/是什么/关系”本体问题优先走本体查询，但“采购金额是多少”仍属于事实查询；
- `Ontology-MetricQuery` 和 `Ontology-FactQuery` 同时可用时只推荐前者，避免一次决策声明两个替代工具都必须调用；
- 若首选工具不可用，可选择表中允许的降级工具；任何情况下都不能推荐未授权工具；
- 一般闲聊可扩展为 `GENERAL_RESPONSE / GENERAL_REQUEST / DELIVER`，但不能误报为需要 Doris 取数。

## 5. WebSession 与事件

- WebSession 初始化时没有伪造的业务决策；首次新用户轮次生成决策后，`cognitive_policy_decision` 属性返回最近一次决策的深拷贝；调用方修改快照不能污染内部状态。
- `generate_turn()` 的事件顺序必须是：`user_message` 之后产生 `cognitive_policy`，且 `cognitive_policy` 必须早于该轮首次 `llm_request`。
- `cognitive_policy` 事件应直接携带第 3 节字段，事件类型为 `type=cognitive_policy`；不得携带原始问题。
- `continue_with_choice()` 和 `retry_from_checkpoint()` 属于同一 Recovery turn，不重新分类、不覆盖原决策。
- Cognitive Policy 只记录计划；实际工具结果、超时、重试和 checkpoint 仍由 Tool Runtime 与 Recovery 管理。
- `bi_agent.web.app._TURN_EVENT_TYPES` 必须包含 `cognitive_policy`，确保 SSE 层附加 `turn_id`。

## 6. 安全与兼容性

- 决策快照及事件不得包含 `question`、`user_text`、`sql`、消息正文、工具结果或凭据字段；
- 摘要必须基于空白规范化后的问题，不能使用 Python 进程随机 hash；
- 未传 `allowed_tools`、传空列表或重复工具时均须安全处理；
- 未识别的新问题不得抛异常；
- 旧客户端会忽略新 SSE 类型，现有事件字段和顺序约束（除新增事件外）保持兼容。

## 7. 验收标准

1. `tests.test_cognitive_policy` 全部通过；
2. 原有 Recovery、Tool Runtime、并发、可靠性和回归测试继续通过；
3. 实现无网络、Doris、真实本体服务或真实用户历史依赖；
4. 无生产代码通过关键词伪造事实、SQL、证据或工具结果；
5. `git diff --check` 通过。
