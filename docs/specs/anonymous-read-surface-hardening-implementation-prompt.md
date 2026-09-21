# 实现提示词：匿名读取面收敛（分析 Agent 线上验收批次 1）

> 把下面整段交给实现人员（人或 Agent）。本批只做**匿名读取面的字段收敛**：让
> `GET /api/sources`、`GET /api/system-prompt`、会话系统提示、`GET /healthz` 不再把
> 内网物理标识（host:port、连接串、账号）、机器主机名和绝对工作目录交给匿名调用方。
> 不改分析策略（`analysis_policy.py`）、不改 SOP/评测集、不改图表与前端交互、不加 known gap、
> 不加鉴权体系。

---

## 0. 你的任务

线上只读验收（PDT / demo2）与仓库 HEAD 复现都确认了三处**匿名可读**的内部信息暴露：

1. `GET /api/sources` 的 `doris` 块原样返回连接真值：
   `jdbc_url = jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?useSSL=false`、
   `api_url = http://172.16.6.163:8030/api/query`、`username = svc_biuser_pdt`（线上实测
   `"admin"`）。`password` 已是空串，因此**没有凭据泄露**，但匿名调用方拿到了内网
   host:port + 数据库账号 + 库名。
2. 会话系统提示里的 `# Environment` 块带 `- Working directory: <绝对路径>`
   （`open_claude/prompt.py:203-204`，值来自 `get_environment_info()`，即**进程 cwd**，
   容器里是 `/app`），而 `GET /api/system-prompt` 未做任何收敛就把整段提示返回给浏览器；
   同一段提示也发给模型，于是线上模型把 `/app` 抄给了用户。
3. `GET /healthz` 回吐机器主机名（`"host": socket.gethostname()`，实测 `"host": "zhen"`）。
   匿名健康检查不需要知道部署机器叫什么。

**不要**只把三个真值换成 `"***"` 就交差：占位符必须能区分"已配置/未配置"、必须让设置页
仍然能改配置且不会误清空（GET→PUT 往返无副作用），系统提示要**删行**而不是只把值改成
相对路径，`/healthz` 要**不回主机名**但**不动 `port`**。

## 1. 先读

1. `docs/specs/anonymous-read-surface-hardening.md`（本批 Spec，逐节读完；§2.1–§2.4 与 §7 是重点；
   §3.1 是本次新确认的 `/healthz` 主机名，§9 是明确不做的残留观察）
2. `tests/test_anonymous_read_surface_red.py`（红测 = 验收标准；`LEAK_PATTERNS` 是 §2.2 的
   可执行版本，含掩码私网地址与主机名两类检测）
3. 生产代码：
   - `bi_agent/web/app.py::get_sources_endpoint`（`app.py:1722`，`doris` 块在函数末尾）
   - `bi_agent/web/app.py::put_sources_endpoint` / `_put_sources_endpoint_impl`（`app.py:1985` 起；
     `DORIS_SOURCE_VALUE` 分支在 `app.py:2110`）
   - `bi_agent/web/app.py::healthz`（`app.py:1152`）
   - `bi_agent/web/app.py::get_system_prompt`（`app.py:2253`）
   - `bi_agent/web/session.py::WebSession._build_system_prompt`（`session.py:489`）
   - `open_claude/prompt.py::build_system_prompt`（`:136`，`# Environment` 块 `:203`）
   - `open_claude/config.py::get_environment_info`（`:59`）
4. 前端消费点（**默认不改**，但要确认不被破坏）：
   `frontend/src/runtime.js:377-381`（读 `data.doris.*`）、`:2485-2490`（回填输入框）、
   `:2580-2583`（保存时回传 payload）、DOM id `sources-doris-jdbc` / `-database` / `-driver` /
   `-user` / `-pass`
