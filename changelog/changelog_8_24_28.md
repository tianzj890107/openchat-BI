# openchat-BI 变更记录（2026-08-24 至 2026-08-28）

> 本文档记录本周已完成的最终用户可见功能变化，已合并 8 月 24、25、26、27、28 日每日变更记录。

## 维护规则

- 每组相关修改合并为一条记录，不记录中间尝试或单纯文件同步。
- 周记录使用高于日报的颗粒度，保留用户可见变化、影响范围、主要文件和验证结果。
- 本周每日 changelog 已完成归档合并，后续只维护本周周 changelog。
- 8 月 24 至 28 日期间发生的部署均属历史事实记录，不代表当前交付规范；8 月 28 日起仓库默认交付规范已统一为“commit + push，不部署”。

## 2026-08-24 至 2026-08-28

### 1. 分析 SOP 演进为六步真循环状态机

- 分析 SOP 一周内从旧六步先后演进为九步、五步，最终收敛为固定六步：`意图识别` → `本体模型匹配` → `深度思考&分析规划` → `数据获取和可视化` → `根因分析` → `决策行动`，编号 `01`–`06`；普通会话、报表会话、Dashboard 与历史会话恢复展示一致。
- SOP 是真实执行轨迹：只有实际进入并完成的步骤标绿，当前步骤显示进行中，支持 `05 → 03`、`04 → 03`、`06 → 05` 等真实回退，回退后后续步骤重新计算为未开始，同一步可重复进入形成循环；同一时刻最多一个“进行中”步骤。
- 新增 `skipped`（已跳过）状态：本轮未执行的步骤结束时显示为已跳过（非绿色样式），只有后端终止事件 `done` 才允许整轮完成，`error` / `session_superseded` / 等待用户选择 / 图表表格正文等都不会把整轮标记完成。
- 结束态统一清理流式光标、“思考中…”占位行、步骤时间线思考行和空白 assistant 占位卡，历史会话恢复同样清除瞬态加载元素，不再出现闪动卡片。
- 后端新增结构化 SSE 事件 `sop_progress`（step/detail/allow_backward/turn_id）作为唯一驱动，工具与正文映射仅作兼容兜底；旧 turn 的 SOP 事件不能污染新 turn；SOP 只负责展示，不构成最终回答门禁，事件缺失时回答照常输出。
- 历史兼容：旧五步 / 旧六步 / 旧九步快照在展示层映射为六步（完成快照恢复为六步全完成，未完成快照映射到最近步骤），历史会话 JSON 不重写、不批量迁移。
- 主要文件：`frontend/src/sopMachine.js`（新增纯函数状态机）、`frontend/src/runtime.js`、`frontend/src/workbench.css`、`bi_agent/web/session.py`、`bi_agent/web/app.py`、`tests/test_regressions.py`。

### 2. 请求生命周期与 SSE 终态一致性

- 新增 `bi_agent/concurrency.py` 并发治理：同一会话已有回答生成时再次请求返回 `409 SESSION_BUSY`；reset / 恢复历史 / 激活报表 / 切换数据源会提升 generation 并立即取消旧 turn（返回 `429 ADMISSION_CANCELLED` 或 `409 TURN_SUPERSEDED`），新问题可立即开始回答；服务繁忙返回 429 并带 `Retry-After`；排队为严格 FIFO，所有关键 SSE 事件带 `turn_id`（`done` 额外带 `generation`），旧流不会清掉新流的 busy 状态。
- 8 月 28 日完成 SSE 终态一致性修复：SSE 流在没有后端明确 `done` 时结束（代理/Nginx 截断、浏览器断网、后端异常退出、残缺 JSON、用户中断、被新请求取代）不再被伪装成成功，按“生成中断”处理——保留已显示正文并提示“连接中断，本轮内容可能不完整”，不清算 SOP、不添加导出按钮、不保存为已完成回答、不自动重试。
- `done` 幂等改为有界 `completedTurnIds` 集合（容量 64 的 FIFO，`frontend/src/turnLifecycle.js`）：同一 turn 无论连续还是延迟重复 `done` 都只执行一次成功副作用（`T1 done → T2 done → T1 done` 中最后一个 T1 被忽略）；error / session_superseded / stream_interrupted 记录的 failed turn，迟到 `done` 不能翻转为成功。
- 旧请求的流被新请求取代后保持静默（request sequence + turn_id 复核），不污染新请求的 busy / 加载卡 / SOP / 保存；HTTP 409/429 拒绝请求时清理本轮“思考中…”占位卡并恢复输入框，不留下永久加载卡。
- 行动建议补写阶段（action repair）模型若返回工具调用：工具不执行、不出现在前端 `llm_response` 的 `tool_uses`（恒为空）、不产生悬空 Tool 卡片、不写入会话上下文和历史；只保留纯文本继续有效性检查，连续只返回工具时按既有上限结束并给出“交付不完整”提示，不收紧任何输出门禁。
- 主要文件：`bi_agent/concurrency.py`（新增）、`frontend/src/streamTerminal.js`（新增）、`frontend/src/turnLifecycle.js`（新增）、`bi_agent/web/app.py`、`bi_agent/web/session.py`、`frontend/src/runtime.js`、`tests/test_concurrency.py`、`tests/test_regressions.py`。

