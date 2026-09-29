# 实现提示词：X360 流程定义接口接入（X360 第一批：只读客户端 + 转督办换真）

> 把下面整段交给实现人员（人或 Agent）。本批**只做只读接入**：新增 X360 客户端，把
> "行动 → 转督办"的流程定义 ID 与责任人从硬编码关键词表换成 X360 实时数据。
> 不改分析策略、Prompt、评测集、模型工具白名单，不加 known gap。

---

## 0. 你的任务

"行动 → 转督办"当前把用户文本按 **14 条硬编码关键词** 映射成一个数字 ID
（`bi_agent/web/app.py` 的 `TASK_ALERT_BP_KEYWORDS` / `_match_task_alert_bp_definition`）。
其中 4 条在 X360 文档给出的流程定义里查无实据（`履约单`、`线索`、`项目`、`合同`），
`履约单` 在文档里还是 `订单` 活动下的**任务**；责任人则永远是环境变量
`TASK_ALERT_DEFAULT_ASSIGNEE=400`，与流程定义无关。

X360 已经提供了 AI 视图接口（`API/X360提供给AI的接口.md` 的两个 GET）。请：

1. 新增只读客户端 `bi_agent/x360/client.py`；
2. 在 `bi_agent/web/app.py` 新增 `_resolve_task_alert_target(text)`，
   用 X360 数据解析出流程定义 ID / 活动 / 责任人；
3. 让 `task_alert_manual_create` 用解析结果发上游请求，并在响应里**如实**暴露来源；
4. 配置、部署与接口文档同步。

**不要**只把"履约单 / 线索 / 项目 / 合同"这四个词换成另一批硬编码 ID——那就没修。

## 1. 先读

1. `docs/specs/x360-process-definition-integration.md`（本批 Spec，逐节读完，§5 与 §8 是重点）
2. `tests/test_x360_process_definition_red.py`（红测 = 验收标准）
3. `API/X360提供给AI的接口.md`（对外契约：两个 path、两级 ID、`responsiblePerson`、`tasks[]`）
4. 生产代码：
   - `bi_agent/web/app.py`：`TASK_ALERT_BP_KEYWORDS`、`_match_task_alert_bp_definition`、
     `_task_alert_enabled`、`_task_alert_timeout`、`_parse_task_alert_response`、
     `TaskAlertCreateRequest`、`task_alert_manual_create`、`_task_alert_successes/_inflight/_lock`
   - `bi_agent/ontology/remote.py`（`_request` 的鉴权头写法，168-176 行）
   - `bi_agent/tools/sql_tools.py`（`DorisHttpConn` 的鉴权头写法，184-195 行）
5. 配置与文档：`.env.example`、`DEPLOYMENT.md`（448-475 行）、
   `API/智能分析Agent前端API.md`（§11）、`API/系统接口调用与代码统计.md`（208-211 行）
6. 既有门禁：`tests/test_regressions.py::TaskAlertProxyTests`（20 条）、
   `tests/test_docker_defaults_and_local_secrets.py`、`tests/test_literal_ip_server_references.py`

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_x360_process_definition_red.py
```

当前实测 **32 failed / 3 passed**（35 条）。失败分布：

| 原因 | 条数 | 缺什么 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'bi_agent.x360'` | 19 | 只读客户端 |
| `尚未实现 bi_agent.web.app._resolve_task_alert_target` | 9 | 转督办解析函数 |
| `KeyError: 'source'` | 3 | 端点响应新增字段 |
| `2081949636213985282 != 2081949112647405570` | 1 | 上游收到的是活动 ID 而不是流程定义 ID |

**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。
那 3 条现在就是绿的用例（`test_endpoint_does_not_call_x360_when_disabled`、
`test_endpoint_response_never_contains_token`、
`test_endpoint_still_reports_upstream_failure_honestly`）是**护栏**，不许删、不许改弱。

先跑既有基线，确认你没接坏东西：

```bash
.venv/bin/python -m pytest -q tests/test_regressions.py -k TaskAlert      # 20 passed
```

## 3. 实现要求

### 3.1 只读客户端（`bi_agent/x360/client.py`）

