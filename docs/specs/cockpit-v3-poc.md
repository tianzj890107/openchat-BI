# V3 经营驾驶舱 POC

## 已确认边界（2026-10-21）

- analytics 主服务提供 `/cockpit`；Fuxi 嵌入固定入口。现有 `/workbench`、旧驾驶舱及 MCP 不替换。
- 三个主页面：全局经营看板、运营 360 整体分析、穿透式问题分析。专项与任务令为页面内状态。
- 两个演示角色：总裁（按钮驱动，无对话）、分析员（Fuxi 对话，不在 cockpit 重建聊天）。数据范围相同，操作不同。
- 最新决定：页面直接调用 analytics 主服务执行 AI 分析并回填插槽；不依赖 Fuxi 触发／回填协议。
- 前两页直接查询数据；第三页首次进入启动分析，同快照同角色同环节复用完成结果，可重新分析。
- 先交付独立演示数据与实际模型执行；本体＋数据库真实连接需要后续映射，不声称已接通。
- 模拟任务令：草稿→模拟下发→接收→反馈→验收关闭。仅本地持久化，不调用任务、通知或业务单据写接口。
- 已有业务预测展示＋显式假设的情景测算；不建设统计预测模型。
- 不部署、不改正式版本，不移动或删除现有历史会话。

## 页面与组件

新增 Vue 3 页面入口，静态资源位于 `bi_agent/web/static/cockpit/`，与旧 React 工作台资源隔离。
使用 ProUI `ProBiDashboard`、`ProKpiCard`、柱图／条形图、`ProMiniCpGraph`、`ProDataTableAtomic`。
分析内容通过 Dashboard `insights` 和 `#insight-sales-shipment-issues` 插槽嵌入。

| 页面 | 行为 |
| --- | --- |
| 全局经营看板 | 交付五项进度卡、销售额／出货量嵌套模板、年度图表与表格；保留原型7条风险文案 |
| 运营 360 | 交付七节点头盔、节点明细模板、阶段概览及出货年度组合；方案摘要只显示事实 |
| 穿透分析 | 四节点头盔、商机／订单变更／发货模板、AI风险／原因／建议、证据、模拟任务及情景测算 |
| 公共 | 固定原型期间／全产品部、两角色、URL导航、口径、历史与任务抽屉、可展开差异清单 |

嵌入路径示例：`/cockpit?role=president#overview`、`/cockpit?role=analyst#analysis`。
支持 `APP_ROOT_PATH` 下静态资源及 API 地址。角色参数仅为 POC 演示，不是正式身份认证。
分析员“复制上下文到 Fuxi”仅复制文本，不自动发送，不同步外层会话，也不声称已完成宿主联调。

## 数据契约和口径

当前页面使用 `PrototypeSource`，静态事实来自 `fixtures/v3-prototype.json`，原型HTML文件名与SHA记录于 `_source`。
交付元数据由 `metadata.py` 编译，三页全部使用 `ProBiDashboard` 与同一份模板注册表；不再使用手写页面图表数组。
图表、表格与AI证据均绑定这一原型源。原型客户姓名等均为其既有演示内容。

- 原型固定期间2025-10、全产品部；没有其他完整快照，不开放虚构筛选。
- 超期未发10条原型订单合计24.3亿元；S1客户设备批次质量异常记录为4.8亿元。
- 商机、投标、订单变更、方案与技术记录独立提取，不复用旧DemoSource台账。
- 出货表按原型 `shipmentAnnualBlock` 保留91／319折算、预测及产品部月度比例分配；它们是原型演示规则，不是新增真实测量。
- 原型10月累计实绩与10–12月预测明确区分；未来月份不是实绩。
- 原型存在2025／2026时点与订未发39.6／44.6／45亿元多种口径，保留原文，不强行对账。
- 快照／分析缓存增加source隔离；旧DemoSource API默认行为和历史数据保留，不能作为当前原型页面结果恢复。
- 原型布局／数据／交互尚不能全部一致，逐项见 [缺失与差异](cockpit-v3-metadata-gaps.md)。

## AI 执行与校验

复用 `bi_agent.llm.provider.stream_message` 和全局模型并发限制。默认模型键 `team-configured`，可选环境变量 `COCKPIT_MODEL_KEY`。
额外限制同时最多3个 cockpit 分析，最多6次模型轮次；轮次及流式事件检查150秒预算。

