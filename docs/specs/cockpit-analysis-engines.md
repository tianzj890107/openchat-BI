# Cockpit 数据接入、分析路线与统一上线

2026-10-29 修订。看板通过主服务代理同一套 AP 接口，AI 消费页面同次查询的服务端结果。
原有对话与 MCP 的本体库、数据库连接不变。2026-10-26已按用户当次授权部署至8765，8876的API代理已切换；不构成未来部署、重启或停服授权。

## 数据路径与隔离

```text
ProUI 查询配置（包含实际筛选）
  → POST /api/cockpit/data/query
  → 独立 AP 连接（固定只读接口、独立认证、独立并发）
  → 返回 AP 原始 data + receiptId
  → 页面展示 data
  → /api/cockpit/analyses 携带同批 receiptId
  → 主服务 WebSession → Cockpit-DashboardQuery 读取已保存结果 → 交付校验 → 插槽
```

AP 地址及认证只从 `COCKPIT_AP_*` 配置读取，不使用 `ONTOLOGY_*`、Doris 参数、默认 source 或用户会话的源绑定。
页面不能指定代理 URL、请求头或证据正文。服务端只允许以下三个接口：

| kind | 方法 | `COCKPIT_AP_BASE_URL` 下的固定路径 |
| --- | --- | --- |
| analysis | POST | `/x360/v1/ontology/data/query` |
| batch | POST | `/x360/v1/ontology/data/multidimensional/batch` |
| helmet | GET | `/x360/v1/graphs/helmet-view` |

本体库 8 的页面只注入 `postAnalysisDataQuery`，不注入批量适配器。ProUI 在批量适配器缺失时
按单个查询并发兜底；当前批量接口仍在请求本体且不可用，不能用空数据或部分结果兜底。
2026-10-29 已按 iba-demo `d01c08a` 切换到该单查路径，并接入 6 条 `activateRules`；跨页跳转在
目标页头盔图挂载后恢复节点，避免初始化竞态。
服务端固定发送 `X-Ontology-Repository-Id: 8`，可用 `COCKPIT_AP_REPOSITORY_ID` 显式覆盖。

原有对话、MCP、报表的连接和工具不变。Cockpit 的临时 WebSession 仅允许 `Cockpit-DashboardQuery`、`CockpitDeliverCards` 和 `AskUser`（2026-10-26已上线），
执行边界拒绝模型请求的其他工具。确定性路由记录 `QUERY_DASHBOARD`，不把 AP 查询误记为 Doris 取数。

AP HTTP 并发默认 2，可配置为 1–8；浏览器请求队列上限 2，重复的进行中查询共用一次响应。
AP 使用独立的网络超时（默认 10 秒），不继承本体服务的超时、代理或认证；不跟随登录重定向。
凭据文件每次请求重新读取，可由运维安全更新；认证、网络、业务失败均返回明确错误，不回退快照或其他数据源。
浏览器可以取消／超时终止等待，服务端断连后不继续交付凭据；已开始的网络读取仍由独立超时和并发限制收敛。

Cockpit 主服务分析最多并行 1 个，排队可取消；执行仍复用主服务原有准入、租约、心跳、恢复、工具运行时及交付校验。
这限制了额外负载，不意味着共享进程的模型、CPU 等资源完全没有竞争。

## 配置

```dotenv
COCKPIT_DATA_MODE=ap
COCKPIT_AP_BASE_URL=http://pdt-dev.eimos.com/api/gateway2
COCKPIT_AP_REPOSITORY_ID=8
COCKPIT_AP_HEADERS_FILE=/absolute/private/path/cockpit-ap-headers.json
COCKPIT_AP_TIMEOUT_SECONDS=10
COCKPIT_AP_CONCURRENCY=2
COCKPIT_AP_RECEIPT_TTL_SECONDS=1800
COCKPIT_ANALYSIS_ENGINE=main
COCKPIT_COMPARISON_ENABLED=true
```

请求头文件是 JSON 对象，应包含上游实际要求的 `X-App-Id`、认证请求头及必要的 Cookie。
`X-Ontology-Repository-Id` 由 `COCKPIT_AP_REPOSITORY_ID` 统一注入，避免浏览器或旧文件带入错误仓库。
文件必须位于仓库外，POSIX 权限为 600；不得提交真实内容，也不得把它返回前端。批量与头盔图同样需要有效认证，
不能只验证单条指标接口。认证过期时更新独立文件，不修改原主服务认证。不要将浏览器临时登录态当作永久有效的部署凭据。

`GET /api/cockpit/data/config` 返回 `mode`、主服务代理能力 `available` 和数据来源说明，不暴露连接认证。
独立 8877 router 不提供 AP 代理或 main 执行；返回 503，不能冒充完整主服务。

`COCKPIT_DATA_MODE=snapshot` 是显式离线回放：使用旧交付包 39 个单条、3 个批量、4 个头盔图快照。
未捕获的配置仍会报快照缺失；AP 失败不会自动进入该模式。新代码默认 AP，部署必须配置并验证独立连接。

## 同次结果凭据

`POST /api/cockpit/data/query` 请求包含 `id=1|2`、`kind`、`payload`，返回：

```json
{"data": "原始AP data，实际为对象或数组", "receiptId": "32位结果凭据", "receivedAt": 0, "expiresAt": 0}
```

真实 AP data 不修改数值、字段、别名、分页或实际筛选。单条和批量成功响应保存到
`dataset/cockpit/history.sqlite3` 的独立 `ap_results` 表。头盔图仅用于展示，不作为业务事实。
失败、部分失败的批量和认证重定向不生成可分析凭据。

