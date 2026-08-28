# openchat-BI 变更记录（2026-08-28）

> 本文档只记录 2026-08-28 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 2026-08-28

### 请求生命周期终态一致性修复（SSE 中断与行动补写悬空 Tool）

用户可见变化：
- SSE 流在没有后端明确 `done` 时结束（代理/Nginx 截断、浏览器断网、后端异常退出、
  残缺 JSON、用户中断、被新请求取代），不再被伪装成成功：界面按“生成中断”处理，
  已显示的正文保留但明确提示“连接中断，本轮内容可能不完整”，不清算 SOP、不添加
  导出按钮、不保存为已完成回答、不自动重试；只有显式收到后端 `done` 才执行成功
  终态（SOP 完成、导出按钮、保存）。
- 同一 turn 重复 `done` 不再重复保存或重复添加导出按钮；已经以 error /
  session_superseded / 中断结束的 turn，迟到 `done` 不会把它翻转为成功。
- 旧请求的流被新请求取代后保持静默：不会清理新请求的 busy、不会删除新请求的加载
  卡、不会保存或推进新请求的数据，也不会在 EOF 时向新请求注入中断提示。
- 行动建议补写阶段（action repair）模型若返回工具调用：工具不执行、不出现在前端
  `llm_response` 的 `tool_uses`（恒为空）、不产生悬空 Tool 卡片、不写入会话上下文
  和历史；只保留纯文本继续有效性检查。补写连续只返回工具时按既有上限结束并给出
  “交付不完整”提示，已有根因回答仍然交付，不收紧任何输出门禁。
- HTTP 409/429 拒绝请求时，清理本轮“思考中…”占位卡并恢复输入框可操作状态，不额外
  创建错误卡。

实现方式：
- 前端新增纯函数 `frontend/src/streamTerminal.js`（`classifyStreamEof`）：EOF 时按
  “stale / terminal / interrupted” 分类，普通 EOF 一律 `interrupted`，绝不合成
  `done`；`streamResponse` 增加 stale 跟踪（request sequence + turn_id），并在 EOF
  时复核 sequence 防止旧流污染新请求。
- 前端新增 `stream_interrupted` 终态分支：清理 loading / cursor / 空白占位，提示
  中断，不执行成功侧副作用；`done` 幂等改为有界的 `completedTurnIds` 集合
  （`frontend/src/turnLifecycle.js`，容量 64 的 FIFO）：同一 turn 无论连续还是延迟
  重复 `done` 都只执行一次成功副作用，`T1 done → T2 done → T1 done` 中最后一个
  T1 被忽略；error / session_superseded / stream_interrupted 记录的 failed turn，
  迟到 `done` 不能翻转为成功；模式切换中止的旧流通过递增请求序号保持静默。
- 后端 `bi_agent/web/session.py` 行动补写阶段的 `llm_response` 事件 `tool_uses`
  固定为空数组，工具名（不含 SQL/输入）仅记内部 warning；补写内容依旧只提交文本
  与 thinking，不把工具写入消息历史。

主要文件：`frontend/src/streamTerminal.js`（新增）、`frontend/src/turnLifecycle.js`
（新增）、`frontend/src/runtime.js`、`bi_agent/web/session.py`、
`bi_agent/web/static/vendor/antd/workbench.js`、`tests/test_regressions.py`。

测试：新增 EOF 分类纯函数（node）、turn lifecycle 真实事件序列纯函数测试（普通
done 单次成功副作用、连续/延迟重复 done 幂等、失败后迟到 done 拒绝、容量有界、
reset 清理）、action repair 三类生成器测试（仅工具不执行且 tool_uses 为空、文本+
工具只取文本、连续仅工具达到上限后非阻断结束）；全量 Python 测试通过；前端生产
构建通过；`git diff --check` 通过。

### 全局交付规范：默认 commit + push，不部署

用户可见变化：
- 仓库级执行规范统一为“修改 → 本地验证 → 复查 Git diff → commit → push 当前远程
  分支 → 结束”，不再默认进入部署阶段。
