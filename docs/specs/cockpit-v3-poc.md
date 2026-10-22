# V3 经营驾驶舱 POC

## 已确认边界（2026-10-22）

- analytics 主服务提供三个独立入口：`/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis`；`/cockpit` 以 `307` 跳到 `overview`。现有 `/workbench`、旧驾驶舱及 MCP 不替换。
- 三个页面只渲染看板本体，顶部仅保留驾驶舱自己的三个视图 Tab：`全局经营看板`、`运营 360 整体分析`、`穿透式问题分析`；不包含宿主工作区、会话区、页面标题或外层筛选栏。
- `/cockpit/overview` 临时直接作为全局经营看板，不再渲染原型首页；首页欢迎语、风险链等原型专属内容不在当前路由中。
- 两个演示身份使用 Fuxi 传入的单一查询参数 `id`：`id=1` 对应总裁，`id=2` 对应分析员。当前三页内容对两个 `id` 完全一致，两个人都可以访问和操作；`id` 只作身份标记并为将来差异化预留。页面和 API 不使用 `role`，`/cockpit` 跳转和页内跳转都保留当前 `id`。
- 最新决定：页面直接调用 analytics 主服务执行 AI 分析并回填插槽；不依赖 Fuxi 触发／回填协议。
- 前两页直接查询数据；第三页首次进入启动分析，同快照同 `id` 同环节复用完成结果，可重新分析。
- 先交付独立演示数据与实际模型执行；本体＋数据库真实连接需要后续映射，不声称已接通。
- 模拟任务令：草稿→模拟下发→接收→反馈→验收关闭。仅本地持久化，不调用任务、通知或业务单据写接口；当前只校验状态和 revision，不按 `id` 分配操作权限。
- 已有业务预测展示＋显式假设的情景测算；不建设统计预测模型。
- 三页静态看板资源与旧工作台隔离；是否部署以当前任务中出现的明确部署授权为准。

## 页面与组件

三页静态资源位于 `bi_agent/web/static/cockpit/`。页面使用交付元数据中的组件配置和模板注册表，通过 `ProBiDashboard` 渲染原生 ProUI 卡片；不再使用原型 DOM、原型内联样式或原型尺寸占位。

| 页面 | 默认内容 |
| --- | --- |
| 全局经营看板 `/cockpit/overview` | 五项经营指标、年度销售目标／实绩／预测、产品结构和团队达成；点击出货量指标可切换出货量模板 |
| 运营 360 `/cockpit/operations` | 五项指标、运营全流程头盔图、商机漏斗、七个环节 KPI／占比／异常明细；默认商机获取模板，点击头盔节点切换环节模板 |
| 穿透分析 `/cockpit/analysis` | 五项指标、销售额口径四节点头盔图、风险结构与原因拆解、客户与超期订单；默认发货风险模板，点击节点切换风险模板 |
| 公共 | 顶部三个 Tab 保留当前 `id`；无宿主壳；卡片标题、图例、表格工具栏和按钮使用 ProUI 组件自身样式 |

入口示例：`/cockpit/overview?id=1`、`/cockpit/operations?id=2`、`/cockpit/analysis?id=1`。
支持 `APP_ROOT_PATH` 下静态资源地址。纯看板页面不渲染旧的角色切换、分析历史或任务抽屉。

## 数据契约和口径

当前页面使用 `PrototypeSource`，静态事实来自 `fixtures/v3-prototype.json`，原型 HTML 文件名与 SHA 记录于 `_source`。`metadata.py` 编译 `iba-demo/feature/demo_1021` 的组件、模板、绑定和插槽，源 JSON 保持冻结。

`runtime.py` 从同一编译结果生成 `static/cockpit/metadata/runtime.json`：

- 输出三个页面根组件和 15 份模板内容，共 131 个可渲染组件。
- 102 个绑定组件写入冻结的演示行数据 `dataConfig.mockData`；浏览器不调用 AP、本体或生产数据库。
- `group`、`template`、`segmented-strip`、`button-group` 等容器使用 ProUI 对应组件，模板切换由 `ProBiDashboard` 的 `templateRegistry` 完成。
- 没有 ProUI 实现的自定义组件不会进入渲染列表，原因记录在 `gaps`；缺失引用子组件的位置保持空位，不补近似图表。
- 静态 8876 页面只读取上述 JSON，不依赖 `/api/cockpit/metadata`。

图表、表格与后端分析证据绑定同一原型源。原型客户姓名等均为既有演示内容。

- 原型固定期间 2025-10、全产品部；没有其他完整快照，不开放虚构筛选。
- 超期未发 10 条原型订单合计 24.3 亿元；S1 客户设备批次质量异常记录为 4.8 亿元。
- 商机、投标、订单变更、方案与技术记录独立提取，不复用旧 DemoSource 台账。
- 出货表按原型 `shipmentAnnualBlock` 保留 91／319 折算、预测及产品部月度比例分配；它们是原型演示规则，不是真实业务统计。
- 看板显示“示例数据”，不声称连接采购、销售或交付生产系统。

