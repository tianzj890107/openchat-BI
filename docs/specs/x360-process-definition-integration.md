# X360 流程定义接口接入 Spec（X360 第一批：只读客户端 + 转督办换真）

> 依据：`API/X360提供给AI的接口.md`（2026-09-21 工作区版本，458 行）
> 红测：`tests/test_x360_process_definition_red.py`
> 实现提示词：`docs/specs/x360-process-definition-integration-implementation-prompt.md`
> 上一批终止条件（`docs/specs/ontology-mal-contract-migration.md` §10.5）明确要求：接 X360
> 必须**另开 Spec + 红测**。本文件即该 Spec。
>
> 本批**只做只读接入**：把"行动 → 转督办"的 `bpDefinitionId` 从硬编码关键词表换成
> X360 实时数据，并把流程责任人（`responsiblePerson`）接进来。不新增模型工具、不改
> 分析策略、不改评测集、不加 known gap。

---

## 0. 一句话结论

"行动 → 转督办"当前把用户行动文本按 **14 条硬编码关键词** 映射成一个数字 ID
（`bi_agent/web/app.py:2863` `TASK_ALERT_BP_KEYWORDS` / `2881`
`_match_task_alert_bp_definition`）。其中 **4 条在 X360 文档给出的流程定义里查无实据**
（`履约单`、`线索`、`项目`、`合同`），而 `履约单` 在文档里根本不是活动、是 `订单` 活动
下的任务；责任人则从来不是流程责任人，而是固定环境变量 `TASK_ALERT_DEFAULT_ASSIGNEE=400`。

X360 已经提供了 AI 视图接口（`/api/gateway2/x360/v1/process-definitions/ai/...`），
返回流程定义的两级 ID（`data.id` 流程定义 + `activities[].id` 活动）与每个活动的
`responsiblePerson`。本批要求：**新增只读 X360 客户端，把流程定义与活动解析搬到运行时**，
让 `bpDefinitionId` 来自 X360 数据、让责任人来自命中的活动，并在 X360 不可用时**明确标记
降级来源**，而不是继续假装关键词表就是流程定义。

---

## 1. 范围与非目标

### 1.1 范围内

| 项 | 生产入口 |
| --- | --- |
| X360 只读客户端（新增） | `bi_agent/x360/client.py`（新文件） |
| 流程定义 / 活动两级 ID 与 `responsiblePerson` 归一化 | 同上 |
| 转督办目标解析（新增内部函数） | `bi_agent/web/app.py::_resolve_task_alert_target` |
| 转督办端点改用解析结果 | `bi_agent/web/app.py::task_alert_manual_create`（`app.py:2958`） |
| 端点响应增加 `source` / `activityName` / `bpDefinitionId` | 同上 |
| 降级与开关 | `X360_*` 环境变量（§6） |
| 配置、部署与接口文档同步 | `.env.example`、`DEPLOYMENT.md`、`API/智能分析Agent前端API.md`、`API/系统接口调用与代码统计.md`（`208-211` 行"未接入"结论作废） |

### 1.2 非目标（本批明确不做）

* **不**把 X360 做成模型可调用工具：不改 `.claude/agents/bi-analyst.md` 工具白名单、
  不改 `bi_agent/web/session.py::_SOP_TOOL_STEP`、不改 `bi_agent/tools/analysis_policy.py`
  路由或 `ALLOWED_TOOLS`；转督办仍然是"前端按钮 + 后端代理"，不是 LLM 工具调用。
* **不**改分析策略、Prompt、评测集、known gap（`--suite all` 570 条 / P0 147 /
  known gap 0 必须逐字保持）。
* **不**做前端展示改造（前端仍只看 `ok`/`taskId`；`source` 的第二批消费另开）；
* **不**把 `responsiblePerson`（数字 ID）解析成人名：文档没有提供用户/员工查询接口，
  本批只透传数字 ID；
* **不**调用 X360 的任何写接口（`manual-create` 仍在既有后端代理里，本批只新增两个 GET）；
* **不**改任务令服务（`TASK_ALERT_API_URL`）自身的协议；
* **不**为了"能预测/能督办"去伪造上游数据。

---

## 2. 对外契约摘要（文档 → 代码映射）

### 2.1 两个端点（都是 GET、无请求体）

| 文档 | 路径 | 用途 |
| --- | --- | --- |
| `API/X360提供给AI的接口.md` §1 | `/api/gateway2/x360/v1/process-definitions/ai/{bpProcessDefinitionId}` | 按**流程定义 ID**查询 |
| 同 §2 | `/api/gateway2/x360/v1/process-definitions/ai/key/{processDefinitionKey}` | 按**流程定义 KEY**查询 |

### 2.2 响应形状（文档示例）

```jsonc
{
  "success": true, "code": 200, "message": "操作成功",
  "data": {
    "id": "2081949112647405570",          // 流程定义 ID
    "code": "MOCK_0728",                   // 流程定义 KEY
    "name": "mock流程",
    "description": "线索到回款（LTC）端到端…",
    "activities": [                        // 11 个活动
      { "id": "2081949636092350465", "name": "线索", "code": "XINSUO",
        "responsiblePerson": "242", "description": "…",
        "tasks": [ { "id": "…", "name": "获取", "code": "HUOQU", "description": "…" } ] }
    ]
  }
}
```

