# eimosp-ontology-agentic-analytics 变更记录（2026-09-07 至 2026-09-11）

> 本文档记录 2026-09-07（周一）至 2026-09-11（周五）当周的最终变更，按周直接维护
> （2026-09-08 起 changelog 只按周维护，不再创建日报）。9/7 当天未建日报，本节内容
> 依据 9/7 git 提交记录补录（提交 `2c6fdf8`…`1ae9894`、`18a3e24`）；9/8 记录
> changelog 维护规则调整；9/9–9/11 变更完成后直接追加到本文档。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 2026-09-07（周一）

### 1. 分析 Agent 工具执行可靠性第一阶段：Tool Runtime 执行边界（TDD RED→GREEN，已完成）

- 新增 Spec `docs/specs/tool-runtime-execution-boundary.md` 与 RED 契约
  `tests/test_tool_execution_boundary.py`（6 项 RED 起步），新增独立模块
  `bi_agent/tool_runtime.py` 承载执行边界，`WebSession` 两条工具路径（AskUser 前
  sibling tools 与普通工具执行）统一接入。
- 关键能力：`execution_id`（UUID，不等于 tool_use_id）；幂等键包含
  session/turn/generation/tool_use_id/tool_name/canonical input（递归稳定排序），
  同键重复投递不重复执行、不隐式重试；单工具超时（`tool_timeouts`，合理默认 + 按
  工具覆盖）；状态机 PENDING→RUNNING→SUCCEEDED/FAILED/CANCELLED/TIMED_OUT，终态
  不可变，转换在 ledger lock 下 CAS。
- executor 启动权原子化：timeout 先取得终结权后 worker 永不再调用 executor；worker
  先取得不可撤销启动权时，超时只撤销提交权、不强杀线程
  （`test_timeout_between_preflight_and_invoke_cannot_start_executor`），迟到结果
  不能覆盖 TIMED_OUT 或污染会话。
- stale-result 门禁：固定捕获 TurnContext，业务提交前复核 cancel/owner/generation/
  execution 状态与提交权；bump_generation 后迟到结果不进入 query_results/claims/
  图表状态，不发成功 tool_result，审计为 CANCELLED/STALE_TOOL_RESULT。
- 错误分类结构化（TOOL_TIMEOUT/TOOL_CANCELLED/STALE_TOOL_RESULT/
  TOOL_EXECUTION_ERROR），内部不再用 `str(output).startswith("Error")` 判断成败，
  仅在 WebSession 边界把结构化失败转旧字符串兼容 LLM 协议。
- 审计安全：`WebSession.tool_execution_records` 返回按创建顺序的防御性快照；审计只
  存 SHA-256 摘要/长度/有界 result_ref/脱敏 error_message，不存 token/password/
  secret/连接串凭据/traceback/无界完整结果；完整业务结果与审计限界分离（成功
  output 完整返回 executor 结果，不受审计限界截断）。
- SSE 兼容：成功 tool_result 保留全部原字段并增加
  `execution_id/execution_status/attempt`；不删除既有 id/name/input/output/
  duration_ms/ontology_entities/chart/table/multi_chart/todos。
- 验证：`tests.test_tool_execution_boundary` 9 OK（含原子启动权竞态测试）；未访问
  真实 Doris/LLM/本体服务。

### 2. 第二阶段：轻量 Recovery 状态机（TDD RED→GREEN，已完成）

- 新增 Spec `docs/specs/lightweight-analysis-recovery.md` 与 RED 测试
  `tests/test_analysis_recovery.py`（9 项起步，后增至 11 项），新增
  `bi_agent/recovery.py`（RecoveryStatus/RecoveryStep/RecoveryCheckpoint/
  RecoveryState/AnalysisRecoveryManager）。
- 七状态：PLANNED/RUNNING/WAITING_USER/SUCCEEDED/FAILED_RETRYABLE/FAILED_FINAL/
  CANCELLED；终态不可覆盖；AskUser 暂停为 WAITING_USER、有效选择后恢复 RUNNING 且
  沿用原 turn_ref；工具超时→FAILED_RETRYABLE 并停止当前轮次（不再请求下一次 LLM）；
  非重试异常→FAILED_FINAL；supersede→CANCELLED。
