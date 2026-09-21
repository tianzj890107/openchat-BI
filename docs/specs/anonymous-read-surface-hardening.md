# 匿名读取面收敛 Spec（分析 Agent 线上验收批次 1：内网字段与工作目录）

> 来源：2026-09-21 PDT / demo2 真实环境只读验收（PDT 12 轮、demo2 7 轮，仅 GET 只读接口 +
> `POST /api/chat` 正常提问，无删除/重置、无真实密钥输出）暴露的 P4 与 P2 根因，
> 以及本轮复核新确认的 `/healthz` 主机名（§3.1，P4 同类）。
> 红测：`tests/test_anonymous_read_surface_red.py`
> 实现提示词：`docs/specs/anonymous-read-surface-hardening-implementation-prompt.md`
>
> 本批**只收敛匿名读取面的暴露字段**：把内网物理地址、数据库账号与绝对工作目录从
> 匿名响应和系统提示里去掉，且不改变产品需要显示的逻辑标识。不改分析策略、Prompt 语义、
> 评测集、图表与前端功能。

---

## 0. 一句话结论

线上（0.1.7）与当前仓库 HEAD 都存在三处**匿名可读**的内部信息暴露：

1. `GET /api/sources` 原样返回 Doris 连接真值：
   `jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?…`、`api_url`、
   `username: "admin"`（口令为空，无凭据泄露，但内网 host:port + 账号 + 库名可被匿名读取）。
   实测（HEAD，伪造 STATE 值）：**三个字段全部原样出现在响应里**。
2. 会话系统提示里带 `# Environment` 块，含 `- Working directory: <绝对路径>`
   （`open_claude/prompt.py:203-204`，取自 `get_environment_info()`，即**进程 cwd**，
   容器里就是 `/app`），而 `GET /api/system-prompt` 未做任何收敛就把整段提示回吐给浏览器；
   同一段提示也发给模型，于是模型会照抄出 `/app`。
   实测（HEAD）：会话提示里出现 `/Users/…/eimosp-ontology-agentic-analytics`，且
   `WebSession(cwd)` 传任何 cwd 都不影响该行（它取进程 cwd）。
3. `GET /healthz` 回吐机器主机名（`socket.gethostname()`，实测 `"host": "zhen"`）。
   `/healthz` 是匿名可读的健康检查，主机名不是产品信息，却让匿名调用方拿到部署机器的
   名字，与 P4 同类（同属 §2.2 的"主机指纹"）。`port` 字段另有既有契约
   （`tests/test_container_port_contract.py` 断言它必须反映实际监听端口），本批**不动 `port`**。

本批要求：**匿名响应不出现内网物理标识、主机名与绝对路径；系统提示不出现绝对工作目录与
主机指纹；设置页仍然可用（能看到"已配置/未配置"、能改配置且不会误清空）。**

---

## 1. 范围与非目标

### 1.1 范围内

| 项 | 生产入口 |
| --- | --- |
| `/api/sources` 敏感字段收敛 | `bi_agent/web/app.py::get_sources_endpoint`（`app.py:1722`） |
| PUT 侧的占位符兼容 | 同文件 `put_sources_endpoint` / `_put_sources_endpoint_impl`（`app.py:2072` 起） |
| 系统提示去掉绝对工作目录与主机指纹 | `bi_agent/web/session.py::WebSession._build_system_prompt`（`session.py:489`）、`open_claude/prompt.py::build_system_prompt`（`:136`，`# Environment` 块 `:203`） |
| `/api/system-prompt` 出口收敛 | `bi_agent/web/app.py::get_system_prompt`（`app.py:2253`） |
| `/healthz` 不再回吐主机名 | `bi_agent/web/app.py::healthz`（`app.py:1152`，`"host": socket.gethostname()`） |
| 匿名面统一扫描（可复用检查器） | 红测 + 实现提示词；实现侧建议抽一个共用扫描函数 |

### 1.2 非目标（本批明确不做）

* **不做鉴权体系**：不新增登录、不新增 token 校验、不改网关；本批只做"字段收敛"，
  即**即使匿名可读，也读不到内网物理标识与绝对路径**；
* 不改 `/api/chat` 的模型调用协议、不改分析策略（`analysis_policy.py`）、不改 SOP 语义；
* 不改评测集（570 / P0 147 / known_gap 0 必须不变）；
* 不改前端交互（设置页输入框仍可编辑并保存；只是预填值变成占位符）；
* 不处理 P1/P3/P6（安全拒绝、行动/预测意图、版本落后）——那三项在仓库 HEAD 已修复，
  属**部署落后**，见 §6 批次划分；
