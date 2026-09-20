# 分析 Agent：发布稳定性（repeat stability）门禁 Spec（第七批·收口批）

- 状态：**Spec 冻结（红测已提交为 Red 用例）**；生产实现**尚未修改**。
- 适用对象：`scripts/run_analytics_eval.py`（repeat 测量与门禁）、`.gitlab-ci.yml`（CI 策略）、
  `tests/test_analytics_release_stability_red.py`（红测）。
- 对应实现提示词：`docs/specs/analytics-release-stability-implementation-prompt.md`
- 产品版本：`v0.1.9`（本批不改版本号）；`policy_version` 保持 `1`。
- 前置批次：安全拒绝、行动建议、元数据/事实路由、残余路由缺口、预测与推演、
  因果/代理真实性（`known_gap=0`、570 条、P0 147/147 全绿）。本批**不重新打开**任何已清零缺陷。

---

## 0. 一句话结论

`repeat_stability` 会被**测量**、会被**报告**，但**从来没有被门禁约束**：
`evaluate_gates` 里没有 `repeat_stability` 门禁，它不在 `RELEASE_REQUIRED_METRICS`，
CI 的 release job（`analytics-eval-release-gate`）跑的是 `--suite smoke --release`，
**没有 `--repeat`**。因此：

```
--suite smoke --release                    → exit 0，repeat_stability = not_measured
--suite all   --repeat 2 --release         → exit 0，5 条用例不稳定（ANA-ISO-001..005）
```

同时，被判定为「不稳定」的 5 条其实不是漂移，而是**指纹没有归一化会话 id**：
两次运行的 `evidence.observations[].id` 是随机 8 位十六进制（`6ac1df67` vs `d4bb3a17`），
而 Spec §4.1 明确把 session/run id 列为允许变化项。真实稳定性被低估为
`140/140 → 138/140 (0.985714)`、`570/570 → 565/570 (0.991228)`。

本批把「发布稳定性」变成**可测、可比、会失败**的门禁。

---

## 1. 普通门禁与 release 门禁的区别

| | 普通开发 pipeline / 本地单次运行 | 正式 release gate |
| --- | --- | --- |
| 运行次数 | 1 次（成本敏感，570 条不重复跑） | 必须重复运行（≥2 次） |
| `repeat_stability` 状态 | `NOT_MEASURED`，门禁 `ok=true`，**不阻断** | `NOT_MEASURED` = 失败（`ok=false`，release 阻断） |
| 门禁 severity | `release`（未测不阻断） | 未测即失败；实测漂移在任何运行都失败（`always`） |
| 失败条件 | 实测 `agreement < 1.0` | 实测 `agreement < 1.0`、有跳过样本、或未测量 |
| 允许的展示 | `repeat_stability = not_measured` | 必须 `measured` 且 `= 1.0` |

硬性要求：

1. `evaluate_gates` 必须输出名为 `repeat_stability` 的门禁。
2. `RELEASE_REQUIRED_METRICS` 必须包含 `repeat_stability`。
3. 门禁阈值：`repeat_stability >= 1.0`（`higher_is_better`）。
4. 实测漂移（哪怕在非 release 运行）必须 `ok=false`、`severity="always"`（CI 的
   repeat job 没有 `--release` 也要让 pipeline 变红）。
5. 未测量（release 运行没重复、或重复次数 < 2）必须 `ok=false`、`severity="release"`。
6. `--repeat 1` **不得**产生稳定性分数（`measure_repeat` 的 `agreement is None`，
   报告 `not_measured`）；`repeat < 2` 视为**非法请求**，CLI 必须非零退出
   （加不加 `--release` 都一样），不得静默降级成一次普通运行后返回 0。

---

## 2. repeat 样本范围

- `repeat >= 2`；建议 release 使用 **2**（成本/收益平衡），上限 3。
- 样本 = 选择集里**每一次重复都真实执行完成**的案例。
- 未执行（skip）的重复：该案例**不计入**稳定样本，列入 `skipped_case_ids`，
  并在 `metric_stats["repeat_stability"]["skipped"]` 计数。
- **部分执行**（同一选择集里有案例被跳过、其余测出结果）在 release 运行中视为
  证据不足 → 门禁失败；整套被跳过（如 live 缺凭据）→ `NOT_MEASURED` 且**不阻断**
  （沿用第五批的 `skipped=True` 语义）。
- 每个案例在样本里最多计 1 次；`agreement = 稳定案例数 / 参与样本的案例数`。
- `cases`（样本数）必须等于"每次重复都执行"的案例数；`repeat=1` 时 `cases = 0`、
  `agreement = null`。

比较对象是**同一案例的多次执行**，不是不同案例之间。

