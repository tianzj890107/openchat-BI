# 实现提示词：会话回收站（把「记忆管理」页做成删除会话的回收站）

> 把下面整段交给实现人员（人或 Agent）。本批把「删除会话」从**物理删除**改成
> **移入回收站 + 保留期内可恢复**，并在既有的「记忆管理」页（`#view-memory`）里
> 提供回收站列表、恢复、彻底删除与清空。不改分析策略 / SOP / 评测集 / 图表 /
> 会话恢复协议，不引入鉴权体系。

---

## 0. 你的任务

现状是三条"删掉就没了"的路径（实测）：

```
DELETE /api/conversations/{cid}            → 200 {"ok":true}，<cid>.json 被 unlink，回收站不存在
GET    /api/conversations/trash            → 405（路径被 DELETE /api/conversations/{cid} 占用）
DELETE /api/conversations/trash?confirm=1  → 200 {"ok":false}（被参数化路由吃掉 → 陷阱）
POST   /api/conversations/trash/…/restore  → 404
连续 save 102 条 → 活跃文件 100（MAX_CONVERSATIONS=100），被裁掉的 2 条物理消失
```

要改成：

1. 侧边栏 `✕` 删除 = **移入回收站**（快照搬到 `dataset/conversations/trash/`，写 `deleted_at`，
   从索引移除；列表/预览/恢复链路都看不到它）；
2. 「记忆管理」页新增**回收站区块**：列出已删除会话（标题 / 模式 / 删除时间 / 剩余保留天数），
   支持**恢复**（回到「最近」的**原时间位置**）、**彻底删除**（不可恢复）、**清空回收站**（需二次确认）；
3. 保留期默认 30 天（可配置），到期自动清理；活跃超上限被自动移出的会话也**进回收站**而不是蒸发。

**不要**只加一个"回收站"标题和空列表：契约要求"删除可恢复、恢复后位置不变、
彻底删除不可恢复、清空必须确认、保留期会自动清理"这几件事都能被真实接口与真实文件证明。

## 1. 先读

1. `docs/specs/conversation-trash-recycle-bin.md`（本批 Spec；§2.1–§2.9 与 §6 是重点）
2. `tests/test_conversation_trash_red.py`（红测 = 验收标准；`metadata_violations` 等检查器是验收口径）
3. 生产代码：
   - `bi_agent/web/conversations.py`：
     `ConversationStore.__init__`（`:249`）、`_path`（`:266`，`CID_RE` 校验）、
     `_read_index`/`_write_index`（`:278`/`:296`）、`_record_paths`（`:404`）、
     `_rebuild_index`（`:407`）、`_index`（`:423`）、`_summary`（`:514`）、
     `_prune`（`:528`）、`save`/`_save_unlocked`（`:557`/`:562`，末尾调用 `_prune()`）、
     `list`（`:692`）、`get`（`:702`）、`delete`（`:747`）、`diagnose`（`:763`）
   - `bi_agent/web/app.py`：`GET /api/conversations`（`:2779`）、`POST /api/conversations/save`（`:2788`）、
     `/restore`（`:2838`）、`/{cid}/preview`（`:2857`）、`/{cid}/assets`（`:2867`）、
     `/{cid}/activate`（`:2888`）、`/{cid}/record`（`:2898`）、`DELETE /api/conversations/{cid}`（`:2908`）、
     `_conversation_preview_payload` / `_load_conversation_record` / `_activate_conversation_record`（`:2674`）
   - 前端：`frontend/src/shell.html` 的 `#view-memory`（`:547`）、
     `frontend/src/runtime.js` 的导航（`:1225`）、`deleteRecent`（`:1450`）、
     既有 `openSources()` / `openRoles()` 模式（`:1230` 一带）、`#btn-reset` 处理（`:7572`）
4. 既有门禁：`tests/test_regressions.py`（会话/删除/凭据相关用例，含 `:1771` 的非法 id 契约）、
   `tests/test_concurrency.py`（`/api/conversations/*` 并发与 `save` 语义）、
   `tests/test_environment_scoped_ontology_and_unused_session.py`（前端静态契约的写法）
5. 批次 1 的安全边界：`docs/specs/anonymous-read-surface-hardening.md` §2.2（回吐模式白名单思路）

## 2. 先跑红测并确认当前失败

```bash
.venv/bin/python -m pytest -q tests/test_conversation_trash_red.py
```

当前实测（首次 HEAD `5eaa678`，批次 1 提交后于 `90fd224` 复测一致）收集
**24 条 = 14 红 / 10 绿**（pytest 汇总行因 R9 的 3 个子断言分别计票显示为
`15 failed, 11 passed`）。14 条红逐条如下：