活动 ID / 名称 / 责任人（文档 §1 示例，共 11 个）：
`线索/242`、`销售项目/94`、`合同/390`、`订单/250`、`生产/246`、`发货/395`、
`签收/400`、`验收/311`、`开票/336`、`回款/224`、`关闭/364`。
活动 ID：`线索=2081949636092350465`、`销售项目=2081949636117516289`、
`合同=2081949636130099201`、`订单=2081949636146876418`、`生产=2081949636172042241`、
`发货=2081949636180430849`、`签收=2081949636188819457`、`验收=2081949636197208066`、
`开票=2081949636205596674`、`回款=2081949636213985282`、`关闭=2090377006986399746`。

### 2.3 文档缺口（必须显式承认，不猜）

1. **没有任何鉴权说明**：全文没有 `Authorization` / 鉴权 / token 章节（已逐行核对）。
   → 本批按仓库既有约定实现（§5.5），并把"上游到底要哪种鉴权"列为待确认项（§10）。
2. **没有 host**：文档只给 path。`X360_BASE_URL` 必须由部署注入，且**不允许**写死 IP
   或 SSH 别名（`tests/test_literal_ip_server_references.py`）。
3. **示例是 mock 数据**：`code=MOCK_0728`、`name=mock流程`。**不能**把 mock 的
   KEY/ID 当作生产默认值写进代码。
4. **两级 ID 语义与参数名不一致**：参数名 `bpDefinitionId` 字面是"流程定义 ID"，
   但当前生产填的是**活动 ID**（§3.3）。这是本批唯一需要上游书面确认的点（§4）。
5. 活动 `code` 与 `id`、任务 `id` 均为字符串数字，**不得**按 int 处理（前导/长度会丢精度）。

---

## 3. 当前缺陷（生产复现）

复现方式：直接调用真实生产入口（`bi_agent/web/app.py`），无 mock、无改写。

```text
.venv/bin/python -c "from bi_agent.web import app as w; print(w._match_task_alert_bp_definition('建议对回款环节发起督办'))"
```

实测输出（2026-09-21，`HEAD=5f2dd2b`）：

| 用户行动文本 | 当前解析结果 | 判定 |
| --- | --- | --- |
| `建议对回款环节发起督办` | `2081949636213985282`（活动「回款」ID） | 值在文档里是**活动** ID |
| `合同签署后开票跟进` | `2081949636205596674`（活动「开票」ID） | 同上 |
| `线索转化率偏低，请督办` | `2082310961683353602` | 文档 11 个活动里**查无此 ID** |
| `履约单交付异常` | `2081949636163653634` | 文档里 `履约单` 是 `订单` 下的**任务**，不是活动 |

其它实测事实：

```text
len(web_app.TASK_ALERT_BP_KEYWORDS)            == 14
hasattr(web_app, "_resolve_task_alert_target") == False
import bi_agent.x360.client                    -> ModuleNotFoundError: No module named 'bi_agent.x360'
os.environ keys starting with "X360"           == ()
TASK_ALERT_DEFAULT_ASSIGNEE                    == "400"（固定值，与流程定义无关）
```

### 3.1 缺陷一：4 条关键词的 ID 在文档里查无实据

| 关键词 | 静态表 ID | 文档 11 个活动 | 结论 |
| --- | --- | --- | --- |
| 销售项目 / 投标 | `2081949636117516289` | 销售项目 `XIANGMU` | ✅ 一致 |
| 开票 | `2081949636205596674` | 开票 `KAIPAIO` | ✅ 一致 |
| 回款 | `2081949636213985282` | 回款 `HUIJUAN` | ✅ 一致 |
| 关闭 | `2090377006986399746` | 关闭 `GUANBI` | ✅ 一致 |
| 订单 | `2081949636146876418` | 订单 `DINGDAN` | ✅ 一致 |
| 生产 | `2081949636172042241` | 生产 `SHCNEGCAN` | ✅ 一致 |
| 发货 | `2081949636180430849` | 发货 `FAHUYO` | ✅ 一致 |
| 签收 | `2081949636188819457` | 签收 `QINSHOU` | ✅ 一致 |
| 验收 | `2081949636197208066` | 验收 `YANSHOU` | ✅ 一致 |
| 履约单 | `2081949636163653634` | 无此活动（`履约单生成/履约单下达` 是 `订单` 下的任务） | ❌ 任务被当成活动 |
| 线索 | `2082310961683353602` | 线索 `XINSUO = 2081949636092350465` | ❌ 不一致 |
| 项目 | `2082310961716908034` | 销售项目 `= 2081949636117516289` | ❌ 不一致 |
| 合同 | `2082310961754656769` | 合同 `HTTONG = 2081949636130099201` | ❌ 不一致 |