### 3. 结构化交付质量与可靠性

- Structured Claims 最终答案去重：有 Structured Claims 时无工具调用的回复作为候选终稿在后端缓冲，先注入 Claims 上下文再逐版独立校验，校验通过后才一次性提交可见 `text_delta`、`llm_response` 并持久化；被拒绝的草稿既不显示也不入库，前端同步清理被丢弃候选留下的空“思考中…”气泡；连续两次校验失败仍正常发出 `answer_blocked` 与 `done`。
- “行动建议”章节提取器新增扩展边界标题（口径说明与限制披露、限制披露、冲突披露、数据限制、证据限制、风险与限制等），指标口径、物理表与关联键、可比样本范围、冲突披露等不再被错误解析成行动条目。
- 根因分析、行动建议与结构化行动卡片只保留在对话区，看板只保留用户问题、结论卡片和表格/图表/多维图；旧历史快照中的 `dash-rootcause` / `dash-actions` / `dash-export` 迁移到对话区并从看板移除。
- Evidence Consistency Guard 与非空回答兜底：Doris / 本体数据接口返回数值字符串时仍能生成 FACT Claim；数字完全退出回答门禁；Claim 从“全部叙述的主门禁”降级为证据一致性护栏（已知冲突未披露、代理指标冒充真实指标仍是硬问题）；校验器自身异常时 fail-open，连续硬校验失败输出“已确认 Claims + 缺失证据 + 后续处理”的安全回答。
- 按用户授权对历史会话 `f8cf8d06` 定点修复：移除被拒候选 Narrative 及内部 claim 注入/拒绝提醒消息，只保留最终通过校验的有效回答与两条真实行动，同步重建 `chat_html`。
- 主要文件：`bi_agent/web/session.py`、`bi_agent/tools/analysis_policy.py`、`bi_agent/reliability.py`、`frontend/src/runtime.js`、`tests/test_reliability.py`、`tests/test_regressions.py`。

### 4. 业务名称优先展示

- 面向用户的正文、结论、表格和图表不再直接展示裸编码：有业务名称时名称是主要展示文本，编码只作为次要追溯信息（首次或需追溯时形如“采购金额（M0001）”），无法解析名称时保留原编码、不猜测、不编造；SQL 代码块、URL、JSON、`source_note` 不被名称处理误改。
- 新增 `bi_agent/display_names.py` 统一确定性名称解析层（本体对象名称优先级、`display_text` 追溯格式、编码识别、`unique_aliases` 稳定去重、图表/多维图/表格参数规范化入口）；`ChartGenerate`、`ChartGenerateMultiDim`、`TableGenerate` 的参数与表头自动规范化，`MetricDataQuery` 的 analysis 请求 `alias` 优先使用稳定业务名称。
- 三类 Agent 提示词新增“业务名称优先展示（最高优先级）”规则段，包含可信来源优先级、图表/表格/SQL 输出规则与输出前强制自检；无可信名称映射时保留原编码，禁止猜测或编造名称。
- 主要文件：`bi_agent/display_names.py`（新增）、`bi_agent/tools/remote_ontology_tools.py`、`bi_agent/tools/chart_tools.py`、`bi_agent/tools/chart_multidim_tools.py`、`bi_agent/tools/table_tools.py`、`bi_agent/tools/sql_tools.py`、`.claude/agents/*.md`、`tests/test_regressions.py`。

