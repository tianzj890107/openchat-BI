# 冻结用例（frozen cases）

这里的用例是从源仓库评测集**冻结**出来的只读快照，用来证明本包脚本的判定
与源仓库一致；它们不依赖源仓库、不需要网络，可离线回放。

## 来源与冻结基线

- 路由用例来自 `dataset/evals/analytics/cases/**` 中所有带 policy 断言的用例
  （`evaluator == "policy"`，或 `expected.policy` 非空）。
- 冻结基线：源仓库 `master` 分支提交 `c94d430`（本包同批次导出）。
- 覆盖：`intent` 49、`adversarial` 35、`diagnosis` 23、`multi_turn` 20、
  `recommendation` 10，共 **137** 条。
- 闸门用例（`gate_cases.jsonl`）是本包按 `references/07-output-gates.md`
  手工整理的行为断言，共 **23** 条，覆盖只读 SQL / 预测披露 / 图表抑制 /
  证据一致性 / 数值对账五类闸门。

## 两类用例

`routing_cases.jsonl` 每行：

```json
{
  "case_id": "ANA-INTENT-001",
  "category": "intent",
  "question": "…用于路由的最终问句…",
  "allowed_tools": ["Ontology-MetricQuery", "AskUser"],
  "expect": {"mode": "CLARIFICATION", "reason_code": "AMBIGUOUS_REQUEST",
             "next_step": "ASK_USER", "required_tools": ["AskUser"],
             "evidence_required": false, "needs_human": true, "intent_level": "L1"}
}
```

- `allowed_tools` **显式存在**时才覆盖默认 14 个工具；空列表 `[]` 表示
  “无可用工具”，用于复现 `CAPABILITY_LIMITATION`，不要回落到默认工具集。
- `multi_turn` 用例的 `question` 已经替换为该 case `fixture.effective_question`
  的解析结果（即多轮上下文补全后的单轮问句），原始追问保留在
  `follow_up_question` 字段；未解析的 `"上个月呢"` 单独送入路由是无效输入。

`gate_cases.jsonl` 每行：

```json
{"case_id": "gate-sql-004", "kind": "sql",
 "input": {"sql": "PRAGMA journal_mode=WAL"},
 "expect": {"ok": false, "error_contains": "PRAGMA assignment is not permitted"}}
```

- `kind == "sql"`：直接调 `gates.validate_sql`。
- 其他 `kind`（当前只有 `"check"`）：把 `input` 作为 turn payload 调
  `gates.check`，断言 `verdict` / `hard_contains` / `warnings_contains`。

## 回放

```bash
python3 scripts/selfcheck.py           # 逐条输出
python3 scripts/selfcheck.py --quiet   # 只输出汇总与失败项
```

全部通过时退出码为 0，任何一条不符合即退出码 1，并打印 `FAIL` 明细。

## 注意

- 这些用例是**快照**：修改 `scripts/vendor/` 下任何规则后必须重跑 selfcheck，
  行为变化要先确认是有意升级，再按“重新冻结”流程更新用例，不得直接改期望值
  去迁就实现。
- 用例只包含问句、工具白名单与期望字段，不含任何用户数据、凭据或业务明细。
- `adversarial` 组里出现 `.env`、`token`、`password` 等字样是**攻击性测试输入**
  （用于验证拒答闸门），不是真实凭据，也不应被当作需要保密的字符串处理。
