---
name: ontology-analytics
name_zh: 硕磐智能分析 Agent
description_zh: 复现硕磐智能分析 Agent 的路由、L1–L5 分档分析与五道交付闸门，用于企业财务与经营数据问答的可追溯结论。
description: 复现「硕磐智能分析 Agent」的分析逻辑：每轮先做确定性路由（意图/模式/下一步/所需工具），再按 L1–L5 分档 SOP 取数与分析，交付前跑证据、预测披露、图表、只读 SQL、数值对账五道闸门。适用于企业财务/经营数据问答（管报损益、应收应付、存货库龄、预算执行等），需要基于读表/本体/指标工具给出可追溯结论的场景。当任务是「让通用 agent 也能照这套规范分析数据」或需要该系统的路由与闸门判定时使用。
dependencies:
  capabilities:
    - runtime:python
---

# ontology-analytics

本技能把一套企业数据分析 Agent 的分析逻辑封装成**可移植规则**：任何通用
agent（Codex、Claude Code 等）只要按下面的顺序执行，就能得到与原系统一致的
路由判定、分析深度和交付质量。这里没有模型、没有网络依赖，只有规范和确定性脚本。

## 何时使用

- 用户对企业经营/财务数据提问（取数、找问题、根因、决策建议、执行监督）。
- 需要判断“这轮该澄清、该取数、还是该拒答”，或需要一组固定的交付闸门。
- 需要把这套分析逻辑移植到别的宿主环境。

## 核心工作流（每轮按顺序执行）

1. **路由（必做，先跑）**：调用 `python3 scripts/route.py --question "<用户原话>"`
   拿到 `mode` / `reason_code` / `next_step` / `required_tools` /
   `evidence_required` / `needs_human` / `refusal_category` / `intent` 等字段。
   **按 `next_step` 行动，不要自由发挥**：`ASK_USER` 就澄清，`DELIVER_LIMITATION`
   就用拒答话术，`QUERY_DORIS` / `QUERY_ONTOLOGY` 才进入取数。
2. **分析（按深度分档）**：依据 `intent.level`（L1–L5）取对应的分析模板与纪律，
   先消歧、先确认口径，再取数；历史结论不复用、口径与结果要分开。
3. **交付前闸门（必做）**：把最终回答与结构化证据交给
   `python3 scripts/gates.py check`（或按需调用 `gates.py sql`）。任何 hard issue
   都要按 `fallback` 兜底话术改写，不得原样输出被拦的回答。

## 按任务读取对应规范

| 要做什么 | 读哪个文件 |
| --- | --- |
| 六步 SOP、意图识别、术语消歧、历史复用判断 | `references/01-sop.md` |
| L1–L5 各档该产出什么 | `references/02-level-templates.md` |
| 分析纪律、语言与禁止事项 | `references/03-discipline.md` |
| 多维下钻（深入洞察）流程 | `references/04-deep-insight.md` |
| 业务名称优先展示、图表/表格/SQL 命名 | `references/05-naming-rules.md` |
| 路由字段含义、枚举、判定优先级、拒答话术原文 | `references/06-routing-rules.md` |
| 五道闸门判据与兜底话术 | `references/07-output-gates.md` |
| 17 个工具的契约、白名单、数据源 | `references/08-tools-and-sources.md` |
| 图库检索模式下的 SOP 调整 | `references/09-graph-mode.md` |
| 用户画像与回答风格（可选） | `references/10-roles.md` |

## 接真实数据（可选）

需要真实数字时，用 `tools/` 里的真实工具执行 `required_tools`（凭据由使用者放在仓库外）：

```bash
python3 tools/serve.py --list-tools
python3 tools/serve.py --call <工具名> --params '{...}'
printf '%s\n' '{"tool":"...","params":{...}}' | python3 tools/serve.py --serve
python3 tools/selftest.py
```

- 工具返回「文本摘要 + `[RESULT_METADATA]` 结构化块」，后者是证据闸门的输入，必须保留。
- 没有真实工具时**不要编数字**：按 `next_step=DELIVER_LIMITATION` 输出限制说明——
  这正是技能内置的兜底行为。

## 目录与命令

```bash
python3 scripts/route.py --question "2025年采购金额合计是多少" --pretty
python3 scripts/route.py --batch cases/routing_cases.jsonl
python3 scripts/gates.py sql --sql "SELECT 1"
python3 scripts/gates.py check --input turn.json
python3 scripts/selfcheck.py --quiet     # 期望 160/160 passed
```

- `scripts/vendor/` 是可执行规则的**真源**（仅标准库）；`references/` 是解释与话术。
  两者冲突时以 `vendor/` 实现为准，并用 `cases/` 回放验证。
- 修改任何 vendor 规则后必须重跑 `scripts/selfcheck.py`，通过后再交付。

## 边界

- `tools/` 提供真实工具实现（本体查询、Doris/指标网关、x360、图表/表格渲染），
  但**凭据不随包交付**，需使用者自建 `credentials.env`；没有凭据或工具不可用时按
  「能力限制」处理，不得编造数字。
- 不处理会话/流式输出/前端；不含凭据、用户数据与业务明细。
- 预测与情景没有统计模型支持，只能按 `references/07-output-gates.md` 披露窗口、
  方法、假设与不确定性，绝不编造置信区间或确定数字。