* 不做 P5（工具链重复调用与耗时）——独立批次。

---

## 2. 目标设计

### 2.1 `/api/sources`：敏感字段不回真值

`doris` 内三个字段属于敏感面：`jdbc_url`、`api_url`、`username`。契约：

| 情况 | 返回 |
| --- | --- |
| 已配置 | **占位符**（非空、与真值不同、不匹配任何内网指纹，例如 `（已配置，见服务端环境变量）`） |
| 未配置 | 空串 `""` |
| `password` | 始终 `""`（既有约定，保持不变） |

并新增三个布尔标志，供设置页显示"已配置/未配置"：
`doris.jdbc_configured`、`doris.api_url_configured`、`doris.username_configured`。

**保留可读（产品必需，逻辑标识而非物理地址）**：`doris.driver`、`doris.database`、
`doris.value`、`ontology.*`（选项/active/`remote_repositories[]` 的 `id`/`name`/
`dorisDatabase`/`cdcTopicPrefix`）、`database.*`、`retrieval.*`、`atomic_source.*`。

### 2.2 绝对路径与主机指纹：匿名响应里一律不出现

对**任何**匿名 GET 响应体，以下模式一律不得出现：

| 类别 | 模式 |
| --- | --- |
| 内网地址 | `IPv4:port`；私网段前缀（`10.` / `172.16-31.` / `192.168.`） |
| 连接串 | `jdbc:<driver>:`、`http(s)://<私网 IP>` |
| 绝对路径 | `/app`、`/srv/…`、`/home/…`、`/Users/…`、`/opt/…`、`/var/…`、`/etc/…`、`/root/…`、`/data/…` |
| 主机指纹 | 主机名、`Platform:` / `OS:` 的取值、容器路径 |
| 环境变量 | `ONTOLOGY_*` / `DORIS_*` / `TEAM_API_KEY` 等变量的**值**（变量名可以出现） |
| 凭据 | 任何 token / password 真值（既有约定，继续有效） |

说明：上表对**任何匿名 GET 响应体**生效，因此 `/healthz` 的 `host` 字段（当前为
`socket.gethostname()`）也在收敛范围内：**删除该字段或返回常量占位符**均可，但不得回主机名。
`/healthz` 的 `port` 字段保持不变（既有契约要求它反映实际监听端口）。

### 2.3 PUT 兼容：占位符不得写进配置，也不得误清空

设置页会把 GET 拿到的值原样回填并可能原样提交。因此：

1. PUT 收到**占位符**（即 GET 返回的那个值）→ 视为"保持原值"（与既有 `None` /
   空串语义一致），**不得**把它写成配置；
2. GET → PUT 往返（不改动任何输入框）必须**无副作用**：配置值不变、响应不变；
3. 这三个字段的"清除"语义保持既有方式（空串/`None` 的现有行为不变），不在本批引入新语义。

### 2.4 系统提示：不出现绝对工作目录与主机指纹

1. 会话系统提示（`WebSession.system_prompt`，也就是 `GET /api/system-prompt` 的返回值，
   以及发给模型的那一段）**不得包含绝对文件系统路径**，也不得包含 `Working directory:`
   行的路径、`Platform:` / `OS:` 的具体取值；
2. 该 Agent 的工具白名单里没有文件/shell 工具（安全批次已固化），因此环境块里的工作目录
   对模型没有用途 —— 允许**整块移除** `# Environment`，也允许只保留非敏感项
   （如日期），两种实现都符合契约；
3. **不得**因为收敛而改动其余段落与工具清单：`# Tools`、`# Skills`、`# Guidelines`、
   `# Doing Tasks`、`# Safety`、`# AnalysisContext`、输出展示规范、分析深度约束必须保留；
4. 工具执行仍使用**真实**工作目录：`WebSession.cwd`、`build_source_executors(...)`、
   会话恢复的 cwd 语义不变；收敛只作用于**提示文本**。

### 2.5 安全与凭据

* 不新增配置项、不新增鉴权头、不读取真实凭据；
* 错误文案不得回显 base URL、token 或内部绝对路径（沿用既有约定）。

---

## 3. 当前行为（生产复现）

真实入口：`TestClient(app)` 的 `GET /api/sources`、`GET /api/system-prompt`，以及
`WebSession(cwd, AgentDef(...), OntologyStore()).system_prompt`。伪造 STATE 值复现：

