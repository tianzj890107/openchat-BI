# 实现提示词：把因果越界与代理指标披露变成离线真实门禁（第六批）

> 把下面整段交给实现人员（人或 Agent）。本批**只做评测与门禁**，
> 生产回答生成逻辑默认不改。

---

## 0. 你的任务

`unsupported_causal_claim_rate` 与 `proxy_disclosure_rate` 目前是恒不触发的假门禁：
黄金集里 15 条案例声明了 `must_separate_correlation_from_cause` /
`must_use_proxy_disclosure_if_proxy_used`，但它们的 evaluator 从不评分最终回答，
分母恒为 0，门禁报 `NOT_APPLICABLE`（`ok=True`），既不阻断发布，也发现不了因果越界
和代理指标不披露。

请让这两个指标成为**确定性、离线、可复现、会失败**的真实门禁。

## 1. 先读

1. `docs/specs/analytics-causal-and-proxy-truthfulness.md`（本批 Spec，必须逐节读完）
2. `tests/test_analytics_causal_proxy_truthfulness_red.py`（红测，就是验收标准）
3. `scripts/run_analytics_eval.py` 中：`LIVE_ONLY_METRICS`、`ALL_METRICS`、
   `score_answer`、`PROXY_KEYWORDS`、`_suite_capabilities`、`MISSING_CASE_HINTS`、
   `RELEASE_REQUIRED_METRICS`、`_metric_gate`、`evaluate_gates`、
   `eval_recorded_provider`、`_record_grounding_metric`、`eval_answer_grounding`
4. `dataset/evals/analytics/README.md` §7、`schemas/case.schema.json`、
   `cases/diagnosis/ANA-RPDIAG-00{1..8}.json`、对应 `fixtures/provider/diagnosis/*.json`

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_analytics_causal_proxy_truthfulness_red.py -p no:randomly
```

预期：约 **53 failed / 14 passed**。请先逐条读懂失败原因，再动手；
**不允许**修改红测、降低断言、删除失败案例、把失败改成 skip/xfail。

## 3. 实现要求

1. **优先补评测和结构化证据**，不要先动生产回答生成。
2. 只有红测证明**生产回答本身**越界时，才允许最小化修改生产回答提示/模板；
   修改后前五批红测必须仍然全绿。
3. 不使用真实 Provider、不读取真实凭据；`live`/`live-canary` 缺凭据继续报
   `not_measured`，不得写成 `passed`。
4. 用**结构化判定**实现语义评分，不要用关键词凑：
   - 因果：按 Spec §2 的分句切分 + 因果谓词 + 同分句弱化 + `expected.causal_support`
     证据引用；另一分句的弱化不能给确定性声明洗白；有证据的因果不得误杀。
   - 代理：按 Spec §3 的三要素披露（代理指标名 + 目标指标名 + 同分句限制说明）；
     分母由案例声明决定，不由回答文本决定；重命名、多代理只披露一个、
     只说「仅供参考」、图表/表格冒充目标指标都算不合格。
5. 把两个指标从「离线不可测」改为「离线可测」：
   - `_suite_capabilities`：选择集含声明案例 + 可评分 evaluator（`recorded_provider`/
     `answer_grounding`/`answers`/`live`）→ capable；
   - 空分母 → `NOT_MEASURED` 且 `ok=False`（release 阻断），**不得** `NOT_APPLICABLE`；
   - `RELEASE_REQUIRED_METRICS` 纳入两个比率指标；`LIVE_ONLY_METRICS` 移除它们；
   - `MISSING_CASE_HINTS` 改指向离线语义评分案例。
6. `eval_recorded_provider` 评分最终回答，只并入
   `answer.unsupported_causal_claim` / `answer.proxy_disclosure` 两个 check 与
   对应两个指标；**不要**把 `must_state_metric_and_scope`、
   `must_include_effective_action_section`、`must_cite_queried_numbers` 搬到离线路径，
   也**不要**让 `score_answer` 的返回值覆盖 `_record_grounding_metric` 的
   `unsupported_number_rate`。
7. 新增负例（negative control）：`expected.expect_causal_violation` /
   `expected.expect_proxy_miss`。回答故意越界，案例通过 = 监督抓住了它；
   样本计入 `unsupported_causal_claim_detection_rate` /
   `proxy_disclosure_detection_rate`，**不计入**真实比率分母。两个 detection 指标
   必须 `== 1.0` 且 `sample_size >= 1`。
8. 按 Spec §4.3 补齐离线样本：causal 与 proxy 各 ≥6 条有样本案例、覆盖 ≥3 个领域，
   且包含正例、反例、边界例、多轮例、否定/澄清例。可复用
   `ANA-RPDIAG-001/002/004/006`（causal）与 `ANA-RPDIAG-003/005/008`（proxy）
   并在其上声明 `expected` 契约；其余新增，id 用 `ANA-TRUTH-CAUSAL-0NN` /
   `ANA-TRUTH-PROXY-0NN`。
   - 录制回答必须与声明契约一致（该披露就披露，该弱化就弱化），
     不要为了凑通过而改写诚实回答；
   - 「交付」类案例归入 `制造`/`通用` 域（域名枚举没有「交付」）。
9. `case.schema.json` 支持 Spec §7 的全部新增字段：
   `causal_claims`、`causal_support`、`expect_causal_violation`、`target_metric`、
   `proxy_metric`、`proxy_limits`、`used_direct_metric`、`expect_proxy_miss`；
   数据集自检（`tests/test_analytics_eval_dataset.py`）必须继续通过。
10. 同步 `dataset/evals/analytics/manifest.json`（案例数与 by_* 分布）、
    `dataset/evals/analytics/README.md`（§7 指标表、`not_measured` 说明改为「离线可测」）。
11. 不新增 known gap、不删除任何案例；`known_gap_ratchet` 保持 `0/0`。
12. 不修改红测、不降低期望、不把 `0.0`/`1.0` 变成「看起来漂亮」的近似值：
    分母为 0 时必须 `null`，且 release 阻断。

## 4. 完成后必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_analytics_causal_proxy_truthfulness_red.py -p no:randomly
.venv/bin/python -m pytest -q \
  tests/test_analysis_security_refusal_red.py \
  tests/test_analysis_security_session_refusal.py \
  tests/test_analysis_action_intent_red.py \
  tests/test_analysis_metadata_fact_routing_red.py \
  tests/test_analysis_residual_routing_gaps_red.py \
  tests/test_analysis_forecast_intent_red.py
.venv/bin/python -m pytest -q tests/test_analytics_eval_dataset.py tests/test_analytics_eval_production_chain.py
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
.venv/bin/python -m scripts.run_analytics_eval --suite regression --release
git diff --check
```

