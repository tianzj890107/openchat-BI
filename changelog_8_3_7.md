# openchat-BI 变更记录（2026-08-03 至 2026-08-07）

> 本文档记录本项目在本周内完成的最终用户可见功能变化。

## 维护规则

- 每次发布或一组相关修改按日期追加，不记录单个操作步骤或中间尝试。
- 每条记录只描述相对于上一版本的最终用户可见差异；同一功能的多次调整合并为一条。
- 每条记录至少说明：用户可见变化、涉及页面、主要文件。
- 不记录重启、部署、文件同步或浏览器刷新等运行操作。

## 2026-08-03

### 1. 新对话欢迎区与空分析 SOP

- 新开智能分析对话中的三个示例问题统一为 8px 圆角，和工作台其他可点击提示保持一致。
- 即使尚未发送问题也显示折叠的“分析 SOP”入口；展开后提示“开始一轮智能分析后，这里会显示本次对话的六步执行进度”，开始分析后自动替换为实时进度和 ThoughtChain 步骤。
- 页面：智能分析新对话欢迎区、对话区顶部。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 2. 任务清单联动看板定位

- 点击任务清单中的任一用户提问时，对话区定位到对应用户问题，看板同时定位到该轮首个可见分析结果；看板已隐藏的用户问题卡片不再作为滚动目标。
- 页面：智能分析、报表分析任务清单、对话区和右侧看板。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。

### 3. 本体命中记录与本体内容完整性

- 智能分析过程现在可以识别本地和远程本体常见编码（指标、术语、维度、活动、流程、规则及元模型关系），远程本体中不在本地 Excel 回退文件里的命中项也会保留在本体内容和系统调用记录中。
- 本体内容接口补充返回业务属性、实体关系、维度、流程和本体元模型关系，不再只返回基础业务对象和指标集合。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 4. 团队模型网关接入

- 默认模型提供商切换为团队 OpenAI-compatible 网关，默认模型为 `direct-deepseek-v4-flash`。
- 团队网关通过 `TEAM_API_KEY`、`TEAM_BASE_URL`、`TEAM_MODEL` 和 `TEAM_MODELS` 配置；模型选择器会展示团队网关中的全部候选模型，并在额度或限流时按配置顺序自动切换。
- 原有 Qwen、Anthropic 和 DeepSeek 提供商仍保留，可通过模型选择器或环境配置切换。
- 主要文件：`bi_agent/llm/provider_team.py`、`bi_agent/llm/provider.py`、`bi_agent/llm/registry.py`、`bi_agent/llm/runtime_config.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`。

### 5. 设置页控件尺寸与圆角统一

- 模型参数页的“恢复默认”“返回”“保存”按钮统一高度和内边距，并与模型、最大输出长度和 API 密钥输入框统一采用 8px 圆角。
- 数据源、本体适配、角色选择、记忆管理和个人账号设置页同步使用同一套圆角控件样式，避免不同设置页面出现直角/小圆角混用。
- 页面：模型参数及全部设置页。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 6. 数据源读取后的保存提示

- 在数据源页点击“读取当前数据源”后，读取到的 Doris 库名现在明确标记为“尚未保存”，并提示点击“保存并切换”后才会真正生效。
- 读取结果使用待保存状态，不再误显示为已完成状态，避免用户以为读取动作已经完成数据源切换。
- 同步更新脚本版本号，确保已部署页面加载最新的保存提示逻辑。
- 页面：数据源。
- 主要文件：`bi_agent/web/static/app.js`、`bi_agent/web/static/index.html`。

### 7. 本体内容与远程 OntologyQuery 结果统一

