# 会话回收站 Spec（把「记忆管理」页做成删除会话的回收站）

> 来源：2026-09-21 需求「记忆管理页做成删除会话的回收站」。
> 红测：`tests/test_conversation_trash_red.py`
> 实现提示词：`docs/specs/conversation-trash-recycle-bin-implementation-prompt.md`
>
> 本批把「删除会话」从**物理删除**改成**移入回收站**，并在既有的
> 「记忆管理」（`#view-memory`）页面里提供回收站列表、恢复、彻底删除与清空。
> 不改分析策略 / SOP / 评测集 / 图表 / 会话协议，不引入鉴权体系。

---

## 0. 一句话结论

**可行。** 现状是三条"删掉就没了"的路径：

1. 侧边栏「最近」条目上的 `✕` → `DELETE /api/conversations/{cid}` → `ConversationStore.delete()`
   直接 `unlink` 快照文件并从索引移除（**硬删除**，无二次确认、无撤销）；
2. 活跃会话超过上限（`MAX_CONVERSATIONS = 100`）时由 `_prune()` 自动**物理删除**最旧的；
3. 报表模式与上传报表各自有删除入口（`DELETE /api/report/{rid}`）。

本批把 (1)(2) 改成"先进回收站、保留期内可恢复"，并把回收站放进已有页面：
「记忆管理」（`frontend/src/shell.html` 的 `#view-memory`，目前只有一个"重置当前对话"按钮），
新增「回收站」区块（列表 / 恢复 / 彻底删除 / 清空），保留期默认 30 天、可配置。

---

## 1. 范围与非目标

### 1.1 范围内

| 项 | 生产入口 |
| --- | --- |
| 删除语义：软删除（移入回收站） | `bi_agent/web/conversations.py::ConversationStore.delete`（`:747`） |
| 回收站存储与索引隔离 | 同文件 `_record_paths`（`:404`）、`_rebuild_index`（`:407`）、`_index`（`:423`）、`_prune`（`:528`） |
| 自动裁剪改为进回收站 | 同文件 `_prune`（`:528`，由 `_save_unlocked` `:681` 调用） |
| 回收站 HTTP 接口 | `bi_agent/web/app.py` 会话区（`GET /api/conversations` `:2779` 一带） |
| 记忆管理页回收站区块 | `frontend/src/shell.html`（`#view-memory` `:547`）、`frontend/src/runtime.js`（导航 `:1225`、`deleteRecent` `:1450`） |

### 1.2 非目标（本批明确不做）

* **不引入鉴权/登录**：沿用批次 1 的边界——匿名接口只做"内容收敛"，不新增身份校验，
  所以本批只保证**回收站接口不返回会话正文**（§2.8），把"谁能删"留到鉴权批次；
* 不做"共享/多人同时编辑历史"、不做云端同步（`_conversation_sync` 目前没有调用点）；
* 不动上传报表库（`DELETE /api/report/{rid}`）与报表模式自身的会话重置语义；
* 不改 `GET /api/conversations` 的字段（只保证不再出现已删除项）；
* 不改「恢复历史会话」既有链路（`preview` / `assets` / `activate`）的协议；
* 不做版本号变更、不做部署。

---

## 2. 目标设计

### 2.1 删除 = 移入回收站

1. `ConversationStore.delete(cid)` 语义改为**软删除**：
   - 成功：把快照从 `<cwd>/dataset/conversations/<cid>.json` 移到
     `<cwd>/dataset/conversations/trash/<cid>.json`，写入 `deleted_at`（ISO，与 `updated_at` 同格式），
     并把该 `cid` 从 `history_index.json` 移除；返回 `True`；
   - `cid` 形状非法（不匹配 `CID_RE`）→ 返回 `False`（**既有契约，不得放宽**）；
   - 快照不存在 → 返回 `False`；
   - 已删除记录再次删除 → `True`（幂等），不得报错、不得重复写入；