10 / 14 与文档一致，**4 条无从核对**。注意：文档示例是 mock 数据，这 4 条 ID 可能是
真实（非 mock）流程定义里的对象 ID，也可能已失效——**在接入 X360 之前无法判断**，
这正是"必须改为运行时解析"的理由：不再由代码替上游猜 ID。

### 3.2 缺陷二：任务被当成活动

`履约单` 在文档里是 `订单` 活动下的两个任务（`履约单生成` / `履约单下达`），
静态表却把它当成一个平级活动并给了独立 ID。用户说"履约单交付异常"时，转督办会挂到
一个既不是活动、也无从核对的 ID 上。

### 3.3 缺陷三：`bpDefinitionId` 语义错位

参数名字面是"流程定义 ID"（文档 §1：`bpProcessDefinitionId`），而静态表填的全是
**活动 ID**。两者不是同一层级：文档同时返回 `data.id`（流程定义）与
`activities[].id`（活动）。当前实现既没有区分层级，也没有任何地方记录这个差异，
因此**无法从代码或日志判断上游实际期望哪一级**（§4 给出决策与开关）。

### 3.4 缺陷四：责任人永远是固定值

文档为 11 个活动都给了 `responsiblePerson`（回款 224、开票 336、线索 242、销售项目 94、
合同 390、订单 250、生产 246、发货 395、签收 400、验收 311、关闭 364），而当前
`task_alert_manual_create` 只在请求体未带 `assignee` 时取
`TASK_ALERT_DEFAULT_ASSIGNEE`（`.env` 里写死 `400`）。也就是：**转督办的责任人与被督办的
流程活动毫无关系**，只有 `签收` 恰好也是 400 才对得上。

### 3.5 缺陷五：X360 完全没接线

`bi_agent/x360/` 不存在、没有 `X360_*` 配置、`API/系统接口调用与代码统计.md:208-211`
明确写着"未接入"。也就是说上面四条不是"实现细节不理想"，而是**整块能力缺失**。

---

## 4. 决策：`bpDefinitionId` 取哪一级，以及如何不把话说死

**决策：按 API 文档实现 —— `bpDefinitionId` 默认取流程定义 ID（`data.id`）。**

理由：参数名与文档路径参数都写作"流程定义 ID"；按字面契约实现是唯一可复现的口径；
活动 ID 仍然保留在响应与日志里（`activityId`），信息不丢。

同时必须承认：**当前生产在发活动 ID，且转督办今天是可用的**（`changelog_8_17_21.md:40`）。
把默认口径从"活动 ID"切到"流程定义 ID"会改变上游收到的值，属于对外副作用，因此：

* 解析出的 **活动** ID 永远单独暴露（`activityId`），切换口径不丢信息；
* 提供 **`X360_BP_ID_LEVEL`** 一键回退：
  * `process_definition`（默认，按文档）→ 请求体 `bpDefinitionId = data.id`；
  * `activity`（回退）→ 请求体 `bpDefinitionId = 命中活动.id`，即与今天的行为等价。
  回退只需改一个环境变量，**不需要改代码、不需要回滚发布**。
* **生产启用 X360 之前必须拿到上游书面确认**（§10 第 1 条）：上游期望的
  `bpDefinitionId` 到底是流程定义 ID 还是活动 ID。未确认前，生产按"保持现状"配置
  （`X360_BP_ID_LEVEL=activity`），确认后再切到 `process_definition`。
* 注意：**无论**取哪一级，本批都修掉了 §3.1/§3.2/§3.4 三条缺陷——因为 ID 来源从
  硬编码换成了 X360 实时数据、`履约单` 归到父活动 `订单`、责任人来自活动。

---

## 5. 目标设计

### 5.1 模块与公开符号（红测按名字断言）

```
bi_agent/x360/__init__.py
bi_agent/x360/client.py
```

| 符号 | 契约 |
| --- | --- |
| `X360ApiError(Exception)` | 所有 X360 侧失败的唯一异常类型（含 HTTP/业务/非 JSON/超时/结构异常） |
| `X360Activity` | 字段：`id: str`、`name: str`、`code: str`、`responsible_person: str`、`tasks: list[dict]`（每项至少含 `id/name/code/description`），以及指回父流程定义的 `process_definition_id` |
| `X360ProcessDefinition` | 字段：`id: str`、`code: str`、`name: str`、`activities: list[X360Activity]` |
| `X360ProcessDefinitionClient` | `.from_env()`、`.fetch_by_key(key)`、`.fetch_by_id(id)`、`.match_activity(text)` |

`from_env()` 在配置缺失时**不得**抛异常：返回一个"未启用"的客户端，让上层走静态回退
（配置缺失是常态，不是错误）。

### 5.2 端点与请求

* 只有 `GET`（红测断言 `{c["method"] for c in x360_calls} == {"GET"}`）；
* 路径必须逐字等于文档：`/api/gateway2/x360/v1/process-definitions/ai/key/{key}` 与
  `/api/gateway2/x360/v1/process-definitions/ai/{id}`（ID / KEY 做 URL 编码）；
* 请求头只加 `Accept: application/json` 与 §5.5 的鉴权头；**不**发送任何请求体；
* 超时 `X360_TIMEOUT_SECONDS`（默认 10，夹在 0.5–120，与 `_task_alert_timeout` 同口径）。