- 远程本体源启用时，本体内容页现在以当前远程仓库返回的对象为准，不再被本地 Excel 中同编码对象覆盖。
- 本体命中按“来源 + 仓库 + 类型 + 编码”区分，补充表节点、列、维度、流程和元模型关系等远程类型；SQL、图表和表格中的来源编码不再误计为本体命中。
- 历史会话恢复时会重建本体去重索引，保留远程命中来源，避免继续追问时重复或错配。
- 页面：本体内容、系统调用记录、智能分析和报表分析。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/web/app.py`、`bi_agent/web/static/app.js`、`tests/test_regressions.py`。

### 8. 历史会话本体卡片迁移

- 打开已有历史会话时，从会话保存的 OntologyQuery 等本体工具结果重新生成本体卡片。
- 旧卡片会按当前远程来源、仓库、类型和编码重新绑定，缺失或过期的本体快照会被纠正；迁移不会改变会话的更新时间和历史排序。
- 无法从历史工具结果安全确认的内容不自动改名，避免把普通数据库字段误改成本体对象。
- 页面：历史会话、本体内容、系统调用记录。
- 主要文件：`bi_agent/web/app.py`、`bi_agent/web/conversations.py`、`tests/test_regressions.py`。

### 9. 本体类型徽标倒角

- 本体内容中的术语、逻辑实体、属性、指标等类型徽标统一增加圆角，和页面其他标签样式保持一致。
- 页面：本体内容。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 10. 思维链步骤间距收紧

- 收紧思维链步骤标题、步骤内容、代码区域和 Ant Design ThoughtChain 项目的上下留白，整体间距约缩减一半。
- 页面：智能分析、报表分析会话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 11. 思维链折叠状态去除内容留白

- 折叠时只保留思维链标题行，不再让隐藏的内容区域或代码区域占用上下间距。
- 展开后再恢复内容区的上下留白，保持内容可读性。
- 页面：智能分析、报表分析会话区。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 12. 本体类型筛选

- 本体内容页顶部新增类型筛选按钮，可按术语、业务对象、逻辑实体、属性、指标等类型显示或隐藏实体卡片。
- 表节点和列默认隐藏，其他类型默认显示；关闭类型后按钮变灰，再次点击即可恢复。
- 业务对象类型统一改为红色，筛选按钮、类型徽标和卡片色条保持一致。
- 页面：本体内容。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/app.js`、`bi_agent/web/static/styles.css`。

## 2026-08-04

### 13. 数据源与图表生成的边界校验

- Doris 数据库名在保存数据源前统一校验为安全标识符，非法值会直接返回可读的表单错误，不再进入后续元数据 SQL。
- Doris HTTP 查询统一识别 `success=false` 和非 200 业务码，并兼容令牌已经带 `Bearer` 前缀的配置；SQL 结果行数限制在有效范围内，避免负数或超大输出。
- SQL 查询继续支持用于结构检查的只读 `PRAGMA`，但会拒绝带赋值的 PRAGMA，保持 SQLRun 的只读约束。
- 独立图表 HTML 对标题和脚本内 JSON 做上下文转义，避免标题内容破坏页面脚本；同一秒生成同名图表时自动追加序号，不再覆盖旧图表。
- 页面：数据源设置、智能分析/报表分析图表及历史图表链接。
- 主要文件：`bi_agent/tools/sql_tools.py`、`bi_agent/ontology/remote.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

## 2026-08-05

### 14. IBA 内部侧栏展开宽度对齐

- IBA 内部智能分析功能栏展开时固定为 230px，使其从外部收起的 72px 导航轨道开始，右边界准确落在顶部 EIMOS 与“产品功能”的中缝。
- 侧栏收起时仍保持原有 72px 窄栏和图标布局，不改变外部导航栏的折叠行为。
- 页面：i-Agent 智能分析工作台（会话、看板及内容设置页）。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。

### 15. 对话输入区单行化

- 输入框与操作区合并为一行，移除中间分隔线；提示文字与发送控件保持同一行显示。
- 发送控件改为单独的大箭头按钮，不再显示“发送”文字；报表模式的辅助操作仍在同一行横向排列。
- 页面：智能分析、报表分析对话输入区。
- 主要文件：`bi_agent/web/static/index.html`、`bi_agent/web/static/styles.css`、`bi_agent/web/static/app.js`。

### 16. 任务清单只显示用户提问

- 任务清单不再重复显示分析 SOP 步骤，只保留当前会话中的用户提问及其定位入口。
- 分析 SOP 继续在上方作为独立的可折叠区域展示。
- 页面：智能分析、报表分析会话区。
- 主要文件：`frontend/src/main.jsx`、`bi_agent/web/static/index.html`、`bi_agent/web/static/vendor/antd/sidebar.js`。

### 17. 分析 SOP 行间距收紧

- 分析 SOP 的六个步骤行间距压缩为原来约一半，保持文字和状态图标可读性。
- 任务清单、对话消息和展开后的详细思考内容间距不变。
- 页面：智能分析、报表分析会话区顶部的分析 SOP。
- 主要文件：`bi_agent/web/static/styles.css`、`bi_agent/web/static/index.html`。
