# 智能分析 ontology-v0.1.4

## 基本信息

- 版本：`ontology-v0.1.4`
- 日期：`2026-10-23`（版本收口）；`2026-10-27`（tag 与 Release 补发）
- 状态：正式版 / 当前版本（tag 与 GitLab Release 已创建）
- 版本位次：**PATCH**（`ontology-v0.1.3` → `ontology-v0.1.4`），版本号由用户在当前任务中明确指定
- 版本关系：在 `ontology-v0.1.3` 的远程 MCP 与通用 Agent 接入能力之上，新增 V3 经营驾驶舱 POC，
  以 `iba-demo feature/demo_1021` 交付元数据和 ProUI 组件为唯一看板来源。
- Release 分支：不单独拉出；通过 `feature/cockpit-v3-poc` → `master` 的 Merge Request 评审合并
- 定版 commit：`3287c91145fb857911becdea02a26085062fcc7d`（加载性能优化前的 v0.1.4 分支提交）
- Git Tag：`ontology-v0.1.4`（annotated，2026-10-27 已创建并推送）
- GitLab Release：[智能分析 ontology-v0.1.4](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.4)（2026-10-27 已创建）

## 版本概述

ontology-v0.1.4 交付 V3 经营驾驶舱 POC。三个看板页面各自拥有独立路由，只渲染交付配置中的
ProUI 看板本体，不包含工作区、会话区、页面标题或第二套导航。看板布局、组件、筛选器和 Tab
来自 `iba-demo feature/demo_1021` 的交付元数据；原型的业务结论由真实模型分析插槽提供，
不再使用静态 mock 文案。

本版本范围仅包含 `feature/cockpit-v3-poc` 分支上的驾驶舱交付，定版于加载性能优化之前。
同期存在的其它并行修改不纳入本版本，也不写入本版本说明。tag、GitLab Release 与部署保持
独立授权；本次已按用户明确授权补发 tag 与 Release，不触发部署。

## 交付主题

### 1. 三个独立看板路由

- 提供 `/cockpit/overview`、`/cockpit/operations`、`/cockpit/analysis` 三个入口，分别激活
  “经营看板”“运营360整体分析”“穿透式问题分析”；
- `/cockpit` 与 `/` 默认进入经营看板，`/cockpit/home` 保留为兼容入口并改写为 `overview`；
- 页面只挂载一个 `ProBiDashboard`，顶部筛选器和三个 Tab 均由交付根配置生成；
- Fuxi 传入的 `id=1|2` 被原样保留；当前两套身份看到相同看板，`id` 作为后续差异化预留；
- 页面不渲染旧工作区、会话抽屉、角色切换、页面标题或额外导航。

### 2. 交付 ProUI 元数据和看板

- 导入 `iba-demo` 分支 `feature/demo_1021` 的模板、组件、Tab、筛选器、指标卡、头盔图、
  表格和插槽位置；运行包保留源配置和来源信息；
- 经营看板、运营 360 与穿透式问题分析直接使用交付组件，不复制原型 HTML 作为主页面；
- 穿透式问题分析的头盔图按当前要求裁剪为“商机获取 → 订单接收 → 发货”三节点，运营 360 的
  完整运营链仍保留投标环节；
- 卡片标题与 AP 指标口径不一致、缺失子组件或未捕获快照时保留源配置原值或空位，并在差异
  清单中记录，不伪造图表或业务数据。

### 3. 真实模型分析插槽

- 交付配置声明 12 个分析插槽：经营看板 0 个、运营 360 4 个、穿透式问题分析 8 个；
- 页面空闲时预取商机、报价、投标、订单、发货 5 个环节，每个环节复用同一分析 Promise；
  首次分析通常约 10–20 秒，已完成范围复用历史结果；
- 阶段数字读取证据包 `facts`，风险、原因、建议和限制读取真实模型结果；失败时在插槽内显示
  错误与重试，不用固定文案冒充模型输出；
- `compact-v1` 契约限制摘要、原因、措施、责任角色、期限和验收长度，减少长文本对看板高度的
  冲击；三个风险插槽共用 `createStageRiskComponent`；
- 商机获取、订单接收、发货卡片按早期 mock 配置复原为概况、风险、原因、建议四段，
  使用 13px／22px 字号行高、8px 间距、`14px 16px 12px` 内边距，并按风险红／原因橙／
  建议蓝区分，验收、补充说明、证据和限制默认折叠。

### 4. 版本显示与文档收口

- 显示版本统一为 `ontology-v0.1.4`：`bi_agent/__init__.py`、`open_claude/__init__.py`、
  `bi_agent/web/app.py`、前端 `PRODUCT_VERSION` 与首屏版本标签；
- 包管理清单保持格式例外：`pyproject.toml` 为 PEP 440 `0.1.4`，
  `frontend/package.json` 与 `package-lock.json` 为 semver `0.1.4`；
- 前端构建产物 `workbench.js` 同步重建；版本文档、版本索引、根 README、版本规范和契约测试
  同步更新。

## 验证结果

- 驾驶舱契约测试 41 项通过；
- 前端构建成功，构建产物包含 `ontology-v0.1.4` 版本标识；
- 浏览器检查三个路由和 `id=1|2`，页面只有一个 `ProBiDashboard`，页内 Tab 切换同步 URL；
- 三个分析节点均挂载同一套四段式分析卡片，1440px 与 390px 视口下卡片内部无横向溢出；
- 页面只回放本地交付快照，不访问 AP、PDT 或生产接口；
- 版本契约测试与 `git diff --check` 在提交前执行。

## 已知限制

- 当前 34 测试环境部署仍属于独立验证，不等同于正式版本发布或生产部署；
- 团队模型网关曾返回 HTTP 400 `budget_exceeded`，真实模型验收需要网关管理方调整额度后重试；
  前端已按要求显示真实失败状态，没有替换账号或使用静态分析冒充成功；
- 商机模板缺少被引用的 `share-bar-79fsomq9` 子组件，运行包保留空位；
- 部分 AP 请求未包含在交付快照中，对应卡片显示组件自带的缺少快照提示；
- 交付 AP 指标口径、数据时点和部分卡片标题存在源配置差异，本版本保持原值并列入差异清单；
- 不拉 `release/ontology-v0.1.4` 分支；不删除、迁移或覆盖任何历史会话和用户数据。
- 整页缓存、生产版 Vue、按页加载和 AP 拆批等加载优化归入后续 `ontology-v0.1.5`，不在本 tag 中。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 分支模型：[Git 分支与合并工作流规范](../git-branch-workflow.md)
- 上一版本：[ontology-v0.1.3](./ontology-v0.1.3.md)
- 驾驶舱说明：[V3 经营驾驶舱 POC](../specs/cockpit-v3-poc.md)
- 差异清单：[交付元数据差异与缺失](../specs/cockpit-v3-metadata-gaps.md)
- 周 changelog：[changelog_10_19_23.md](../../changelog/changelog_10_19_23.md)