2. `GET /api/conversations/{cid}` 一类的"活跃面"读取（列表 / 预览 / 详情 / 激活）**看不到**已删除记录
   （今天是"文件都没了"，改造后必须靠索引与目录隔离达到同样效果）；
3. 删除响应保持 `{"ok": bool}`（前端 `deleteRecent` 依赖 `response.ok`），**不得**改成 4xx/5xx。

### 2.2 存储与索引

1. 回收站是**同一个 store 目录下的子目录** `trash/`：`glob("*.json")` 不递归，因此
   `_record_paths()` / `_rebuild_index()` / `_index()` / `diagnose()` / `migrate_exact_duplicates()`
   天然看不到回收站里的记录——**不得**复活已删除会话；
2. 已删除记录**不进入** `history_index.json`，也不计入 `MAX_CONVERSATIONS` 的活跃配额；
3. `trash/` 目录按需创建；旧安装目录里没有 `trash/` 时必须正常启动，
   且**不得**把已有 `dataset/conversations/*.json` 误判成垃圾；
4. 回收站中的记录保留原始字段（`messages` / `chat_html` / `dashboard_html` / `ontology_html` /
   `tools_html` / `llm_html` / `sop_steps` / `source_config` / `recovery_state` / 时间戳），
   恢复后必须与删除前**逐字段一致**（除回收站专用字段被移除）。

### 2.3 HTTP 接口契约（新增）

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| `GET` | `/api/conversations/trash` | `{"trash": [summary…], "count": N, "retention_days": D}`，按 `deleted_at` 倒序 |
| `POST` | `/api/conversations/trash/{cid}/restore` | 恢复一条：`{"ok": true, "id": cid}` |
| `DELETE` | `/api/conversations/trash/{cid}` | 彻底删除一条：`{"ok": true}` / 不在回收站 `{"ok": false}` |
| `DELETE` | `/api/conversations/trash?confirm=1` | 清空回收站：`{"ok": true, "purged": N}`；缺 `confirm=1` → `400` |

细则：

1. **路由顺序**：`DELETE /api/conversations/trash` 必须声明在
   `DELETE /api/conversations/{cid}` **之前**，否则会被参数化路由吃掉
   （见 §3 实测：今天 `DELETE /api/conversations/trash?confirm=1` 返回 `{"ok": false}`）；
2. `cid` 形状非法 → `400`；不要落到 `500`；
3. 恢复一条**当前已存在**的活跃 `id`（同 id 冲突）→ `200 {"ok": true, "already_active": true}`，
   **不得**产生第二条记录、不得覆盖活跃记录的内容；
4. 恢复后 `updated_at` **保持删除前的值**：恢复不得走 `save()`（那会把会话顶到「最近」最前面），
   而要"移回文件 + 重建索引条目"；这样恢复后仍回到原来的时间位置；
5. 恢复时必须移除回收站专用字段（至少 `deleted_at`），否则快照会带着过期标记回到活跃面；
6. 清空 / 彻底删除必须**幂等**：重复调用返回 `{"purged": 0}` / `{"ok": false}`，不得报错。

### 2.4 保留期与容量上限

| 项 | 默认 | 说明 |
| --- | --- | --- |
| 保留期 | **30 天** | 环境变量 `CONVERSATION_TRASH_RETENTION_DAYS` 覆盖；`≤ 0` 表示**永不自动清理** |
| 判定 | `deleted_at < now - retention` 才清理 | **严格小于**：正好到期的当天仍然保留（避免"刚删就没"） |
| 回收站上限 | `MAX_TRASH = 500` | 超出时按 `deleted_at` 最旧的先**永久删除**（兜底，防止无限增长） |
| 触发时机 | store 打开时 + 回收站列表请求时 | 与既有 `migrate_titles()` 的"打开时一次性维护"模式一致 |
| 裁剪顺序 | 先清理、再返回列表 | 列表里出现的条目一定还在（可恢复），不能让用户点一条已经不存在的记录 |