- 默认禁止部署服务器、SSH/rsync/scp 同步、重启 systemd 或进程、更新生产/测试运行
  目录、调用部署脚本、触发发布流水线、修改服务器 `.env` 或数据。
- 只有用户在当前任务中明确说“部署”“发布到服务器”时才允许部署；历史任务的部署授权
  不延续；“完成”“修复”“验收通过”“继续做”等表述不构成部署授权；用户明确说“不部
  署”时禁止任何服务器写操作和服务重启。
- push 前必须完成合理验证；禁止 force push；禁止提交 secret、`.env`、用户数据和
  运行产物；若 push 会触发仓库已有自动部署流水线，先停止并报告，不得通过 push 间
  接部署。

实现方式：
- 根目录 `AGENTS.md` 新增“Git 推送与部署规则”小节作为仓库级永久规范。
- `debug.md` 全面修订：顶部闭环、默认交付、完成条件、最终报告模板和执行原则总结
  均改为 commit + push 且默认不部署；部署相关章节全部明确标注“仅当用户当前任务明
  确要求部署时适用”。
- 检查确认仓库无 `.github/workflows`、GitLab CI、Jenkinsfile、deploy hooks 等自动
  部署触发配置，普通 push 不会自动部署。

主要文件：`AGENTS.md`、`debug.md`。

验证：`git diff --check` 通过；全局扫描确认残留命中均为条件性部署说明或历史事实，
无“默认自动部署”类规范指令。


### 品牌与版本：智能分析 v0.1.0

用户可见变化：
- 左上角品牌由“智析”改为“智能分析”，并显示版本 `v0.1.0`；`bi-analyst` 不再显示在
  产品名后冒充版本，实际 Agent 角色配置保留。
- HTML title、加载骨架、aria-label 与 React 工作台品牌全部统一为“智能分析”。
- 版本契约统一为 `0.1.0`：`pyproject.toml`、`bi_agent/__init__.py`、FastAPI 应用、
  `frontend/package.json`、`frontend/package-lock.json` 根包；产品版本与会话 schema
  版本（数值）相互独立。

实现方式：
- `frontend/src/main.jsx` 新增统一常量 `PRODUCT_NAME` / `PRODUCT_VERSION`，React
  侧栏品牌用 Ant Design Tag 渲染版本号；`frontend/src/shell.html` 与
  `bi_agent/web/static/index.html` 的品牌、title、骨架文案同步更新；
  `frontend/src/workbench.css` 增加版本样式。
- 新增 `docs/versions/README.md`（版本索引）与 `docs/versions/v0.1.0.md`（正式版本
  说明），根 `README.md` 增加版本与文档链接；不创建根目录 `CHANGELOG.md`，不创建
  Git tag / Release。

主要文件：`frontend/src/main.jsx`、`frontend/src/shell.html`、
`bi_agent/web/static/index.html`、`frontend/src/workbench.css`、
`docs/versions/README.md`、`docs/versions/v0.1.0.md`、`README.md`、
`bi_agent/web/static/vendor/antd/workbench.js`、
`bi_agent/web/static/vendor/antd/openchat-bi-workbench.css`。

测试：新增品牌/版本回归测试（左上角品牌为“智能分析”、显示 `v0.1.0`、不再出现
“智析”/“bi-analyst”、五个版本契约文件一致、版本独立性）；全量 Python 测试与前端
构建通过。

后续修正：
- `v0.1.0` 正式版本说明移除已不存在的 `SQLRun`、`MetricDataQuery`，改为与代码注册
  一致的工具表述：`MetricCalculation`（指标定义、业务公式、统计口径、SQL 组件和
  适用维度）、`Ontology-MetricQuery`（远程本体指标配置查询接口计算指标数据，已获得
  指标编码和维度编码时优先）、`Ontology-FactQuery`（只读事实查询或自主 SQL，指标
  配置接口不支持/失败或需核验底层明细时使用），以及 `TableGenerate`、
  `ChartGenerate`、`ChartGenerateMultiDim` 和 `ListTables`/`DescribeTable`。
- 正式版本文档中的现行 Tool 名称与 Agent `tools:` 声明和 Tool Schema 注册保持一致；
  当前版本仍为 `v0.1.0`；本次没有创建 tag、GitHub Release，也没有部署。