### 5.3 归一化

* 只认 `data.activities[].id/name/code/responsiblePerson/tasks[]`，缺字段用空字符串/空列表
  兜底，**不抛异常**；
* `activities` 为空 → 返回空活动的定义（不是错误）；上层自然走静态回退；
* 结构非法（`data` 不是 dict、`success=false`、非 JSON、HTTP ≠ 2xx、超时、
  `data=null`）→ `X360ApiError`（见 §5.7）；
* 所有 ID 一律字符串，禁止 int 化后回写（`2081949112647405570` 超 32 位）。

### 5.4 匹配算法（确定性，长名优先）

对命中顺序做**分级**匹配，第一级命中即返回；同级多命中取**名称最长**者：

1. 活动 `name` 被文本包含（例：`建议对回款环节发起督办` → `回款`）；
2. 活动 `code` 命中（大小写不敏感、ASCII 词边界，例：`check HUIJUAN stage` → `回款`）；
3. **任务** `name` 被文本包含 → 返回其**父活动**（例：`履约单生成的进度异常` → `订单`）；
4. 任务 `code` 命中（同上，返回父活动）。

都不命中 → `None`（上层降级，不得凭空造 ID）。该规则刻意不引入同义词表、不做模糊/
前缀模糊匹配：`履约单交付异常` 这种"关键词是任务名前缀、但不是完整任务名"的文本会
落到静态回退（保持今天的行为），直到上游给出真实流程定义。

### 5.5 鉴权（仓库既有约定，文档未给）

沿用 `bi_agent/ontology/remote.py:168-176` 与 `bi_agent/tools/sql_tools.py:184-195`
的同一套约定：

* `X-App-Id`：默认取 `X360_APP_ID`，未配置时回退 `ONTOLOGY_APP_ID`（两环境共用的
  非密值 `ApTH1EHKdRk58WhDQB`）；
* `Authorization`：`X360_AUTH_TOKEN` 非空时发送；值已以 `bearer` 开头则原样透传，
  否则自动加 `Bearer ` 前缀；为空则**不发送**该头；
* token 只从服务端环境读取，**不得**进响应、错误信息、日志或前端。

### 5.6 缓存与并发

* 按 `(base_url, selector)` 缓存解析后的 `X360ProcessDefinition`，TTL =
  `X360_CACHE_TTL_SECONDS`（默认 300；`0` = 每次回源）；
* 缓存读写加锁（与 `_task_alert_lock` 同风格）；**失败不缓存**；
* 增加失败冷却（`X360_FAILURE_COOLDOWN_SECONDS`，默认 30）：冷却期内的解析直接走静态
  回退，避免 X360 长时间不可用时每次点击转督办都要等满超时（这是相对今天的**可感延迟
  回归**，必须挡掉）。冷却状态跟随客户端实例（§7 环境变化重建实例即重置）。

### 5.7 错误语义与凭据保护

* 所有失败抛 `X360ApiError`，消息只允许包含：接口用途 + 失败类别 + 上游 `message`
  （截断 200 字符），例：`X360 流程定义接口 HTTP 500`、`X360 流程定义接口业务失败: 流程定义不存在`、
  `X360 流程定义接口超时`、`X360 流程定义接口返回非 JSON`；
* 消息**不得**包含 token、`X360_BASE_URL` 全文或 host（红测逐字符断言）。

### 5.8 开关与降级矩阵（`_resolve_task_alert_target` 的唯一真值表）

| `X360_ENABLED` | `X360_BASE_URL` | selector | X360 结果 | `source` | `bpDefinitionId` |
| --- | --- | --- | --- | --- | --- |
| 显式 `false/0/no/off` | — | — | 不请求 | `static_fallback` / `default` | 静态表 / `None` |
| 开（未设置即开） | 空 | — | 不请求 | `static_fallback` / `default` | 静态表 / `None` |
| 开 | 有 | 空（KEY 与 ID 都空） | 不请求 | `static_fallback` / `default` | 静态表 / `None` |
| 开 | 有 | 有 | 命中活动 | `x360` | 按 `X360_BP_ID_LEVEL` |
| 开 | 有 | 有 | 未命中活动 | `static_fallback` / `default` | 静态表 / `None` |
| 开 | 有 | 有 | 任何失败（§5.3） | `static_fallback` / `default` | 静态表 / `None` |
| 请求体已带 `bpDefinitionId` | — | — | 不请求 | `request` | 入参（最高优先级） |

补充规则：

* `static_fallback` = 命中了遗留关键词表；`default` = 连关键词表都没命中；
* 非 `x360` 来源时 `activityId` / `activityName` 一律为 `None`（不把关键词猜成活动名）；
* `x360` 来源时 `assignee` 取该活动 `responsiblePerson`，为空/缺失才回落到环境默认；
* `source=request`（显式入参）时**不动** `assignee`，保持既有行为，且**不再发起** X360 请求；
* 任何分支都不得让 `bpDefinitionId` 变成"猜出来的新值"——只有三种来源：入参、X360、静态表。