环境变量解析失败（空值 / 非数字）→ 取默认 30 天；**不得**因为解析失败而永久保留或立刻清空。

### 2.5 自动裁剪（100 条上限）改为进回收站

`_prune()` 触发的"活跃超上限"记录，也必须**先进回收站**，在保留期内可找回；
它的清理同样受 §2.4 的保留期与 `MAX_TRASH` 约束。

**理由**：今天是"用户没有任何操作，旧会话却永久消失"。改成进回收站后，
"消失"只有两种结局——在回收站里等保留期，或被用户明确彻底删除。

（此条是本批的**产品决策**，见 §6 待确认项 1。）

### 2.6 「记忆管理」页回收站区块（UI 契约）

在 `#view-memory` 的 `page-body` 内新增区块，**保留**既有「重置会话 · 开始新对话」
区块与 `#btn-reset` / `#memory-status`：

| 元素 | 要求 |
| --- | --- |
| 容器 | `id="memory-trash"`，含标题「回收站」 |
| 计数 | `id="memory-trash-count"`，显示条数（如「回收站 · 3 条」） |
| 列表 | `id="memory-trash-list"`，每行 `data-cid="<id>"`，显示标题 / 模式（智能分析·报表分析）/ 删除时间 / 剩余保留天数 |
| 单条恢复 | 行内按钮 `class="memory-trash-restore"`，文案「恢复」 |
| 单条彻底删除 | 行内按钮 `class="memory-trash-purge"`，文案「彻底删除」 |
| 清空回收站 | `id="memory-trash-empty"`，文案「清空回收站」 |
| 状态行 | `id="memory-trash-status"`，反馈「已恢复」「已彻底删除」等 |
| 空态 | 无记录时列表显示「回收站是空的」 |

文案必须让用户明白三件事：

1. 这里的「删除」是**移入回收站**，保留期内可恢复；
2. 「彻底删除 / 清空回收站」**不可恢复**；
3. 保留期（默认 30 天）到期后系统会自动永久清理。

交互要求：

1. 「彻底删除」与「清空回收站」必须**二次确认**（`confirm(...)`），文案要写明不可恢复；
2. 「恢复」无需确认，成功后该条目从回收站列表消失、并回到「最近」列表的**原时间位置**；
3. 进入「记忆管理」时自动拉取回收站（见 §2.7），失败时状态行给出可读提示，不得静默空白；
4. 已删除条目的**正文不进列表**：列表只显示元数据（§2.8）。

### 2.7 前端接线

1. 导航：`data-view="memory"` 的点击必须先加载回收站再把页面显示出来
   ——按既有 `openSources()` / `openRoles()` 的模式新增一个 `openMemory()`，
   在 `runtime.js` 的 `navItems` 处理里加 `else if (view === "memory") { openMemory(); }`；
2. 侧边栏 `deleteRecent(id)` 仍打同一个 `DELETE /api/conversations/{cid}`，
   但按钮 `title` 文案改为「移入回收站」；删除成功后侧边栏刷新、回收站计数同步更新；
3. 前端不得持有"已删除 = 永久消失"的旧文案或旧假设（例如删除后提示"已删除"要改成"已移入回收站"）。

### 2.8 安全与匿名面（与批次 1 一致）

1. `GET /api/conversations/trash` **只返回元数据**：
   `id` / `mode` / `title` / `first_user_question` / `created_at` / `updated_at` / `deleted_at` /
   `turn_count` / `message_count` / 剩余保留天数；
   **不得**返回 `messages` / `chat_html` / `dashboard_html` / `ontology_html` / `tools_html` /
   `llm_html` / `source_config` / `recovery_state`（否则等于把匿名读取面扩大到已删会话）；
