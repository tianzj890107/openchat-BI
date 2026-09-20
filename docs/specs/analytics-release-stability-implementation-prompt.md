# 实现提示词：把发布稳定性变成真实门禁（第七批·收口批）

> 把下面整段交给实现人员（人或 Agent）。本批只做**评测门禁与 CI 策略**，
> 不新增普通意图案例、不重开已清零缺陷、不改生产回答生成。

---

## 0. 你的任务

`repeat_stability` 现在会被测量、会被报告，但**没有任何门禁**：

```
--suite smoke --release                → exit 0，repeat_stability = not_measured
--suite all   --repeat 2 --release     → exit 0，5 条不稳定（ANA-ISO-001..005）
```

而且那 5 条是**误报**：两次运行只差 `evidence.observations[].id` 这个随机 8 位十六进制
会话 id，Spec §4.1 明明把它列为允许变化项。

请让「发布稳定性」成为可测、可比、会失败的门禁，并修掉这个误报。

## 1. 先读

1. `docs/specs/analytics-release-stability.md`（本批 Spec，逐节读完）
2. `tests/test_analytics_release_stability_red.py`（红测 = 验收标准）
3. `scripts/run_analytics_eval.py` 中：`measure_repeat`、`result_signature`、
   `semantic_signature`、`generic_signature`、`_canonical_value`、
   `_normalize_volatile_text`、`_VOLATILE_TEXT_PATTERNS`、`VOLATILE_SIGNATURE_KEYS`、
   `aggregate`、`build_report`、`evaluate_gates`、`_metric_gate`、
   `RELEASE_REQUIRED_METRICS`、`_suite_capabilities`、`MISSING_CASE_HINTS`、`main`