- 测试：`tests/test_versioning_policy.py` 新增正式版本文档工具名一致性测试（不包含
  `MetricDataQuery`/`SQLRun`、三者职责区分、文档工具名均可从权威入口找到）。

### 双远端镜像工作流与正式版本文档

用户可见变化：
- 交付动作升级为双远端推送：同一个 commit 同时推送到 `origin/20260727`（主协作）
  与 `personal/main`（个人私有镜像），完成标准 `HEAD == origin/20260727 ==
  personal/main`；push 不等于部署，未获当前任务明确部署授权时双 push 后结束。
- 正式版本文档路径建立：`docs/versions/README.md` + `docs/versions/vX.Y.Z.md`，
  与每日 changelog 分开维护。

实现方式：
- 新增 `scripts/push_dual_remotes.py`：支持 `--check`、校验当前分支/两个远端
  URL/工作区干净/detached HEAD/远端祖先关系，拒绝覆盖远端独有提交，禁止 force
  push，先推 origin 再推 personal，推送后校验三个 hash 一致；personal 失败时报告
  部分成功、不回滚 origin、不生成补偿 commit。
- 新增 `docs/git-dual-remote-workflow.md` 记录远端映射、日常流程、首次设置、安全
  规则与失败恢复；`AGENTS.md` 增加“提交、双远端推送与禁止部署（最高优先级）”与
  “正式版本文档工作流”；`.claude/agents/devops.md` 与 `DEPLOYMENT.md` 增加“仅用户
  当前任务明确授权时部署”的最高优先级限制。

主要文件：`scripts/push_dual_remotes.py`（新增）、`docs/git-dual-remote-workflow.md`
（新增）、`AGENTS.md`、`README.md`、`.claude/agents/devops.md`、`DEPLOYMENT.md`、
`tests/test_push_dual_remotes.py`（新增）。

测试：新增双远端脚本行为测试（临时目录 + 本地 bare 仓库，共 12 项：正常双推、
personal/main 首次创建、重复执行幂等、dirty worktree 拒绝、detached HEAD 拒绝、
缺少 personal 拒绝、remote 地址错误拒绝、personal/origin 独有提交拒绝、origin 成功
personal 失败不回滚、三 hash 一致、无 force push）；全部通过。

### 语义化版本与正式发布规范

用户可见变化：
- 固定产品版本格式 `vMAJOR.MINOR.PATCH`，当前版本仍为 `v0.1.0`；版本号由变更性质
  决定，不按日期、commit 数量或部署次数机械递增。
- 明确边界：commit、每日 changelog、正式版本文档、Git tag、GitHub Release、部署
  相互独立；commit/push/部署不自动触发版本升级；Agent 不得自行升级正式版本，只有
  用户明确指定目标版本时才可升级。
- 每日可发布 PATCH（修复/稳定性/文案等），每周只有形成完整新能力时才发布 MINOR；
  纯文档、测试补充和格式化不单独发布正式版本。

实现方式：
- 新增 `docs/versions/versioning-policy.md` 作为唯一完整规范；`README.md`、
  `docs/versions/README.md`、`AGENTS.md`、`docs/git-dual-remote-workflow.md` 增加
  摘要与链接。
- `AGENTS.md` 增加“版本升级强制规则（最高优先级）”：不得自行升级版本、每周不自动
  升级 MINOR、每次部署不自动升级 PATCH、tag/Release/部署需要各自独立授权。
- 本次没有创建新版本、Git tag、GitHub Release，也没有部署。

主要文件：`docs/versions/versioning-policy.md`（新增）、`docs/versions/README.md`、
`README.md`、`AGENTS.md`、`docs/git-dual-remote-workflow.md`、
`changelog/changelog_8_28.md`、`tests/test_versioning_policy.py`（新增）。

测试：新增版本文档契约测试（规范存在与关键语义、各文件链接与强制授权规则、当前
版本仍为 v0.1.0、未创建 v0.1.1 文档或 tag）；全量 Python 测试与 `git diff --check`
通过。