| 用例 | 实测失败原因 |
| --- | --- |
| R1 | 删除后 `<cid>.json` 直接消失，`trash/` 不存在 → 无法恢复 |
| R2 | `GET /api/conversations/trash` 返回 405（路由不存在） |
| R3 | `POST …/trash/{cid}/restore` 返回 404 |
| R4 | `DELETE …/trash/{cid}` 返回 404 |
| R5 | `DELETE /api/conversations/trash` 未要求 confirm（且被 `{cid}` 路由吃掉） |
| R6 | 无保留期概念，过期条目不会被清理（接口也不存在） |
| R7 | `_prune()` 物理删除被裁掉的会话，回收站里找不到 |
| R8 | 冲突恢复无契约（接口不存在） |
| R9 | 非法 id（`not-a-hex-id`）返回 404 而不是 400；`DELETE …/trash/deadbeef` 返回 404 而不是 `ok:false` |
| R10 | 「记忆管理」页没有回收站区块（`#memory-trash*` 全部缺失） |
| R11 | `runtime.js` 没有 `openMemory()`、没有拉取 `api/conversations/trash` |
| R12 | 侧边栏删除入口没有「移入回收站」文案 |
| R13 | 回收站快照不存在 → 无法校验软删除没有绕过凭据清洗 |
| R14 | 回收站无排序契约（接口不存在）；且删除后快照已消失，无法回填 `deleted_at` 做排序断言 |

10 条绿色用例是护栏，**必须保持绿**：G13（非法 id 仍被拒且不动文件系统）、
G14（活跃列表字段与排序契约）、G15（活跃面删除未知 id 仍 `{"ok": false}`）、
G16（活跃快照不含凭据）、G17（`#btn-reset` / `#memory-status` 仍在）、
G18（`recent-del` / `deleteRecent` 仍在），以及 M1–M4 的 Mutation Guard
（回收站列表回吐正文、已删除 id 出现在活跃列表、恢复刷新 `updated_at`、清空不校验 confirm）。

测试基类提供两个**只用于消除墙钟不确定性**的辅助方法，不要改动它们：
`seed_at(title, updated_at)`（钉死 `_now_iso()`，用于排序类断言）与
`age(cid, days)`（回填 `deleted_at`，用于保留期与排序）。断言口径不得放宽。

**不允许**修改红测、降低断言、删除失败用例、把失败改成 skip/xfail。
`metadata_violations(...)` 等检查器就是验收口径：实现必须满足它，而不是让它迁就实现。

## 3. 实现要求

### 3.1 `ConversationStore.delete()` 改为软删除

1. 成功：把 `<root>/<cid>.json` 移动到 `<root>/trash/<cid>.json`，在记录里写入
   `deleted_at`（ISO、与 `updated_at` 同格式，建议复用 `_now_iso()`），
   然后把 `cid` 从 `history_index.json` 移除；返回 `True`；
2. `cid` 形状非法 → 返回 `False`（**既有契约，不得改成抛异常或 400**，G13 锁定）；
   记录不存在 → `False`；已删除再次删除 → `True`（幂等，不得重复写文件、不得报错）；
3. 移动必须原子：先 `os.replace` 到 `trash/`，失败时**不得**留下"活跃与回收站各一份"；
   所有写操作走 `self._lock`（与 `save` 同一把锁）；
4. `trash/` 目录按需创建；`_record_paths()` 用的是非递归 `glob("*.json")`，
   因此回收站天然不进索引 —— **不要**把它改成 `rglob`，也不要在 `_rebuild_index()` / `_index()` /
   `diagnose()` / `migrate_exact_duplicates()` 里扫描回收站。

### 3.2 回收站读取

1. `trash_records()`（命名自由）：读 `trash/*.json`，跳过 `duplicate_of` 记录与损坏文件，
   按 `deleted_at` 倒序；每条返回**元数据白名单**：
   `id` / `mode` / `title` / `first_user_question` / `created_at` / `updated_at` /
   `deleted_at` / `turn_count` / `message_count`（如需剩余天数可加 `days_left` 或 `expires_at`）；
2. **绝不**在列表里返回 `messages` / `chat_html` / `dashboard_html` / `ontology_html` /
   `tools_html` / `llm_html` / `source_config` / `recovery_state` / `preview`
   （R2 + M1 锁定；这也是批次 1 的匿名面收敛精神——回收站不能变成匿名正文读取口）；
3. 读取不属于任何会话的目录/文件时不得改动它们（§2.2 第 3 条）。

### 3.3 恢复 / 彻底删除 / 清空

