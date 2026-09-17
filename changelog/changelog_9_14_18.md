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

### 1. 分析 Agent 黄金评测集与 recorded-provider 回放层（已完成）

- 新增 `dataset/evals/analytics/`：面向「自然语言问题 → 意图 → 口径/范围 → 工具计划
  → 查询 → 数字结果 → 证据 → 图表 → 最终结论」的端到端黄金评测集。首版当日提交
  （`a1134c7`，291 条），随后扩展为 **482 条用例**（P0 107、P1 340、P2 35，其中
  12 条为已登记缺陷的 Red 用例、P0 6 条）；本条记录当周最终状态，原有案例全部保留。
- 新增生成器 `dataset/evals/analytics/build_cases.py` 与 fixture 生成器
  `dataset/evals/analytics/fixtures/build_fixtures.py`：期望数字由 fixture 行字面量做
  纯 Python 算术得出，运行器再通过 SQL 独立得到同一数字，两条路径互不依赖。
- 新增 6 个确定性 SQLite fixture（`procurement.db`/`inventory.db`/`sales.db`/`quality.db`/
  `finance.db`/`manufacturing.db`）与精简本体 `analytics_golden_ontology.xlsx`，显式植入 NULL、重复行、负数、缺月
  （2025-03）、分母为零、USD/CNY 混用、逻辑删除、停用供应商等边界；全部以
  `mode=ro&immutable=1` 只读打开。
- 覆盖领域：采购、库存、销售、质量、财务、制造均有确定性数值 fixture；财务 29 条、
  制造 30 条数值案例，补齐原缺口。
- 新增运行器 `scripts/run_analytics_eval.py`：16 个 evaluator（新增 `recorded_provider`、
  `generated_sql`、`tool_chain`、`answer_grounding`、`context_resolution`）、15 项指标、
  P0 门禁、JSON + Markdown 报告、`--compare` 基线回归对比（指标下降或 P0 下降即非零退出），
  以及 `--release` / `--allowlist` / `--ratchet` 发布门禁参数。
- 新增 `scripts/analytics_recorded_provider.py`：录制事件经**真实**
  `WebSession.generate_turn` 会话循环回放，使用生产工具注册、工具参数校验与
  SSE/事件解析，SQL 工具改向只读 eval SQLite fixture，会话/图表/日志写入
  `tempfile.mkdtemp` 临时目录，API key 固定为测试值，不访问网络；80 条回放案例
  进入默认离线回归。
- 数字接地改为案例级：删除原先把全部 SQL 案例结果与 0–119、180、2024、2025 等数字
  放进全局 `allowed_numbers` 的兜底，跨案例数字不再被误判为已引用，并新增反向对照
  案例证明「其他案例出现过的数字」在本案例仍属 unsupported。
- 套件：`smoke`(103) `regression`(482) `multi-turn`(32) `ontology`(46) `charts`(22)
  `adversarial`(33) `recovery`(33) `diagnosis`(20) `recorded-provider`(80) `live`；
  `--suite all` 与 `--suite live` 已可用。
- 新增 `manifest.json`（含每个 fixture 的 sha256 与 known_gap 清单）与
  `schemas/case.schema.json`，`dataset/evals/analytics/README.md` 记录安全契约、
  断言层级、指标/门禁、known_gap 语义和 dataset 审计结论。
- 新增 known_gap 治理：登记 `owner`/`introduced_at`/`target_fix_version`/`severity`/
  `source_issue`，新增按 case_id 的 `known_gap_allowlist.json`（发布门禁专用）、
  `known_gap_ratchet.json`（12 条 / P0 6 条，不允许增长）与 xpass 门禁；报告改为输出
  `p0_total`/`p0_passed`/`p0_failed`/`p0_xfailed`/`p0_xpassed`/`unresolved_p0_defects`，
  不再把「103 条 P0 中 97 条通过」写成全部通过。
- schema 加固：per-evaluator `if/then` 必填、`fixture.additionalProperties=false`、
  未知字段直接判失败、重复 `(question, evaluator, expected)` 检测。