- checkpoint 原子提交：工具 checkpoint 保存 tool_use_id + input/result SHA-256 摘要
  与有界 result_ref，不存 SQL/完整输入/凭据；stale、cancelled、未过 Evidence Gate
  的结果不能成为成功 checkpoint；只有最终回答通过 Claim/Evidence/Action/Render
  门禁才 RUNNING→SUCCEEDED 并生成 DELIVER checkpoint。
- 显式 retry：仅 FAILED_RETRYABLE 可调用；先验证状态→checkpoint→retry
  descriptor→attempt 上限，最后才 FAILED_RETRYABLE→RUNNING（避免先进 RUNNING 再
  失败）；attempt 1→2，再失败 RETRY_EXHAUSTED→FAILED_FINAL。
- 持久化恢复：ConversationStore 保存 recovery_state（规范化、有界）；RUNNING 快照
  恢复时降级 FAILED_RETRYABLE/INTERRUPTED_DURING_EXECUTION；
  `restore_recovery_state` 依据 checkpoint.tool_use_id 只在当前会话已持久化
  assistant tool_use messages 中重建 retry 描述，找不到输入立即降级
  FAILED_FINAL/RECOVERY_INPUT_MISSING；旧快照缺 recovery_state 时正常恢复并初始化
  为 PLANNED。
- 验证：`tests.test_analysis_recovery` 11 OK（含持久化后重试重建与不可恢复快照降级
  两项验收修复）。

### 3. 第三阶段：共享多实例协调与租约 + 生产接线（TDD RED→GREEN，已完成）

- 新增 Spec `docs/specs/shared-multi-instance-coordination.md` 与 RED 测试
  `tests/test_shared_coordination.py`，新增 `bi_agent/shared_coordination.py`，从
  `bi_agent.concurrency` 重新导出测试约定入口。
- 能力：InMemorySharedCoordination（多个 registry/controller 共享同一 backend、
  fake clock、TTL、单调 fence、共享 admission、snapshot/health/wait_until_queued）
  与 RedisSharedCoordination（acquire/renew/release/bump generation/admission 均
  走 Redis Lua `eval` 原子入口，不依赖本地 Python 锁；key 带 namespace）；
  SessionSlotRegistry/AdmissionController 以 `shared_backend=None` 保持本地默认行为
  完全兼容。
- TurnLease 扩展 fence/shared_key/instance_id/expires_at（默认值保持旧构造兼容）；
  共享 lease 的 owner 为不可预测随机 token；fence 严格递增且不因过期/release 重置；
  acquire/renew/release 全字段验证（key/owner/generation/fence/TTL）；heartbeat
  丢失或 owner mismatch 置同一 cancel event；实例崩溃依靠 TTL 回收。
- 配置工厂 `build_coordination_backend`：local 默认；redis 缺 URL 抛 ValueError；
  closed 模式初始化失败即启动失败；仅显式 local fallback 允许降级
  （redis_degraded/effective_mode=local）；`CHATBI_*` 环境变量；health() 不暴露
  Redis 密码/URL/用户内容。
- 生产接线（验收修复，3 项 RED → 13 项全绿）：`AppState.configure_coordination/
  configure_coordination_from_env` 把同一 backend 安装到 session_slots/admission，
  应用启动 `configure()` 调用配置工厂；`_begin_turn` 共享模式带 TTL 取得 fencing
  lease（lease.fence>0）；SSE turn heartbeat guard（start_turn_heartbeat/stop/join，
  renew 失败或 owner mismatch 置 cancel，本地模式 no-op 不建线程）；
  `_run_turn_stream` finally 顺序停止 heartbeat→clear_current_cancel→
  owner-validated release→admission release；healthz 增加有界 coordination 摘要；
  conversation save 纳入共享 lease/fence 提交门禁。
- 验证：`tests.test_shared_coordination` 13 OK；本地默认模式不回归；未连接真实
  Redis。

### 4. 轻量结构化 Cognitive Policy 决策记录（Spec + TDD RED→GREEN，已完成）

- 新增 Spec `docs/specs/structured-cognitive-policy.md` 与 RED 测试
  `tests/test_cognitive_policy.py`（10 项起步，后增至 11 项）；
  `bi_agent/tools/analysis_policy.py` 新增纯函数
  `build_cognitive_policy_decision(question, allowed_tools)`（无 LLM/网络依赖，
  JSON 可序列化）。