1. 恢复（`restore`）：把 `trash/<cid>.json` 移回 `<root>/<cid>.json`；**移除** `deleted_at`
   等回收站专用字段；用 `_metadata(rec)` 重建索引条目——**不要**走 `save()`，
   否则 `updated_at` 会被刷新、会话跳到「最近」最前面（R3 + M3 锁定）；
2. 恢复时若活跃面已存在同 `id`：**不覆盖、不追加**，返回"已在活跃面"（R8）；
3. 彻底删除（`purge`）：`unlink()` 回收站里的那一条；不存在 → `{"ok": false}`（R4，幂等）；
4. 清空（`purge_all`）：删除回收站内全部快照并返回删除条数；**必须先校验显式确认**（见 §3.5）；
5. 失败路径一律不得 500：非法 id → 400；不存在 → 404（恢复）或 `ok:false`（删除）（R9）。

### 3.4 保留期与上限（`conversations.py` 模块级常量）

```python
DEFAULT_TRASH_RETENTION_DAYS = 30        # 环境变量 CONVERSATION_TRASH_RETENTION_DAYS 覆盖
MAX_TRASH = 500                          # 回收站条数上限（超出按 deleted_at 最旧永久删除）
```

1. 判定：`deleted_at < now - retention` **才**清理（严格小于：正好到期的当天保留，R6 锁定）；
2. `retention <= 0` → **永不自动清理**；环境变量为空/非数字 → 取默认 30（不得变成 0 或无限大）；
3. 触发时机：store 打开时（`__init__` 里，与 `migrate_titles()` 并列）**以及**每次回收站列表请求时；
   清理必须先于列表返回，保证列表里的条目点下去一定还在；
4. 清理失败（文件被占用等）不得让列表接口报错；
5. `_prune()`（`:528`）里被裁掉的活跃会话改为**移入回收站**，而不是 `unlink`；
   随后由回收站的保留期 / `MAX_TRASH` 决定它最终何时真正消失（R7 锁定）。

### 3.5 HTTP 接口（`bi_agent/web/app.py`）

| 方法 | 路径 | 成功 | 失败 |
| --- | --- | --- | --- |
| `GET` | `/api/conversations/trash` | `{"trash": [...], "count": N, "retention_days": D}` | — |
| `POST` | `/api/conversations/trash/{cid}/restore` | `{"ok": true, "id": cid}` | 非法 400；不在回收站 404；已在活跃面 `{"ok": true, "already_active": true}` |
| `DELETE` | `/api/conversations/trash/{cid}` | `{"ok": true}` | 非法 400；不存在 `{"ok": false}` |
| `DELETE` | `/api/conversations/trash?confirm=1` | `{"ok": true, "purged": N}` | 缺确认 400（不得删任何东西） |

**路由顺序陷阱**：`DELETE /api/conversations/trash` 必须声明在
`DELETE /api/conversations/{cid}` **之前**（`app.py:2908` 之前），否则 `trash` 会被当成 `cid`
（实测今天 `DELETE /api/conversations/trash?confirm=1` 返回 `{"ok": false}`）。
同理，`GET /api/conversations/trash` 要避免与既有的 `/{cid}/…` 路由混淆——它是 2 段路径，
与 `/{cid}/preview` 等不冲突，但仍建议把回收站路由成组放在会话区同一处，便于阅读。

其它要求：

1. 四个接口都沿用 `_require_conversation_store()`（未配置 → 500，与既有接口一致）；
2. `confirm` 参数只接受真值写法（`1` / `true` / `yes`），其余按"未确认"处理；
3. `GET /api/conversations`（活跃面）**不得**返回已删除项，字段保持 G14 的键集合；
4. 响应不得包含批次 1 §2.2 的模式（绝对路径 / `jdbc:` / 内网 `IPv4:port` / 主机名）。

### 3.6 前端：「记忆管理」页 + 侧边栏

1. `frontend/src/shell.html` 的 `#view-memory` 内新增区块（**保留** `#btn-reset` 与 `#memory-status`）：

| 元素 | 契约 |
| --- | --- |
| 容器 | `id="memory-trash"` |
| 计数 | `id="memory-trash-count"`（如「回收站 · 3 条」） |
| 列表 | `id="memory-trash-list"`，行 `data-cid="<id>"`，显示标题 / 模式 / 删除时间 / 剩余天数 |
| 行内操作 | `class="memory-trash-restore"`（恢复）、`class="memory-trash-purge"`（彻底删除） |
| 清空 | `id="memory-trash-empty"` |
| 状态 | `id="memory-trash-status"` |

文案必须写明：删除＝移入回收站可恢复；彻底删除/清空**不可恢复**；保留期（默认 30 天）到期自动清理。