### 5.9 转督办接线

新增 `bi_agent/web/app.py::_resolve_task_alert_target(text: str) -> dict`，返回
`{"bpDefinitionId": int|None, "activityId": str|None, "activityName": str|None,
"assignee": str|None, "source": str}`，并在 `task_alert_manual_create` 中**先解析一次**，
把同一个结果同时用于日志与请求体（禁止解析两次——否则日志和实际载荷可能不一致）。

调用链（改造后）：

```
前端 dispatchSupervise（frontend/src/runtime.js:999，本批不改）
  → POST /api/task-alert/manual-create
    → task_alert_manual_create(app.py:2958)
      → _resolve_task_alert_target(title + "\n" + content)
        → X360ProcessDefinitionClient.from_env()（按环境签名缓存/重建）
          → GET /api/gateway2/x360/v1/process-definitions/ai/key/{key}
        → match_activity(text) → 活动 → {bpDefinitionId, activityId, activityName, assignee, source}
      → POST ${TASK_ALERT_API_URL}（载荷与既有字段一致）
      → {ok, taskId, clientRequestId, source, activityName, bpDefinitionId}
```

既有行为必须保持：`title`/`content` 非空（422）、`level` 白名单（422）、
`bpDefinitionId` 必须为数字串（422）、`clientRequestId` 进程内幂等（成功缓存/进行中 409/
失败可重试）、上游失败 502/504 且不缓存。

### 5.10 四个边界（route / tools / plan / answer 的等价物）

| 边界 | 约束 |
| --- | --- |
| 解析（route） | 只有 §5.8 矩阵里的三条 ID 来源；未命中就是 `None`，不猜 |
| 调用（tools） | 只允许 `GET`；只允许文档两个 path；X360 关闭时**零**出网请求 |
| 载荷（plan） | 请求体字段集不变（`title/content/assignee/level/bpDefinitionId`）；`bpDefinitionId` 级别由 `X360_BP_ID_LEVEL` 决定；不新增未与上游约定的字段 |
| 回应（answer） | 响应新增 `source`/`activityName`/`bpDefinitionId`；`source` 必须如实反映"真流程/静态回退/默认/入参"，不得把回退写成成功解析；响应不得回显 token |

### 5.11 日志

`logger.info` 记录 `source`、`activityName`、`bpDefinitionId`、`clientRequestId`、
`taskId`；`logger.warning` 记录 X360 失败类别（不带 token/host）。日志是"这次督办到底
按哪个流程发的"的唯一事后证据。

---

## 6. 配置

| 变量 | 默认 | 说明 | `.env.example` | 键集归属 |
| --- | --- | --- | --- | --- |
| `X360_ENABLED` | 未设置 = 开启 | 显式 `false/0/no/off` 关闭 | `true` | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_BASE_URL` | 空 | 空 = 未配置（走静态回退）；**必须**是域名，禁止 IP/别名 | 空 | `ENVIRONMENT_SCOPED_KEYS` |
| `X360_PROCESS_DEFINITION_KEY` | 空 | 首选 selector（文档 §2） | 空 | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_PROCESS_DEFINITION_ID` | 空 | 备用 selector（文档 §1） | 空 | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_APP_ID` | 回退 `ONTOLOGY_APP_ID` | 非密 App ID | `ApTH1EHKdRk58WhDQB` | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_AUTH_TOKEN` | 空 | 空 = 不发 `Authorization` | 空 | `RUNTIME_SECRET_KEYS` |
| `X360_TIMEOUT_SECONDS` | 10 | 0.5–120 | `10` | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_CACHE_TTL_SECONDS` | 300 | 0 = 每次回源 | `300` | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_BP_ID_LEVEL` | `process_definition` | `process_definition` / `activity` | `process_definition` | `BASELINE_LOCAL_ENV_KEYS` |
| `X360_FAILURE_COOLDOWN_SECONDS` | 30 | 失败冷却，见 §5.6 | `30` | `BASELINE_LOCAL_ENV_KEYS` |

落位（必须同步，否则门禁变红）：

* `tests/test_docker_defaults_and_local_secrets.py`：非密键进 `BASELINE_LOCAL_ENV_KEYS`
  （值进 `NON_SECRET_DEFAULTS`），`X360_AUTH_TOKEN` 进 `RUNTIME_SECRET_KEYS`，
  `X360_BASE_URL` 进 `ENVIRONMENT_SCOPED_KEYS`（只断言存在，不把环境地址烤进镜像）；
* `.env.example`（现有 `TASK_ALERT_*` 块之后）与 `DEPLOYMENT.md`（`448-475` 的
  task-alert 小节）同步；
* `API/智能分析Agent前端API.md` §11：`bpDefinitionId` 语义说明改为"默认流程定义 ID，
  由 X360 解析，可用 `X360_BP_ID_LEVEL` 切回活动 ID"，并把示例里的活动 ID 解释清楚；
* `API/系统接口调用与代码统计.md:208-211` 的"未接入 X360"结论必须改写。

---

## 7. 兼容性与误伤控制