```
STATE.doris_jdbc_url = "jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?useSSL=false"
STATE.doris_username = "svc_biuser_pdt"
STATE.doris_api_url  = "http://172.16.6.163:8030/api/query"

GET /api/sources →
  {"doris": {"api_url": "http://172.16.6.163:8030/api/query",
             "jdbc_url": "jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?useSSL=false",
             "driver": "com.mysql.cj.jdbc.Driver",
             "username": "svc_biuser_pdt", "password": "",
             "database": "ontology_demometaerp_scm_po"}}
  → 内网 host:port、账号、连接串全部原样返回（三处断言全红）

WebSession(...).system_prompt 的 # Environment 块 →
  "- Working directory: /Users/…/eimosp-ontology-agentic-analytics | - Platform: darwin |
   - OS: Darwin 25.5.0 | - Git repo: true | - Date: 2026-09-21 | - Shell: bash"
  → 绝对工作目录 + 主机指纹（红）
```

线上（0.1.7）同源：`/api/sources` 返回 `jdbc:mysql://172.16.6.163:9030/…` 与
`username: "admin"`；`GET /api/system-prompt` 内容含 `- Working directory: /app`，
模型因此在回答里给出 `/app`。

### 3.1 `/healthz`（HEALTH，本批新确认）

```
GET /healthz →
  {"ok":false,"status":"not_ready","app":"…","version":"0.1.9",
   "host":"zhen",                 ← socket.gethostname()，匿名可读
   "port":8765,"uptime_seconds":…,"dependencies":{…}}
```

未配置依赖时 `status` 为 `not_ready`（HTTP 503，既有契约
`test_healthz_never_requires_a_model_call`），但**响应体仍然回吐主机名**。

### 3.2 非生产入口的判定说明

三处都通过**真实生产入口**复现（`TestClient(app)` 打的 `GET /api/sources`、
`GET /api/healthz`、`GET /api/system-prompt`，以及
`WebSession(cwd, …).system_prompt`），不是 evaluator 或 fixture 造成的假象：
`/api/sources` 与 `/healthz` 走的是线上同一份 `app.py` 路由函数，
`system_prompt` 走的是线上同一份 `bi_agent/web/session.py` +
`open_claude/prompt.py`。已核对：known-gap evaluator 与本缺陷无关（本批不新增
known gap），`expected` 与安全边界一致，且**这三处暴露没有任何后续工具层门禁**——
它就是匿名 HTTP 出口本身。

**实测（2026-09-21，HEAD `53ecaad`，`.venv/bin/python -m pytest -q tests/test_anonymous_read_surface_red.py`）**：
收集 25 条，**11 条红 / 14 条绿**（pytest 汇总行因 `subTest` 分别计票显示为
`13 failed, 15 passed`；R15 一条用例覆盖 3 个端点，3 个子断言失败）。

```
R1  AssertionError: ['ipv4_with_port:172.16.6.163:8030', 'private_ipv4:172.16.6.163'] != []
R2  AssertionError: 'jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po' unexpectedly found in …
R3  AssertionError: 'svc_biuser_pdt' unexpectedly found in …（username='svc_biuser_pdt'）
R4  AssertionError: 'jdbc_configured' not found in {'value': '__doris_api__', 'active': True, …}
R5  AssertionError: 'jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?useSSL=false'
                   != 真值（占位符缺失）：jdbc_url 不得回吐真值
R9  AssertionError: Lists differ: ['absolute_path:/Users/sher/Boulderaitech/…'] != []
R10 AssertionError: 'Working directory' unexpectedly found in '# Environment\n- Working directory: /Users/…'
R11 AssertionError: Lists differ: ['absolute_path:/Users/…', 'working_directory_line:Working directory'] != []
R12 AssertionError: '- Platform:' / '- OS:' 仍出现在会话提示里
R15 三个端点全部失败：
    /healthz            → ['hostname_value:zhen']
    /api/sources        → ['ipv4_with_port:…', 'private_ipv4:…', 'jdbc_url:…', 'secret_value:…']
    /api/system-prompt  → ['absolute_path:…', 'working_directory_line:Working directory']
R16 AssertionError: 'zhen' == 'zhen' : /healthz 的 host 字段仍是主机名 'zhen'
```

---

## 4. Red Test 对照表

文件：`tests/test_anonymous_read_surface_red.py`（离线，`TestClient(app)` + 伪造 STATE 与
`WebSession`，无凭据、无真实服务、无 LLM、不碰用户数据、**不调用任何删除/重置接口**）。

