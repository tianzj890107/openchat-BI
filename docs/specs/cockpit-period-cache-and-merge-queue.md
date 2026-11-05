# 看板分析按期间缓存与合并队列（第一阶段）

日期：2026-11-05
状态：实现中
范围：`bi_agent/cockpit/{periods,store,page_cache,refresh}.py`

## 1. 背景

当前刷新链路把「数据变化」和「需要重新分析」绑定得过紧：

- 整页任一查询结果变化，`RefreshManager.refresh()` 会遍历整页所有已保存环节重新分析。
- 每个作用域刷新完成后一律 `next_check = now + interval`，历史期间也会被反复取数和重算。
- 运行中的任务再次被请求时，`Store.request_refresh()` 直接丢弃请求（返回 `False`），
  数据变化可能被永久错过，无法表达「先算完这版，再补最新一版」。

客户场景中年度/月度期间数量有限，分析应按期间预计算并长期复用，只有当前期间需要持续维护。

## 2. 目标

1. 分析按「期间 × 环节」维护：历史期间分析一次后冻结，当前期间按间隔更新，上一期间在宽限期内继续更新。
2. 同一作用域同时最多一个运行任务，额外变化只保留一个「待更新」标记，且以最新一次为准。
3. 整页刷新时按环节判断证据变化，只重新分析变化的环节；未变化环节沿用原分析，页面仍可发布。
4. 刷新失败保留上次成功发布会话，不清空卡片。

非目标（第二阶段）：风险/原因/建议的稳定标识与增量维护。

## 3. 期间口径

### 3.1 当前期间与运行模式

`COCKPIT_PERIOD_MODE` 决定正常维护哪个期间：

| 模式 | 当前期间来源 |
|---|---|
| `live`（默认） | 客户业务时区（`COCKPIT_BUSINESS_TIMEZONE`，默认 `Asia/Shanghai`）下的系统年月 |
| `backfill` | 必须显式配置 `COCKPIT_ACTIVE_PERIOD`；为空时退回交付默认值 |

`COCKPIT_ACTIVE_PERIOD` 在两种模式下都优先。页面默认选中的月份**不再**隐式决定服务端长期
维护哪个期间；演示或补数回填必须显式写 `COCKPIT_PERIOD_MODE=backfill` 与
`COCKPIT_ACTIVE_PERIOD=YYYY-MM`（否则 live 模式会把 2025-10 判为历史并冻结）。

上一期间同时包含月份与年度边界：1 月时上一期间是「去年 12 月」和「去年」，二者分别维护。

### 3.2 作用域期间

`periods.period_state(ui_scope, fallback)` 返回 `{period, periodType, source}`：

- 先看最后一次 `setButtonGrainSelection`：`YEAR` 选年度、`MONTH` 选月度；
- 在该粒度下取最后一个匹配值（`YYYY` 或 `YYYY-MM`），残留的旧月份不会覆盖新的年度选择；
- `uiScope == 'default'` 或解析不出日期时退回 `fallback`（分析上下文里的 `period`）。

`period_of_scope()` 只是取其中的 `period`。

### 3.3 刷新策略

| 期间 | 判定 | 重算间隔 |
|---|---|---|
| 当前期间 | 与当前期间相同 | `COCKPIT_REFRESH_INTERVAL_SECONDS`（默认 900 秒） |
| 上一期间 | `previous_periods()` 中的期间（跨年含上一年度），且当月日期 ≤ `COCKPIT_PERIOD_GRACE_DAYS`（默认 7，读环境变量） | 同当前期间 |
| 上一期间（超出宽限期） | 同上 | 冻结 |
| 更早期间 | 早于当前期间 | 冻结（`COCKPIT_HISTORY_REFRESH_ENABLED=1` 时改为按天刷新） |
| 未来期间 | 晚于当前期间 | 冻结 |
| 未知 | 解析不出期间 | 按当前期间处理（保持现有行为） |

冻结语义：写入 `status='frozen'`、`next_check=0`，`due_refresh_scopes()` 不再返回该行；
已发布结果继续可读，不删除任何历史。

## 4. 合并队列

`page_refresh` 增加 `pending` / `pending_since`：

