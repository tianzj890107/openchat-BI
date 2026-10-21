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
分析内容通过 Dashboard `insights` 和 `#insight-diagnosis` 插槽嵌入。

| 页面 | 行为 |
| --- | --- |
| 全局经营看板 | 年度销售／出货切换；目标、实绩、预测、订未发；月度与产品部图；五类风险与运营链入口 |
| 运营 360 | 七环节头盔、节点选择、完成率／周期、环节独立处理记录；进入穿透分析 |
| 穿透分析 | 环节切换、确定性事实卡与原因分布、AI 风险／原因／建议、证据查看、逐单表、原因筛选、假设测算、报告导出 |
| 公共 | 期间／产品部／角色切换、URL hash 导航、口径说明、刷新恢复、历史抽屉、任务抽屉 |

嵌入路径示例：`/cockpit?role=president#overview`、`/cockpit?role=analyst#analysis`。
支持 `APP_ROOT_PATH` 下静态资源及 API 地址。角色参数仅为 POC 演示，不是正式身份认证。
分析员“复制上下文到 Fuxi”仅复制文本，不自动发送，不同步外层会话，也不声称已完成宿主联调。

## 数据契约和口径

`bi_agent/cockpit/data.py` 中 `CockpitSource` 是未来本体／数据库适配边界，当前唯一启用源为 `DemoSource`。
期间为 2025-10、2025-09；部门为全体、AIDC、国内电力、国际电力。所有输入由服务端枚举校验。

- 全局十月：年度目标319亿元、已发货191.4亿元、订单接收236亿元。
- 订未发44.6＝正常20.3＋超期24.3；超期由12条订单汇总。
- 四主因：排产7.9、厂线生产与质量7.5、物流单证4.5、客户提货4.4，合计24.3。
- 电量按演示比例319亿元／91 GWh折算，页面明确声明不是真实量价关系。
- 已有业务预测280亿元；未来月份预测合计与全年预测减累计实绩相等。月度目标合计等于年度目标。
- 报价以已批准红区申请逐单计数；产品、客户分级及区域来自独立演示记录。
- 商机有20家战略客户演示样本，7家无商机、13家未进入投标；样本不代表全部商机。
- 投标有独立49项结果台账（24中标、20丢标、5弃标），不复用发货原因。
- 订单取消／减量使用独立变更台账，金额不重复计入发货超期。
- 各环节统计口径独立，不把不同对象总体假装成同一漏斗转化。非发货环节头盔的未完成状态拆分为演示分布，不是实际统计。
- 快照包含内容摘要ID；分析缓存绑定角色、期间、部门、环节、数据版本，防止跨范围串用。

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
| GET `/snapshot?period=&department=` | 同口径跨页面数据 |
| GET `/evidence?period=&department=&stage=` | 当前环节事实、明细、证据 |
| POST `/analyses` | role、period、department、stage、refresh；返回分析任务 |
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

离线契约测试：`python -m pytest -q tests/test_cockpit_poc.py`。
脚本语法：`node --check bi_agent/web/static/cockpit/cockpit.js`。
浏览器验收使用独立临时工作目录，避免接触用户会话。真实模型验证使用主服务现有配置，绝不把凭据写入前端。


## 2026-10-21 组件资源与前端元数据交付补充

按资源目录 <http://pro-ui.eimos.com/assets/> 重新获取发布的 BI UMD 和配套 `pro-ui.min.css`，
增加内容哈希缓存参数；Vue仍为同一份3.5.25，旧工作台资源不变。
已拉取 `shimenglan/iba-demo` 的 `feature/demo_1021`（commit `55842efc`），
根组件、14份子模板和3个插槽声明存于 `static/cockpit/metadata/iba-demo-1021/`。
这是原样冻结的接入参考，不是已经接通AP接口或替换当前POC页面的声明。
页面对应、源配置缺失子组件及接入边界见该目录 README 和 source.json。
