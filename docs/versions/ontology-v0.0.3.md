# 智能分析 ontology-v0.0.3

## 基本信息

- 版本：`ontology-v0.0.3`
- 历史命名：本版本原以 `v0.1.2` 发布，2026-09-29 随版本族切换到 `ontology-v0.0.x` 时改名，定版 commit 未变
- 日期：`2026-09-03`
- 状态：正式版
- Git Tag：`ontology-v0.0.3`
- 定版 commit：以 `ontology-v0.0.3` annotated tag 指向的 commit 为准

## 版本概述

ontology-v0.0.3 在 ontology-v0.0.2 基础上交付本体子图“语义环形可视化”的完整闭环（共享环形布局接入、
自定义布局选择器、键盘可访问性、option 悬浮说明、异步竞态与渲染器生命周期修复、
可重复浏览器验收证据），并补记 ontology-v0.0.2 定稿与部署、9/3 开发记录与 MR 提交范围规范。
版本号 `ontology-v0.0.3` 由用户在当前任务中明确指定，按 PATCH 级发布执行；本体子图弹窗仍是
原有入口与 Context/Expand 数据源，未新增独立业务流程。

## 核心变化（相对 ontology-v0.0.2，按交付主题）

- 本体子图语义环形可视化（Spec：`ontology-radial-visualization.md` 及验收修复）：
  - 本体子图弹窗默认仍为“关系聚类可视化”（Sigma + ForceAtlas2，行为不变），新增
    “语义环形可视化”展示模式：当前锚点置于中心，其余节点按与锚点的最短关系距离
    （无向 BFS）由内向外分环（`distance:0..N`、`unrelated`），支持滚轮缩放、拖动画布
    与按当前视口重新布局；
  - `buildRadialGraph(data)` 为分析端纯数据转换，环形算法只从共享包
    `@boulderaitech/ontology-graph/radial` 导入（`prepareRadialLayout` /
    `radialGraphOption`），分析仓库内不存在算法副本，共享包未修改未升版；
  - 布局切换与重新布局只复用当前已加载子图数据，不重新请求 `/api/ontology/subgraph`、
    不调用 LLM、不写聊天历史、不推进 Agent SOP；Context/Expand 请求完成后保持当前
    布局偏好；空图、无关系边、ECharts 加载失败、环形契约错误均有可读提示且不关闭弹窗；
  - 异步与生命周期修复：子图请求/渲染期间 strategy/layout/relayout 三类控件统一禁用；
    `requestEpoch`/`renderToken` 守卫让旧请求与迟到渲染不能解锁或覆盖新任务；
    Sigma `kill()` 与 ECharts `dispose()` 收敛为幂等 renderer handle；关闭弹窗、
    切换策略/布局、失败路径统一先销毁旧实例再操作 canvas；
    跨弹窗打开时 `requestEpoch`/`renderToken` 保持单调递增，实体 A 的迟到任务不会
    被误判为实体 B 的任务。
- 布局控件体验收敛（Spec 系列：白色 Tooltip → 验收修复 → 键盘闭环与工具栏等高 →
  option 悬浮说明 → 无边框选项 → 窄屏 hover 证据）：
  - “布局 [关系聚类可视化 ▼]”改为页面自绘自定义 combobox + listbox（移除原生
    `<select>` 与早期双按钮）：真实 button trigger，`role="combobox"`、
    `aria-expanded`/`aria-controls`/`aria-activedescendant` 完整，option 带稳定 id、
    `role="option"`、`aria-selected` 只表示已提交布局；
  - 键盘闭环：Enter/Space/ArrowDown/ArrowUp/Home/End/Escape/Tab 全部走 trigger 纯
    键盘转换入口，焦点始终留在 trigger，纯键盘可完成 cluster → radial → cluster，
    切换布局网络请求增量为 0；
  - trigger 与“重新布局”按钮显式 `26px` 等高（`box-sizing:border-box`），disabled
    前后与 720px 以下换行后仍等高；
  - 布局控件右侧“?”与旧 Tooltip 已完全删除；说明气泡只在布局菜单展开后鼠标悬浮
    option 时显示（白底、深色文字、浅灰边框、圆角、阴影、`max-width:280px`、
    `pointer-events:none`，默认在 option 右侧、窄屏自动翻转）；trigger/option 无原生
    `title`；两段说明文案只存在于 `ontologyLayoutOptions.js`；
  - 下拉选项改为无边框列表行（`border:0`、透明背景），hover/键盘活动项整行浅蓝，
    已选行蓝色文字与勾选，面板外层保留白底/浅灰边框/圆角/轻量阴影；
  - 新增仓库内可重复浏览器验收脚本
    `scripts/verify_ontology_layout_borderless_ui.mjs` 与证据契约测试，窄屏
    700x900 真实 hover 的白色说明气泡可见、文案精确、完全位于视口内。