`CockpitEvidenceQuery` 仅在当前请求中执行，读取已冻结证据，无原始SQL、Bash、生产修改或任务下发工具。
工具保留全部汇总事实和最多均匀抽取24条处理记录，避免大清单无限填充上下文；完整列表在页面中可查。
模型先取证，再输出严格 JSON（summary、causes、recommendations、limitations）。
Pydantic校验长度、字段；引用必须来自本轮查询；已支持原因必须关联具体记录；建议必须关联原因；限制由服务端追加。
这些检查保证结构与引用有效，不能证明模型自然语言中的所有因果推论；POC明确显示演示记录支持／待核实假设。

模型缺配置、调用失败、JSON或证据校验失败均显示失败，不回退为假成功。
取消后禁止迟到结果覆盖终态。底层供应商同步网络读可能仍需等待自身超时才能退出；本模块不承诺杀死上游请求。

## API

| 方法／地址（前缀 `/api/cockpit`） | 用途 |
| --- | --- |
| GET `/bootstrap` | 角色、期间、部门、环节、数据模式 |
| GET `/metadata` | 当前页面模板、显式绑定、插槽、差异及适配记录 |
| GET `/snapshot?period=&department=&source=prototype` | 原型固定快照（不传source保留旧demo契约） |
| GET `/evidence?period=&department=&stage=&source=prototype` | 当前环节事实、明细、证据 |
| POST `/analyses` | role、period、department、stage、source、refresh；返回分析任务 |
| GET `/analyses?role=` | 角色历史，可按期间和部门筛选 |
| GET `/analyses/{id}` | 状态、进度、工具取证记录、结果 |
| POST `/analyses/{id}/cancel` | 停止；不删除记录 |
| GET `/analyses/{id}/report` | 完成后的转义HTML报告 |
| POST `/analyses/{id}/draft` | 基于完成结果幂等创建任务草稿 |
| GET `/tasks`、`/tasks/{id}` | 模拟任务及状态 |
| POST `/tasks/{id}` | 带 revision 的保存／下发／接收／反馈／关闭 |

错误：422无效范围／字段、404未知记录、409状态或版本冲突、403演示角色不符、429分析并发已满。
角色为可切换演示参数，403仅用于演示操作规则，不能作为生产安全机制。

## 持久化与恢复

服务工作目录下 `dataset/cockpit/history.sqlite3`，已gitignore。SQLite事务和revision防止覆盖更新。
不与现有会话表混用，不提供清空或删除接口。分析缓存及任务按分析ID关联。
本POC使用单进程内存任务执行器；服务首次打开存储时把未结束分析标记为interrupted，保留证据并可重试。
正式多worker部署需使用共享任务协调器替换内存作业管理，不应直接多进程运行这个POC执行器。
刷新能恢复作用域与保存记录；浏览器localStorage仅保存视图参数／分析ID，结果和任务保存在后端。

## 资源

ProUI 文档站与 PDT 当前发布的 BI UMD 相同，冻结SHA见 `static/cockpit/vendor/resources.json`。
保留旧工作台BI包不变；新包只由cockpit加载。Vue版本均为3.5.25，哈希一致，直接复用原有Vue文件。
资源文档：<http://pro-ui.eimos.com/bi-components/setup/>、<http://pro-ui.eimos.com/bi-components/dashboard/>。

## 验证

离线契约测试：`python -m pytest -q tests/test_cockpit_poc.py tests/test_cockpit_resource_contract.py tests/test_cockpit_metadata.py`。
脚本语法：`node --check bi_agent/web/static/cockpit/cockpit.js`。
浏览器验收使用独立临时工作目录，避免接触用户会话。真实模型验证使用主服务现有配置，绝不把凭据写入前端。


## 2026-10-21 组件资源与前端元数据交付补充

按资源目录 <http://pro-ui.eimos.com/assets/> 重新获取发布的 BI UMD 和配套 `pro-ui.min.css`，
增加内容哈希缓存参数；Vue仍为同一份3.5.25，旧工作台资源不变。
已拉取 `shimenglan/iba-demo` 的 `feature/demo_1021`（commit `55842efc`），
根组件、14份子模板和3个插槽声明存于 `static/cockpit/metadata/iba-demo-1021/`。
2026-10-22起已由运行适配层替换当前三页配置；源JSON保持冻结，不连接AP。
页面对应、源配置缺失子组件及接入边界见该目录 README 和 source.json。