* 公开符号：`X360ApiError`、`X360Activity`、`X360ProcessDefinition`、
  `X360ProcessDefinitionClient`（`from_env` / `fetch_by_key` / `fetch_by_id` / `match_activity`）。
* 路径逐字按文档：`/api/gateway2/x360/v1/process-definitions/ai/key/{key}` 与
  `/api/gateway2/x360/v1/process-definitions/ai/{id}`；**只有 GET**，无请求体。
* 归一化：`data.id/code/name` + `activities[].id/name/code/responsiblePerson/tasks[]`，
  任务保留 `id/name/code/description`；ID 一律字符串，禁止 int 化。
* 匹配分级（长名优先，第一级命中即返回）：活动 `name` → 活动 `code`（大小写不敏感、
  ASCII 词边界）→ 任务 `name`（返回**父活动**）→ 任务 `code`（返回父活动）；
  都不命中返回 `None`。不要引入同义词表或模糊匹配。
* `from_env()` 在配置缺失时返回"未启用"客户端，**不抛异常**（配置缺失是常态）。
* 缓存：`(base_url, selector)` → 解析结果，TTL `X360_CACHE_TTL_SECONDS`（0 = 回源），
  加锁；失败不缓存；失败后进入 `X360_FAILURE_COOLDOWN_SECONDS` 冷却（默认 30），
  冷却期内直接回退（避免用户点一次转督办等满超时）。环境变化必须重建客户端实例。
* 鉴权（文档没写，按仓库既有约定）：`X-App-Id`（`X360_APP_ID`，回退 `ONTOLOGY_APP_ID`）；
  `X360_AUTH_TOKEN` 非空时发 `Authorization`，已以 `bearer` 开头则原样透传，否则加
  `Bearer ` 前缀，为空则不发该头。
* 错误：HTTP ≠ 2xx / `success:false` / 非 JSON / 超时 / 结构非法 → `X360ApiError`，
  消息只写"接口用途 + 失败类别 + 上游 message（截断）"，
  **不得**包含 token、`X360_BASE_URL` 全文或 host。

### 3.2 解析函数（`bi_agent/web/app.py::_resolve_task_alert_target`）

返回 `{"bpDefinitionId": int|None, "activityId": str|None, "activityName": str|None,
"assignee": str|None, "source": str}`，严格实现 Spec §5.8 的 7 行真值表：

* `source ∈ {x360, static_fallback, default, request}`；
* `request`：请求体已带 `bpDefinitionId` → 原样优先，**不再请求 X360**，也不动 `assignee`；
* `x360`：命中活动 → `bpDefinitionId` 按 `X360_BP_ID_LEVEL`（默认 `process_definition`
  取 `data.id`；`activity` 取活动 ID），`activityId`/`activityName` 恒有值，
  `assignee` 取该活动 `responsiblePerson`（空才回落环境默认）；
* `static_fallback`：X360 关闭/未配置/未命中/任何失败 → 走**遗留关键词表**，
  并把 `source` 标成 `static_fallback`（命中）或 `default`（未命中）；
* 非 `x360` 来源时 `activityId`/`activityName` 必须是 `None`（不许把关键词猜成活动名）；
* 任何分支都不许"造"一个 ID：只允许 入参 / X360 / 遗留表 三个来源。

### 3.3 端点接线（`task_alert_manual_create`）

* 先解析**一次**，同一个结果用于日志与请求体（禁止解析两次）；
* 请求体字段集不变（`title`/`content`/`assignee`/`level`/`bpDefinitionId`）；
  `bpDefinitionId` 为 `None` 时不带该字段（沿用今天的行为）；
* 响应新增 `source`、`activityName`、`bpDefinitionId`，保留 `ok`/`taskId`/`clientRequestId`；
* 既有行为一条都不能变：422（title/content/level/bpDefinitionId 校验）、409（并发提交）、
  502/504（上游失败，且失败不缓存）、`clientRequestId` 成功缓存。
* 日志记录 `source`/`activityName`/`bpDefinitionId`（不带 token/host）。

### 3.4 配置与文档

按 Spec §6 的落位表：

