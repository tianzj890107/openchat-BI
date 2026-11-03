# 变更记录（2026-11-02 至 2026-11-06）

按自然周维护，不创建日报。

### 2026-11-02 单一源码主目录约定

- 在 AGENTS.md 固定用户要求：未经明确授权不创建 worktree、额外 clone 或 POC/集成源码副本；已合并工作区核对线上路径及独有数据后清理。
- 允许测试框架自动清理的隔离 fixture；目录清理不授权线上重启、部署或删除历史数据。
- 验证：规则内容已核对，git diff --check 通过；仅工程约定变更，无业务行为变化。

### 2026-11-02 17:05 Cockpit 同步 iba-demo be99db5 品牌色板

- 用户可见变化：经营看板、运营页和穿透页的 KPI 数值色、图表色板与对比色更新为上游品牌色
  （`#4C8BF3` / `#63AD73` / `#5CBBD5` / `#E7B550` / `#DD8142` / `#DE5A60` / `#D751AD` 等），
  页面布局、15 个 AI 插槽和三张订单表结构保持不变。
- 运行包：`vendor/pro-bi-ui.min.js` 更新为 `iba-demo feature/demo_1021` `be99db5` 的 UMD；
  `index.html` 缓存参数改为 `?v=e152acd8`，`resources.json` 提交号、哈希和字节数同步。
  上游 UMD 未带头盔图销毁后的空实例保护，同步后重新补回 `fitView` 守卫；`pro-ui.min.css`
  与 Vue 运行时未变化。
- 配置同步：`metadata/iba-demo-1021/template-registry.json` 按上游色板更新并重新生成
  `metadata/runtime.json`；`components.json` 上游仅移除了宿主适配的默认期间，已重新写回
  `YWLN_D044=2025-10`，因此文件内容与上一版一致。
- 上游数据修复：新模板配置有 4 处中文标签以 U+FFFD 乱码交付（进行中超期电量、报价办理状态、
  投标状态分布、销售订单编号），同步时恢复为上一版正确文案，没有按乱码入库。
- 主要文件：`bi_agent/web/static/cockpit/vendor/{pro-bi-ui.min.js,resources.json}`、
  `index.html`、`metadata/iba-demo-1021/{template-registry,source}.json`、`metadata/runtime.json`、
  `tests/test_cockpit_{metadata,resource_contract}.py`。
- 验证：Cockpit 相关 Python 257 项、前端 Node 88 项通过；UMD `node --check` 通过；
  资源清单与 `source.json` 哈希一致；`git diff --check` 通过。

### 2026-11-02 17:20 Cockpit 合并客户覆盖、核查交付与宿主面板修复

- 用户可见变化：运营页商机覆盖提示可使用已核验 AP 客户覆盖数，报价状态口径修正；
  穿透页的核查建议必须有证据支撑，阶段策略支持缓存预热，任务令下发前要求确认具体
  日历期限；看板不再显示宿主自绘的“元数据缺失与渲染限制”面板。
- 交付契约：核查类动作与改善类动作分开校验，假设只能生成核查任务；责任角色和期限
  未确认时保持“待确认”，不写成已下发安排。
- 评测与修复：合入 40 条 Cockpit 业务评测用例及运行器；任务令 POC 测试改用具体日期，
  与“工作日建议不是可下发日期”的期限校验保持一致。
- 验证：全量 Python 与前端 Node 测试通过；`git diff --check` 通过。

### 2026-11-02 Cockpit 风险事项去重与客户表局部筛选

- 顶栏风险统计改为按业务风险事项去重，统一节点卡、综合分析卡及自动指标判断的同义事项；不再把指标编码组合视为风险唯一标识。同一指标上的不同风险可以独立交付。
- 汇总按风险所属领域收集全部插槽，补计商机卡中属于出货量的风险；统计返回可核对的去重风险清单、稳定事项键及分析／插槽／证据引用，数量直接来自该清单。
- 客户表内客户等级、商机类型、投标状态、客户商机筛选及重置保留为组件局部行为，不再触发宿主全页筛选、清空缓存和重建看板；全页时间筛选继续生效。保留局部筛选的重放记录，不更改厂家组件与交付元数据。
- 主要文件：`bi_agent/cockpit/{risk,agent}.py`、`bi_agent/web/static/cockpit/{data-client,cockpit}.js`；补充风险同义去重、跨节点归属、同指标不同事项、局部筛选与全局筛选隔离测试。
- 本地浏览器验收：在隔离 AP／模型 fixture 下，客户等级 1、2 与重置均保持原看板 DOM 和 runtime 实例；未触发整页重建。线上历史响应只读复算为总裁销售 7 条、出货 3 条，不作为已部署结果。
- 验证：Cockpit Python 291 项、前端 Node 91 项通过；本地浏览器局部筛选与全页月度筛选对照通过；`git diff --check` 通过。本轮未部署。

### 2026-11-02 18:05 Cockpit 旧口径提示改为文字提示

- 用户可见变化：AI 卡片上方的“当前展示上次分析”类旧口径提示不再使用橙色警告底色和边框，
  改为带 `ⓘ` 前缀的灰色辅助文字；提示内容和触发逻辑不变。
- 主要文件：`bi_agent/web/static/cockpit/cockpit.css`、`tests/cockpit_insight_runtime.test.mjs`。
- 验证：Cockpit 运行时测试 6 项、Cockpit Python 测试 284 项通过；`git diff --check` 通过。

### 2026-11-02 18:30 Cockpit 风险去重与提示样式上线

- 用户可见变化：顶栏风险数量改按业务风险事项去重，同一指标上的不同风险独立计数；客户表内的
  客户等级、商机类型、投标状态和客户商机筛选不再触发整页重建。旧口径提示统一为灰色 `ⓘ`
  辅助文字，不再使用橙色警告块。
- 发布：合并 MR `!36`、`!37` 后部署 `master` `53c4662`，8765 release
  `process360-cockpit-53c4662-20261102-1823`，PID `1561973`；8876 继续代理 8765。
- 验证：两个角色 15/15 个 AI 插槽可渲染；风险计数总裁销售 9／发货 3、分析员销售 8／发货 2；
  三页两角色在 8765 与 8876 均 200，启动日志无异常。合并后前端 92 项、Python 1876 项及
  1072 个子测试通过。GitLab runner 因外部依赖网络超时未完成流水线，未修改 CI。

### 2026-11-03 客户驾驶舱与Process360离线部署包

- 新增客户专用启动入口，仅开放驾驶舱、Process360 MCP及产物／下发接口，支持原默认MCP路径；启动不依赖远程本体平台与Doris，不开放完整工作台或异步分析任务入口。
- 提供离线镜像Dockerfile、Compose和启动脚本；实际客户地址、端口、模型、PG、AP认证及Fuxi接收人全部在交付包.env，不写死在代码，不提交Git或嵌入镜像。
- 主服务与兼容入口端口由env注入，运行数据持久化；交付客户本体、catalog、Skill、配置清单及供DBA审核的逻辑视图SQL，不自动执行数据库脚本或下发待办。
- 主要文件：`bi_agent/web/customer.py`、`bi_agent/web/app.py`、`deploy/customer/`、`tests/test_customer_cockpit_entrypoint.py`。客户入口、Process360 MCP及主服务回归22项通过；离线镜像安装依赖并通过pip check，容器健康检查与19项Process360工具检查通过；未部署客户服务器。