5. 既有门禁：`tests/test_container_port_contract.py`（`/healthz` 的 `port` 契约）、
   `tests/test_regressions.py`（`test_healthz_never_requires_a_model_call` 要求未就绪时 503）、
   `tests/test_application_base_path.py`、`tests/test_concurrency.py`、`dataset/evals/analytics`
   （570 / P0 147 / known_gap 0）

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_anonymous_read_surface_red.py
```

当前实测（HEAD `53ecaad`）收集 **25 条 = 11 红 / 14 绿**（pytest 汇总行因 `subTest`
分别计票显示为 `13 failed, 15 passed`）。11 条红逐条如下：

| 用例 | 实测失败原因 |
| --- | --- |
| R1 | `/api/sources` 返回 `['ipv4_with_port:172.16.6.163:8030', 'private_ipv4:172.16.6.163']` |
| R2 | `'jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po'` 出现在响应里 |
| R3 | `'svc_biuser_pdt'` 出现在响应里（线上是 `admin`） |
| R4 | `doris` 块里没有 `jdbc_configured` / `api_url_configured` / `username_configured` |
| R5 | `jdbc_url` 仍等于真值：占位符不存在 |
| R9 | 会话提示里出现 `absolute_path:/Users/…/eimosp-ontology-agentic-analytics` |
| R10 | `- Working directory: /Users/…` 行仍在 |
| R11 | `GET /api/system-prompt` 同样带绝对路径与 `Working directory` 行 |
| R12 | 会话提示里仍有 `- Platform: darwin` / `- OS: Darwin 25.5.0` |
| R15 | 三个匿名端点全红：`/healthz` → `hostname_value:zhen`；`/api/sources` → 私网地址 + 连接串 + 账号；`/api/system-prompt` → 绝对路径 + `Working directory` |
| R16 | `/healthz` 的 `host` 字段仍等于 `socket.gethostname()` |

14 条绿色用例是护栏，**必须保持绿**：G6（`password` 仍为空串）、G7（GET→PUT 原样往返
无副作用、不误清空、不 400）、G8（`driver` / `database` / 选项 / active 等逻辑标识仍可读）、
G13（提示段落与工具清单保留）、G14（`WebSession.cwd` 仍是真实工作目录），以及 M1–M9 的
Mutation Guard（真值块、掩码私网地址、主机名、干净占位符、带绝对 cwd 的提示、
容器路径、相对 cwd 行、整段删提示、真实提示画像）。

**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。红测里的
`LEAK_PATTERNS` 是验收口径，实现必须服从它，而不是反过来。

## 3. 实现要求

### 3.1 `/api/sources`：不返回真值，返回占位符 + 布尔标志

`doris` 块里三个敏感字段（`jdbc_url`、`api_url`、`username`）：

| 情况 | 返回 |
| --- | --- |
| 已配置（真值非空） | **占位符**：非空、与真值不同、不匹配任何 §2.2 模式（不能出现
`jdbc:`、`172.16.`、`192.168.`、内网 `http://`、绝对路径） |
| 未配置（真值为空串） | 空串 `""` |
| `password` | 始终 `""`（既有约定，不改） |

并新增三个布尔标志：`doris.jdbc_configured`、`doris.api_url_configured`、
`doris.username_configured`（真值非空即 `True`）。

**保持不变（产品必需的逻辑标识，红测 G8 锁定）**：`doris.driver`、`doris.database`、
`doris.value`、`doris.active`、`ontology.*`、`database.*`、`retrieval.*`、`atomic_source.*`、
`Cache-Control: no-store` 响应头。

建议：占位符用一个模块级常量（例如 `SOURCES_REDACTED_PLACEHOLDER`），
`GET` 与 `PUT` 两侧共用同一个常量，避免两处文案漂移（R5 断言"多次调用稳定"）。
`jdbc_configured` 这类字段名必须与红测一致。

### 3.2 PUT：占位符 = "保持原值"，且必须在校验之前解析

设置页会把 GET 拿到的值原样回填并可能原样提交（`frontend/src/runtime.js:2580-2583`），
因此 `_put_sources_endpoint_impl` 的 `DORIS_SOURCE_VALUE` 分支（`app.py:2110` 起）必须：