### 5. 模型与可见思考

- Team/LiteLLM 网关模型目录按实测结果维护：ChatBI 模型选择列表更新为 24 个已验证可用模型，排除未路由、鉴权失败或被拒绝的条目；`supports_thinking` 改为本地实测能力表（24 个模型逐一最小真实请求验证），不再统一标记。
- 团队网关默认模型由 `Qwen/Qwen3-80B-AWQ` 切换为 `direct-deepseek-v4-flash`，代码内置默认值、`.env.example`、部署文档示例与生产 `.env` 的 `TEAM_MODEL` 同步；thinking 参数按模型族路由，thinking 关闭时上游即使仍返回 reasoning 也不会向用户展示。
- 用户开启 thinking 且模型支持时注入简体中文可见思考约束（简短概括、不暴露逐 token 推理与内部提示）；自动配额 fallback 改为仅当前 turn 生效，不再改写用户已保存的模型选择，下一轮从用户显式选择的原模型开始。
- 主要文件：`bi_agent/llm/registry.py`、`bi_agent/llm/provider_team.py`、`bi_agent/web/session.py`、`.env.example`、`DEPLOYMENT.md`、`tests/test_regressions.py`。

### 6. 本体与工具

- Agent Tool 对外标识统一为 `Ontology-SemanticQuery`、`Ontology-MetricQuery`、`Ontology-FactQuery`、`Ontology-TermDisambiguate`、`Ontology-RelationQuery`、`Ontology-EntityDescribe`（指标计算保持 `MetricCalculation`，图库工具为 `Ontology-GraphContext` / `Ontology-GraphExpand`），三个 Agent 的白名单、本地及远程 Tool Schema、SSE/SOP 映射、前端工具卡片与来源识别全部同步；新增 `docs/ChatBI_Tools.md` 纯名称清单，历史会话内旧 Tool 名称按用户要求精确迁移（不删除、不重建）。
- `Ontology-FactQuery` 工具卡片首行改为简短中文查询目标（如“查询超期未接收含税金额”），完整 SQL 与参数保留在卡片展开后的输入详情中；该逻辑由前端纯函数确定性完成，不调用额外大模型，历史会话恢复按同一套规则重新生成摘要。
- 全局本体子图卡片：工具调用后的“命中的本体”标签与“本体内容”实体卡统一支持点击弹出本体子图（GraphContext 上下文子图 + GraphExpand 扩散图），复用 ontology-agent 的 Sigma + Graphology + ForceAtlas2 实现；子图查询为独立只读接口，不调用 LLM、不执行 SQL、不写入聊天历史、不推进 SOP；兼容远程本体“未知本体类型: TableNode”已知缺陷的只读 OpenCypher 降级。
- 主要文件：`bi_agent/tools/ontology_tools.py`、`bi_agent/tools/remote_ontology_tools.py`、`bi_agent/tools/sql_tools.py`、`bi_agent/ontology/remote_retriever.py`、`bi_agent/web/session.py`、`bi_agent/web/app.py`、`frontend/src/runtime.js`、`frontend/src/factQueryPreview.js`（新增）、`frontend/src/ontologySigmaGraph.js`、`docs/ChatBI_Tools.md`（新增）、`tests/test_regressions.py`。

### 7. 版本、品牌与交付规范