要求：

- 新红测全绿；
- 前六批红测全绿（安全 61+6、行动 51、元数据 55、残余 55、预测 64）；
- `adversarial` 62/62、`smoke` 140/140、`recorded-provider` 113/113
  （新增案例后按新基线，只增不减）、`regression`/`all` 全绿；
- `known_gap_ratchet`、`p0_known_gap_allowlist`、`known_gap_overdue`、
  `unresolved_security_defects` 全部 PASS；
- 两个指标：`unsupported_causal_claim_rate = 0.0`、`proxy_disclosure_rate = 1.0`，
  且 `metric_sample_sizes > 0`；两个 detection 指标 `= 1.0` 且 `sample_size >= 1`；
- `--release` 退出码 0。

## 5. 报告要求

最终报告必须包含：

1. 修改文件清单（评测器 / schema / 案例 / fixture / manifest / README / 测试）；
2. 两个指标的最终 `sample_size`、`numerator/denominator` 与领域分布；
3. 前六批红测与四个评测套件的实际数字；
4. **误伤验证**：明确列出既有诚实回答被判定为合规的证据
   （113 条 recorded-provider 全绿、7 条声明案例样本为 `false`/`true`）；
5. 负例（detection）被抓住的证据；
6. 剩余风险与未覆盖项（`repeat_stability` 仍 `not_measured`、live 未运行）；
7. 明确说明：未部署、未重启服务、未创建 MR/tag/Release、未改版本号、未读取真实凭据。

## 6. 禁止事项

- 禁止只加「导致/代理」关键词就宣称完成；
- 禁止为了让指标变 1.0 而伪造样本、跳过失败回答或降低判定标准；
- 禁止删除负例、删除声明案例、把指标改回 `not_measured`；
- 禁止把 `NOT_APPLICABLE` 当作通过；
- 禁止修改红测迁就实现；
- 禁止 commit/push/tag/Release/部署（除非用户在当前任务中另行明确要求）。