4. `.gitlab-ci.yml`（`analytics-eval-release-gate` / `analytics-eval-repeat-stability` /
   普通 eval job）

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_analytics_release_stability_red.py -p no:randomly
```

预期 **16 failed / 47 passed / 12 subtests passed**。先读懂每条失败，再动手；
**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。

## 3. 实现要求

1. **release gate 真实重复运行**：`evaluate_gates` 必须新增 `repeat_stability` 门禁
   （阈值 `>= 1.0`），并把 `repeat_stability` 加入 `RELEASE_REQUIRED_METRICS`。
   - 未测量：release 运行 `ok=false`（阻断）；普通运行 `ok=true`（不阻断，允许
     `repeat_stability = not_measured`）。
   - 实测漂移（`agreement < 1.0`）：`ok=false` 且 `severity="always"`，普通运行也返回非 0，
     这样没带 `--release` 的 CI repeat job 也会让 pipeline 变红。
2. **不伪造 stability**：
   - `repeat < 2` 时 `measure_repeat` 必须返回 `agreement = None`、`cases = 0`，
     绝不返回 `1.0`；
   - 零样本（`cases == 0`）不得写入 `metrics["repeat_stability"] = 1.0`，
     必须是 `None` + `metric_stats.measured = false`；
   - `build_report` 收到 `repeat["cases"] == 0` 时不得采用传入的 `agreement`。
3. **样本与 skip**：
   - 新增 `stable_case_ids` / `unstable_case_ids` / `skipped_case_ids`；
   - 只有在**每一次重复都执行完成**（`status != SKIP`）的案例才计入样本；
   - 出现在 `skipped_case_ids` 的案例不得计入 stable；其数量进入
     `metric_stats["repeat_stability"]["skipped"]`；
   - release 运行中"部分执行"（有案例被跳过）必须阻断；
   - 整套被跳过（live 缺凭据，`skipped=True`）保持 `NOT_MEASURED` 且**不阻断**。
4. **canonical 比较，不锁死无语义字段**：
   - 补齐 id 类归一化：6–40 位十六进制串（含 8 位会话 id）与
     key ∈ {`id`, `session_id`, `run_id`, `request_id`, `trace_id`} → 归一化；
   - 继续归一化时间戳、沙箱路径、chart/report 文件名时间戳、SQL 空白/大小写、
     dict 键顺序、耗时/token/成本；
   - **不得**把语义字段纳入归一化：单位、币种、指标名、维度名、filter、group by、
     时间范围、数值结果、intent/route/tools/next_step、refusal category、
     forecast flags、chart type/series/x 轴、check 结果、metric 布尔值。
   - 修完后 `ANA-ISO-001..005` 必须变为稳定：`smoke` = `1.0 (n=140)`、
     `regression`/`all` = `1.0 (n=570)`。
5. **CI 策略**：
   - `analytics-eval-release-gate` 必须带 `--repeat 2`（保留 `--release`、
     `allow_failure: false`、`when: manual` + tag 自动执行、不带 `--provider`）；
   - `analytics-eval-repeat-stability` 保留 `--repeat 2`，不得加 `--no-gate`；
   - 普通 dev job（smoke / regression / recorded-provider）**不得**加 `--repeat`
     （570 条 × N 成本不可接受）；
   - `analytics-eval-live-canary` 保持 `when: manual`、`allow_failure: true`、不注入凭据。
6. **保持前六批行为**：570 条案例、P0 147/147、`known_gap = 0/0`；
   四个真实性指标（causal / proxy / 两个 detection）在 repeat 后仍保持
   `sample_size >= 6 / >= 1` 且达标；`cross_session_leak_rate = 0`。
7. **报告主体仍取第一轮**：重复轮只喂稳定性指标，不得用第二轮覆盖或掩盖第一轮。
8. 不新增普通意图案例、不改 `bi_agent/**`、不改 `policy_version`、不重开已清零缺陷。
9. 同步 `dataset/evals/analytics/README.md`（新增 `repeat_stability` 门禁说明与
   CI 策略），并更新当周 `changelog/changelog_9_14_18.md`。
10. 不修改红测迁就实现、不使用真实 Provider、不读取真实凭据、不部署。

## 4. 完成后必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_analytics_release_stability_red.py -p no:randomly
.venv/bin/python -m pytest -q tests
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
.venv/bin/python -m scripts.run_analytics_eval --suite smoke --repeat 2 --release
.venv/bin/python -m scripts.run_analytics_eval --suite all --repeat 2 --release
.venv/bin/python -m scripts.run_analytics_eval --suite smoke --release   # 必须失败：无 repeat
git diff --check
```

要求：

- 新红测全绿（63 个测试方法）；
- 单次运行：5 个套件全绿，`repeat_stability = not_measured` 且**不阻断**；
- `--repeat 2`：`repeat_stability = 1.0`，`sample_size = 选择集案例数`，
  `unstable_case_ids = []`，`skipped_case_ids = []`；
- `--suite smoke --release`（无 repeat）**退出码非 0**，门禁 `NOT_MEASURED + ok=false`；
- `--suite all --repeat 2 --release` 退出码 0；
- 全量 `pytest -q tests` 全绿（25 条 opt-in skip 不变，不得把 skip 写成 pass）；
- `known_gap_ratchet 0/0`、`p0_known_gap_allowlist`、`unresolved_security_defects` 全 PASS。

## 5. 报告要求

必须包含：

1. 修改文件清单（评测器 / CI / README / changelog）；
2. repeat 次数、样本数、`stable/unstable/skipped` 案例数；
3. `ANA-ISO-001..005` 由"不稳定"变为"稳定"的证据（差异仅在 id 类字段）；
4. 17 类禁止变化各自如何被检出（哪些是新增断言、哪些是既有断言）；
5. 允许变化清单的实现位置（归一化函数）；
6. 单次运行与 release 运行的退出码对照；
7. 四个真实性指标 + `cross_session_leak_rate` 在 repeat 后的样本数与取值；
8. 全量测试结果与 25 条 skip 的原因分类；
9. 剩余风险（live 未运行、`repeat_stability` 只覆盖离线链路）；
10. 明确说明未部署、未重启服务、未创建 MR/tag/Release、未改版本号、未读取真实凭据。

## 6. 禁止事项

- 禁止让 release gate 不重复运行就通过；
- 禁止用 `--repeat 1` 或零样本伪装 `1.0`；
- 禁止忽略 intent / query scope / 安全拒绝 / 代理披露等漂移；
- 禁止把第二次 skip 当稳定；
- 禁止把语义字段（单位、指标、filter、数值）归一化掉；
- 禁止继续增加普通案例、重新打开已清零的 known gap；
- 禁止修改红测迁就实现；
- 禁止 commit/push/tag/Release/部署（除非用户在当前任务中另行明确要求）。