---

## 3. canonical 比较规则

指纹 `result_signature(result)` 由三部分组成，全部经 `_canonical_value()` 归一化：

1. `status` + 每个 check 的 `(name, ok, canonical(actual))`；
2. 每个 `metric` 的布尔值；
3. 语义块 `semantic_signature(result)`：
   - 手写签名（`live` / `answers` 提供），或
   - `generic_signature(result)`：从 `evidence` 中取 `SEMANTIC_SIGNATURE_KEYS`
     （intent/policy、tool_chain、tool_status、SQL、chart 参数、unsupported numbers、
     recovery、contract、observations、evidence、anchors、metric）+ 回答结构与引用数字。

归一化规则（必须实现）：

| 规则 | 说明 |
| --- | --- |
| 空白与大小写 | 文本按键去重空白；SQL 走 `_canonical_sql`（空白 + 标点两侧空格 + 大小写） |
| 键顺序 | dict 按 key 排序（`sort_keys=True`） |
| 时间戳 | ISO-8601（含 T/空格/时区/小数秒）→ `<ts>` |
| 随机十六进制 id | 6–40 位十六进制串 → `<id>`，**包括** 8 位会话 id |
| id 类字段 | key ∈ {`id`, `session_id`, `run_id`, `request_id`, `trace_id`} → 归一化 |
| 易变 key | `VOLATILE_SIGNATURE_KEYS`（updated_at/created_at/checkpoint_id/session_id/cost/duration_ms/duration/tokens/token_usage/started_at/finished_at/execution_id）不进签名 |
| 沙箱路径 | `/…analytics-eval-…` → `<sandbox>`；`chart-YYYYMMDD-HHMMSS-`/`report-…` → `<ts>` |
| 长文本 | 截断到固定长度，避免不稳定尾串 |
| 语义单位 | **不**归一化：单位、币种、指标名、维度名属于语义 |
| 图表 | 比较 `chart_type` + `chart_params`（x 轴 / series / unit / semantic type），不比较随机 id 与 HTML 字体格式 |

`_canonical_value` 与 `_normalize_volatile_text` 是既有函数：本批只要求**补齐 id 类归一化**，
不得把语义字段纳入归一化。

---

## 4. 允许变化与禁止变化

### 4.1 允许变化（不得误报为不稳定）

时间戳；trace/run/session id；耗时与成本；token 数；临时沙箱路径；chart/report 文件名
时间戳；JSON key 无语义顺序；SQL 空白与安全别名等价格式；长文本截断位置。

### 4.2 禁止变化（必须判定为漂移并阻断）

| # | 漂移 | 出现位置 |
| --- | --- | --- |
| 1 | intent level / mode / reason_code 改变 | `evidence.policy` |
| 2 | route / next_step 改变 | `evidence.policy` |
| 3 | required tools 改变 | `evidence.policy` / `tool_chain` |
| 4 | tool 状态改变（SUCCEEDED → FAILED_*） | `tool_status` |
| 5 | 查询范围 / filter / group by / time range 改变 | `resolved_contract` / `contract` |
| 6 | 数值结果改变 | `answer_numbers` / `reference_sql` 结果 |
| 7 | 单位或币种改变 | `contract.unit` / `contract.currency` |
| 8 | 安全拒绝变成普通查询（refusal_category 消失） | `evidence.policy` |
| 9 | 代理披露消失 | `metrics.proxy_disclosure_rate` |
| 10 | 因果限制消失 | `metrics.unsupported_causal_claim_rate` |
| 11 | forecast 假设/类型消失 | `evidence.policy.forecast_kind` |
| 12 | 一次合格、一次出现无依据数字 | `unsupported_numbers` / `unsupported_number_rate` |
| 13 | session 数据串漏 | `observations` |
| 14 | 图表语义改变（类型/x 轴/series/单位） | `chart_type` / `chart_params` |
| 15 | 回答结构（结论/证据/限制/建议段）消失 | `answer_structure` |
| 16 | evidence coverage / answer schema 改变 | `metrics` |
| 17 | check 结果改变 | `checks` |

---

## 5. 分类、查询、回答、会话与图表稳定性（逐项合同）

### 5.1 分类稳定性
固定：intent level、mode、reason_code、wants_action、wants_root_cause、forecast flags
（`wants_forecast` / `forecast_kind` / `forecast_assumption`）、refusal category、
required tools、next step。安全拒绝案例在任何重复中都必须继续拒绝，且拒绝类别一致。

### 5.2 查询稳定性
固定：查询合同（表、指标、维度、filter、group by、时间范围、币种/单位）与参考结果。
允许 SQL 文本的等价格式差异 → 比较 `_canonical_sql` 与 canonical contract，不比较字符串。