- 工程与文档（并入 main 的补记与规范）：
  - `AGENTS.md` 明确 MR 标题与描述必须归纳完整提交范围（禁止只写分支关系）；
  - 记录 9/2 ontology-v0.0.2 定稿与 172.16.10.34 部署、9/3 开发记录（`changelog_9_3.md`）；
  - 共享包依赖 `@boulderaitech/ontology-graph@0.1.1` 保持锁定。

## 用户可见变化

- 本体子图弹窗工具栏出现“布局”下拉：默认“关系聚类可视化”，可切到“语义环形可视化”
  （锚点居中、按最短关系距离分环），布局与重新布局不再触发子图请求；
- 选择器可鼠标也可纯键盘操作，聚焦/展开/选中状态有清晰视觉与 ARIA 反馈；布局切换与
  重新布局按钮高度一致；
- 说明文字改为“鼠标悬停下拉选项”时显示，页面不再有“?”按钮与浏览器原生黑色气泡；
- 快速切换布局、连续发起 Context/Expand、随后关闭弹窗时，不会出现旧渲染覆盖、控件
  提前解锁或重复画布实例；
- 页面品牌与版本号显示 `ontology-v0.0.3`。

## 兼容性与运维变化

- 布局内部值仍为 `cluster`/`radial`，Context/Expand 策略语义与接口不变，默认布局
  仍为关系聚类；不迁移历史会话，不修改后端接口与图算法；
- 部署仍需同步前端构建产物（`bi_agent/web/static/vendor/antd/workbench.js` 与 CSS），
  共享包版本不变（`@boulderaitech/ontology-graph@0.1.1`）；
- 历史会话、上传文件、图表、日志等用户数据目录保护规则不变；正式版本文档、tag 与
  Release 相互独立并各自单独授权。

## 验证情况

- 前端 `node --test tests/*.test.mjs`：76 passed（radial 模型、视图状态、renderer
  handle、picker、layout options、option tooltip 状态及全部既有用例无减少）；
- `npm run build` 成功，构建产物随仓库同步；
- 共享包 `ontology-graph npm test`：6 passed；
- `pytest tests/test_regressions.py -q`：219 passed；浏览器证据契约测试通过；
- `node scripts/verify_ontology_layout_borderless_ui.mjs`：21/21 通过，同一运行重新
  生成 JSON 与 `g1..g4` 截图（g3/g4 哈希不同，窄屏 hover 气泡可见）；
- `git diff --check` 通过；推送后 `HEAD == gitlab/20260727`；tag 与 GitLab Release
  已创建；172.16.10.34 部署记录见 `DEPLOYMENT.md` §9。

## 已知限制

- ChatBI 并发治理当前只支持单 Uvicorn worker；
- L1/L2 简单查询不进入根因分析（第 5 步跳过，属设计行为）；
- 容器镜像的真实构建与运行验证仍以契约测试与文档为准（延续 ontology-v0.0.2 说明）。

## 升级说明

- 从 ontology-v0.0.2 升级：
  - 非容器：更新代码到 ontology-v0.0.3，`python -m pip install -e '.[web]'`，同步本次前端
    构建产物（`bi_agent/web/static/vendor/antd/workbench.js` 与 CSS），再重启服务；
  - 容器：重新构建/拉取 `eimosp-ontology-agentic-analytics:ontology-v0.0.3`，按
    `-p 8765:8080` 映射并挂载数据卷；
- 历史会话迁移前先完整备份 `dataset/conversations/`，不直接改写用户数据；
- `.env` 配置（LLM/Doris/远程本体/Nacos 占位）保持不变。

## 版本管理

- 统一代码位于 GitLab `gitlab/20260727`（`ai-team/eimosp-ontology-agentic-analytics`）；
- merge 到 `main` 需要 `tianzijing` code review 后单独发起 Merge Request；
- 日常 push 保持 `HEAD == gitlab/20260727`；
- Git tag 和 GitLab Release 属于正式版本动作，不属于日常 push。

## 相关记录

- [2026-09-03 日开发记录](../../changelog/changelog_9_3.md)
- [2026-09-02 日开发记录](../../changelog/changelog_9_2.md)
- Spec：`docs/specs/ontology-radial-visualization.md`、`ontology-radial-visualization-acceptance-fixes.md`、
  `ontology-layout-selector-white-tooltip.md`、`ontology-layout-selector-acceptance-fixes.md`、
  `ontology-layout-keyboard-and-toolbar-height-fixes.md`、`ontology-layout-option-hover-hints.md`、
  `ontology-layout-borderless-options.md`、`ontology-layout-narrow-hover-evidence-fix.md`
- 证据：`docs/test-evidence/`（ontology-layout-*、g1..g4 截图与 JSON）
- GitLab Release：[智能分析 ontology-v0.0.3](https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.3)
- Release 基于 `ontology-v0.0.3` tag，指向定版 commit（见 tag 指向）。