- 决策字段：policy_version=1、mode、reason_code、next_step、required_tools、
  evidence_required、needs_human、input_digest（`sha256:`+64 位小写 hex，基于空白
  规范化问题）；决策不保存原始问题/SQL/工具结果/密钥；工具集合去重且不受输入顺序
  影响；同一规范化问题与工具集合的决策完全确定。
- 路由复用现有 `classify_intent`/`wants_root_cause`/`wants_action`（不复制第二套
  异常正则）：FACT_QUERY（Ontology-MetricQuery 优先、FactQuery 兜底）、
  DIAGNOSTIC_ANALYSIS（L2 异常/问题/波动/偏差与 L3/L4/L5 根因/行动均进入）、
  ONTOLOGY_LOOKUP（仅 Ontology-SemanticQuery）、CLARIFICATION（仅 AskUser 可用时）、
  CAPABILITY_LIMITATION（无对应工具时 required_tools=[]）；required_tools 永远是
  allowed_tools 的子集，不推荐未授权工具。
- WebSession：每个新用户轮次只生成一次决策；`cognitive_policy_decision` 返回深拷贝
  防御性快照；`user_message` 之后、首次 `llm_request` 之前发 `cognitive_policy`
  SSE 事件（直接携带决策字段、不含原始问题）；`continue_with_choice`/
  `retry_from_checkpoint` 不重新分类；`bi_agent.web.app._TURN_EVENT_TYPES` 注册该
  事件类型以附加 turn_id，旧前端忽略后不受影响。
- 验证：`tests.test_cognitive_policy` 11 OK（含 L2 异常/问题/波动 3 子场景路由修复
  与 `Any` 注解解析修复）。

### 5. 文档与交付状态

- 周 changelog 8/31–9/4 汇总创建：`changelog/changelog_8_31_9_4.md`（提交
  `18a3e24`），合并 8/31、9/1、9/2、9/3 四份日报为周颗粒度。
- `gitlab/20260727` 推进至 `1ae9894` 并推送成功（HEAD == gitlab/20260727）。
- MR !5（`20260727` → `main`）创建并更新至完整交付范围：207 提交 / 231 文件
  （+95,388 / −5,151），标题与描述按主题覆盖全部提交（后端可靠性四阶段、本体控件
  验收、版本定版 v0.1.x、GitLab 工程规范、React 工作台、远程本体与历史会话等）；
  reviewer `tianzijing`、assignee `zhangzhen`；只创建 MR，未自动合并、未直接推送
  main。
- 后端相关全量回归：Recovery 11 + Tool Runtime 9 + Shared 13 + concurrency 39 +
  reliability 25 + regressions 219 = 316 项通过；含 Cognitive Policy 11 项合计
  327 项通过；`git diff --check` 干净。

## 2026-09-08（周二）

### 1. changelog 维护规则改为只按周维护（流程调整，2026-09-08 09:28）

- 按用户要求：删除上周日报与本周预建日报（8/31、9/1、9/2、9/3 已并入
  `changelog/changelog_8_31_9_4.md`；9/7–9/11 日报内容并入本文件），changelog 只
  保留周文件，以后直接按周维护。
- 规则同步：`AGENTS.md` 的「Changelog workflow」小节改写为「按周维护」；
  `docs/versions/versioning-policy.md` 中“每日 changelog”记录格式与发布工作流引用
  同步改为当周 changelog；每条记录需注明改动时间。
- 历史日报内容均已并入对应周文件，未丢失内容，git 历史保留原文件。
- 主要文件：`changelog/changelog_8_31_9_4.md`（归档说明）、
  `changelog/changelog_9_7_11.md`（本周新增）、`AGENTS.md`、
  `docs/versions/versioning-policy.md`。

### 2. Configurable Application Base Path（子路径部署适配，TDD RED→GREEN，2026-09-08 12:05）

- 新增 Spec `docs/specs/configurable-application-base-path.md` 与 RED 测试
  `tests/test_application_base_path.py`（6 项）；`APP_ROOT_PATH` 支持外部反向代理
  子路径前缀（生产示例 `/api/ontology-agentic-analytics`），未配置时保持域名根路径
  行为不变，不复制注册一套固定前缀路由。
