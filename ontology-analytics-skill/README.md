# ontology-analytics · 分析逻辑剥离包

把「硕磐智能分析 Agent」的分析逻辑从原系统里剥离出来，做成一个自包含、
可移植的交付包：**任何通用 agent（Codex、Claude Code 等）读完 `SKILL.md` 和
`references/`，配合 `scripts/` 里的确定性模块，就能复现同样的路由判定、
分析 SOP 和交付闸门**，而不需要原仓库、原 Web 服务或任何第三方依赖。

本包与原系统解耦：不修改、不依赖原系统运行时，也不包含任何凭据或用户数据。

## 目录

```
ontology-analytics-skill/
├─ SKILL.md                 入口说明：何时使用、工作流、按任务读哪份规范
├─ README.md                本文件（交付说明）
├─ references/              「制度」：给人和通用 agent 读的分析规范
│  ├─ 01-sop.md             六步 SOP：意图识别→消歧→取数→分析→表达
│  ├─ 02-level-templates.md L1–L5 五档分析深度模板
│  ├─ 03-discipline.md      分析纪律与语言要求
│  ├─ 04-deep-insight.md    深入洞察（多维下钻）流程
│  ├─ 05-naming-rules.md    业务名称优先展示规则
│  ├─ 06-routing-rules.md   确定性路由规则（字段、枚举、优先级）
│  ├─ 07-output-gates.md    五道交付闸门与兜底话术
│  ├─ 08-tools-and-sources.md 17 个工具契约、白名单、数据源
│  ├─ 09-graph-mode.md      图库检索模式的 SOP 调整
│  └─ 10-roles.md           用户画像与回答风格（可选）
├─ scripts/                 「执法」：可执行的确定性规则
│  ├─ route.py              路由决策 CLI（意图/模式/下一步/所需工具）
│  ├─ gates.py              交付闸门 CLI（证据/预测/图表/SQL/对账）
│  ├─ selfcheck.py          冻结用例离线自检
│  └─ vendor/               规则真源（自原系统原样复制，仅标准库）
└─ cases/                   冻结用例（137 路由 + 23 闸门）与来源说明
```

## 运行要求

- 只需 Python 3（标准库），无第三方依赖，无需安装。
- 无需网络；`vendor/` 中的模块都是纯确定性规则，不调用模型。

```bash
cd ontology-analytics-skill

# 1. 每轮开始前：路由决策
python3 scripts/route.py --question "2025年采购金额合计是多少" --pretty
python3 scripts/route.py --batch cases/routing_cases.jsonl      # 批量

# 2. 交付前：跑全部闸门
python3 scripts/gates.py sql --sql "SELECT SUM(amount) FROM fact_purchase_order WHERE is_deleted = 0"
python3 scripts/gates.py check --input turn.json                # 或从 stdin

# 3. 自检：回放冻结用例，确认规则未被破坏
python3 scripts/selfcheck.py --quiet     # 期望 160/160 passed
```

## 谁是真源

- `references/*.md` 是把分析逻辑讲清楚的**规范与理由**，供人和通用 agent 阅读。
- `scripts/vendor/*.py` 是**可执行的规则真源**：路由、证据、预测披露、图表抑制、
  只读 SQL、名称解析。文档与实现冲突时以实现为准，并以 `cases/` 回放验证。
- `cases/` 是从原系统评测集冻结的行为快照（来源见 `cases/README.md`）。

## 不包含在本包内

- 具体工具实现（本体查询、Doris/指标网关、x360、图表渲染等）：受让方需自备
  等价实现，或改为调用服务端接口；本包只定义契约与调用规则。
- Web 会话 / SSE 流式输出 / 前端工作台：与宿主运行时绑定。
- 任何凭据、`.env`、用户数据、会话记录、业务明细数据。
- 原仓库的完整提交历史、分支与运行时配置；仅 `scripts/vendor/` 顶部保留一行来源与
  基线提交注释，用于说明规则出处、方便后续同步。

## 接收方如何开始

1. 读 `SKILL.md`，按其工作流接入自己的 agent。
2. 需要确定性判定时调用 `scripts/`；需要解释与话术时读 `references/`。
3. 接入后先跑一遍 `python3 scripts/selfcheck.py --quiet`，确认行为与快照一致。