* `.env.example`：新增 `X360_ENABLED`、`X360_BASE_URL`（空）、`X360_PROCESS_DEFINITION_KEY`（空）、
  `X360_PROCESS_DEFINITION_ID`（空）、`X360_APP_ID`、`X360_AUTH_TOKEN`（空）、
  `X360_TIMEOUT_SECONDS`、`X360_CACHE_TTL_SECONDS`、`X360_BP_ID_LEVEL`、
  `X360_FAILURE_COOLDOWN_SECONDS`，并注释"默认按 API 文档取流程定义 ID；
  上游确认前生产保持现状时改为 `activity`"；
* `tests/test_docker_defaults_and_local_secrets.py`：非密键进 `BASELINE_LOCAL_ENV_KEYS`（值进
  `NON_SECRET_DEFAULTS`），`X360_AUTH_TOKEN` 进 `RUNTIME_SECRET_KEYS`，
  `X360_BASE_URL` 进 `ENVIRONMENT_SCOPED_KEYS`；
* `DEPLOYMENT.md` 的 task-alert 小节、`API/智能分析Agent前端API.md` §11、
  `API/系统接口调用与代码统计.md:208-211` 同步（把"未接入 X360"的结论改掉）。
* 默认值里**不许**出现 mock 的 `MOCK_0728` / `2081949112647405570`；
  `X360_BASE_URL` 必须是域名，不许写 IP 或 SSH 别名。

### 3.5 明确不做

* 不加模型工具、不改 `.claude/agents/bi-analyst.md` 白名单、
  不改 `bi_agent/web/session.py::_SOP_TOOL_STEP`、不改 `bi_agent/tools/analysis_policy.py`；
* 不改 `dataset/evals/analytics`、不新增/删除用例、不动 known gap；
* 不改前端 `frontend/src/runtime.js`（`source` 的第二批消费另开）；
* 不把 `responsiblePerson` 解析成人名（文档没有用户查询接口）；
* 不调用 X360 的任何写接口；
* 不读真实凭据、不使用真实 Provider、不部署。

## 4. 环境未确认项（不得假装已确认）

Spec §10 的 6 条必须结清后才允许在生产把 `X360_BP_ID_LEVEL` 切到 `process_definition`：

1. `bpDefinitionId` 到底要流程定义 ID 还是活动 ID（**唯一阻塞项**）；
2. 鉴权方式（文档没写）；
3. 生产流程定义的 KEY / ID（文档只有 mock）；
4. `responsiblePerson` 的含义与取值域；
5. 是否需要任务级督办；
6. `履约单` 在真实流程定义里的归属。

未结清时：代码按文档默认（`process_definition`），生产配置按"保持现状"
（`X360_BP_ID_LEVEL=activity`，必要时 `X360_ENABLED=false`），并在交付报告里如实写明。

## 5. 完成前必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_x360_process_definition_red.py
.venv/bin/python -m pytest -q tests/test_regressions.py -k TaskAlert
.venv/bin/python -m pytest -q tests/test_ontology_mal_contract_red.py
.venv/bin/python -m pytest -q tests/test_docker_defaults_and_local_secrets.py tests/test_literal_ip_server_references.py
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
.venv/bin/python -m pytest -q
```

要求：红测 35 条全绿；`TaskAlertProxyTests` 20 条全绿；评测 570 / P0 147 / known gap 0
不变；全量 `pytest` 全绿且 skip 数量不劣化（skip 不得写成 pass）。
`--suite live` 不得运行（需要真实凭据）。

## 6. 交付报告（必须包含）

1. 修改文件清单（新增/修改/同步的文档）。
2. 红测从 32 failed / 3 passed 变为 35 passed 的实测输出。
3. `TaskAlertProxyTests` 20 条的实测输出，以及"为什么没有回归"的一句话解释
   （未配置 `X360_BASE_URL` 的用例走静态回退）。
4. §4 的 6 项未确认项当前状态（哪些已问、哪些未答、生产当前配置值）。
5. 误伤验证：静态回退路径、显式 `bpDefinitionId` 路径、X360 关闭路径各自的行为差异。
6. 剩余风险（尤其是"上游期望哪一级 ID"未确认时的兜底方式）。
7. `git diff --check` 结果与 `git status --short`。
8. 明确声明：未部署、未 push tag、未创建 Release。