2. `frontend/src/runtime.js`：
   - 新增 `openMemory()`（对标 `openSources()` / `openRoles()`）：拉 `api/conversations/trash` →
     渲染列表与计数 → 再 `showView("memory")`；失败时在 `#memory-trash-status` 给出可读提示；
   - 导航里加分支：`else if (view === "memory") { openMemory(); }`（`view === "memory"` 必须出现）；
   - 「彻底删除」与「清空回收站」用 `confirm(...)` 二次确认；「恢复」不确认；
   - 恢复成功后：该行从回收站列表消失、`loadRecent()` 刷新「最近」（会话回到原时间位置）；
   - 侧边栏 `deleteRecent(id)` 仍打 `DELETE /api/conversations/{id}`，但按钮 `title`
     改为「移入回收站」；删除成功后同步刷新回收站计数/提示；
   - 不得引入新的真值回填路径（沿用既有 `withBasePath` / `withClientSession` 约定）。

### 3.7 明确不做

* 不引入鉴权/登录/token（回收站接口与其它历史接口一样匿名，只保证不回吐正文）；
* 不改上传报表库（`DELETE /api/report/{rid}`）与报表模式的重置语义；
* 不改 `preview` / `assets` / `activate` 的恢复协议、不改 `save` 的字段与 `_prune` 的阈值（100）；
* 不改分析策略 / SOP / 评测集 / 图表，不新增 known gap；
* 不部署、不改版本号、不创建 tag/Release。

## 4. 需要产品确认的点（不得假装已确认）

1. **自动裁剪是否也进回收站**（Spec §2.5）：本批默认"进回收站"。若产品要"超 100 条＝真删除"，
   请回来把 R7 移出本批并记录为残留观察——**不要**在实现里偷偷改成物理删除。
2. **保留期天数**（默认 30）与是否按环境区分（PDT / demo2）。
3. **回收站上限** `MAX_TRASH = 500` 是否合适（快照含 HTML，单条最大 4 MB）。
4. **清空回收站**是否需要比 `confirm=1` + 前端 `confirm()` 更强的确认（例如要求输入文字）。
5. 是否把**上传报表**也纳入回收站（本批不做）。

## 5. 完成前必须运行的验证

```bash
.venv/bin/python -m pytest -q tests/test_conversation_trash_red.py            # 目标：24 passed
.venv/bin/python -m pytest -q tests/test_regressions.py tests/test_concurrency.py
.venv/bin/python -m pytest -q tests/test_environment_scoped_ontology_and_unused_session.py
.venv/bin/python -m pytest -q tests/                                          # 全量 0 failed
.venv/bin/python -m scripts.run_analytics_eval --suite smoke
.venv/bin/python -m scripts.run_analytics_eval --suite adversarial
.venv/bin/python -m scripts.run_analytics_eval --suite recorded-provider
.venv/bin/python -m scripts.run_analytics_eval --suite regression
.venv/bin/python -m scripts.run_analytics_eval --suite all
```

* 全量 `pytest -q tests` 基线：**1171 passed / 0 failed / 25 skipped / 1036 subtests**，
  失败项不得多于基线；评测 570 / P0 147 / known_gap 0 不变；
* 某项因缺少真实 Provider 无法运行时如实标 `not_measured`，**不得**写成 passed；
* **禁止**对真实用户会话执行删除/恢复验证：所有验证都在 `TemporaryDirectory()` 里做。

## 6. 交付报告（必须包含）

1. 修改文件清单与每个文件的改动要点；
2. 红测从 `14 红 / 10 绿` 到 `24 passed` 的实际输出；
3. 存储证据：删除前后 `dataset/conversations/` 与 `trash/` 的文件清单（可脱敏为文件名）、
   `history_index.json` 里该 id 的出现/消失；
4. 恢复证据：恢复后 `updated_at` 与删除前一致、`deleted_at` 已移除、活跃列表回到原位置；
5. 保留期证据：把 `deleted_at` 回填到"保留期 +1 天 / 正好到期 / 保留期内"三种情形下的实际结果；
6. 自动裁剪证据：连续 save 超过 100 条后，被裁掉的会话出现在回收站且可恢复；
7. 接口证据：四个接口的正常/异常返回（含非法 id 400、缺失确认 400、未知 id `ok:false`）；
8. 安全证据：回收站列表响应**不含**正文与 `source_config`；回收站快照不含凭据；
9. 误伤验证：活跃列表/预览/恢复链路行为不变，`#btn-reset` 仍可用，侧边栏删除仍可用；
10. 评测门禁结果与 known gap 数量；
11. §4 各项的确认结果或默认取值说明；
12. 明确说明：未引入鉴权、未读取真实凭据、未触碰真实用户会话、未部署、未创建 MR/tag/Release。