| 编号 | 覆盖 | 期望今天为红 |
| --- | --- | --- |
| R1 | `/api/sources` 不出现 `IPv4:port` / 私网段 | 红 |
| R2 | `/api/sources` 不出现 `jdbc:` / 内网 `http://<ip>` | 红 |
| R3 | `/api/sources` 不出现数据库账号名 | 红 |
| R4 | `doris.*_configured` 三个布尔标志存在且为真 | 红 |
| R5 | 已配置字段返回占位符（非空、非真值、不含内网指纹、多次调用稳定） | 红 |
| R9 | 会话系统提示不含绝对路径 | 红 |
| R10 | 会话系统提示不含 `Working directory:` 行与 cwd 值 | 红 |
| R11 | `GET /api/system-prompt`（data）不含绝对路径与主机指纹 | 红 |
| R12 | 会话系统提示不含 `Platform:` / `OS:` 取值等主机指纹 | 红 |
| R15 | 匿名 GET 面统一扫描（`/healthz`、`/api/sources`、`/api/system-prompt`） | 红（3 个端点全红） |
| R16 | `/healthz` 的 `host` 不回吐主机名 | 红 |
| G6 | `doris.password` 仍为空串 | 绿（护栏） |
| G7 | GET → PUT 往返无副作用（配置不变、不泄露、不误清空） | 绿（护栏） |
| G8 | 逻辑标识仍可读（`driver` / `database` / 选项 / active / 仓库列表） | 绿（护栏） |
| G13 | 提示段落与工具清单保留 | 绿（护栏） |
| G14 | `WebSession.cwd` 仍为真实工作目录（工具语义不变） | 绿（护栏） |
| M1–M9 | Mutation Guards（见 §5） | 绿（9 条，今天即绿） |

编号说明：编号沿用测试文件里的 `R*` / `G*` 标记（`R6–R8` 未使用），不重排，
避免与既有批次的红测编号冲突。

---

## 4.1 今天为绿、但属于"实现后必须仍然绿"的护栏

| 护栏 | 锁定的事实 |
| --- | --- |
| G6 | `doris.password` 仍返回 `""`（口令面本来就没有泄露） |
| G7 | `GET /api/sources` → `PUT /api/sources` 原样往返：配置值不变、不误清空、PUT 不报 400 |
| G8 | 逻辑标识仍可读：`driver` / `database` / `options` / `active` / 仓库列表 |
| G13 | 提示段落（`# Tools` / `# Guidelines` / `# AnalysisContext` …）与工具清单保留 |
| G14 | `WebSession.cwd` 仍是真实工作目录（工具执行语义不变） |

## 5. Mutation 方案

| 变异 | 会被杀死的用例 |
| --- | --- |
| 继续返回真实 `jdbc_url` / `api_url` / `username` | R1、R2、R3 |
| 用保留了私网前缀的"掩码"（`172.16.*.*`） | R1（私网段指纹） |
| 占位符等于真值 / 为空串却把 `*_configured` 置假 | R4、R5 |
| 只改字段不改 PUT：占位符被写进配置 | G7 |
| 把整段系统提示砍掉（含工具清单） | G13 |
| 提示里保留 cwd 行但只把值改成相对路径 | R10 仍红（行仍在 → 实现必须删行或删块） |
| 提示里保留 `Platform:` / `OS:` 值 | R12 |
| 收敛提示时顺带改了工具执行 cwd | G14 |
| 只收敛 `/api/sources`、不收敛 `/api/system-prompt` | R11、R15 |
| `/healthz` 继续回吐 `socket.gethostname()` | R16、R15（`/healthz` 子断言） |
| 把主机名换成掩码但保留可识别前缀（`172.16.*.*`） | `test_masked_but_range_preserving_value_is_still_caught`（M） |
| 检查器本身分不清"主机名"与普通词（假阳性） | `test_hostname_value_in_a_response_is_caught`（M，仅在本机 hostname 有区分度时生效） |

---

## 6. 批次划分（本批是第 1 批）

| 批次 | 内容 | 性质 | 消掉验收里的 |
| --- | --- | --- | --- |
| **批次 1 · 本批** | 匿名读取面收敛：`/api/sources` 内网字段 + 系统提示绝对工作目录/主机指纹 + `/healthz` 主机名 | 代码（Spec + 红测 + 提示词，本轮不实现） | P4、P2 根因 |
| 批次 2 | 工具链重复调用与耗时（demo2 一次提问 16 次工具调用 / 80.5s） | 代码 | P5 |
| 批次 3 | 发布上线 + 线上复验（把 0.1.9 之后的能力部署到 PDT / demo2，并把只读验收做成可重复脚本） | 运维（**需单独授权**） | P1、P2 现象、P3、P6 |