### 5.3 回答真实性稳定性
固定：unsupported number、unsupported causal claim、proxy disclosure、evidence coverage、
answer schema、结论/证据/建议分段、limitation 与假设披露（含第五批的
`FORECAST_LIMITATION_NOTE` 语义）。

### 5.4 会话稳定性
固定：多轮上下文继承、session 隔离、refresh/recovery 状态、同一 turn 不重复、
不串其他 session、安全拒绝不因重跑改变。跨会话哨兵（`cross_session_leak_rate`）必须
在重复运行中保持 0；重复运行不得让 A 会话的数字出现在 B 会话。

### 5.5 图表稳定性
固定：chart type、series、x 轴、unit、semantic type、是否应生成图表。
不比较：随机 id、HTML/CSS 逐字一致、字体与渲染细节。

---

## 6. 真实性指标与稳定性

第五批/第六批的四个指标在重复运行下必须保持：

| 指标 | 阈值 | 重复运行要求 |
| --- | --- | --- |
| `unsupported_causal_claim_rate` | `<= 0.0` | `sample_size >= 6`，两次运行同值 |
| `unsupported_causal_claim_detection_rate` | `>= 1.0` | `sample_size >= 1` |
| `proxy_disclosure_rate` | `>= 1.0` | `sample_size >= 6` |
| `proxy_disclosure_detection_rate` | `>= 1.0` | `sample_size >= 1` |
| `cross_session_leak_rate` | `= 0.0` | 重复运行不得出现泄漏 |
| `repeat_stability` | `= 1.0` | 本批新增门禁 |

稳定性报告取**第一轮**的结果作为报告主体（既有行为），重复轮只用于稳定性度量；
不得用"第二轮更好"覆盖第一轮，也不得用"第一轮更好"掩盖第二轮失败。

---

## 7. skip / not_measured 规则

| 场景 | `repeat_stability` 状态 | 门禁 |
| --- | --- | --- |
| 普通运行，未加 `--repeat` | `NOT_MEASURED` | `ok=true`（不阻断） |
| release 运行，未加 `--repeat` | `NOT_MEASURED` | `ok=false`（阻断） |
| `--repeat 1`（非法参数） | `NOT_MEASURED`（无分数） | 阻断：CLI 非零退出，不得静默降级 |
| `--repeat >= 2`，全部执行且一致 | `1.0` | PASS |
| `--repeat >= 2`，存在漂移 | `< 1.0` | FAIL（任何运行都阻断） |
| 部分案例在第二次被 skip | `agreement` 仅覆盖执行完的案例，`skipped_case_ids` 非空 | release 运行阻断 |
| 整套被跳过（live 缺凭据） | `NOT_MEASURED`，`run.status=not_measured` | 不阻断，但绝不写成 passed |

零样本**永远不得**显示为 `1.0`（`metrics[repeat_stability] is None`，
`metric_stats.measured=false`，`sample_size=0`）。

---

## 8. CI 策略

现状（缺陷）：

- `analytics-eval-release-gate`：`--suite smoke --release`（**无** `--repeat`）→ 未测量也通过。
- `analytics-eval-repeat-stability`：`--suite recorded-provider --repeat 2`（无 `--release`），
  且由于没有门禁，漂移也不会让 job 变红。

要求：

| job | 要求 |
| --- | --- |
| `analytics-eval-release-gate` | 必须带 `--repeat 2`（或等效地引用一份已测量的 repeat 报告），保留 `--release`、`allow_failure: false`、`when: manual` + tag 自动执行 |
| `analytics-eval-repeat-stability` | 保留 `--repeat 2`；满足"实测漂移在任何运行都 FAIL"后，该 job 会在漂移时让 pipeline 变红；不得加 `--no-gate` |
| 普通开发 job（smoke / regression / recorded-provider） | **不允许**加 `--repeat`（成本：570 条 × N，见下） |
| `analytics-eval-live-canary` | 保持 `when: manual`、`allow_failure: true`、不注入任何 Provider 凭据 |

成本评估：`--suite smoke --repeat 2` 约 1.4s×2；`--suite all --repeat 2`（570 条）约 12s。
因此 release 门禁选择**同时**执行 `recorded-provider --repeat 2` 与
`smoke --repeat 2 --release` 是可接受的；把 570 条放进每个普通 pipeline 不可接受。

CI 门禁不得因为 live 未运行而否定离线 release 结论（live 是独立外部条件）。

---

## 9. Red Test 对照表

文件：`tests/test_analytics_release_stability_red.py`（63 个测试方法 + 子测试）