2. 响应中不得出现批次 1 §2.2 的模式：绝对路径、`jdbc:` 连接串、内网 `IPv4:port`、主机名；
3. 回收站快照沿用 `sanitize_source_config`——凭据（如 `doris_password`）**不得**写进回收站；
4. 清空回收站需要显式 `confirm=1`（§2.3），避免一次误请求清空全部历史；
5. **已知边界（如实记录）**：这批仍是匿名接口，能删/能恢复的人＝能访问服务的人。
   真正的身份校验属独立的鉴权批次，不在本批假装完成。

### 2.9 无副作用与并发

1. 回收站列表是**只读**操作（除 §2.4 的到期清理），不得改动活跃会话、不得触碰索引中已有条目；
2. 所有回收站写操作走 `ConversationStore._lock`（与 `save` 同一把锁），
   不得出现"保存与删除并发导致索引与文件不一致"；
3. 删除/恢复/彻底删除都必须是**原子**的：移动失败时不得留下"活跃与回收站各一份"的状态。

---

## 3. 当前行为（生产复现）

复现方式：`tempfile.mkdtemp()` + `configure(tmp, tmp, tmp, agent_name="bi-analyst")`
（`OntologyStore.from_xlsx` 打桩）+ `TestClient(app)`，全部落在临时目录，
**不触碰任何真实用户会话**。实测（HEAD `5eaa678`）：

```
seed: store.save(mode="data", title="采购金额下降", messages=[…])  → cid=6d1f0372
GET  /api/conversations                → {"conversations": [{"id": "6d1f0372", …}]}
GET  /api/conversations/trash          → 405 {"detail":"Method Not Allowed"}
                                          （路径被 DELETE /api/conversations/{cid} 占用）
DELETE /api/conversations/6d1f0372     → 200 {"ok":true}
                                          删除后 <cid>.json 已不存在；trash/ 目录不存在
DELETE /api/conversations/trash?confirm=1 → 200 {"ok":false}   ← 被参数化路由吃掉（陷阱）
POST /api/conversations/trash/…/restore   → 404 {"detail":"Not Found"}
DELETE /api/conversations/deadbeef        → 200 {"ok":false}   ← 既有契约，必须保持
自动裁剪：连续 save 102 条（mode=report）后活跃文件 = 100（MAX_CONVERSATIONS=100），
          被裁掉的 2 条**物理消失**（无 trash/、无法恢复）
```

`frontend/src/shell.html` 的 `#view-memory` 目前只有：一条说明、一个
「重置会话 · 开始新对话」区块（`#btn-reset`）和状态行 `#memory-status`——**没有回收站**。

**实测（2026-09-21，首次 HEAD `5eaa678`，批次 1 提交后于 `90fd224` 复测一致）**：
`tests/test_conversation_trash_red.py` 收集 24 条 = **14 红 / 10 绿**
（pytest 汇总行因 R9 的 3 个子断言分别计票显示为 `15 failed, 11 passed`；
R9 的 3 个子断言里 1 条今天即通过）。逐条失败原因见 §4。

> 护栏用例 G14 依赖"活跃列表按 `updated_at` 倒序"。`_now_iso()` 只精确到秒，
> 同一秒内连续两次 `save()` 会退化成按 `id` 排序，因此 G14 用 `seed_at()`
> 把时间钉死（断言本身不变）；排序类断言也必须显式回填 `deleted_at`（`age()`），
> 不允许依赖墙钟。

---

## 4. Red Test 对照表

文件：`tests/test_conversation_trash_red.py`（离线；临时目录 + `TestClient(app)`；
**不读取、不修改任何真实用户会话**；本文件本身就是"验证删除功能"的授权范围，
且全部在 `TemporaryDirectory()` 内进行）。