| 会被影响的既有契约 | 要求 |
| --- | --- |
| `tests/test_regressions.py::TaskAlertProxyTests`（20 条，今天全绿） | 必须继续全绿。其中 `test_bp_definition_matched_by_content_keyword`（`回款` → `2081949636213985282`）、`test_upstream_request_field_mapping_and_defaults`（无关键词 → 载荷**不含** `bpDefinitionId`）、`test_bp_definition_explicit_overrides_keyword`（入参 55 优先）、`test_missing_assignee_uses_env_defaults`（空 assignee → `400`）之所以保持成立，是因为这些用例不配置 `X360_BASE_URL` → 按 §5.8 第二行走静态回退 |
| `tests/test_ontology_mal_contract_red.py`（当前 69 passed / 1 pre-existing failure） | `test_migration_does_not_call_the_x360_process_api` 必须保持绿：X360 客户端只被转督办解析调用，本体路径仍不得触发任何 `x360` 请求。该文件另有 1 条**迁移前遗留的自相矛盾断言**（见 §8.1），本批不修、不得因它把 X360 接进本体路径 |
| `tests/test_docker_defaults_and_local_secrets.py` | 键集按 §6 同步；不得把 `X360_BASE_URL` 的**值**写成固定默认 |
| `tests/test_literal_ip_server_references.py` | `X360_BASE_URL` 用域名，禁止 IP/SSH 别名 |
| `frontend/src/runtime.js` + `test_frontend_no_fake_success_logic` | 前端本批不改，仍只认 `ok`/`taskId`；不得因此把回退说成成功 |
| 分析策略/评测集 | 不改 `analysis_policy.py`、不改 `dataset/evals/analytics`；`--suite all` 570 / P0 147 / known gap 0 不变 |

误伤控制（明确不做）：

* 不把"配置缺失/网络不可用"变成用户可见失败——转督办必须仍能创建（降级 + `source` 标记）；
* 不因为接了 X360 就扩大工具面（不加模型工具、不加白名单、不改 SOP 步骤映射）；
* 不把 `responsiblePerson` 当人名展示（本批只透传数字 ID）；
* 不把 mock KEY（`MOCK_0728`）写进任何默认值；
* 不在 X360 不可用时静默丢弃 `assignee` 默认值。

---

## 8. Red Test 对照表

文件：`tests/test_x360_process_definition_red.py`（35 个测试方法；离线、loopback HTTP、
假 X360 + 假任务令服务、无凭据、无 LLM、不碰用户数据）。

| 组 | 数量 | 覆盖 | 当前 |
| --- | --- | --- | --- |
| `X360ClientContractTests` | 7 | 公开符号；两个文档路径；两级 ID 与 `tasks` 归一化；按 `name`/`code`（大小写不敏感）匹配；不命中返回 `None` | 7 red |
| `X360AuthTests` | 5 | `X-App-Id`；`Bearer` 前缀不重复；token 为空不发头；**只允许 GET** | 5 red |
| `X360ErrorTests` | 5 | HTTP 错误、业务失败、非 JSON、超时都抛 `X360ApiError`；错误文本不回显 token / base URL | 5 red |
| `X360CacheTests` | 2 | TTL 内第二次命中缓存；TTL=0 每次回源 | 2 red |
| `TaskAlertTargetResolutionTests` | 7 | 默认取流程定义 ID；`X360_BP_ID_LEVEL=activity` 回退；`assignee`/`activityName` 来自命中活动；`activityId` 始终可见；关闭时静态表 + `static_fallback` 且零 X360 请求；未命中 → `bpDefinitionId=None` + `default`；换环境重建客户端 | 7 red |
| `TaskAlertEndpointTests` | 6 | 响应暴露 `source`/`activityName`/`bpDefinitionId`；上游收到解析后的 ID 与责任人；X360 不可用仍创建（`static_fallback`）；关闭时零请求；响应不含 token；上游失败仍 502 | 3 red / 3 pass |
| `MutationGuardTests` | 3 | 任务名必须归到父活动（`履约单生成` → `订单`）；X360 命中不得被静态表覆盖；显式 `bpDefinitionId` 不被覆盖且不白跑 X360 | 3 red |

**当前实测：32 failed / 3 passed。**失败原因分布（`pytest -q`，逐条核对）：

| 原因 | 条数 | 生产入口 |
| --- | --- | --- |
| `尚未实现 bi_agent.x360.client`（`ModuleNotFoundError: No module named 'bi_agent.x360'`） | 19 | `bi_agent/x360/client.py`（不存在） |
| `尚未实现 bi_agent.web.app._resolve_task_alert_target` | 9 | `bi_agent/web/app.py`（函数不存在） |
| `KeyError: 'source'` | 3 | `task_alert_manual_create` 响应没有新增字段 |
| `AssertionError: 2081949636213985282 != 2081949112647405570` | 1 | 上游实际收到的是**活动** ID，而不是流程定义 ID |

### 8.1 与既有全量套件的关系（实测，2026-09-21）

