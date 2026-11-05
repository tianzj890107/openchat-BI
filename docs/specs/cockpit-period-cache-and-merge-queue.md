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

### 3.1 当前期间

按以下顺序确定「当前期间」：

1. 环境变量 `COCKPIT_ACTIVE_PERIOD`（如 `2026-11` 或 `2026`）；
2. 交付元数据 `runtime.json` 中日期筛选组件默认值（`YWLN_D044`）；
3. 系统当月。

当前期间是刷新基准，不是系统时间：客户数据仍停留在 2025-10 时，默认作用域必须继续按间隔
刷新，不能因为系统日期更晚而被判为历史。

### 3.2 作用域期间

`periods.period_of_scope(ui_scope, fallback)`：

- `uiScope == 'default'` 或无法解析出日期时，使用 `fallback`（分析上下文里的 `period`）；
- 否则从 `uiScope` 字符串中提取 `YYYY-MM` / `YYYY年M月` / 纯 `YYYY`，优先取最后一个匹配项
  （对应最近一次筛选提交）。

### 3.3 刷新策略

| 期间 | 判定 | 重算间隔 |
|---|---|---|
| 当前期间 | 与当前期间相同 | `COCKPIT_REFRESH_INTERVAL_SECONDS`（默认 900 秒） |
| 上一期间 | 同粒度下紧邻当前期间，且当月日期 ≤ `COCKPIT_PERIOD_GRACE_DAYS`（默认 7） | 同当前期间 |
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
- 运行结束（成功或失败）时若 `pending=1`：清除标记，`next_check=now`，状态 `waiting`，
  让最新数据紧接着处理一次；
- `request_refresh()` 仅在真正新排入任务时返回 `True`；运行中的请求只记录 pending，
  返回 `False`，调用方据 `refresh_queue_stats()['pendingCount']` 观测合并数量；
- 队列统计输出 `pendingCount`，便于观测被合并的任务量。

## 5. 按环节独立刷新

`page_cache.stage_evidence(records)` 按 `filter_stage_selected()` 把整页证据拆到各环节，
返回 `{stage: {'fingerprint': str, 'queries': [str]}}`。某环节没有匹配证据时不出现在结果中。

`RefreshManager.refresh()`：

1. 计算整页指纹与各环节指纹；
2. 环节已有分析且 `context.dataFingerprint` 等于该环节指纹、`chartQueries` 等于该环节查询集合时，
   沿用原分析，不调用模型；
3. 其余环节重新分析；
4. 组装整页发布。

`build_page()` 校验放宽为：环节分析的数据指纹/查询集合必须等于「整页口径」**或**「该环节口径」，
避免沿用未变化环节时整页发布被拒。HTTP 路径仍按整页口径提交，行为不变。

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
