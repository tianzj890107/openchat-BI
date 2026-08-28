# openchat-BI 变更记录（2026-08-27）

> 本文档只记录 2026-08-27 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-27

### Agent Tool 命名统一与执行清单

- 将本体语义查询、指标查询、事实数据查询、术语消歧、关系查询和实体描述 Tool 的对外标识统一为 `Ontology-SemanticQuery`、`Ontology-MetricQuery`、`Ontology-FactQuery`、`Ontology-TermDisambiguate`、`Ontology-RelationQuery`、`Ontology-EntityDescribe`，指标计算 Tool 保持为 `MetricCalculation`。
- 同步更新三个 Agent 的 Tool 白名单、本地及远程 Tool Schema、会话 SOP 映射、前端工具卡片与来源识别、分析策略、测试和相关设计文档，确保模型调用名、运行时事件名与界面显示一致。
- 新增 `docs/ChatBI_Tools.md`，以纯名称清单区分 Agent 默认 Tools、图库检索模式 Tools，以及已注册但未默认导入的 Tools；同时明确这些名称对应实际可执行的 Agent Tools，而非独立的 Skills 注册项。
- 按用户要求同步迁移现有历史会话内保存的旧 Tool 名称；仅精确替换名称字段及相关展示文本，不删除、清空或重建会话，迁移后的 10 个会话 JSON 文件均通过结构校验。
- 主要文件：`.claude/agents/*.md`、`bi_agent/tools/ontology_tools.py`、`bi_agent/tools/remote_ontology_tools.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/web/session.py`、`frontend/src/main.jsx`、`frontend/src/runtime.js`、`docs/ChatBI_Tools.md`。
- 验证：前端生产构建通过；Python 测试共 253 项通过；`git diff --check` 通过。
- 部署：已发布至测试服务器当前 release，重启后 `/healthz` 正常；服务器运行时 Schema、三个 Agent 白名单和前端构建产物均使用最终名称，76 个服务器历史会话完成旧名称迁移并通过 JSON 与旧名称残留检查。部署前已分别创建代码备份和完整会话压缩备份。
- Tool 名称最终严格收口到 `docs/ChatBI_Tools.md` 清单：图库工具的运行时 Schema、SSE、SOP 与界面名称统一为 `Ontology-GraphContext` / `Ontology-GraphExpand`；前端颜色和图标直接按规范名称映射，保持改名前的视觉语义，不修改 SVG、色值或布局，也不再把旧 Tool 名称或 `DataQuery` 别名注册为新会话的视觉名称。
- 点击本体元素打开的关系图弹窗与 Ontology 平台的“关系聚类可视化”布局对齐：补齐孤立节点规整、稀疏小图双轴铺展和关系权重呈现；工具栏策略按钮改为面向业务的“子图检索”“关系扩散”，布局入口显示“关系聚类可视化”。本次仅修改前端渲染与文案，子图接口及 `context` / `expand` 参数保持不变。

### Ontology-FactQuery 工具卡片首行改为中文查询目标

用户可见变化：
- 工具调用卡片（工具页签与对话区步骤）第一行不再直接显示 SQL，改为简短中文查询
  目标，示例：`查询超期未接收含税金额`、`按事业部查询应收账款`、
  `查询 2026 年 8 月销售额`、`查询按供应商采购金额`；无法可靠识别时显示
  `查询业务数据`。
- 摘要只使用工具参数中明确提供的 `query_description`（或 description / purpose /
  question / metric）；没有可用描述时首行摘要保持为空，不从 SQL 推导摘要、不回退
  `查询业务数据`，更不会在首行显示 SQL。该逻辑由前端纯函数确定性完成，不调用额外
  大模型。
- 完整 SQL 与全部参数仍保留在卡片展开后的输入详情中，执行参数、SQL 逻辑和会话
  保存的数据结构不变；历史会话恢复时前端按同一套规则从已保存参数重新生成首行
  摘要，不批量改写历史 JSON。
- 其他 Ontology Tool 卡片首行规则不变；Tool 名称仍为 `Ontology-FactQuery`，
  Dashboard / 普通会话 / 报告会话行为一致。
- Agent 提示词新增要求：调用 `Ontology-FactQuery` 时尽量填写简短中文
  `query_description`（可选参数，不设为必填，不影响 SQL 执行）。

主要文件：`frontend/src/factQueryPreview.js`（新增纯函数模块）、
`frontend/src/runtime.js`、`bi_agent/tools/sql_tools.py`、
`.claude/agents/bi-analyst.md`、`.claude/agents/report-analyst.md`、
`.claude/agents/report-generator.md`、`tests/test_regressions.py`。

测试：新增 node 纯函数测试（query_description 优先、SQL 摘要、兜底文案）与
运行时/恢复/保留断言；前端生产构建通过；Python 测试共 261 项通过；
`git diff --check` 通过。

