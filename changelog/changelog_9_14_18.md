# eimosp-ontology-agentic-analytics 变更记录（2026-09-14 至 2026-09-18）

> 本文档记录 2026-09-14（周一）至 2026-09-18（周五）当周的最终变更，按周直接维护
> （2026-09-08 起 changelog 只按周维护，不再创建日报）。9/14–9/16 未建日报，本节内容
> 依据当周 git 提交记录（`dff2ec4`）补录；9/17 变更完成后直接追加到本文档。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 2026-09-14（周一）

### 1. 分析 Agent 前端 API 契约文档（已完成）

- 新增 `API/智能分析Agent前端API.md`（1720 行），在 `README.md` 增加索引入口，
  把前端需要对接的接口、事件流、状态字段和错误码集中成一份契约（提交 `dff2ec4`）。

## 2026-09-17（周四）

### 1. 分析 Agent 黄金评测集与防回归评测框架（已完成）

- 新增 `dataset/evals/analytics/`：面向「自然语言问题 → 意图 → 口径/范围 → 工具计划
  → 查询 → 数字结果 → 证据 → 图表 → 最终结论」的端到端黄金评测集，共 **291 条用例**
  （P0 103、P1 188，其中 12 条为已登记缺陷的 Red 用例）。
- 新增生成器 `dataset/evals/analytics/build_cases.py` 与 fixture 生成器
  `dataset/evals/analytics/fixtures/build_fixtures.py`：期望数字由 fixture 行字面量做
  纯 Python 算术得出，运行器再通过 SQL 独立得到同一数字，两条路径互不依赖。
- 新增 4 个确定性 SQLite fixture（`procurement.db`/`inventory.db`/`sales.db`/`quality.db`）
  与精简本体 `analytics_golden_ontology.xlsx`，显式植入 NULL、重复行、负数、缺月
  （2025-03）、分母为零、USD/CNY 混用、逻辑删除、停用供应商等边界；全部以
  `mode=ro&immutable=1` 只读打开。
- 覆盖领域：采购、库存、销售、质量有确定性数值 fixture；财务、制造以意图、口径、
  图表和对抗用例覆盖（无独立数值 fixture，已在 README 标注为缺口）。
- 新增运行器 `scripts/run_analytics_eval.py`（1862 行）：12 个 evaluator、15 项指标、
  P0 门禁、JSON + Markdown 报告、`--compare` 基线回归对比（指标下降或 P0 下降即非零退出）。
  子命令/参数：`--suite`、`--case`、`--category`、`--repeat`、`--baseline`、`--compare`、
  `--answers`、`--list`、`--no-gate`、`--verbose`。
- 套件：`smoke`(103) `regression`(291) `multi-turn`(20) `ontology`(34) `charts`(22)
  `adversarial`(31) `recovery`(29) `diagnosis`(20) `live`(20)；`--suite all` 与
  `--suite live` 已可用。
- 新增 `manifest.json`（含每个 fixture 的 sha256 与 known_gap 清单）与
  `schemas/case.schema.json`，`dataset/evals/analytics/README.md` 记录安全契约、
  断言层级、指标/门禁、known_gap 语义和 dataset 审计结论。
- 新增 `tests/test_analytics_eval_dataset.py`（27 项）：schema、case_id 唯一性与
  文件名一致、fixture 存在性、参考 SQL 只读性与禁写关键词、manifest 与 runner 选择
  结果一致、fixture 指纹、覆盖率下限。
- 安全边界：评测集不读写 `dataset/conversations`、`dataset/charts`、`dataset/logs`、
  `dataset/databases`、`dataset/uploaded_reports`；evaluator 的写操作全部落在
  `tempfile.mkdtemp` 临时目录；不调用会话删除类接口；不读历史业务库
  `HyperFusion.db`/`Kingdee.db`；运行输出 `dataset/evals/analytics/reports/` 已加入
  `.gitignore`，只提交 `baselines/`。
- 离线结果：`--suite regression` 279/279 通过、`--suite smoke` 97/97 通过，
  12 条 known_gap 单独报告为 xfail；`--repeat 3` 的 `repeat_stability=1.0`
  （修掉会话隔离用例在同一进程内复用目录、以及恢复快照里 `checkpoint_id`/
  `created_at` 造成的伪抖动）。
- 新增 Red（未修业务）登记：`ANA-ADV-010/011/012`、`ANA-INTENT-052/061/064/071/072/073`、
  `ANA-REC-003/009/010`，覆盖凭据/破坏性请求误判为数据查询、「采取什么行动」「该怎么处理」
  「怎么改善」不触发行动意图、指标「口径」提问不走本体查询、预测类问题无等级、
  列表型问法不查询数据等缺陷。
- live 套件实测暴露两个产品缺陷（仅登记、未修改业务实现）：`session._run_loop` 在工具终端
  失败时提前 `return`，留下带 `tool_calls` 却没有对应 tool 结果的 assistant 消息，导致同一
  会话下一次请求被 provider 以 400 拒绝；以及 `Ontology-SemanticQuery` 在本地本体 fixture
  上稳定 `TOOL_TIMEOUT`。
- 验证：`pytest -q tests` 456 passed / 25 skipped / 193 subtests passed；8 个离线套件
  + `all` 全部 exit 0；`git diff --check` 干净。
- 未修改业务实现，未改版本号、未打 tag、未推送、未部署。