| 组 | 数量 | 覆盖 |
| --- | --- | --- |
| `ReleaseGateTests` | 13 | 门禁存在/阈值/release-required；release 无 repeat 阻断；普通运行不阻断；`--repeat 1` 不给分；实测漂移 FAIL；第二轮 FAIL/SKIP 可见；样本覆盖；整套 skip 不阻断；零样本不得 1.0 |
| `CanonicalNoiseTests` | 12 | session/run id、时间戳、trace id、沙箱路径、SQL 空白、JSON key 顺序、耗时/成本不误报；真实 smoke/regression 必须 1.0；ISO 案例差异仅在 id |
| `SemanticDriftTests` | 25 | 17 类禁止变化逐一必须被检出；植入跨会话泄漏必须翻转稳定性；安全拒绝类别稳定；四个真实性指标在 repeat 后仍有样本且达标；detection rate 变差阻断 release |
| `CiPolicyTests` | 8 | release job 必须 `--repeat ≥2`；repeat job 不得 `--no-gate`；普通 job 不得 repeat；repeat 范围受限；live-canary 保持 manual 且无凭据；release job 不带 `--provider` |
| `GovernanceTests` | 5 | `known_gap_ratchet=0/0`；570 条 / P0 147 不变；regression 全绿且 P0 全过；repeat 不改变 pass 率 |

红测只调用真实入口：`main()`（真实 CLI，含退出码）、`measure_repeat`、
`result_signature` / `semantic_signature` / `generic_signature`、`aggregate`、
`build_report`、`evaluate_gates`、`RELEASE_REQUIRED_METRICS`，以及真实
`.gitlab-ci.yml` 解析。全部离线、确定性、无需凭据。

---

## 10. 实现验收清单

1. `evaluate_gates` 输出 `repeat_stability` 门禁（阈值 `>= 1.0`）。
2. `RELEASE_REQUIRED_METRICS` 包含 `repeat_stability`。
3. 未测量：release 运行 `ok=false`（release 阻断）；普通运行 `ok=true`。
4. 实测漂移：`ok=false`、`severity="always"`（普通运行也返回非 0）。
5. `--repeat 1` 与大 `repeat` 的 `agreement` 语义正确（`repeat<2` → `None`）。
6. 零样本不得产生 `1.0`。
7. `measure_repeat` 输出 `stable_case_ids` / `unstable_case_ids` / `skipped_case_ids`，
   `skipped` 进入 `metric_stats`。
8. 指纹归一化补齐 id 类字段（6–40 位十六进制与 `id`/`*_id` 类 key）；
   `ANA-ISO-001..005` 由不稳定变为稳定，`smoke`/`regression`/`all` 的
   `repeat_stability = 1.0`（`n = 140 / 570 / 570`）。
9. `.gitlab-ci.yml` 的 release job 带 `--repeat 2`，repeat job 保留 `--repeat 2` 且不加
   `--no-gate`，普通 job 不加 `--repeat`。
10. 四个真实性指标、`cross_session_leak_rate`、570 条与 P0 147 全部保持。
11. `--suite all --repeat 2 --release` 退出码 0，且报告中
    `repeat_stability=1.0 (n=570)`。
12. 全量 `pytest -q tests` 全绿；新红测全绿。

---

## 11. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 归一化过度，把真实漂移也抹掉 | §4.2 的 17 类禁止变化逐一有红测；归一化只针对 id/时间/路径/空白/键序 |
| repeat 让 release 变慢 | release 选择 smoke/recorded-provider（140/122 条），不是 570 条；成本见 §8 |
| 双重运行掩盖第一轮失败 | 报告主体取第一轮；重复轮只喂稳定性指标（既有行为，红测守护） |
| 把 skip 当稳定 | `skipped_case_ids` + 部分执行阻断 |
| 回滚 | 本批只改评测器与 CI；回滚 = 还原 `scripts/run_analytics_eval.py` 与 `.gitlab-ci.yml`，新测试文件可保留为 Red 用例 |

---

## 12. 治理终止条件（本批之后）

1. `known_gap_ratchet = 0/0`、`manifest.totals.known_gap = 0` 永久保持。
2. 570 条案例、P0 147 条全绿；`adversarial` / `smoke` / `recorded-provider` /
   `regression` / `all` 全绿，且 `--release` 退出码 0。
3. 四个真实性指标可测且达标；`repeat_stability = 1.0` 且样本非 0。
4. 连续缺陷治理到此收口：不再新增普通意图案例、不再重开已清零缺陷；
   后续若出现新缺陷，按"先 Spec + 红测、后实现"的同一流程逐批处理。
5. 任何新批次都必须保持本 Spec 的禁止变化清单不被削弱（红测即守护）。