说明：P1（安全拒绝未落策略层）、P3（行动/预测意图漏识别）在仓库 HEAD 已修复并全绿
（`test_analysis_security_refusal_red.py` 61 passed、`test_analysis_action_intent_red.py`
51 passed、`test_analysis_forecast_intent_red.py` 64 passed），线上复现只是因为部署停在
**0.1.7**；这两个问题的解法是批次 3，不是新的代码批次。

---

## 7. 实现验收清单

1. `/api/sources` 的 `jdbc_url` / `api_url` / `username` 不回真值，未配置返回空串，
   并新增 `jdbc_configured` / `api_url_configured` / `username_configured`；
2. 响应（含 `ontology` / `database` / `retrieval` / `atomic_source` 全部子对象）不出现
   §2.2 的任何模式；
3. PUT 兼容占位符，GET→PUT 往返无副作用；
4. 会话系统提示与 `/api/system-prompt` 不含绝对路径、`Working directory:` 行、主机指纹；
5. `/healthz` 不再回吐主机名（删除 `host` 字段或返回常量占位符），且 `port` 契约不变；
6. 提示段落与工具清单保留；`WebSession.cwd` 与工具执行 cwd 语义不变；
7. 红测 `tests/test_anonymous_read_surface_red.py` 全绿（25 条：11 红转绿 + 14 护栏保持绿）；
8. 未触碰 `port` 字段契约：`tests/test_container_port_contract.py` 保持通过；
9. `tests/test_regressions.py`、`tests/test_concurrency.py`、`tests/test_application_base_path.py`
   等既有前端/接口门禁不劣化；全量 `pytest -q tests` 0 failed；
10. 评测 `smoke` / `adversarial` / `recorded-provider` / `regression` / `all` 全绿，
    570 / P0 147 / known_gap 0 不变；
11. 未知字段策略：**只增不减**（前端忽略未知字段，但既有字段名不得删除）；
12. 未部署、未读取真实凭据、未调用删除/重置接口、未新增鉴权体系。

---

## 8. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 设置页输入框变成占位符后，用户直接保存会清空配置 | §2.3 + 红测 G7 锁定"占位符=保持原值" |
| 运营需要查看真实连接串 | 真值仍在服务端环境变量/`.env`；需要可视化的场景另开"管理员鉴权"批次（本批不做鉴权） |
| 提示去掉 `# Environment` 后模型行为变化 | 该 Agent 无 shell/文件工具（安全批次固化），环境块无功能用途；G13 锁定其余段落不变 |
| 逻辑库名仍可见引起争议 | §2.1 明确保留并列为决策点：如需连逻辑库名一起隐藏，另开一句需求 |
| 运维/监控依赖 `/healthz` 的 `host` 做实例区分 | `/healthz` 是匿名端点，不适合承载实例区分；如确需 per-instance 诊断，应放到需要凭据的诊断接口（本批不做鉴权，故建议先删字段）。删除 `host` 前先确认监控只读 `status` / `ok` / `version` |
| 本批新确认的 `/healthz` 主机名不在原始验收报告里 | 已单独标注为 §3.1；它属 P4 同类（匿名可读的内网指纹）。若产品决定保留 `host`，可把 R16 移出本批（记录为残留观察），其余红测不受影响 |
| 回滚 | 还原 `get_sources_endpoint` / `put_sources_endpoint` 的字段映射与 `session.py::_build_system_prompt`；红测文件保留为回归 |

---

## 9. 残留观察（本批不处理，仅记录）

以下问题在复核过程中可见，但**不属于本批范围**，也没有对应断言；记录以免遗忘：

| 观察 | 位置 | 说明 |
| --- | --- | --- |
| 提示里仍保留 Claude Code 风格的 `# Skills`（`/commit`、`/review`…）与 `# Doing Tasks`（Read/Write/Edit/Glob/Grep/Bash） | `open_claude/prompt.py` | 该 Agent 的工具白名单里没有这些工具，段落对模型是无效指引；属 Prompt 一致性清理，与本批的"路径/主机指纹收敛"无关 |
| `/api/system-prompt` 本身未鉴权 | `bi_agent/web/app.py::get_system_prompt` | 本批只收敛内容（不泄露基础设施），不加鉴权；如要限制读取，需单独一批 |
| `/api/sources` 暴露内网 `base_url`（远程本体库地址） | `get_sources_endpoint` | 远程仓库的 `base_url` 属内网地址，但它是产品用来显示"当前指向哪个环境"的字段；线上实测指向 `pdt-dev` / `demo2`（非私网 IP），暂视为逻辑标识保留，如需隐藏另开一句需求 |
| 逻辑库名 `ontology_demometaerp_scm_po` 仍可见 | `doris.database` | §2.1 列为决策点 |