| 编号 | 覆盖 | 期望今天为红 |
| --- | --- | --- |
| R1 | 删除后快照进入回收站（文件仍在 `trash/`、带 `deleted_at`、活跃列表不含它） | 红 |
| R2 | 回收站列表只回元数据（含 `deleted_at`，且不含 `chat_html`/`messages`/`source_config`） | 红 |
| R3 | 恢复后逐字段一致、`updated_at` 不变、`deleted_at` 被移除、重回「最近」 | 红 |
| R4 | 彻底删除一条后物理文件消失，且重复调用幂等 | 红 |
| R5 | 清空回收站必须显式 `confirm=1`；不带确认不得删除任何条目 | 红 |
| R6 | 保留期：过期的被自动清理，保留期内与"正好到期"的保留 | 红 |
| R7 | 自动裁剪（100 条上限）移出的会话可在回收站找回 | 红 |
| R8 | 恢复同 id 的活跃会话不产生重复、不覆盖活跃内容 | 红 |
| R9 | 非法 id 与不存在 id 一律 4xx/`ok:false`，不得 500 | 红 |
| R10 | 「记忆管理」页含回收站区块（§2.6 的 id 与文案） | 红 |
| R11 | `runtime.js` 有 `openMemory()` 并挂到 `data-view="memory"`；`openSources`/`openRoles` 模式一致 | 红 |
| R12 | 侧边栏 `✕` 文案改为「移入回收站」，且仍打同一个 DELETE | 红 |
| R13 | 回收站快照同样不得带凭据（软删除不得绕过清洗） | 红 |
| R14 | 回收站按 `deleted_at` 倒序（最近删的排最前，§2.3） | 红 |
| G13 | 非法 id（`../outside`）仍被拒，文件系统不受影响 | 绿（护栏） |
| G14 | 活跃列表字段与排序契约不变（`_summary` 键集合） | 绿（护栏） |
| G15 | `DELETE /api/conversations/<未知 hex>` 仍返回 `{"ok": false}` | 绿（护栏） |
| G16 | 凭据永不进**活跃**快照（`doris_password` 被 `sanitize_source_config` 过滤） | 绿（护栏） |
| G17 | 「记忆管理」页保留既有「重置当前对话」控件（`#btn-reset` / `#memory-status`） | 绿（护栏） |
| G18 | 侧边栏 `recent-del` 按钮与删除处理仍存在（未误删入口） | 绿（护栏） |
| M1–M4 | Mutation Guards（见 §5） | 绿 |

---

## 5. Mutation 方案

| 变异 | 会被杀死的用例 |
| --- | --- |
| "软删除"只写索引不搬文件（文件消失） | R1、R3 |
| 回收站列表顺手回吐 `chat_html` / `messages` | R2（元数据白名单）、M1 |
| 恢复时走 `save()`（`updated_at` 被刷新、会话跳到最前） | R3、M3 |
| 恢复后不删 `deleted_at` | R3 |
| 彻底删除改成"移回活跃"或直接 200 但不删文件 | R4 |
| 清空回收站不校验 `confirm` | R5、M4 |
| 保留期写成 `<=` 或按天数取整错误（刚删就清） | R6 |
| 自动裁剪继续物理删除 | R7 |
| 恢复同 id 时产生第二条记录 | R8 |
| 非法 id 走到未捕获异常（500） | R9 |
| 路由顺序错误：`DELETE /api/conversations/trash` 被 `{cid}` 吃掉 | R5（`confirm` 分支不可达 → 红） |
| 只加后端、不动「记忆管理」页 | R10、R11 |
| 只加 UI、不改删除语义 | R1–R9 |
| 软删除时从请求体重建快照（绕过 `sanitize_source_config`） | R13 |
| 回收站列表不排序（按文件名 / 插入顺序返回） | R14 |

Mutation Test 必须验证**真实行为**（打真实接口、看真实文件与响应），
不允许只 grep 源码关键字。

---

## 6. 需确认项（不得假装已确认）

1. **自动裁剪是否也进回收站**（§2.5）：本 Spec 采用"进回收站"。若产品希望
   "超过 100 条＝真删除"，则把 R7 移出本批、并在 Spec 中记录为残留观察。
