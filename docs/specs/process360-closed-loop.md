# Process360 五场景闭环实现

> 状态：v0.1.6 功能分支实现说明（2026-10-27）
> 范围：SC01-SC05；S00-S07；本地 catalog + 只读业务库 + Fuxi 待办唯一执行出口

## 1. 分层

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 本地语义 catalog | `dataset/process360/ywln-v3.1/catalog.json` | 由 V3.1 Excel + V1.2 设计文档生成；运行时唯一语义来源 |
| 生成与校验 | `scripts/build_process360_catalog.py`、`bi_agent/process360/catalog.py` | 中文表名到稳定 key、SOP/场景装配、引用与重复编码校验 |
| 编排 | `bi_agent/process360/service.py` | S00 → S04 → S05 → S07；不允许调用方传 SQL |
| 确定性路由 | `bi_agent/process360/router.py` | P01-P18、SC01-SC05、所需输入、澄清项 |
| 上下文 | `bi_agent/process360/context.py` | 流程/活动/角色/规则/证据/缺口装配 |
| 只读数据库 | `bi_agent/process360/db.py` | 固定 SELECT/CTE、参数化、read-only transaction、statement timeout |
| 受控取数 | `bi_agent/process360/queries.py` | 五场景固定语句；缺口返回 blocked/partial，不补 0 |
| 分析 | `bi_agent/process360/analysis.py` | 异常、影响、候选原因、证据缺口；候选原因不等于根因 |
| 方案/任务草稿 | `bi_agent/process360/plans.py` | 方案、任务模板、验收要求；不含手机号 |
| 执行 | `bi_agent/process360/execute.py` + `bi_agent/integrations/fuxi_todo.py` | 只发 Fuxi 待办，来源 `boulderai-anaylize-todo` |
| 复验 | `bi_agent/process360/verify.py` | 交付验收与效果验收分开；缺基准/RF 目标时不可关闭 |
| MCP / Skill | `bi_agent/process360/tools.py`、`bi_agent/web/mcp_endpoint.py`、`ontology-analytics-skill/SKILL.md` | 七个只读工具；`TaskOrderCreate` 仍是唯一写工具 |

## 2. 场景与取数

| 场景 | 指标 | 已实现 | 明确缺口 |
| --- | --- | --- | --- |
| SC01 发货超期治理 | M0143/M0134/M0336/M0337 | 当前快照超期余额、金额、电量、逐单清单 | 历史快照不可回填；G12/G13/G16 验收前不宣称完整闭环 |
| SC02 红区报价治理 | M36001/M0137/M36002 | 已批准报价申请数、状态分布、台账 | 报价头缺红区价格区间映射，M0137/M36002 blocked |
| SC03 战略客户突破 | M0257/M36003/M0140/M0180 | 战略客户清单、无有效商机客户数 | 缺批准计划客户全集 G03，覆盖率不可计算 |
| SC04 中标未签治理 | M0179/M0142/M36004 | 中标未签项目、金额、电量、等待天数 | G04 关联/周期仍需业务验收 |
| SC05 计划外发货偏差 | M0334/M0335/M36006 | 实际发货、计划匹配、未匹配候选、占比 | 计划无历史快照；同一键多计划版本时 blocked；RF09 目标为空 |

关键口径：

- 超期：`DATE(requestdeliveryby) < LEAST(as_of, CURRENT_DATE)`；到期当天不算超期，空值不归正常/超期。
- 计划记录按订单 + 行号 + 产品 + 计划日期 + 月度计划键去重，取当前最新版本。
- SC05 未匹配记录只称“待核查候选”，不认定计划外违规；匹配歧义时整场景 blocked。
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
S05 Process360Draft.tasks[]
  → 用户在 Fuxi HTML 点击“发送任务令”
  → Fuxi 宿主携带 recipients_raw（当前用户/责任人手机号）
  → TaskOrderCreate（source=boulderai-anaylize-todo）
  → Fuxi 待办侧承接业务处理
```

- 手机号不进入 HTML、日志、catalog 或模型提示；由宿主点击时提供。
- 不调用 X360 任务令，不发送 Fuxi IM，不伪造发运/签单/排产写操作。
- `TaskOrderCreate` 使用 `sourceTodoId` 保证重复点击幂等。

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

## 7. 测试

```bash
pytest -q tests/test_process360_catalog.py tests/test_process360_engine.py
pytest -q tests/test_fuxi_todo_actions.py tests/test_mcp_endpoint_red.py
```

已覆盖：catalog 生成结果/引用/重复编码、五场景 bundle、P01-P18、双入口检索、
路由、范围校验、历史快照阻断、五场景取数、候选原因、任务草稿、手机号保护、
只读 SQL 校验、MCP 工具暴露、复验阻断。
