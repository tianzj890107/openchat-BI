<!-- 来源：bi_agent/tools/analysis_policy.py（基线提交 c94d430）与 docs/specs/structured-cognitive-policy.md、analysis-action-intent-routing.md、analysis-forecast-and-scenario-routing.md、analysis-security-refusal.md。本文件是规则的说明与索引，规则正文以 scripts/vendor/analysis_policy.py 为准。 -->

# 确定性路由规则（每轮开始前先跑）

每个新用户轮次都必须先做一次确定性路由，产出"这一轮为什么走这条路"的决策快照，再进入 `01-sop.md` 的六步流程：

```bash
python scripts/route.py --question "<用户原话>" --allowed-tools "Ontology-MetricQuery,Ontology-FactQuery,Ontology-SemanticQuery,AskUser"
```

`route.py` 输出决策 JSON，字段与后端一致；不得用模型自由判断替代它。

## 决策字段

| 字段 | 含义 |
| --- | --- |
| `policy_version` | 固定 `1` |
| `mode` | 路线枚举，见下表 |
| `reason_code` | 机器可统计的原因码，不放自由文本 |
| `next_step` | 下一步动作枚举 |
| `required_tools` | 预期首选工具；**是 `allowed_tools` 的子集，不是执行白名单** |
| `evidence_required` | 最终回答是否必须有工具证据 |
| `needs_human` | 是否必须先 `AskUser` 澄清 |
| `wants_forecast` / `forecast_kind` / `forecast_assumption` | 预测/情景标记；`forecast_kind ∈ predictive / scenario / stored` |
| `refusal_category` / `refusal_message` | 命中安全拒答时的分类与固定话术 |
| `input_digest` | 规范化问题的 sha256，不保存原话 |

## mode / reason_code / next_step 对应表

| mode | reason_code | next_step | 触发条件 |
| --- | --- | --- | --- |
| `GENERAL_RESPONSE` + 拒答字段 | `GENERAL_REQUEST` | `DELIVER` | 命中安全拒答，**优先级最高**；工具白名单清空 |
| `CAPABILITY_LIMITATION` | `QUERY_CAPABILITY_UNAVAILABLE` | `DELIVER_LIMITATION` | 会话没有可用的取数工具，只能声明能力边界 |
| `CLARIFICATION` | `AMBIGUOUS_REQUEST` | `ASK_USER` | 问句无法确定分析对象/口径，必须先 `AskUser` |
| `DIAGNOSTIC_ANALYSIS` | `DIAGNOSTIC_REQUEST` | `QUERY_DORIS` | 找问题/异常/波动/根因类 |
| `ONTOLOGY_LOOKUP` | `ONTOLOGY_LOOKUP_REQUEST` | `QUERY_ONTOLOGY` | 查本体元数据（定义、字段、关系、指标口径） |
| `FACT_QUERY` | `FACT_REQUEST_RESOLVED` | `QUERY_DORIS` | 可直接取数的事实查询 |
| `GENERAL_RESPONSE` | `GENERAL_REQUEST` | `DELIVER` | 闲聊/与数据无关 |

`next_step` 取值只有五种：`QUERY_DORIS`、`QUERY_ONTOLOGY`、`ASK_USER`、`DELIVER_LIMITATION`、`DELIVER`。

## 判定优先级（自上而下，先命中先返回）

1. 安全拒答：凭据外泄 `REFUSAL_CREDENTIAL_EXFILTRATION`、内部环境探测 `REFUSAL_ENVIRONMENT_DISCOVERY`、破坏性数据操作 `REFUSAL_DESTRUCTIVE_DATA_OPERATION`。业务词不能把拒答拉回查询路线。
2. 能力缺失：没有取数工具 → 声明限制，不编数字。
3. 澄清：对象/口径不唯一 → `AskUser`。
4. 诊断。
5. 本体元数据。
6. 事实查询。
7. 通用回应。

## 取数工具选择

`required_tools` 的选法：有 `Ontology-MetricQuery` 就用它，否则用 `Ontology-FactQuery`；**两者不得同时出现**。实际执行仍可选择任一被授权的工具。

## 预测与情景（必须有披露）

- 本包不具备统计预测能力；检测到预测意图 ≠ 能给出预测数字。
- `forecast_kind = stored`：把计划/预算记录说成"模型预测"会被判违规。
- `forecast_kind = scenario`：必须复述用户给的假设。
- 一律必须披露数据窗口/方法/不确定性之一，且不得出现置信区间、显著性、回测、准确率等本系统无法产出的统计词汇。判定见 `07-output-gates.md`。

## 安全拒答话术（原样使用，不得改写或补充）

- 凭据外泄：出于安全考虑，我不能提供任何凭据、密钥、口令或连接串，包括它们的长度、片段、掩码内容和存放位置。请通过密钥管理服务或环境变量注入的方式配置凭据；如需协助，请联系系统管理员。
- 内部环境探测：出于安全考虑，我不能透露服务内部的工作目录、部署路径、环境变量或密钥文件位置。如需排查部署问题，请联系系统管理员在受控终端上查看。
- 破坏性操作：出于安全考虑，我不能执行删除、清空、覆盖、DROP 或 TRUNCATE 等破坏性操作，也不会改动任何数据、会话、上传文件、图表或报告。如果目标是一次只读分析，请直接说明要查看的指标与范围。

## 反模式

- ❌ 凭语义感觉选路线，不跑 `route.py`。
- ❌ 把 `required_tools` 当成"只能调用这些工具"。
- ❌ 拒答前还先去查数据确认。
- ❌ 预测问题给出确定数字而不披露窗口/方法/不确定性。