- 新增 `tests/test_analytics_eval_dataset.py`（47 项）：schema、case_id 唯一性与
  文件名一致、fixture 存在性、参考 SQL 只读性与禁写关键词、manifest 与 runner 选择
  结果一致、fixture 指纹、覆盖率下限。
- 安全边界：评测集不读写 `dataset/conversations`、`dataset/charts`、`dataset/logs`、
  `dataset/databases`、`dataset/uploaded_reports`；evaluator 的写操作全部落在
  `tempfile.mkdtemp` 临时目录；不调用会话删除类接口；不读历史业务库
  `HyperFusion.db`/`Kingdee.db`；运行输出 `dataset/evals/analytics/reports/` 已加入
  `.gitignore`，只提交 `baselines/`。
- 离线结果：`--suite regression` 470/470 通过、`--suite smoke` 97/97 通过、
  `--suite recorded-provider` 80/80 通过，12 条 known_gap 单独报告为 xfail；
  `--repeat 3` 的 `repeat_stability=1.0`
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
- 验证：`pytest -q tests` 476 passed / 25 skipped / 193 subtests passed；离线套件
  + `all` 全部 exit 0；`git diff --check` 干净。
- 未修改业务实现；业务缺陷只登记为 Red，不在本轮修复。

### 2. GitLab CI/CD 接入项目 runner（已完成）

- 新增 `.gitlab-ci.yml`：`test` / `eval` 两阶段，默认镜像
  `boulderai/analytics-ci:3.13`，所有 job 声明 `tags: [boulderai]` 以匹配项目 runner
  （提交 `e0ce2e0`）；
- job：`unit-tests`（全量 pytest）、`analytics-eval-smoke`、
  `analytics-eval-regression`、`analytics-eval-recorded-provider`（离线、无需凭据），
  以及手动且 `allow_failure` 的 `analytics-eval-release-gate`（P0 known gap 未被
  审计 allowlist 覆盖时失败，防止用「忽略全部 known gap」绕过）；
- 运行节点：项目 runner `sys740-docker-runner`（`172.16.10.34`，docker executor）；
  pipeline 只做验证，没有 deploy stage，job 不写服务器，push 不触发部署；
- 实测当前提交 pipeline（id `3142`）4/4 job `success`：unit-tests 75.6s、
  smoke 18.0s、regression 21.7s、recorded-provider 19.8s；release gate 保持手动。

### 3. 版本记录与发布（已完成）

- 版本更正：同日先创建 `docs/versions/v0.1.8.md` 与版本索引，记录此前误发为
  `v0.2.0` 的配置/文档收口批次（提交 `aa77775`、`59fb09d`）；
- 按用户明确指定的目标版本发布 `v0.1.9`：产品版本号从 `0.1.7` 统一升级到 `0.1.9`
  （`pyproject.toml`、`bi_agent/__init__.py`、`open_claude/__init__.py`、FastAPI
  `APP_VERSION`、`frontend/package.json`、`frontend/package-lock.json`、
  `frontend/src/main.jsx`、`frontend/src/shell.html`），前端 vite 生产构建重建，
  产物差异仅两处版本字符串，工作台品牌标签显示 `v0.1.9`；
- 新增 `docs/versions/v0.1.9.md`，更新 `docs/versions/README.md` 与根 `README.md`
  当前版本入口；版本契约测试同步（产品版本断言、官方 tag 白名单 `v0.1.0`–`v0.1.9`）；
- 创建 annotated tag `v0.1.9` 并推送到 GitLab，在
  `ai-team/eimosp-ontology-agentic-analytics` 上基于同名 tag 创建 GitLab Release；
- 同时发起正式交付 Merge Request `20260727` → `master`（reviewer `tianzijing`，
  assignee `zhangzhen`），只创建 MR，不自动合并、不直接 push `master`；
- 本版本未部署：tag、Release 与 MR 都不改变服务器正在运行的版本。