- 根 `README.md` 归位为 openchat-BI“智能分析”项目入口（产品能力、六步分析流程、系统结构、配置、Web 启动、前端构建、测试、Agent/Tool 文档、数据安全、语义化版本、双远端交付与 GitHub Release），Open Claude 通用 Runtime 说明迁移至 `open_claude/README.md` 并与根 README 相互链接。
- 品牌由“智析”改为“智能分析”，左上角显示版本 `v0.1.0`（Ant Design Tag）；`bi-analyst` 不再显示在产品名后冒充版本，实际 Agent 角色配置保留；HTML title、加载骨架、aria-label 与 React 工作台品牌统一；版本契约统一为 `0.1.0`（`pyproject.toml`、`bi_agent/__init__.py`、FastAPI 应用、`frontend/package.json`、`frontend/package-lock.json` 根包），产品版本与会话 schema / 知识库 / 缓存版本相互独立。
- 正式版本文档路径建立：`docs/versions/README.md` 版本索引 + `docs/versions/v0.1.0.md` 正式版本说明 + `docs/versions/versioning-policy.md` 语义化版本规范（`vMAJOR.MINOR.PATCH`，版本由变更性质决定，不按日期/commit 数量/部署次数机械递增；Agent 不得自行升级版本，tag / GitHub Release / 部署需要各自独立授权）。
- 双远端镜像工作流：新增 `scripts/push_dual_remotes.py`（`--check`、校验分支与远端 URL、拒绝 dirty worktree / detached HEAD / 覆盖远端独有提交、禁止 force push、先推 origin 再推 personal、推送后校验 `HEAD == origin/20260727 == personal/main`）；新增 `docs/git-dual-remote-workflow.md`；`AGENTS.md` 增加“提交、双远端推送与禁止部署（最高优先级）”与正式版本文档工作流。
- 全局交付规范统一为“修改 → 本地验证 → 复查 Git diff → commit → push 当前远程分支 → 结束”，默认不部署；`AGENTS.md` 新增“Git 推送与部署规则”，`debug.md` 全面修订，`.claude/agents/devops.md` 与 `DEPLOYMENT.md` 增加“仅用户当前任务明确授权时部署”的最高优先级限制；确认仓库无自动部署 CI 配置，普通 push 不会自动部署。
- 双仓 GitHub Release 规范固化：用户授权创建 Release 后默认在 `tianzj890107/openchat-BI` 与 `zhenzhang0408/openchat-BI` 两个仓库各发布一个，两个 Release 使用相同版本号、tag、名称和正式版本说明，tag 指向同一个定版 commit；只补缺失项、不覆盖已有 Release、单仓成功不回滚。
- 定版：`v0.1.0` 完成正式定版，创建 annotated tag `v0.1.0` 并双推 origin / personal（peeled commit 与双推后 HEAD 一致）；正式 Release“智能分析 v0.1.0”已在两个仓库发布（主协作仓库原已存在保留，个人镜像仓库补建）。
- 主要文件：`AGENTS.md`、`README.md`、`debug.md`、`DEPLOYMENT.md`、`.claude/agents/devops.md`、`scripts/push_dual_remotes.py`（新增）、`docs/git-dual-remote-workflow.md`（新增）、`docs/versions/`（新增）、`frontend/src/main.jsx`、`frontend/src/shell.html`、`bi_agent/web/static/index.html`、`tests/test_versioning_policy.py`（新增）、`tests/test_push_dual_remotes.py`（新增）。

### 8. 部署记录（历史事实）

- 8 月 24 日：Team 模型目录与默认模型发布到测试服务器 `f08a67b` release 并重启，健康检查正常，`/api/config` 返回 24 个 Team 模型且当前模型为 `Qwen/Qwen3-80B-AWQ`。
- 8 月 25 日：九步 SOP 拆分与循环进度、ChatBI 第一阶段并发治理发布到测试服务器 `f08a67b` release 并重启，`/healthz`、`/workbench` 与线上 `workbench.js` 验证通过。
- 8 月 26 日：三次同步生产——五步 SOP 状态机 / Team thinking 能力表 / 可见思考中文约束 / turn 级 fallback / 业务名称优先展示 / 并发治理 / 看板卡片位置（备份 `f08a67b-backup-20260826-110556-thinking-sop`）；SOP 名称与团队默认模型切换为 `direct-deepseek-v4-flash`（含生产 `.env` 定点修改，已备份）；SOP 面板移除 detail 行；随后发布全局本体子图卡片（备份 `f08a67b-backup-20260826-152652-ontology-subgraph`）。每次部署前均备份被覆盖的源码/静态资源，未触碰历史会话、上传、图表与日志，部署前后历史会话文件数与指定会话 SHA-256 一致。
- 8 月 27 日：Agent Tool 命名统一与六步 SOP 发布到测试服务器当前 release 并重启，`/healthz` 正常，76 个服务器历史会话完成旧名称迁移（发布前创建代码备份与完整会话压缩备份）。
- 以上部署均为当周历史事实；自 8 月 28 日起仓库默认交付规范已改为 commit + push、不部署，后续任务只有用户明确授权才执行部署。