- 运行中收到新的刷新请求：设置 `pending=1`、`pending_since=now`，不新开任务；
- 重复请求只更新时间，不产生多条待处理任务；
- 运行结束（成功或失败）时若 `pending=1`：清除标记、状态 `waiting`，但**不得**绕过
  `COCKPIT_REFRESH_MIN_RECHECK_SECONDS`（默认 60 秒）：成功时排到 `now + 最小间隔`，
  失败时取 `max(本次退避时间, now + 最小间隔)`；`frozen` 状态不会被 pending 解冻；
- `request_refresh()` 仅在真正新排入任务时返回 `True`；运行中的请求只记录 pending，
  返回 `False`，调用方据 `refresh_queue_stats()['pendingCount']` 观测合并数量；
- 队列统计输出 `pendingCount`，便于观测被合并的任务量。

## 4.1 期间发布索引

`period_publications` 保存「权限范围 + 期间 + 节点 + 规范化筛选 + 定义版本 → 当前分析 ID（含 view_key）」：

- `view_scope()` 纳入 `period` 与 `filters` 摘要，不同月份不再共享同一个 view key；
- 页面发布、单卡刷新、期间预热都写同一条索引；
- 覆盖率统计只读该索引，因此 2025-09 与 2025-10 可同时被识别；
- `publication_views` 继续只指向最近一次发布，默认卡片入口不会被其他月份的预热覆盖。

## 5. 按环节独立刷新

`page_cache.stage_evidence(records)` 按 `filter_stage_selected()` 把整页证据拆到各环节，
返回 `{stage: {'fingerprint': str, 'queries': [str]}}`。某环节没有匹配证据时不出现在结果中。

`RefreshManager.refresh()`：

1. 计算整页指纹与各环节指纹；
2. 环节已有分析且 `context.dataFingerprint` 等于该环节指纹、`chartQueries` 等于该环节查询集合时，
   沿用原分析，不调用模型；
3. 其余环节重新分析；
4. 组装整页发布。

每个环节分析在 `analysis_stage_evidence` 中固定保存自己的证据指纹与查询集合；
`build_page()` 按该环节自己的记录校验，不再接受「上一轮整页指纹」。历史分析（只有整页指纹）
在首次刷新且证据未变化时补写一次环节记录（不调用模型、不改变分析 ID）。HTTP 路径新建的分析
仍按当轮整页口径校验。

## 5.1 期间目录预热

`COCKPIT_PREHEAT_PERIODS`（逗号分隔，如 `2025,2025-01,2025-02`）声明需要长期保温的期间目录；
为空表示不额外预热（当前期间仍由常规 preheat 目标维护）。

- 调度为每个「期间 × 角色 × 环节」登记目标，缺少发布结果的目标进入低优先级排队，已发布的按常规
  节奏维护并冻结历史期间；
- 期间目标优先复用该期间已存在的查询计划；没有时按真实 AP 协议生成：
  取组件查询模板（交付配置或快照），把日期维度 `YWLN_D044` 的条件改写为
  `{"operator":{"code":"BETWEEN","type":"DATE"},"valueType":"ABSOLUTE","value":[开始日, 结束日]}`；
  月度取当月首末日、年度取 1-1 至 12-31。**模板里没有日期维度时直接丢弃**，
  绝不把无期间条件的查询当成某个月的结果；全部被丢弃时写入 `awaiting-plan`；
- 已处于 `retry_wait` / `awaiting-plan` 的目标不会被注册流程改写执行时间；
- `GET /api/cockpit/publications/period-coverage?periods=2025-10,2025-09` 返回
  `total / ready / missing` 与逐条状态。

## 6. 可观测

`publication_status()['update']` 增加：

- `period`：本次作用域解析出的期间；
- `periodPolicy`：`{kind, recheckAfter, graceDays, activePeriod}`；
- `queue.pendingCount`：被合并的待更新任务数。

## 7. 验收用例

见 `tests/test_cockpit_period_refresh.py`：

1. 当前期间按间隔刷新；
2. 上一期间宽限期内刷新、宽限期外冻结；
3. 历史期间冻结且不再进入 due 队列；
4. 未知期间保持原间隔（不改变既有行为）；
5. `period_of_scope` 能从 `default`、月份、年度、中文月份中取到期间；
6. 运行中重复请求只保留一个 pending；
7. 多次 pending 以最新时间为准；
8. 完成后存在 pending 时立即重排；
9. 整页刷新只重算证据变化的环节；
10. 未变化环节沿用原分析且整页仍能发布；
11. 刷新失败保留上次发布版本并记录错误；
12. 冻结作用域仍能读到上次发布结果。
