# 看板分析按期间缓存与合并队列（第一阶段）

日期：2026-11-05
状态：第一阶段已实现；客户 AP 与线上期间切换仍待部署验收
范围：`bi_agent/cockpit/{periods,store,page_cache,refresh,router,targets}.py`

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

`scope_is_period(ui_scope)` 只接受日期/年度月度粒度变更。包含客户、产品部等业务筛选的
范围不会读取期间默认卡片，避免把未筛选的期间分析误当成当前筛选结果。

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
- AI 插槽、表格分析字段和发布状态按同一规则读取：UI 范围只含期间时，先用
  `period_state()` 解析生效期间，再查精确期间索引；精确命中时返回该期间分析并标记
  `periodMatch=true`，未命中才回退最近默认卡片并保留 `scopeMatch=false`；
- `default`、空范围以及不带日期的月度粒度不是「无期间」：统一解析为交付默认期间
  （`YWLN_D044` 默认月份，缺失时才用当前业务期间），再查该期间的精确索引。后台补齐
  历史月份的顺序不能改变默认页面的分析 ID；只有其他月份可展示时，回退卡片必须保留
  `scopeMatch=false`，不能伪装成默认期间命中；
- 命中精确期间时，刷新状态只聚合该期间、节点对应的期间任务；当前月任务和通用默认预热
  任务不参与该卡片状态。未来才执行的 `waiting` 归类为 `scheduled`，不计为正在更新；
- 覆盖率统计只读该索引，并按当前定义版本、当前数据身份和可交付分析校验；因此
  2025-09 与 2025-10 可同时被识别，配置轮换后的旧索引保留为历史但不计为 ready；
- `publication_views` 继续只指向最近一次发布，默认卡片入口不会被其他月份的预热覆盖。

## 4.2 分析库存与双节拍

`analysis_inventory` 持久保存每个刷新范围当前可交付的分析库存：

- 身份、页面、环节、期间、筛选摘要和定义版本对应的刷新 `scope`；
- 当前结果 ID、结果类型（整页发布或环节分析）、证据指纹；
- 分析依据数据时间 `data_as_of`、最近检查数据时间 `latest_data_as_of`；
- 分析时间 `analyzed_at`、最近检查时间、最近变化时间；
- 当前待处理指纹与数据时间、首次待处理时间 `pending_since`；
- 下次允许模型分析时间 `next_analysis_at` 和状态。

数据检查仍按 `COCKPIT_REFRESH_INTERVAL_SECONDS`（默认 900 秒）执行；
模型分析由 `COCKPIT_ANALYSIS_MIN_INTERVAL_SECONDS`（默认 1800 秒）限制。
`COCKPIT_ANALYSIS_COALESCE_SECONDS`（默认 300 秒）合并短时间内的连续变化。
连续变化不会不断推迟分析：`pending_since` 保留第一次未处理变化的时间，
`next_analysis_at = max(上次分析时间 + 最小分析间隔, 首次待处理时间 + 合并窗口)`。

同一范围正在运行时仍由一个 `pending` 标记合并请求；分析库存只保留最新待处理指纹。
完成后先发布本轮固定证据，再按最小间隔处理最新版本。失败重试由刷新退避控制，
不会被最小分析间隔额外阻塞。历史期间仍按期间策略冻结。

`GET /api/cockpit/publications/status` 增加 `analysisPolicy` 与 `analysisInventory`，
用于确认当前结果的分析时间、最新数据时间、待处理状态和下次允许分析时间。

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

`COCKPIT_PREHEAT_PERIODS`（逗号分隔，如 `2025,2025-01,2025-02`）声明额外的历史期间目录。
有效目录始终先包含当前业务月份及其年度；处于宽限期的上月/上一年度会自动加入，再合并显式配置。
跨月无需修改环境变量或先打开页面。

- 调度为每个「期间 × 角色 × 环节」登记目标，缺少发布结果的目标进入低优先级排队，已发布的按常规
  节奏维护并冻结历史期间；
- 期间目标优先复用该期间已存在的查询计划；没有时按真实 AP 协议生成：
  取组件查询模板（交付配置或快照），把日期维度 `YWLN_D044` 的条件改写为
  `{"operator":{"code":"BETWEEN","type":"DATE"},"valueType":"ABSOLUTE","value":[开始日, 结束日]}`；
  月度取当月首末日、年度取 1-1 至 12-31。组件模板本身不带期间条件时，按同一协议把
  `YWLN_D044` 条件补进 `commonConfig.filters.children`；只有连 `commonConfig` 都不存在的
  载荷才丢弃，全部不可用时写入 `awaiting-plan`，绝不把无期间条件的查询当成某个月的结果；
- 根筛选为 `OR` 时，用新的 `AND` 根节点包裹原筛选与期间条件，保留原筛选子树；已有
  `YWLN_D044` 条件的操作符必须是 `BETWEEN` / `DATE` / `ABSOLUTE`，其他操作符直接拒绝该模板，
  不改写日期值猜测口径；
- 已处于 `retry_wait` / `awaiting-plan` 的目标不会被注册流程改写执行时间；
- 期间预热属于低优先级任务，不会挤占已经到期、用户可打开的页面或单卡维护；
- `GET /api/cockpit/publications/period-coverage?periods=2025-10,2025-09` 返回
  `total / ready / missing` 与逐条状态。

## 6. 可观测

`publication_status()` 增加：

- `period`：本次作用域解析出的期间；
- `periodPolicy`：`{kind, recheckAfter, graceDays, activePeriod}`；
- `analysisPolicy`：`{minIntervalSeconds, coalesceSeconds}`；
- `analysisInventory`：当前结果、数据时间、待处理版本和下次分析时间；
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
12. 冻结作用域仍能读到上次发布结果；
13. 最近已分析过的范围收到变化时只记录一个最新待分析版本，不调用模型；
14. 达到最小分析间隔后才重算，并更新持久化分析库存。

第三轮补强用例另覆盖：两个年度/三个月度与五节点在重启后逐期间读取；日期范围精确命中时
AI 插槽、表格字段和状态接口返回同一分析；配置轮换后旧期间不计 ready；期间目录自动包含
当前年月与宽限期上月；OR 筛选包裹和非法日期操作符拒绝。