### 分析 SOP 重构为六步状态机

用户可见变化：
- 会话 SOP 为固定六步：`意图识别` → `本体模型匹配` → `深度思考&分析规划` →
  `数据获取和可视化` → `根因分析` → `决策行动`，编号 `01`–`06`，普通会话、
  报表会话、Dashboard 与历史会话恢复展示一致；不再显示旧版五步名称。
- SOP 是真实执行轨迹：只有实际进入并完成的步骤显示绿色完成，当前步骤显示
  进行中；支持 `05 → 03`、`04 → 03`、`06 → 05` 等真实回退，回退后后续步骤
  重新计算为未开始，同一步可重复进入形成循环。
- 第 5 步「根因分析」不再因“执行过 SQL”自动点亮：L1 取数（“有多少订单”“销售
  额是多少”）执行第 4 步后直接进入第 6 步整理结论；L2 只做异常定位也不进入
  第 5 步；仅当用户问题属于 L3–L5 或最终正文确实包含根因分析章节时，后端才
  发送第 5 步事件。前端不再根据正文关键词自行伪造根因步骤。
- 新增 `skipped`（已跳过）状态：本轮未执行的步骤在结束时显示为已跳过（非绿色
  样式，对话区与 Dashboard 一致），`done` 只表示本轮成功结束，不会把未访问的
  步骤染成绿色完成；状态机按实际访问轨迹（visited）判定完成与跳过，而不是
  “当前步骤之前全部完成”的线性算法。
- 结束态不再保留任何加载动画：`done` / `error` / `session_superseded` / SSE
  自然关闭兜底统一清理流式光标、`思考中…` 占位行、步骤时间线思考行和空白的
  assistant 占位卡，真实正文、工具步骤、图表、表格、多维图与选择卡不会被误删；
  历史会话恢复同样清除瞬态加载元素，已完成的会话不再出现闪动卡片。
- SOP 状态映射明确化：ThoughtChain 的 `pending`（可加载/动画）状态只保留给
  `in_progress`，`pending` 与 `skipped` 映射为自定义静态 `idle` 状态并配合
  静态灰色样式（`skipped` 显示短横线，非绿色勾），`completed` 仍为静态绿色勾；
  动画强制关闭规则限定在 SOP/Workflow 面板范围，不影响其他真正加载中的 UI。
- 工具映射按职责归属：`AskUser` 与用户问题解析归 `01 意图识别`；本体检索、
  术语/指标匹配、图库上下文类工具归 `02 本体模型匹配`；`Ontology-MetricQuery` /
  `Ontology-FactQuery` / `ListTables` / `DescribeTable` / `TableGenerate` /
  `ChartGenerate` / `ChartGenerateMultiDim` 归 `04 数据获取和可视化`；根因证据
  链组装归 `05 根因分析`；结论整理、行动建议、风险预警、最终报告组装与返回归
  `06 决策行动`。
- 结构化 `sop_progress` 事件（1–6，1-based）是唯一驱动；`error` /
  `session_superseded` / 等待用户选择不会补齐后续步骤；SOP 只负责展示执行过程，
  不构成最终回答门禁，事件缺失时回答照常输出。
- 历史兼容：旧五步 / 旧六步 / 旧九步快照在展示层映射为六步（完成快照恢复为
  六步全完成，未完成快照映射到最近步骤），保留进行中步骤的 detail；历史会话
  JSON 不重写、不批量迁移。

主要文件：`frontend/src/sopMachine.js`、`frontend/src/runtime.js`、
`frontend/src/workbench.css`、`bi_agent/web/session.py`、
`.claude/agents/bi-analyst.md`、`docs/ChatBI_Agent场景分析SOP.md`、
`tests/test_regressions.py`。

测试：新增六步名称/顺序、L1 无工具与 L1 取数均不进入第 5 步、L2 异常定位不进入
第 5 步、L3 根因章节才进入第 5 步、L1 终态第 5 步为 skipped、05→03 回退后不保留
绿色、04→03→04 重试轨迹、done 不染绿未访问步骤、查询失败/中断/等待用户选择不
补齐后续步骤、历史五/六/九步兼容恢复、刷新恢复轨迹保持、单状态机被会话与
Dashboard 共用、SOP 缺失不阻断回答，以及 ThoughtChain 状态映射纯函数（skipped /
pending 静态、in_progress 唯一动态）、终态占位清理与恢复清理等回归测试；
Python 测试共 265 项通过；前端生产构建通过；`git diff --check` 通过。

部署：已发布到测试服务器当前 release 并重启服务；`/healthz` 正常，服务器端 SOP
源码与前端构建产物均已核验六步名称、静态 `skipped` / `pending` 映射及终态加载占位
清理逻辑，原有 76 个历史会话文件保持完整。发布前已创建带时间戳的代码备份。