- 后端：`_normalize_app_root_path` 规范化前缀并对非法值（协议/域名/查询串/重复斜杠/
  `.`/`..` 段）启动时快速失败；FastAPI `root_path=APP_ROOT_PATH` + 前缀剥离中间件；
  `/` 根重定向带 base path 并保留 query；workbench HTML 安全注入运行时 base path
  （token 模板替换 + `window.APP_ROOT_PATH` 配置 script）；charts CDN 回退与静态
  资源地址带前缀；对外入口
  `/api/ontology-agentic-analytics/{workbench,static/*,api/*,healthz}`。
- 前端：`frontend/src/runtime.js` 新增唯一 `withBasePath` helper，根绝对
  `/api|static|charts|workbench` 的 fetch/动态脚本/图表/下载/预览/导航 URL 全部改走
  helper；正式构建产物 `static/vendor/antd/workbench.js` 重新构建，产物内无根绝对
  应用 URL。
- 容器与文档：内置 HEALTHCHECK 仍探测不带前缀的 `http://127.0.0.1:8080/healthz`；
  `.env.example`、`README.md`、`DEPLOYMENT.md` 补充 `APP_ROOT_PATH` 配置与子路径
  部署口径；未升级版本号（仍 v0.1.2）。
- 验证：`tests.test_application_base_path` 6 OK；`tests.test_regressions` +
  `tests.test_container_port_contract` 231 OK；非法配置 fail-fast；
  `git diff --check` 干净。

### 3. main 退役与仓库级 master 口径收口（规则/文档/测试，2026-09-08 12:14）

- 仓库规则统一为 `master` 唯一发布主线、`main` 已退役并删除：`AGENTS.md`、
  `docs/gitlab-push-workflow.md`、`docs/versions/versioning-policy.md`、
  `DEPLOYMENT.md`、`scripts/push_gitlab.py`（`HISTORICAL_BRANCH` 替换为
  `RETIRED_BRANCH`）；禁止重新创建 `main`、向其 push 或用作 MR source/target；
  原“一次性 main 历史清理授权”标记为已失效历史审计记录（提交 `0de7cda`）。
- 仓库级清扫：`README.md`（应用信息、版本提交发布说明）与
  `docs/git-dual-remote-workflow.md`（已迁移指针页）中残留的“发布分支 main /
  merge 到 main”当前口径清除；新增 Spec
  `docs/specs/repository-wide-master-branch-consistency.md` 与 RED 门禁
  `tests/test_repository_wide_master_consistency.py`（提交 `6b94919`）。
- 新增/更新验收测试：`tests/test_main_branch_retirement.py`、
  `tests/test_master_default_protection.py`、`tests/test_master_mainline_policy.py`、
  `tests/test_push_gitlab.py` 与对应 Spec（`delete-historical-main`、
  `master-default-protection-cutover`）；历史 changelog 与归档版本文档不机械改写。
- 验证：main 退役门禁 29 OK（`RUN_GITLAB_MAIN_DELETION_TESTS=1`，需去除本机
  `HTTP_PROXY/HTTPS_PROXY` 后 urllib 才能访问 GitLab API）；仓库级一致性 5 OK；
  mainline+push 21 OK；regressions+container 231 OK。

### 4. 交付状态（2026-09-08 12:14）

- `gitlab/20260727` 推进至 `6b94919` 并推送成功（HEAD == gitlab/20260727），包含
  四个主题提交：`0de7cda` main 退役规则、`cf700dd` changelog 周维护整理、
  `706e0d5` configurable application base path、`6b94919` 仓库级 master 口径清扫；
  已同步 `gitlab/master`（`6004bc9`，本地祖先，无内容差异）。
- MR !9（`20260727` → `master`）创建并更新至完整交付范围，标题
  “feat: support configurable application base path and finalize master-only
  repository policy”，reviewer `tianzijing`、assignee `zhangzhen`；只创建 MR，
  未自动合并、未直接 push master。
- 测试汇总：base path 6 + regressions/container 231 + mainline 本地 37（16 只读
  门禁跳过）+ 仓库级 5 + mainline/push 21；`git diff --check` 干净。
- 无 tag、无 GitLab Release、无部署；MR !9 等待 `tianzijing` code review。

### 5. 容器固定配置与环境变量增量同步契约（Spec / TDD Green，2026-09-08）