1. 先把 `req.doris_jdbc_url` / `req.doris_api_url` / `req.doris_username` 中的**占位符**
   归一化成"未提供"（等价于 `None`），再走既有的
   `(req.X or source.X or "")` / `is not None` 取值逻辑；
2. **顺序很重要**：`api_url.startswith(("http://","https://"))` 与
   `_doris_http_conn(api_url, database)` 校验必须在归一化之后执行，否则占位符会被当成
   非法 URL → 400（红测 G7 会失败）；
3. GET → PUT 原样往返必须无副作用：`source.doris_jdbc_url` / `doris_api_url` /
   `doris_username` 三个值不变、`doris_password` 不被清掉、不触发多余的重新注册；
4. "清除"语义不放宽也不新增：空串/`None` 的既有行为保持原样（不要把空串当成占位符）；
5. 注意 `_source_binding_signature` 的比较：往返时签名不变 → `changed` 应清空，不得因此
   重置会话（既有逻辑已有该收敛，别破坏）。

### 3.3 系统提示：删掉绝对工作目录与主机指纹

可改的最小面是 `open_claude/prompt.py::build_system_prompt` 的 `# Environment` 块，或
`bi_agent/web/session.py::_build_system_prompt` 拼装处（二选一，行为一致即可）：

1. **必须移除**：`- Working directory: {abs}` 整行（只把值改成相对路径不算通过，R10 断言
   的是这一行不存在）；`- Platform:`；`- OS:`；以及任何等价的主机/容器指纹行；
2. **可以保留**：`- Date: <today>`、`- Git repo: true/false`；也可以**整块移除**
   `# Environment`——该 Agent 的工具白名单（`.claude/agents/bi-analyst.md`）里没有
   shell/文件工具，环境块对模型没有用途；
3. **不得**改动其余段落：`# Tools`、`# Skills`、`# Guidelines`、`# Doing Tasks`、
   `# Safety`、`# AnalysisContext`、输出展示规范、分析深度与卡片约束（G13 锁定）；
4. **不得**改动工具执行语义：`WebSession.cwd`、`build_source_executors(...)`、
   `_cwd_file` / `_cwd_relative_value` / 会话恢复的 cwd 全部保持真实工作目录（G14 锁定）。
   收敛只作用于**提示文本**；
5. `GET /api/system-prompt`（`app.py:2253`）返回的就是这段提示，因此按 §3.3 收敛后它自然
   干净；不要为此再加一层字符串替换（会把两份实现永久绑在一起）。

### 3.4 `/healthz`：不回主机名，`port` 不动

`bi_agent/web/app.py::healthz`：

1. **删除** `"host": socket.gethostname()`，或改为常量占位符（红测只要求它不等于
   `socket.gethostname()`）；同步更新函数 docstring 里"响应字段固定"的列举；
2. **保留** `port`（`tests/test_container_port_contract.py` 断言它必须反映实际监听端口）
   以及 `ok` / `status` / `app` / `name` / `version` / `uptime_seconds` / `configured` /
   `llm_call` / `dependencies` / `coordination`；
3. **保留**未就绪时 503 的语义（`tests/test_regressions.py::test_healthz_never_requires_a_model_call`）；
4. 如果运维确实需要 per-instance 诊断信息，不要放回匿名接口——在交付报告里说明，
   留待"需要鉴权的诊断接口"批次。

### 3.5 前端与文档

1. 前端**默认不改**：回填的值会变成占位符文本，用户直接保存时靠 §3.2 保证无副作用；
   `sources-doris-*` 的 DOM id 与 payload 字段名不得改；
2. 如果顺手做体验优化（例如输入框留空 + 用 `*_configured` 显示"已配置"），必须保证
   §3.2 的 PUT 语义与红测 G7 不变、且不引入新的真值回填路径；
3. 同步文档：`DEPLOYMENT.md` / `README.md` 里如果列了 `/healthz` 的响应字段或
   `/api/sources` 的返回字段，按实际实现更新（不要留下"host"这类已删字段）。

### 3.6 明确不做