`pytest -q tests`（1145 条）当前为 **34 failed / 1086 passed / 25 skipped / 1011 subtests passed**，
逐条归因后**没有一条由本批引入的文档或红测之外的原因造成**：

| 失败 | 条数 | 归因 |
| --- | --- | --- |
| `tests/test_x360_process_definition_red.py` | 32 | 本批红测（功能未实现，预期为红） |
| `tests/test_ontology_mal_contract_red.py::RequestContractTests::test_list_repositories_uses_the_documented_context_endpoint` | 1 | **HEAD 就存在**的遗留矛盾：该用例要求本体库目录端点带 `x-ontology-repository-id`，而同文件 `test_list_repositories_can_omit_the_repository_header` 与 `ScopeGuardTests::test_client_never_sends_repository_header_to_the_catalog_endpoint` 要求**不带**（生产实现 `bi_agent/ontology/remote.py:540-545` 明确 `include_repository_header: False`）。用 `git archive HEAD` 纯净副本复跑：**1 failed / 69 passed**，与本批无关 |
| `tests/test_analytics_eval_release_ci.py::ReleaseCiContractTest::test_a_dropped_release_flag_is_caught` | 1 | 属于**另一个并行会话尚未提交的在途修改**（`scripts/run_analytics_eval.py`、`.gitlab-ci.yml`、`tests/test_analytics_eval_dataset.py`）；同一文件在 HEAD 纯净副本上 **19 passed**。该会话随后以 `537e01e`（"make release repeat-stability a real measurement gate"）自行提交，此失败随之消失——它从头到尾都不是本批造成的 |

`537e01e` 落地后的复测：`pytest -q tests` = **33 failed / 1087 passed / 25 skipped / 1011 subtests passed**，
失败项 = 本批红测 32 条 + §8.1 表内那条 HEAD 遗留矛盾 1 条；
`tests/test_analytics_eval_release_ci.py`、`tests/test_analytics_release_stability_red.py`、
`tests/test_regressions.py`（除本批 `-k TaskAlert` 子集外的 350 条）全部通过。

25 条 skip 全部是既有 opt-in 用例（live / 需要真实凭据），数量与原因不变；skip 不得写成 pass。

那 3 个当前为绿的用例（`test_endpoint_does_not_call_x360_when_disabled`、
`test_endpoint_response_never_contains_token`、
`test_endpoint_still_reports_upstream_failure_honestly`）**不是"已经通过的新功能"**，它们是
"今天就该成立、接入后不得被破坏"的护栏（关闭时不出网、不回显 token、上游失败仍 502）。
不得为了凑绿色而删除它们，也不得把它们算成已实现项。

---

## 9. Mutation 方案

`MutationGuardTests` 用**真实行为**杀变异（不看源码里有没有某关键词）：

| 变异 | 会被杀死的用例 |
| --- | --- |
| 把任务 `履约单生成` 当成新的活动 / 继续用凭空的 `履约单` 硬编码 ID | `test_mutant_task_name_must_resolve_to_its_parent_activity` |
| X360 命中后又被静态关键词表覆盖（等于白接） | `test_mutant_x360_hit_must_not_be_overridden_by_static_keyword_table`（同时被 `test_bp_id_defaults_to_process_definition_id_per_documented_contract` 覆盖） |
| 显式 `bpDefinitionId` 被解析结果覆盖，或解析仍然白跑一次 X360 | `test_mutant_explicit_bp_id_must_not_be_overridden_by_x360` |
| 把 X360 的 `responsiblePerson` 丢掉、继续用固定 400 | `test_assignee_comes_from_matched_activity`、`test_endpoint_sends_resolved_bp_id_upstream` |
| 失败时静默返回空定义而不抛错 | `X360ErrorTests` 5 条 |
| 把错误信息直出（含 token / 内部地址） | `test_errors_never_leak_token_or_base_url` |
| 忽略缓存 TTL | `X360CacheTests` 2 条 |
| 用写接口"顺手同步" | `test_client_is_read_only` |
| X360 不可用时让转督办失败（用户侧 5xx 回归） | `test_endpoint_still_creates_task_when_x360_unavailable` |
| `bpDefinitionId` 级别写死（开关失效） | `test_activity_level_switch_is_honoured` |

---

## 10. 待上游确认清单（阻塞项，必须在生产启用前结清）

1. **`bpDefinitionId` 到底要哪一级 ID**（流程定义 ID 还是活动 ID）？文档参数名与当前
   生产实践不一致，本批默认按文档（`process_definition`）实现，并在接到答复后由
   `X360_BP_ID_LEVEL` 定稿。
2. **鉴权方式**：文档完全没有鉴权章节。当前按仓库既有约定实现
   （`X-App-Id` + 可选 `Bearer`）。需要确认：X360 网关是否要求 token？用哪个 App？
   令牌是否与本体网关共用？
3. **生产流程定义的 KEY / ID**：文档只给 mock（`MOCK_0728`/`2081949112647405570`）。
   需要给出真实 LTC 流程定义的 KEY（或 ID），否则生产只能保持静态回退。
