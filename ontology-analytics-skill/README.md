# ontology-analytics-skill

硕磐智能分析 Agent 的可移植规则包：把意图路由、分析 SOP、证据纪律、交付闸门和
整页 HTML 交付契约写成通用 Agent 可执行的说明。真实数据由主服务的远程 MCP 提供，
技能包本身不启动服务、不保存凭据、不包含用户数据。

## 目录

```text
ontology-analytics-skill/
├─ SKILL.md                 主入口：接入方式、工具顺序、交付契约
├─ references/              分析规则与话术
│  ├─ 01-sop.md             六步分析 SOP
│  ├─ 02-level-templates.md L1–L5 模板
│  ├─ 03-discipline.md      证据与表达纪律
│  ├─ 04-deep-insight.md    多维下钻
│  ├─ 05-naming-rules.md    业务名称优先
│  ├─ 06-routing-rules.md   路由字段与优先级
│  ├─ 07-output-gates.md    五道交付闸门
│  ├─ 08-tools-and-sources.md 远程 MCP 的 17 个工具契约
│  ├─ 09-graph-mode.md      图库检索模式
│  └─ 10-roles.md           用户画像与回答风格
├─ scripts/                纯规则脚本（仅标准库，可选离线校验）
│  ├─ route.py              路由决策
│  ├─ gates.py              交付闸门
│  ├─ selfcheck.py          冻结用例回放
│  └─ vendor/               规则真源
└─ cases/                   路由与闸门冻结用例
```

本目录**不包含** `serve.py`、`mcp_server.py`、`_vendor/`、`credentials.env` 或
任何 `dataset/` 运行产物。真实工具和 HTML 生成由主服务的 `/api/mcp` 提供。

## Fuxi 接入

只需要一个远程 MCP 配置：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
```

连接后，Fuxi 工具面板会显示 17 个真实工具，包括 `AnalysisRoute`、
`MetricFactQuery`、`ChartGenerate`、`TableGenerate`、`CanvasGenerate` 和
`TaskOrderCreate`、`OutputGateCheck`。不会显示 `AnalysisRun`、`AskUser`、`TodoWrite`、
原始 SQL 或表结构工具。

用户只输入业务问题；工具选择、指标解析、取数、对账、HTML 生成和闸门都由技能规则
与远程 MCP 自动完成。用户不需要填写 `.env`、App ID、Token、输出目录，也不需要
执行 `run_scratch` 或 `promote_artifact`。

## 推荐执行顺序

```text
AnalysisRoute
  → MetricFactQuery
  → TableGenerate / ChartGenerate
  → CanvasGenerate
  → OutputGateCheck
  → 返回业务结论 + Artifact URL
```

行动建议在 Canvas 中以 `kind=actions` 输出。只有用户点击“发送任务令”后才调用
`TaskOrderCreate`，由 Fuxi 宿主带入当前用户手机号写入 Fuxi 风险待办。

名称无法解析时才增加 `Ontology-SemanticQuery` / `Ontology-TermDisambiguate`；
指标口径有疑问时才增加 `MetricCalculation`。不要每轮先堆叠元数据查询。

## 纯规则脚本

`scripts/` 只用于离线校验和开发排查，不是 Fuxi 的运行入口：

```bash
cd ontology-analytics-skill

python3 scripts/route.py --question "2025年采购金额合计是多少" --pretty
python3 scripts/route.py --batch cases/routing_cases.jsonl
python3 scripts/gates.py sql --sql "SELECT 1"
python3 scripts/gates.py check --input turn.json
python3 scripts/selfcheck.py --quiet     # 期望 160/160 passed
```

- 运行要求：Python 3.10+；只使用标准库；不需要网络。
- 规则实现与文档冲突时，以 `scripts/vendor/` 为准，并用 `cases/` 回放验证。
- Fuxi 运行时直接调用 MCP 的 `AnalysisRoute` 和 `OutputGateCheck`，不要执行上述 CLI。

## 交付物

- 对话结论：业务结论、路由模式、取数工具、对账结果和闸门 verdict。
- 整页 HTML：由 `CanvasGenerate` 返回 `Artifact URL`，可直接打开、保存或转发。
- 不含凭据、用户数据、会话记录和内部暂存路径。

## 边界

- 远程 MCP 由主服务 `bi_agent.web` 部署；技能包不启动服务。
- 没有 MCP 连接、网络不可达或权限不足时，明确说明能力限制，不编造数字。
- 预测与情景没有统计模型支持，必须披露窗口、方法和假设，不得编造置信区间或准确率。