分析请求必须携带 `engine=main, source=service`、`chartSnapshotId`、`chartQueries` 及 `apReceiptIds`。
服务端验证身份标记、有效期、凭据对应的原始请求，并按请求和响应内容哈希绑定任务。
浏览器不能伪造事实、混入其他身份凭据或声明未应用的筛选。现有 id 仍是两种固定 POC 身份标记，不是新增的登录体系。
请求接受时校验有效期；已接受任务读取冻结材料，凭据随后过期不会让任务重新请求 AP。
有效期默认 30 分钟，过期需刷新页面取数，不自动删除历史结果或分析记录。

前端记录每个查询定义的当前结果；相同定义的筛选／分页变化替换旧凭据，迟到的旧响应不回填。
等待 AP 查询稳定后才提交分析，提交和回填都核对当前查询与凭据集合。任一业务查询失败或仍在加载时不提交完整分析。
既有 `period`／`department` 字段只保留协议兼容，实际范围以原始 AP 请求为准，不把历史 `2025-10` 标签当作查询条件。
分析材料是当前已加载图表查询的集合，尚无交付方明确的“每个插槽 → 具体指标”映射，不自行推断该映射。

工具保留原始请求／响应，并将数值单元格按“字段原始标签 + identifierCode”登记到主服务证据闸门。
AP 成功仅代表接口返回数据，不证明销售标题与底层指标语义一致。没有同源因果明细，当前交付保持 `limited` 或 `needs_input`，
不制造已验证根因、责任人、期限，也不从正文猜测措施后自动创建任务令。

## 分析路线与上线收口

| 路线 | 执行 | 证据 |
| --- | --- | --- |
| main（默认） | 现有WebSession.generate_turn，向原AI插槽提交结构化卡片；正文和轨迹保留追溯 | 页面同批 AP 结果；显式离线模式用交付快照 |
| standalone（仅联调） | 既有有限轮次工具循环 | 原型演示，或指定 main 任务的服务端冻结证据 |

三页仍为 `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`。联调可全局使用 `?engine=main|standalone`，
同页所有插槽使用同一引擎，不按插槽混用，不因失败静默降级。主服务正文不再调用模型改写。
`limited`、`needs_input` 保留证据不足或待确认状态；AskUser 补充后新建任务，失败不显示候选草稿。

main 有证据时可通过 `baselineAnalysisId` 让独立路线读取同身份、同范围的冻结证据。
冻结查询行最多 24 条，超过 8000 字符的行不进入材料；原始行标记 `causeSupport=false`，不能仅凭引用就认定根因。
这是材料归纳对照，不是两套完整取数流程的公平竞速。分析历史和冻结材料不会被新查询覆盖或清空。

选型后设置 `COCKPIT_COMPARISON_ENABLED=false`，全站只允许 `COCKPIT_ANALYSIS_ENGINE` 指定的一条路线。
若选择 main，静态站 `/api/cockpit/*` 应代理到主服务；旧 8877 不继续承载 AP 或 AI 槽位分析。
2026-10-26已实施代理切换及8765更新，旧8877进程停止；历史8877数据保留原地，没有复制、迁移、覆盖或删除。

## 验证与已知边界

- 自动化覆盖独立连接、固定路径、并发、认证／超时错误、不换源、批量完整性、凭据范围与过期、真实主服务 API 的同次结果消费、原会话源不被访问。
- 前端测试覆盖并发去重、队列上限、筛选变化替换凭据、迟到响应、错误与过期阻止分析。
- 2026-10-26 本地新代理实际读通此前缺失的四组指标；浏览器三个路由的单条／批量／头盔图请求均成功，无快照缺失和运行异常。
  使用独立临时认证与临时数据目录，未修改线上服务器；验收阻止模型调用，不能据此报告新路线的模型耗时或真实分析质量。
- 2026-10-23 约 32.8 秒的历史实验走的是修正前本体／数据网关路线，且域名解析失败；不能拿它作为当前 AP 路线性能结论。

本轮回归：141 项 Python 测试通过、1 项环境条件跳过、34 个子测试通过；`node --test tests/cockpit_data_client.test.mjs` 的 5 项通过。JS语法和 `git diff --check` 通过。

## 服务器验收（2026-10-26）

临时18765预检后切换8765及8876代理；线上返回 `mode=ap, available=true, default=main`。
四组缺失指标、批量和头盔图均实时成功；三页浏览器AP请求7／15／14次全部200，未触发快照缺失。
真实主服务任务 `10c657bf6d414c17bba590c972c95548` 20.619秒、3轮、2次Cockpit-DashboardQuery、1项事实，
按预期受限交付，没有改用默认本体／数据库。原 `/api/sources` 配置完全一致，328个受保护数据文件哈希未变。
独立凭据当前使用POC的PDT登录授权，失效需更新独立文件；不能将其当作长期服务凭据。详细路径与回滚备份见DEPLOYMENT.md。

## AI插槽样式与上次成功内容（2026-10-26已预热上线）

主服务不再用长正文块替代交付组件，通过同一模型循环中的CockpitDeliverCards提交结构化字段。
服务端持久保存同范围上次成功卡片，首屏读取缓存，后台分析成功后自动替换；换筛选无缓存时使用AI卡片加载态。
失败、取消及迟到的旧任务不清空或覆盖上次成功版本，重复打开不因新的AP凭据而重新分析。
接口、范围、首次预热和测试边界见 [卡片交付与持久缓存](cockpit-card-publications.md)。

2026-10-26正式更新到ca3d29b：两个身份默认页面的6组环节卡片已用真实AP和模型预热，重启后缓存保留；8876加载原设计组件，8765统一执行分析，8877继续停止。