4. **`responsiblePerson` 的含义与可用性**：是用户 ID 还是员工工号？`400` 是否等于
   "签收默认责任人"？任务令服务是否接受这个取值域？
5. **是否需要任务级督办**：文档的 `tasks[]` 是否能作为督办对象（若需要，是否要新增
   上游字段承载 `taskId`，本批不猜）。
6. **`履约单` 在真实流程定义里的归属**：确认它是否为 `订单` 下的任务，以及历史
   硬编码 ID `2081949636163653634` 的真实语义。

---

## 11. 实现验收清单

1. `bi_agent/x360/client.py` 提供 §5.1 全部符号；`from_env()` 在配置缺失时返回未启用客户端而不抛错。
2. 请求路径逐字等于文档两个 path；方法只有 `GET`；无请求体。
3. 归一化产出 `X360ProcessDefinition` / `X360Activity`，任务保留 `id/name/code/description`。
4. 匹配按 §5.4 分级（活动名 → 活动 code → 任务名 → 任务 code，长名优先），命中任务时返回父活动，未命中返回 `None`。
5. 鉴权头按 §5.5；token 为空时不发 `Authorization`；token 不出现于响应/错误/日志。
6. TTL 缓存 + 失败冷却按 §5.6；换环境（`X360_BASE_URL` 等变化）后客户端重建。
7. 错误按 §5.7 抛 `X360ApiError`，且消息不含 token/host。
8. `_resolve_task_alert_target` 实现 §5.8 真值表全部 7 行；非 `x360` 来源的 `activityId`/`activityName` 为 `None`。
9. `task_alert_manual_create` 只解析一次，响应新增 `source`/`activityName`/`bpDefinitionId`，其余行为（422/409/502/504/幂等）不变。
10. `.env.example`、`DEPLOYMENT.md`、`API/智能分析Agent前端API.md`、`API/系统接口调用与代码统计.md` 按 §6 同步；`test_docker_defaults_and_local_secrets.py` 键集同步。
11. 红测 35 条全绿（其中 32 条从红转绿，3 条护栏始终绿）。
12. `tests/test_regressions.py::TaskAlertProxyTests` 20 条全绿；
    `tests/test_ontology_mal_contract_red.py` 保持 69 passed / 1 pre-existing failure（§8.1，不得变差）；
    `--suite smoke/adversarial/recorded-provider/regression/all` 全绿且用例数不变（570 / P0 147 / known gap 0）。
13. 全量 `pytest -q tests`：本批红测 32 条转绿；其余失败项与 §8.1 对照后不多出任何一条；
    skip 数量与原因不劣化（skip 不得写成 pass）。
14. 生产启用前的 6 项上游确认（§10）有书面结论并在文档中留痕。

---

## 12. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 上游其实期望**活动** ID，默认切成流程定义 ID 导致督办挂错对象 | `X360_BP_ID_LEVEL` 一键回退（纯配置）；`activityId` 始终随响应/日志返回；生产启用前必须结清 §10 第 1 条 |
| 生产流程定义的 KEY/ID 未知 → 解析永远未命中 | 未命中即静态回退（与今天等价），不报错；§10 第 3 条结清后再填配置 |
| X360 不可用导致转督办变慢（每次点击等满超时） | 失败冷却（§5.6，默认 30s）+ 超时上限 120s；冷却期内直接回退 |
| 接了 X360 后把 mock 的 KEY/ID 写进默认值 | §6 默认值全为空；`MOCK_0728` 只允许出现在文档与红测 fixture 里 |
| 错误信息泄露 token / 内部地址 | `X360ErrorTests::test_errors_never_leak_token_or_base_url` 逐字符断言 |
| 键集同步漏项导致 `test_docker_defaults_and_local_secrets` 变红 | §6 落位表逐项对照；该测试自身就是门禁 |
| 误伤普通业务行为（分析策略/评测集） | 本批不碰 `analysis_policy.py`、不碰评测集；`--suite all` 570 条守护 |
| 回滚 | 代码回滚 = 删 `bi_agent/x360/`、还原 `bi_agent/web/app.py` 的转督办段落与 4 个文档；**或**只设 `X360_ENABLED=false` 立刻回到今天的静态表路径（无需回滚发布）。红测文件保留为回归 |

---

## 13. 治理终止条件

1. 红测 35 条全绿，`MutationGuardTests` 3 条全绿。
2. `TaskAlertProxyTests` 20 条、`test_ontology_mal_contract_red.py`、
   `test_docker_defaults_and_local_secrets.py`、`test_literal_ip_server_references.py` 全绿。
3. `--suite smoke`、`adversarial`、`recorded-provider`、`regression`、`all` 全绿；
   570 / P0 147 / known gap 0 不变，不得借本批新增用例或重开 known gap。
4. 全量 `pytest -q tests` 全绿，skip 不劣化。
5. §10 的 6 项确认结清并在文档留痕之前，**不得**在生产把 `X360_BP_ID_LEVEL` 切到
   `process_definition`，也不得把本批宣称成"流程定义口径已确认"。
6. 若要把 X360 能力开放给模型（工具/白名单/SOP 步骤），必须再开一份 Spec + 红测。
