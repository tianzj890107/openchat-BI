# 本体库白名单与未使用新会话收敛规范

## 目标

一次交付两项彼此独立、但都属于"多租户环境安全"的收敛能力：

1. **本体库白名单**：用环境变量限制某个部署可见、可切换的本体库目录，而不是在
   `_remote_repository_catalog()` 里写死 `repository_id != "3"`。默认不启用，未配置
   时完全保持现有行为。
2. **未使用新会话收敛**：连续点击「新会话」但不使用它们时，侧边栏最多只显示一条
   空白草稿，不再无限累积 `未命名对话`。

## 一、本体库白名单

### 环境变量

```text
ONTOLOGY_ALLOWED_REPOSITORY_IDS=3        # 单值
ONTOLOGY_ALLOWED_REPOSITORY_IDS=3,7      # 多值
ONTOLOGY_ALLOWED_REPOSITORY_IDS=         # 未设置或空值 = 不过滤
```

demo2 配置：

```text
ONTOLOGY_REPOSITORY_ID=3
ONTOLOGY_ALLOWED_REPOSITORY_IDS=3
DORIS_DATABASE=ontology_demometaerp
```

### 行为契约

1. 过滤发生在唯一入口 `bi_agent/web/app.py:_remote_repository_catalog()`；三个调用方
   （启动校验、`GET /api/sources`、`PUT /api/sources`）自动共享同一份过滤后的目录，
   不允许只在任何一层单独写死 ID。
2. 变量未设置或为空时，返回全部可访问本体库（向后兼容，其它客户环境不受影响）。
3. 设置后只返回允许列表中的本体库；支持 `3,7` 多值，忽略空白项和空项。
4. `ONTOLOGY_REPOSITORY_ID` 必须属于允许列表，否则 `configure()` 启动失败
   （`RuntimeError`）。该校验不依赖远端目录是否可用。
5. `PUT /api/sources` 重新查询过滤后的目录：绕过前端直接请求非白名单本体库必须返回
   `400`，且不得改变当前数据源。
6. 过滤只裁剪目录，不改变 `namespaceCode` / `dorisDatabase` 的原子配对语义，也不改变
   目录不可用时的单条回退条目（回退条目使用的就是已通过校验的当前本体库）。

### 影响范围

- 数据源设置下拉框：过滤后 demo2 只显示 `ECore本体库-勿动` 与其 Doris 数据库
  `ontology_demometaerp`。
- 数据源切换接口：过滤后无法切换到 repository 1、2、4、7。

### 不改动

- `APP_ROOT_PATH` 规范化、base-path 前缀剥离、`/static` 挂载、`/healthz`；
- 网关（Vane / Ingress / OpenResty）配置；
- 前端构建产物。

## 二、未使用新会话收敛

### 定义

「未使用新会话」（unused draft）指一条**没有任何用户内容**的会话记录：没有
`first_user_question`、`messages` 为空、`chat_html`/`dashboard_html`/`ontology_html`/
`tools_html`/`llm_html` 全部为空、没有 `sop_steps`。只要有任何一处内容，就不是草稿。

### 行为契约

1. **不新增：** 当一次保存的是一份未使用草稿，且该模式下已存在未使用草稿时，复用最新的
   那条草稿记录（返回它的 `id`），不再创建新记录。这样连续点击「新会话」不会产生新文件。
2. **只显示一个：** `ConversationStore.list()` 每个模式最多返回一条未使用草稿（最新的一条）。
   历史遗留的多条空草稿仍保留在磁盘上，不会被删除，只是不再出现在侧边栏。
3. **不误伤真实会话：** 有内容的历史会话永不被合并、隐藏或删除；已有真实会话时，再点
   「新会话」仍会得到一条新的空白草稿（用于下一次提问）。
4. 收敛发生在持久化/列表层（`ConversationStore`），因此所有客户端（含旧前端）都受约束，
   不是只改提示文案。

### 实现要点

- `_metadata()` 增加仅供索引使用的 `is_draft`；`_summary()` 的对外字段保持不变，对外
  摘要契约不新增字段。
- 旧版本写下的索引没有 `is_draft`，读取时一次性惰性重建（仅重写小型元数据索引，不
  改 `HISTORY_INDEX_VERSION`，也不删除任何记录），之后恢复正常快路径。

## 验收

```bash
.venv/bin/python -m unittest tests.test_ontology_repository_allowlist
.venv/bin/python -m unittest tests.test_single_unused_conversation
.venv/bin/python -m unittest tests.test_regressions
git diff --check
```