## AI 分析与任务令

主服务复用现有模型调用链执行分析。每次分析使用当前 `id`、期间、部门和环节对应的只读证据快照；模型失败、证据不足或输出校验失败时不回退为预写成功结论。

模型先取证，再输出严格 JSON（summary、causes、recommendations、limitations）。Pydantic 校验长度和字段；引用必须来自本轮查询；原因必须关联具体记录；建议必须关联原因；限制由服务端追加。这些检查保证结构与引用有效，不能证明自然语言中的所有因果推论。

取消后禁止迟到结果覆盖终态。底层供应商同步网络读可能仍需等待自身超时才能退出；本模块不承诺杀死上游请求。

## API

| 方法／地址（前缀 `/api/cockpit`） | 用途 |
| --- | --- |
| GET `/bootstrap` | 角色、期间、部门、环节、数据模式 |
| GET `/metadata` | 当前页面模板、显式绑定、插槽、差异及适配记录 |
| GET `/snapshot?period=&department=&source=prototype` | 原型固定快照（不传 source 保留旧 demo 契约） |
| GET `/evidence?period=&department=&stage=&source=prototype` | 当前环节事实、明细、证据 |
| POST `/analyses` | id、period、department、stage、source、refresh；返回分析任务 |
| GET `/analyses?id=` | 当前身份历史，可按期间和部门筛选 |
| GET `/analyses/{id}` | 状态、进度、工具取证记录、结果 |
| POST `/analyses/{id}/cancel` | 停止；不删除记录 |
| GET `/analyses/{id}/report` | 完成后的转义 HTML 报告 |
| POST `/analyses/{id}/draft` | 基于完成结果幂等创建任务草稿 |
| GET `/tasks`、`/tasks/{id}` | 模拟任务及状态 |
| POST `/tasks/{id}` | 带 revision 的保存／下发／接收／反馈／关闭 |

错误：422 无效范围／字段、404 未知记录、409 状态或版本冲突、429 分析并发已满。
`id=1|2` 是 Fuxi 传入的唯一身份参数，当前不作为页面或操作权限依据；分析历史仍按 `id` 归属保存。

## 持久化与恢复

服务工作目录下 `dataset/cockpit/history.sqlite3`，已 gitignore。SQLite 事务和 revision 防止覆盖更新。
不与现有会话表混用，不提供清空或删除接口。分析缓存及任务按分析 ID 关联。
本 POC 使用单进程内存任务执行器；服务首次打开存储时把未结束分析标记为 interrupted，保留证据并可重试。
正式多 worker 部署需使用共享任务协调器替换内存作业管理，不应直接多进程运行这个 POC 执行器。

## 资源

ProUI 文档站与 PDT 当前发布的 BI UMD 相同，冻结 SHA 见 `static/cockpit/vendor/resources.json`。
旧工作台 BI 包保持不变；cockpit 使用新版 `pro-bi-ui.min.js` 与 `pro-ui.min.css`。
页面渲染入口是 `ProBiDashboard`，组件类型映射包括 `ProKpiCard`、`ProProgressCard`、`ProDataTable`、`ProBarChart`、`ProDualAxisChart`、`ProHorizontalBarChart`、`ProFunnelChart`、`ProShareBar`、`ProMiniCpGraph`、`ProTitle`、`ProButtonGroup` 及分组／模版容器。
Vue 版本为 3.5.25，哈希一致，复用原有文件。
资源文档：<http://pro-ui.eimos.com/bi-components/setup/>、<http://pro-ui.eimos.com/bi-components/dashboard/>。

## 验证

离线契约测试：

```bash
/path/to/venv/bin/python -m pytest -q \
  tests/test_cockpit_poc.py tests/test_cockpit_resource_contract.py tests/test_cockpit_metadata.py
```

当前结果：`36 passed`。JavaScript 语法检查：

```bash
node --check bi_agent/web/static/cockpit/cockpit.js
```

浏览器验收使用独立临时工作目录，避免接触用户会话。已检查：

- 三个路由均返回 200，`/cockpit` 跳到 `overview`。
- 顶部只有三个 Tab，标签和当前页正确；`id=1|2` 在 Tab 和路由中保留。
- `/cockpit/overview` 默认显示全局经营看板，点击出货量指标可切换出货量模板。
- 三页均由 ProUI 卡片渲染；桌面 1440px 和窄屏 480px 无横向溢出。
- 年度图、头盔图、表格和 KPI 组件正常生成；页面不请求 `/api/cockpit/*`。
