# Process360 五场景闭环实现

> 状态：V1.2 范围内代码侧已补齐；真实业务批准、宿主权限注入和 Fuxi 端到端联调仍未完成。
> 详细优化、RED/GREEN 和未完成问题见 [验收报告](process360-acceptance-2026-10-28.md)。
> 范围：SC01-SC05；S00-S08；本地 catalog + 只读业务库 + Fuxi 待办唯一执行出口

## 1. 分层

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 本地语义 catalog | `dataset/process360/ywln-v3.1/catalog.json` | 由 V3.1 Excel + V1.2 设计文档生成；运行时唯一语义来源 |
| 生成与校验 | `scripts/build_process360_catalog.py`、`bi_agent/process360/catalog.py` | 中文表名到稳定 key、SOP/场景装配、引用与重复编码校验 |
| 编排 | `bi_agent/process360/service.py` | 按 SOP 选择停止点；查询不自动升级诊断/任务；不允许调用方传 SQL |
| 确定性路由 | `bi_agent/process360/router.py` | P01-P18、SC01-SC05、所需输入、澄清项 |
| 上下文 | `bi_agent/process360/context.py` | 流程/活动/角色/规则/证据/缺口装配 |
| 只读数据库 | `bi_agent/process360/db.py` | 固定 SELECT/CTE、参数化、read-only REPEATABLE READ transaction、statement timeout |
| 受控取数 | `bi_agent/process360/queries.py` | 五场景固定语句；缺口返回 blocked/partial，不补 0 |
| 分析 | `bi_agent/process360/analysis.py` | 异常、影响、候选原因、证据缺口；候选原因不等于根因 |
| 方案/任务草稿 | `bi_agent/process360/plans.py` | 方案、任务模板、验收要求；不含手机号 |
| 执行 | `bi_agent/process360/execute.py` + `bi_agent/integrations/fuxi_todo.py` | 只发 Fuxi 待办，来源 `boulderai-anaylize-todo` |
| 复验 | `bi_agent/process360/verify.py` | 交付验收与效果验收分开；缺冻结基准/批准目标时不可关闭 |
| 身份与权限 | `bi_agent/process360/identity.py` | 宿主注入 tenant/user；权限范围与业务筛选取交集；交集为空拒绝取数 |
| 运行记录 | `bi_agent/process360/store.py` | SQLite 记录 runs/drafts/actions/executions/receipts，支持导出；不写客户 PG |
| 证据验证 | `bi_agent/process360/evidence.py` | 来源、哈希、对象、期间、规则、必需内容和反证分别校验 |
| 闭合计算 | `bi_agent/process360/closure.py` | 只使用冻结 baseline、批准目标和交付证据；样例数字不生效 |
| 多期/结构/流程/进度/预测/综合 | `bi_agent/process360/advanced.py` | P04/P05/P07/P14/P17/P18；缺数据时明确 blocked |
| 多目标与探索 | `bi_agent/process360/planner.py` | 多目标 DAG、依赖、计划版本、共享预算、探索工具白名单 |
| MCP / Skill | `bi_agent/process360/tools.py`、`bi_agent/web/mcp_endpoint.py`、`ontology-analytics-skill/SKILL.md` | Process360 工具族；`TaskOrderCreate` 仍是唯一写工具 |

## 2. 场景与取数

| 场景 | 指标 | 已实现 | 明确缺口 |
| --- | --- | --- | --- |
| SC01 发货超期治理 | M0143/M0134/M0336/M0337 | 当前快照超期余额、金额、电量、逐单清单 | 历史快照不可回填；G12/G13/G16 验收前不宣称完整闭环 |
| SC02 红区报价治理 | M36001/M0137/M36002 | 已批准报价申请数、状态分布、台账 | 报价头缺红区价格区间映射，M0137/M36002 blocked |
| SC03 战略客户突破 | M0257/M36003/M0140/M0180 | 战略客户清单、无有效商机客户数 | 缺批准计划客户全集 G03，覆盖率不可计算 |
| SC04 中标未签治理 | M0179/M0142/M36004 | 中标未签项目、金额、电量、等待天数 | G04 关联/周期仍需业务验收 |
| SC05 计划外发货偏差 | M0334/M0335/M36006 | 按订单/行/产品/日期聚合实际发货，计算明确无计划或已对齐计划的超发量与免税金额分摊 | 计划无历史快照；同一键多计划版本时 blocked；RF09 目标为空 |

关键口径：

- 超期：`DATE(requestdeliveryby) < LEAST(as_of, CURRENT_DATE)`；到期当天不算超期，空值不归正常/超期。
- 计划记录按订单 + 行号 + 产品 + 计划日期 + 月度计划键去重，取当前最新版本。
- SC05 未匹配、未知标记/对齐状态、无可靠行映射不分类，不作为计划外分子；分类不完整或多计划歧义时 blocked，正式指标为 null。
- SC02 报价状态 `3` 为审核通过；红区必须依赖价格区间映射，当前不可用。
- SC04 取每个项目最新投标版本，排除弃标、未公布结果和已有有效正式订单的记录。

## 3. 状态契约

所有阶段返回统一 envelope：

```text
schema=process360.result.v1
stage=S00..S07
status=ok | partial | blocked | needs_clarification | not_applicable
metrics[] / records[] / evidence[] / gaps[] / limitations[] / nextSteps[]
```

`blocked` 与 `partial` 必须原样交付；禁止把不可评估的指标改成 0，也禁止用当前余额
回填历史。`candidateCauses` 只表示待证据验证的候选原因。

## 4. 执行边界

