# 智能分析 ontology-v0.1.5

## 基本信息

- 版本：`ontology-v0.1.5`
- 日期：`2026-10-27`
- 状态：正式版 / 当前版本（tag 与 GitLab Release 已创建）
- 版本位次：**PATCH**（`ontology-v0.1.4` → `ontology-v0.1.5`），版本号由用户在当前任务中明确指定
- 版本关系：在 `ontology-v0.1.4` 的 V3 驾驶舱能力之上，优化首次显示、整页数据一致性和 Fuxi 内嵌加载体验
- Release 分支：不单独拉出；通过 `feature/cockpit-v3-poc` → `master` 的 Merge Request !26 合并
- Git Tag：`ontology-v0.1.5`（annotated，2026-10-27）
- GitLab Release：[智能分析 ontology-v0.1.5](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.1.5)（2026-10-27）

## 版本概述

ontology-v0.1.5 是驾驶舱加载性能 PATCH。本版本不改变 V3 看板的信息架构和业务口径，重点减少
首次打开、筛选切换和 Fuxi 内嵌展示时的等待，并确保图表与 AI 卡片始终使用同一数据版本。

## 交付主题

### 1. 整页完整版本缓存

- 新增服务器校验的整页发布版本，保存图表数据、筛选范围、AI 卡片和数据时间；
- 页面打开时先回放上次完整版本，后台再取新 AP 数据并更新；
- 只有所有可见图表和 AI 卡片属于同一数据版本时才原子替换页面；
- 更新失败、数据不完整或筛选已变化时保留上次完整内容，并显示更新时间或失败原因；
- 页面版本追加保存，不覆盖历史，不把旧请求结果回填到新筛选范围。

### 2. AP 取数与一致性

- 新增按连接、认证配置和完整查询条件隔离的短时结果复用及并发合并；
- 默认 `COCKPIT_AP_BATCH_MODE=individual`，按原顺序把批量查询拆成 AP 单项请求，全部成功才交付；
- `native` 模式保留，供批量接口修复后联调；失败时不使用空数据、静默降级或跨数据源替代；
- AI 结果首屏使用紧凑返回，仅携带卡片所需摘要、建议、限制和证据，完整来源保留在分析记录中。

### 3. 首屏与静态资源

- 使用 Vue 生产版构建，静态资源支持 gzip 预压缩；
- 目标路由在挂载前确定，配置、运行模块和已发布卡片并行初始化；
- AI 插槽按当前页面实际出现的模块动态加载，不再在每页启动时加载全部 12 个模块；
- 新增内容哈希 release 构建、`release.json`、`manifest.sha256` 和 nginx 静态缓存模板。

## 验证结果

- Cockpit 相关 Python 测试 94 项通过；
- 整页缓存、数据客户端与卡片发布前端测试 21 项通过；
- 本地浏览器验收覆盖目标路由、按页加载 AI 模块、整页回放、AP 失败保留、筛选切换、旧页到新页替换和三个页面路由，全部通过；
- 静态站点构建 127 个文件（含 62 个 gzip 文件），`release.json` 与 `manifest.sha256` 校验通过；
- `git diff --check` 通过。

## 已知限制

- AP 原生批量接口仍存在“本地查询组合未配置／未启用”，当前使用显式 individual 拆批策略；
- 部分 AP 请求没有交付快照，页面继续显示组件自身的缺少快照提示；
- 本版本不部署，不修改服务器运行状态或用户历史会话；
- 不拉 `release/ontology-v0.1.5` 分支。

## 相关记录

- 版本规范：[语义化版本与正式发布规范](./versioning-policy.md)
- 上一版本：[ontology-v0.1.4](./ontology-v0.1.4.md)
- 驾驶舱说明：[V3 经营驾驶舱 POC](../specs/cockpit-v3-poc.md)
- 卡片发布契约：[Cockpit 卡片发布与同源证据](../specs/cockpit-card-publications.md)