- 修订 Spec `docs/specs/docker-defaults-and-local-secrets.md` 至 Implemented / TDD
  Green：固定非敏感运行参数进入 Dockerfile；本地 `.env`、`.env.example` 与 10.34
  服务器配置严格只增不减，保留全部既有键和值并补齐缺项；Kubernetes 自动生成的
  Service Link 不复制进配置；Secret 一律不进入镜像。
- `Dockerfile` 以 `ENV` 注入测试 `NON_SECRET_DEFAULTS` 定义的完整固定默认值（应用与
  base path、Team LLM、本体、Doris、会话同步、并发治理、本地协调与任务提醒），空值
  键（`TEAM_QWEN_ENABLE_THINKING`、`TASK_ALERT_DEFAULT_BP_DEFINITION_ID`）与华为云
  基础镜像、8080 内部端口、`/healthz` 健康检查保持兼容；未写入任何 Secret/`.env`。
- 本地 `.env` 与 `.env.example` 只做末尾增量补齐：补入缺失的非敏感默认值键以及
  `ONTOLOGY_AUTH_TOKEN`、`DORIS_PASSWORD` 空值占位；`.env.example` 中 Secret 仅为
  空占位或 `<key>` 形式，未复制任何真实凭据，`.env` 仍被 Git/Docker 忽略且权限 600。
- 10.34 当前 v0.1.2 release 的 `.env` 已直接增量同步：修改前创建同目录权限 600 的带
  时间戳备份（`.env.backup-20260908-165743`），以临时文件+原子替换追加缺失键，原有
  键与值经校验保持不变，未重启 8765、未切换 release、未修改其他 release。
- 门禁 `tests/test_docker_defaults_and_local_secrets.py` 转绿：本地 8 passed + 1
  skipped（服务器用例默认跳过），`RUN_SERVER_ENV_SYNC_TESTS=1` 下 9 passed 全通过；
  `test_container_port_contract`、`test_application_base_path` 与
  `test_regressions` 回归保持通过；`git diff --check` 干净。
- 明确仓库配置无法替代的外部条件：新 Pod 到 Team LLM、本体/Doris、会话同步服务的网络
  可达性，Ingress 子路径，以及真实凭据仍须由运维确认并安全注入；配置同步不等于进程
  已加载新值（本任务未重启）。

### 6. 服务器引用统一使用 IP（Spec / TDD Green，2026-09-08）

- 修订 `docs/specs/literal-ip-server-references.md` 至 Implemented / TDD Green；
  仓库内不再依赖或描述本机 SSH Host 别名，服务器引用统一直接使用
  `172.16.10.34`。
- 全量清理所有 Git 跟踪文本文件中的别名引用：`DEPLOYMENT.md`、环境同步 Spec、
  历史周 changelog `changelog_8_31_9_4.md`、正式版本文档 `docs/versions/v0.1.2.md`
  与 `tests/test_docker_defaults_and_local_secrets.py`，仅改写服务器称谓，未改变
  历史日期、端口、版本状态与部署事实。
- 环境同步集成测试的 SSH 调用改为 `"ssh", "172.16.10.34"`，服务器只读验收与
  Docker/`.env` 增量同步门禁保持全绿；未修改服务器、未重启服务、未部署。
- 门禁 `tests/test_literal_ip_server_references.py` 2 passed；
  `tests/test_docker_defaults_and_local_secrets.py` 本地 8 passed + 1 skipped、
  `RUN_SERVER_ENV_SYNC_TESTS=1` 下 9 passed；`git diff --check` 干净。

## 2026-09-09（周三）

### 1. 版本契约过期断言修复（2026-09-09）

- `tests/test_versioning_policy.py::test_product_version_is_v0_1_2` 中 FastAPI 构造
  断言仍是 base path 功能加入 `root_path=APP_ROOT_PATH` 之前的旧字符串，导致该契约
  测试在 master 与开发分支上失败；本次将该断言更新为当前实际构造
  `FastAPI(title=APP_DISPLAY_NAME, version=APP_VERSION, root_path=APP_ROOT_PATH)`，
  与 `tests/test_regressions.py` 中已有的完整构造断言保持一致，版本 v0.1.2 契约语义
  不变，未改动 `bi_agent/web/app.py` 与其他断言。