2. **保留期天数**：默认 30 天；是否要按环境（PDT / demo2）区分、是否要在页面上显示为"剩余 N 天"。
3. **回收站上限**：`MAX_TRASH = 500` 是否合适（一个会话快照含 HTML，单条可达数 MB）。
4. **清空回收站是否需要更强确认**（例如输入"清空"或二次弹窗），本批只要求 `confirm=1` + 前端 `confirm()`。
5. **是否把上传报表（`DELETE /api/report/{rid}`）也纳入回收站**：本批不做。
6. **鉴权**：本批不引入；回收站接口与其它历史接口一样是匿名的，只保证不回吐正文。

---

## 7. 实现验收清单

1. `ConversationStore.delete()` 改为移动进 `trash/` + 写 `deleted_at` + 移出索引，返回值语义不变；
2. `_prune()` 的裁剪对象进入回收站；
3. 四个新接口按 §2.3 实现，`DELETE /api/conversations/trash` 声明在 `{cid}` 之前；
4. 回收站列表只回元数据（§2.8），且不含批次 1 §2.2 的任何模式；
5. 保留期 / 上限按 §2.4，边界为严格小于；解析失败取默认值；
6. 恢复保持 `updated_at`、移除 `deleted_at`、不产生重复；
7. 「记忆管理」页含 §2.6 的 id、文案与二次确认；进入页面自动加载；
8. 侧边栏 `✕` 文案与行为符合 §2.7；
9. 红测 `tests/test_conversation_trash_red.py` 全绿（24 条：14 条由红转绿 + 10 条护栏/变异守卫）；
10. 既有门禁不劣化：`tests/test_regressions.py`、`tests/test_concurrency.py`、
    `tests/test_environment_scoped_ontology_and_unused_session.py`、全量 `pytest -q tests` 0 failed（基线：
    1171 passed / 0 failed / 25 skipped / 1036 subtests）；
11. 评测 `smoke` / `adversarial` / `recorded-provider` / `regression` / `all` 全绿，
    570 / P0 147 / known_gap 0 不变；
12. 未部署、未读取真实凭据、未对真实用户会话执行删除。

---

## 8. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 软删除后旧客户端仍以为"删掉就没了"，回收站悄悄堆积 | 保留期 + `MAX_TRASH` 双约束；「记忆管理」页显示条数与剩余天数 |
| 已有安装里存在同名 `trash/` 目录或历史备份 | `trash/` 只作为子目录使用，读取路径固定；不扫描、不清理非快照文件 |
| 磁盘占用变大（快照含 HTML） | 单条上限 4 MB（既有 `MAX_HTML_BYTES`）；保留期与上限共同兜底 |
| 恢复把会话顶到「最近」最前（用户找不到） | R3/M3 锁定 `updated_at` 不变 |
| 路由顺序错误导致清空回收站打到单条删除 | R5 锁定 `confirm` 分支可达；Spec §2.3 明确声明顺序 |
| 匿名接口可被清空历史 | `confirm=1` + 前端二次确认；真正的鉴权归独立批次（§2.8 如实记录） |
| 回滚 | 把 `delete()` 改回 `unlink`、删除四个新接口与页面区块；红测文件保留为回归 |
| 回收站成为"第二份数据"，隐私面翻倍 | §2.8 只回元数据 + §2.4 双重约束；R2/R13 锁定 |

---

## 9. 残留观察（本批不处理）

| 观察 | 说明 |
| --- | --- |
| 上传报表删除（`DELETE /api/report/{rid}`）仍是硬删除 | 报表库与上传文件不在会话 store 内，另开批次 |
| 回收站接口无鉴权 | 与 `/api/sources`、`/api/system-prompt` 同源问题，归鉴权批次 |
| `_conversation_sync` 定义了但无调用点 | 历史同步属独立议题；回收站改造不引入远端副本 |
| `diagnose()` 不报告回收站条目 | 诊断面暂不覆盖回收站，如需可在后续批次补充 |
