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
├─ tools/                   真实工具运行时（接真实数据用）
│  ├─ serve.py              CLI / JSONL 入口，暴露 17 个真实工具
│  ├─ selftest.py           离线自检（临时 SQLite，无需凭据）
│  ├─ config.example.env    配置模板（只有变量名，没有值）
│  └─ _vendor/              真实工具实现原样副本（见 _vendor/README.md）
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

## 接真实数据（可选，内网用）

只做「判定/规范」时不需要真实数据；要出真实数字就接工具层：

```bash
mkdir -p ~/.config/ontology-analytics
cp tools/config.example.env ~/.config/ontology-analytics/credentials.env   # 填真实值，600 权限
python3 tools/serve.py --list-tools          # 17 个工具，无需凭据
python3 tools/serve.py --call ListBusinessObjects --params '{}'
python3 tools/serve.py --call Ontology-FactQuery --params '{"sql":"SELECT 1"}'
python3 tools/selftest.py                    # 离线自检，不需要凭据
```

- 凭据只放 `tools/credentials.env`（已被忽略）或 `~/.config/ontology-analytics/credentials.env`，
  **不进仓库、不进压缩包**；`credentials.env` 一旦缺失，工具会明确报错而不是静默降级。
- 远程本体 + Doris HTTP 网关形态**零第三方依赖**；本地 Excel 模式需 `openpyxl`，
  Doris MySQL 协议需 `pymysql`，多进程协调需 `redis`（后两者源仓库本就是惰性导入）。
- 三种后端形态与变量见 `tools/config.example.env`；工具清单、返回格式、对接方式见 `tools/README.md`。

## 谁是真源

- `references/*.md` 是把分析逻辑讲清楚的**规范与理由**，供人和通用 agent 阅读。
- `scripts/vendor/*.py` 是**可执行的规则真源**：路由、证据、预测披露、图表抑制、
  只读 SQL、名称解析。文档与实现冲突时以实现为准，并以 `cases/` 回放验证。
- `cases/` 是从原系统评测集冻结的行为快照（来源见 `cases/README.md`）。

## 不包含在本包内

- **凭据**：`credentials.env` / `.env` 一律不随包交付，由使用者在仓库外自建（600 权限）。
  本包不含任何 secret、用户数据、会话记录或业务明细。
- Web 会话 / SSE 流式输出 / 前端工作台：与宿主运行时绑定，本包只接工具层。
- 原仓库的完整提交历史、分支与运行时配置；仅 `scripts/vendor/`、`tools/_vendor/` 顶部
  保留来源与基线提交注释，用于说明出处、方便后续同步。

> 注意：`tools/_vendor/` 是真实工具实现的原样副本（内部资产），仅供公司内网分发，
> 不要转发到外部。

## 接收方如何开始

1. 读 `SKILL.md`，按其工作流接入自己的 agent。
2. 需要确定性判定时调用 `scripts/`；需要解释与话术时读 `references/`。
3. 接入后先跑一遍 `python3 scripts/selfcheck.py --quiet`，确认行为与快照一致。