- 验证：`tests/test_versioning_policy.py` 19 passed；相关回归（regressions/container/
  base path/literal-ip/env-sync/mainline/push）保持通过；`git diff --check` 干净。

### 2. changelog 仅按周维护规范固化（2026-09-09）

- 新增 `docs/specs/weekly-changelog-only.md` 与
  `tests/test_weekly_changelog_only.py`，明确现行流程只按周维护 changelog、不再
  创建日报，并禁止重新引入日报文件。
- `README.md` 目录树说明、`docs/versions/README.md`、`docs/versions/
  versioning-policy.md` 与 `AGENTS.md` 中所有现行规则统一为周维护口径：删除“每日
  工程记录”“每日可以发布 PATCH”等表述，版本号与是否按日记录无关；历史 changelog
  中的“每日/日报”字样保留原貌，不改写历史。
- 历史日报与历史周 changelog 全部保留在 `changelog/` 与 git 历史中，未删除、未重写；
  无版本号变更、无 tag、无部署、未推送。

## 2026-09-10（周四）

### 1. 应用根入口直接返回工作台，不再跳转 /workbench（TDD RED→GREEN，2026-09-10 11:47）

- 现象：配置 `APP_ROOT_PATH=/api/ontology-agentic-analytics` 时，访问
  `GET /api/ontology-agentic-analytics` 会被 307 跳转到 `/workbench`，浏览器地址栏
  被改写；网关只暴露该子路径根入口时，跳转后工作台静态资源易 404。
- 现在根入口与兼容入口由唯一构造函数 `_workbench_response()`
  （`bi_agent/web/app.py`）共同返回工作台 HTML：`GET /api/ontology-agentic-analytics`
  直接 200 `text/html`，不再返回 307/308、不再带 `Location` 响应头，浏览器地址保持
  不变；`GET /api/ontology-agentic-analytics/workbench` 继续 200 且 HTML 与根入口
  完全一致。
- 未配置 `APP_ROOT_PATH` 时行为一致：`GET /` 直接返回工作台 HTML，`GET /workbench`
  继续兼容。两处共用同一 HTML 渲染与 no-store 缓存响应头逻辑，删除根路由的
  `RedirectResponse`，并移除 `fastapi.responses` 中不再使用的该 import。
- 未改动：`APP_ROOT_PATH` 规范化、base path 前缀剥离中间件、`/static` 挂载、
  `/api` 路由、`/healthz`、网关（Vane/Ingress/OpenResty）配置与前端构建产物。
- 测试：新增 `docs/specs/direct-root-workbench-entry.md` 与
  `tests/test_direct_root_workbench_entry.py`（RED→GREEN，3 passed）；
  `tests/test_application_base_path.py` 中原 307 断言更新为新根入口 200 契约（7
  passed，静态资源、前缀、HTML 注入与兼容性断言保持不减）；
  `tests/test_regressions.py` 中同类过期断言同步更新为根入口 200 且无 `Location`
  （219 passed）；`tests.test_container_port_contract` 12 passed；
  `git diff --check` 干净。
- 无版本号变更、无 tag、无推送、无部署。

### 2. 产品版本号统一升级到 v0.1.7（用户指定目标版本，2026-09-10 12:05）

- 按用户明确指定的目标版本 v0.1.7，将产品版本号从 0.1.2 统一升级到 0.1.7：
  `pyproject.toml`、`bi_agent/__init__.py`、`open_claude/__init__.py`、
  `bi_agent/web/app.py`（`APP_VERSION`，同时改变 `/healthz` 的 `version` 字段）、
  `frontend/package.json` 与 `frontend/package-lock.json`、
  `frontend/src/main.jsx`（`PRODUCT_VERSION`）与 `frontend/src/shell.html`
  （左上角品牌版本标签）。
- 前端构建产物 `bi_agent/web/static/vendor/antd/workbench.js` 用仓库既有
  `vite build` 重新构建；重建结果与旧产物仅 2 字节差异（两处 `v0.1.2`→`v0.1.7`），
  同目录 CSS 与 `lib/` 与旧产物完全一致，工作台界面版本标签现显示 v0.1.7。
- 同步更新版本契约测试 `tests/test_versioning_policy.py` 与
  `tests/test_regressions.py` 中的版本断言（0.1.2→0.1.7），其余断言不变。