```text
S05 Process360Draft.canvasActions[]
  → CanvasGenerate kind=actions（只带草稿引用和展示字段）
  → 用户在 Fuxi HTML 点击“发送任务令”
  → Fuxi 宿主补 principal + recipients_raw（当前用户/责任人手机号）
  → TaskOrderCreate
  → 服务端回读草稿、校验租户/用户/hash/审批/canDispatch
  → 单个 actionId 一次性消费，persistent idempotency key
  → Fuxi POST /source/todo-batches（source=boulderai-anaylize-todo）
  → Fuxi 待办侧承接业务处理
```

- 建议卡只携带 `draftId/draftHash/runId/actionId/scenario/approvalStatus/expiresAt/
  dispatchTool`。`CanvasGenerate` 拒绝行动条目中出现手机号字段或 11 位手机号文本。
- `approvalStatus` 不是 `approved` / `host_click_authorized` 时按钮显示“待审批”并禁用；
  过期草稿点击时要求重新生成。服务端仍会二次校验，前端不能绕过。
- 标题、正文、场景、严重程度、期限、责任人从服务端草稿回读，调用方不能改写。
- Fuxi 契约只有批量推送和状态事件，没有单条查询或执行进度接口。字段名固定为
  `sourceTodoId/title/severity/itemType/category/sourceStatus/sourceUpdatedAt/
  recipientsRaw/dueAt/description/impactText/ownerRef/ownerName/evidence/activity/
  caliberMeta`，不改名、不补造。
- 网络失败可用同一 `idempotency_key` 和 `retry=true` 重试；已成功回执重放不重复创建。
- 不调用 X360 任务令，不发送 Fuxi IM，不伪造发运/签单/排产写操作。
- S07 只能使用冻结 run、批准目标和交付证据；上游口头完成或本地 RF 样例不能关闭。

## 5. 配置

```bash
PROCESS360_PG_ENABLED=1
PROCESS360_PG_HOST=<read-only host>
PROCESS360_PG_PORT=5432
PROCESS360_PG_DATABASE=<database>
PROCESS360_PG_USER=<read-only user>
PROCESS360_PG_PASSWORD=<secret>
PROCESS360_PG_SCHEMA=ywln_crm
PROCESS360_PG_STATEMENT_TIMEOUT_MS=15000
# 可选：catalog 不在 <cwd>/dataset 下时指定绝对/相对路径
PROCESS360_CATALOG_PATH=
```

`web` extras 增加 `psycopg[binary]>=3.1`。未安装驱动或未配置连接时，
`Process360Query` 返回 `blocked` + `DATABASE_UNAVAILABLE`，不会回退到 mock 或伪数据。

## 6. 数据库与 catalog 的关系

- `ywln_crm` 是业务事实来源，只读。
- `ywln_crm.meta_*` 存在本体元数据，但当前版本不覆盖、不写入本地 catalog；
  只允许在后续做差异核对。
- catalog 冻结来源 SHA 记录在 `dataset/process360/ywln-v3.1/catalog.json` 的
  `source` 字段；原始 `.xlsx/.docx` 不入仓。

## 7. 已支持筛选与停止点

| 场景 | 已落 SQL 的维度 |
| --- | --- |
| SC01 | 客户、负责人、产品 |
| SC02 | 客户、负责人 |
| SC03 | 客户 |
| SC04 | 客户 |
| SC05 | 客户、产品 |

未支持的筛选在访问数据库前返回 `needs_clarification`，不静默扩大范围。
SC01/03/04 当前存量不回填历史；显式当前快照调整实际观察日并保留请求范围。
SC05 历史对账缺计划快照返回 blocked。当期分类仍需业务验收。

P03 问数到 S03 停止；P06/P08/P09 分析到 S04 停止；明确要求 P11 才生成草稿。
P01/P02 使用检索/上下文，P12 使用宿主点击下发，P15 使用专用复验工具。

| 能力 | 工具 | 已实现 | 停止条件 |
| --- | --- | --- | --- |
| P04 多期比较 | `Process360Compare` | 同一场景、范围、对象集合的 2-12 期比较 | 期间交集/口径不一致时 blocked |
| P05 结构排名 | `Process360Structure` | 已映射维度汇总、排名、占比、未知维度单列 | 维度未映射时 needs_clarification |
| P07 流程转化 | `Process360ProcessFlow` | 按 objectKey/batchKey 计算节点转化和停留 | 缺阶段轨迹时 blocked，不用节点总数相除 |
| P14 任务进度 | `Process360Progress` | 本服务 execution + Fuxi 推送回执 | Fuxi 未回传处理状态时只报告“已推送” |
| P17 条件预测 | `Process360Forecast` | 显式假设下的规则推算、区间和敏感性 | 无实际值/目标/进度/假设时 blocked |
| P18 综合编排 | `Process360Solutions` | 多子目标独立验收、汇总缺口 | 任一子目标 blocked 时整体不得称完成 |
| S08 自主探索 | `Process360Explore` | 服务端工具白名单、调用哈希去重、共享预算 | 越权工具/预算耗尽/无效 path 时停止并回原步骤 |
| 方案比较 | `Process360Solutions` | 结构、约束、适用条件校验 | 缺成本/周期/效果依据时不做量化评分 |

## 8. 测试

```bash
pytest -q tests/test_process360_*.py tests/test_fuxi_todo_actions.py tests/test_mcp_endpoint_red.py
```

已覆盖：catalog 生成结果/引用/重复编码、五场景 bundle、P01-P18、双入口检索、
路由、范围校验、历史快照阻断、五场景取数、候选原因、任务草稿、手机号保护、
只读 SQL 校验、MCP 工具暴露、身份交集、证据验证、冻结基准、单条行动消费、
持久化幂等、回执、P04/P05/P07/P14/P17/P18、多目标 DAG、探索白名单。
9 项 PostgreSQL 合约测试需显式设置 `PROCESS360_ACCEPTANCE_DSN`，不同步执行。
