# openchat-BI 变更记录（2026-08-10 至 2026-08-16）

> 本文档记录本周已完成的最终用户可见功能变化，已合并 8 月 12、13、14 日每日变更记录。

## 维护规则

- 每组相关修改合并为一条记录，不记录中间尝试或单纯文件同步。
- 周记录使用高于日报的颗粒度，保留用户可见变化、影响范围、主要文件和验证结果。
- 本周每日 changelog 已完成归档合并，后续只维护本周周 changelog。

## 2026-08-10 至 2026-08-14

### 1. 优化工作台导航、历史会话与任务定位

- 恢复侧栏外层滚动与最近会话内层滚动的连续交互：最近会话最多展示 6 条，滚轮按可视范围和边界在内外层之间传递。
- 新会话从创建时即进入历史清单，首个问题提交后立即更新标题和进行中的 SOP；切换本体内容等页面不会清除正在执行的会话，历史会话点击也不会中止当前 SSE 任务。
- 修复智能分析/报表分析历史会话串用、任务清单定位偏移、看板只向上滚动及历史会话默认选中任务等问题；点击任务可在聊天区和看板双向定位并同步选中。
- 删除任务清单多余的“用户提问”分组，统一问题序号、文字基线、字号、悬浮/选中态和自动滚动行为。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/static/vendor/antd/workbench.js`、`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

### 2. 重构思维链与分析 SOP 展示

- 思维链正文改为标题链后的独立高度容器，展开/折叠连续推动后续步骤，统一标题和耗时对齐到内容区 80% 宽度；历史恢复时清理重复 Host 和旧结构。
- 分析 SOP 支持自然文字宽度和自动换行，步骤状态统一为进行中蓝色空心圆、未开始灰色空心圆、完成绿色勾，清除 Ant Design 残留方块及蓝色背景。
- AskUser 卡片出现时清除重复的“思考中”状态，提交完成后显示“已选择/已提交”并移除多余底部进度线。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`tests/test_regressions.py`。

### 3. 统一本地与远程本体、指标及数据源能力

- 统一本地 Excel 本体与远程本体在 `OntologyQuery`、指标/实体识别、历史本体卡片、编码/名称/别名匹配和实体类型展示上的行为。
- 统一远程 `MetricLookup` 的指标定义、公式、口径、计算规则、来源表、聚合方式和周期；新增远程 `MetricDataQuery`，支持分页、过滤、排序，失败时明确提示并允许继续使用 `SQLRun`。
- 远程本体库与对应 Doris 数据库绑定切换，切换失败整体回滚；不同浏览器会话隔离本体、数据库、工具执行器和分析上下文。
- 整理 `dataset/`、`API/`、`scripts/` 等资产目录，新增统一路径模块，区分可发布资源与会话、报表、图表、日志等运行产物。
- 主要文件：`bi_agent/tools/remote_ontology_tools.py`、`bi_agent/ontology/remote.py`、`bi_agent/web/app.py`、`bi_agent/web/session.py`、`bi_agent/paths.py`、`dataset/README.md`、`scripts/README.md`。

### 4. 补齐远程图库检索并完善本体适配

- 远程图库从扁平关联对象扩展为受限邻域的有向关系、业务属性、最短证据路径和结构化关联子树，覆盖业务对象、逻辑实体、属性、指标、维度、活动、流程及物理表列。
- `GraphContext`、`GraphExpand` 与本地保持一致的锚点/下钻语义；指标会回挂业务对象，关联业务对象可继续作为锚点扩展，并提供深度、对象数、关系数和短时缓存边界。
- 边查询不支持时保留完整顶点邻域并明确合成关系不能作为方向证据；本体适配页在远程模式下将本地图文件显示为灰色只读提示，不再允许选择或提交 `graph_path`。
- 主要文件：`bi_agent/ontology/remote_retriever.py`、`bi_agent/tools/graph_tools.py`、`bi_agent/tools/remote_ontology_tools.py`、`frontend/src/runtime.js`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 5. 接入 ChatBI 分析可靠性框架

- 在真实 ChatBI 分析链路中将 SQL/Metric 结果规范化为 `QueryResult`，自动生成带 scope、semantic、provenance 的 FACT/ASSOCIATION Claim，并传播到表格、图表和最终回答。
- 支持分析上下文按轮次继承、父级/下钻结果 reconciliation、同范围矛盾检测、Proxy 结果披露、因果越级阻断和 unsupported number 校验；冲突证据未披露时阻止确定性回答。
- 图表自动补齐单位、语义类型和范围，表格同步携带分析元数据；删除未被主链路消费的冗余对象和注册 API。
- 主要文件：`bi_agent/reliability.py`、`bi_agent/web/session.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/table_tools.py`、`tests/test_reliability.py`。
- 验证：可靠性端到端测试 84 项通过；回归测试 70 项通过，另完成 `compileall` 与 `git diff --check`。

### 6. 完成 ChatBI 工作台视觉统一与默认入口调整

- 根路径 `/` 自动进入 `/workbench`，`/dashboard.html` 保留为独立驾驶舱入口。
- 统一浅色语义色彩体系：极浅蓝灰页面、白色工作面、蓝色主操作和用户气泡、深蓝灰正文；思考/命令、读取、写入、成功、审批、特殊流程、错误等节点按语义着色。
- 统一导航、历史会话、设置入口、SOP、任务清单、结果卡片和报告操作按钮的白色背景、蓝色悬浮/选中态、字重、间距和提示；发送按钮改为纯蓝色并支持悬浮跳动。
- 主要文件：`bi_agent/web/app.py`、`frontend/src/main.jsx`、`frontend/src/workbench.css`、`bi_agent/web/static/index.html`、`tests/test_regressions.py`。

### 7. 完善 ChatBI 部署稳定性与安全校验

- 远程本体服务超时或不可达时不再阻断 ChatBI 启动；数据源/本体适配页面提示依赖状态，实际切换或查询时返回明确错误。
- 修复本体任务数据库凭据解密的 fail-open：缺少密钥、密钥错误、密文损坏或 Tag 校验失败时直接阻止任务，返回 `DATABASE_CREDENTIAL_DECRYPTION_FAILED`，不透传密文且不在日志输出敏感信息；明文兼容路径保留。
- 完成测试服务器部署、远程代码备份、旧目录字段兼容和服务健康验证；当前部署使用 `zhangzhen` 账号，`/healthz` 与 `/workbench` 可访问。
- 修复部署遗留的空历史会话、历史会话打开后记忆管理持续选中，以及 SSE 尾部事件缺失导致 SOP 卡在最后一步和输入框无法继续提问的问题。
- 主要文件：`bi_agent/web/app.py`、`bi_agent/ontology/remote.py`、`frontend/src/main.jsx`、`frontend/src/runtime.js`、`DEPLOYMENT.md`。
- 验证：凭据解密测试 5 项通过；服务健康检查通过，前端静态资源版本更新并完成部署。