- 未创建 tag（`v0.1.7` tag 已存在）、未新建或修改 `docs/versions/` 正式版本文档与
  版本索引、未创建 GitLab Release、未部署、未修改网关。
- 验证：全量 `python -m unittest` 445 passed（24 skipped）；`git diff --check` 干净。

### 4. 环境隔离的本体/Doris 网关与未使用新会话复用（Spec + TDD RED→GREEN，2026-09-10）

- 先撤销上一版"按 repository ID 白名单过滤"的做法（revert 提交 `915b168`，对应原提交
  `bd7fbc6`）：不再引入 `ONTOLOGY_ALLOWED_REPOSITORY_IDS`，也不在前端过滤本体库。
  ECore 目录必须由各环境自己的本体服务真实返回。
- 环境隔离本体连接：镜像与 Python 默认值不再固定直连跨环境地址。`Dockerfile` 删除
  `ONTOLOGY_BASE_URL`、`DORIS_API_URL` 两条固定值，`bi_agent/tools/sql_tools.py` 的
  `DEFAULT_DORIS_API_URL` 改为空串；生产/远程模式缺少 `ONTOLOGY_BASE_URL` 或
  `DORIS_API_URL` 时 `configure()` 直接 `RuntimeError` 快速失败（实测缺一个也会报错），
  不会静默连到另一个环境。显式环境变量仍是最高优先级。
- 两套环境地址写进 `DEPLOYMENT.md`：PDT
  `ONTOLOGY_BASE_URL=http://pdt-dev.eimos.com/api/gateway2/ontology` /
  `DORIS_API_URL=…/agent/doris/query`；Demo2
  `ONTOLOGY_BASE_URL=http://demo2.eimos.com/api/gateway2/ontology` /
  `DORIS_API_URL=…/agent/doris/query` 且 `ONTOLOGY_REPOSITORY_ID=3`。文档同时说明
  `ONTOLOGY_APP_ID` / `ONTOLOGY_AUTH_TOKEN` 必须各环境独立、仓库与镜像不保存真实 token。
- `.env.example` 只保留地址结构与占位符：`ONTOLOGY_BASE_URL=<set-per-environment>`、
  `DORIS_API_URL=<set-per-environment>`（注释中给出 PDT/demo2 结构），不再内置
  172.16.5.181:30834。
- 未使用新会话复用：新增纯函数模块 `frontend/src/conversationDraftPolicy.js`，导出
  `shouldReuseUnusedDraft(state)`（convId 存在、`hasContent=false`、首问为空、
  `turnCount=0`）与 `collapseUnusedDrafts(items)`（data/report 分开，每模式只保留
  `updated_at` 最新的一个未使用草稿，真实会话全部保留）。
- 行为：`resetConversation()` 在当前仍是未使用草稿时直接复用——不清 convId、不删
  `conversationDraftIds`、不再次调用空草稿保存接口、不生成新 cid，左侧只留当前这一条
  空草稿；已有问题时正常归档并创建新草稿。`normalizeConversationSummaries()` 统一调用
  `collapseUnusedDrafts()`，首次加载、刷新、保存事件和 React Sidebar 共用同一套去重结果；
  历史遗留的多余空草稿只在前端列表隐藏，不删除服务器历史 JSON。
- 已执行 `cd frontend && npm run build` 同步 `bi_agent/web/static/vendor/antd/workbench.js`
  （CSS 未变）。
- 旧测试更新（仅限原先固定断言 172.16.5.181 的部分）：
  `tests/test_docker_defaults_and_local_secrets.py` 把 `ONTOLOGY_BASE_URL`、`DORIS_API_URL`
  从"固定默认值"表移出，改为必须存在的"按环境注入"键集合；其余断言不减。
- 验证：`tests.test_environment_scoped_ontology_and_unused_session` 6 tests
  （1 skipped：需 `RUN_DEMO2_ONTOLOGY_ENV_TESTS=1` 的 demo2 在线校验）；
  `tests.test_application_base_path`、`tests.test_regressions` 全绿；全量
  `python -m unittest` 451 passed（25 skipped）；`git diff --check` 干净。
- 未修改 demo2 运行环境，未做线上验收；无版本号变更、无 tag、无推送、无部署。