* 不新增登录 / token / 网关鉴权（本批只做字段收敛，不做鉴权体系）；
* 不改 `bi_agent/tools/analysis_policy.py`、SOP、Prompt 语义（除 §3.3 的环境块）；
* 不改评测集（570 / P0 147 / known_gap 0 必须不变）、不改图表、不改会话协议；
* 不处理 §9 的残留观察（提示里的 Claude Code 风格段落、远程 `base_url`、逻辑库名）；
* 不处理 P1/P3/P5/P6（已在仓库修复或属其他批次）；
* 不读取真实凭据、不跑 live、不部署、不 commit 到 `master`/`main`。

## 4. 需要产品/运维确认的点（不得假装已确认）

1. **是否连逻辑库名 `doris.database` 一起隐藏**？Spec §2.1 明确保留为逻辑标识，红测 G8
   锁定它仍可读。若要一起隐藏，必须先改 Spec 与红测（**不要**在实现里悄悄改）。
2. **占位符文案**：Spec 建议 `（已配置，见服务端环境变量）`；实现可自选，但必须非空、
   非真值、不含 §2.2 模式，且 GET/PUT 共用一个常量。
3. **`# Environment` 是删块还是只留日期**：两种都符合契约；请选择一种并在报告里写明，
   不要出现"值是相对路径但行还在"的中间态。
4. **`/healthz` 的 `host` 是删字段还是给占位符**：需要与运维确认没有监控依赖该字段的
   **取值**（只读 `status`/`ok`/`version` 的监控不受影响）。这是本批新确认的第三处暴露，
   如产品决定保留，必须回来把 R16 移出本批并记录为残留观察，其余红测不受影响。
5. **远程本体库 `base_url`**（`ontology.production.base_url`）本批保留不动：它属内网地址，
   但产品用它显示"当前指向哪个环境"。若要求一起隐藏，另开一句需求。

## 5. 完成前必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_anonymous_read_surface_red.py          # 目标：25 passed
.venv/bin/python -m pytest -q tests/test_container_port_contract.py            # port 契约不得回退
.venv/bin/python -m pytest -q tests/test_regressions.py tests/test_concurrency.py \
    tests/test_application_base_path.py
.venv/bin/python -m pytest -q tests/                                          # 全量 0 failed
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
```

* 570 / P0 147 / known_gap 0 必须不变；全量 `pytest -q tests` 失败项不得多于改动前基线
  （改动前基线：1171 passed / 0 failed / 25 skipped）；
* 某项因缺少真实 Provider 而无法运行时，如实标 `not_measured`，**不得**写成 passed；
* 未确认项按 §4 处理：确认了就按确认实现，没确认就按 Spec 默认值实现并在报告里写明。

## 6. 交付报告（必须包含）

1. 修改文件清单与每个文件的改动要点（含被删字段）；
2. 红测从 `11 红 / 14 绿` 到 `25 passed` 的实际输出；
3. 逐端点的收敛前后对照：把 `GET /api/sources`、`GET /api/system-prompt`、
   `GET /healthz` 的响应（可以脱敏为键名 + 是否命中 §2.2 模式）各贴一次；
4. GET→PUT 往返证据：原样 PUT 后 `STATE.doris_jdbc_url` / `_api_url` / `_username` 不变、
   `password` 未被清空、响应 `status < 400`；
5. `/healthz` 的 `host` 处理方式与 `port` 契约回归结果；
6. 系统提示收敛方式（删块/留日期）与段落保留证据（`# Tools` / `# Guidelines` /
   `# AnalysisContext` 仍在，工具清单完整）；
7. 误伤验证：设置页仍能改配置（改成一个**新**的合法 `api_url` 时确实生效）、
   未配置状态下三个字段仍返回空串、`driver`/`database`/选项/active 仍可读；
8. 评测门禁结果与 known gap 数量；
9. §4 各项的确认结果或默认取值说明；
10. 明确说明：未新增鉴权体系、未读取真实凭据、未跑 live、未部署、未创建 MR/tag/Release。
