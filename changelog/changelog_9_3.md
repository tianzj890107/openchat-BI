# eimosp-ontology-agentic-analytics 变更记录（2026-09-03）

> 本文档只记录 2026-09-03 当天完成的最终变更。
> 本文件由用户当天明确要求创建，补录当日此前未写入 changelog 的变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 变更

### 1. 本体子图弹窗新增“语义环形可视化”（Spec + 实现 + 验收修复，已完成）

- 用户可见变化：本体子图弹窗工具栏现提供两个布局选项——默认“关系聚类可视化”
  （Sigma + ForceAtlas2，行为不变）与新增“语义环形可视化”；环形视图将当前锚点置于
  中心，其余节点按与锚点的最短关系距离分环展示（`distance:0..N`、`unrelated`），
  支持滚轮缩放、拖动画布与按当前视口重新布局；布局切换与重新布局只复用已加载子图
  数据，不重新请求 `/api/ontology/subgraph`、不调用 LLM、不写聊天历史、不推进 SOP。
- Context/Expand 子图检索仍走原接口，响应到达后保持当前布局偏好；无关系边、空图、
  ECharts 加载失败、环形契约错误等边界均有可读提示且不会关闭弹窗。
- 异步控件与生命周期修复：子图请求与渲染期间，strategy/layout/relayout 三类控件统一
  禁用；请求与渲染分别用 `requestEpoch`/`renderToken` 守卫，旧请求或迟到渲染不能解锁
  新任务或覆盖新状态；Sigma `kill()` 与 ECharts `dispose()` 收敛为幂等 renderer
  handle，关闭弹窗、切换策略、切换布局、失败路径都先销毁旧实例再操作 canvas。
- 跨弹窗异步身份修复（验收修复）：`openOntologyGraphView` 不再从全新状态重建
  `requestEpoch`/`renderToken`，而是从上一个弹窗状态继续递增；关闭实体 A 后打开
  实体 B，A 的迟到请求或 ECharts 渲染无法通过 B 的当前身份判断，避免旧任务覆盖
  新弹窗（新增 5 项 reopen 单调性/不碰撞测试与 1 项 Runtime 契约回归测试）。
- 数据转换：`buildRadialGraph(data)` 在分析端保持纯函数，无向 BFS 分环、稳定
  `parentId`、样式沿用 `NODE_STYLE`；共享环形算法只从 `@boulderaitech/ontology-graph/radial`
  导入，分析仓库内无算法副本，共享包未修改。
- 主要文件：`docs/specs/ontology-radial-visualization.md`、
  `docs/specs/ontology-radial-visualization-acceptance-fixes.md`（新增 Spec）；
  `frontend/src/ontologyGraphModel.js`、`frontend/src/ontologyGraphViewState.js`（新增）、
  `frontend/src/ontologyGraphRendererHandle.js`（新增）、`frontend/src/runtime.js`、
  `frontend/src/workbench.css`；`frontend/tests/ontologyRadialGraphModel.test.mjs`、
  `frontend/tests/ontologyGraphViewState.test.mjs`、
  `frontend/tests/ontologyGraphRendererHandle.test.mjs`（新增）；`tests/test_regressions.py`。
- 验证：共享包 `npm test` 6 passed；前端单测 41 passed；`npm run build` 成功；
  `pytest tests/test_regressions.py -q` 215 passed（含新增契约测试）；
  `git diff --check` 通过。未部署、未发包。

### 2. 本体布局控件：自定义选择面板 + 键盘闭环 + 白色说明气泡 + 工具栏等高（Spec + 实现 + 验收修复，已完成）

- 用户可见变化：本体子图弹窗工具栏将原来的“关系聚类可视化 / 语义环形可视化”两个并列
  按钮收敛为控件组“布局 [选择器 ▼] (? )”：默认“关系聚类可视化”，可切换“语义环形
  可视化”，沿用 `cluster`/`radial` 状态值与原切换逻辑（复用已加载子图，不重新请求
  接口、不调 LLM、不写聊天历史）。选择器为页面自绘自定义 combobox + listbox（曾用
  原生 `<select>`，验收修复后移除）：点击或键盘打开自绘白色选项面板，选项为完整可点击
  行，当前项有选中态与勾选，hover/活动项浅蓝反馈；点击外部或关闭弹窗自动收起；busy
  时 trigger 禁用并自动收起面板，结束后恢复。
- 键盘闭环（本轮验收修复）：所有按键统一走 trigger 的纯键盘转换入口
  `handleOntologyLayoutPickerKey`，DOM 焦点始终留在 trigger，menu 不再承担需要焦点才
  能工作的 keydown 导航（菜单仅响应鼠标点击）；Enter/Space 打开或提交、ArrowDown/Up
  循环移动、Home/End 首末项、Escape 取消不提交、Tab 关闭菜单并按正常顺序离开；纯键盘
  可完成 cluster → radial → cluster，全程子图请求增量为 0。
- 可访问性：trigger 为真实 button（`role="combobox"`、`aria-haspopup="listbox"`、
  `aria-expanded`、`aria-controls`、`aria-activedescendant`）；option 使用稳定唯一 id
  （`ontology-layout-option-*`）、`role="option"`、`tabIndex=-1`；打开时
  `aria-activedescendant` 指向活动项、关闭时移除；`aria-selected`/`.is-selected` 只表示
  已提交布局，键盘临时活动项只反映为 `.is-active`，二者不混淆。
- 工具栏等高：layout trigger 与“重新布局”按钮统一为显式 `height:26px` +
  `box-sizing:border-box`（relayout 另设 `min-height:26px`、inline-flex 垂直居中），
  不依赖 transform/scale/负 margin；disabled 前后与 720px 以下换行后仍等高。
- 说明气泡：白色 `role="tooltip"` 气泡以 `?`（`[data-graph-layout-help]`）为锚点右对齐
  （`right:0;left:auto`，箭头 `right:6px` 指向 `?`），深色文字、浅灰边框、轻阴影、最大
  宽度 280px；切换布局后气泡文案即时同步；帮助按钮不设 `title`。
- 实现：`frontend/src/ontologyLayoutOptions.js` 为布局名称与说明文案唯一来源；
  `frontend/src/ontologyLayoutPickerState.js` 提供 picker 开关/活动项/统一键盘转换/
  busy 纯状态转换；`frontend/src/runtime.js` 只负责 DOM 渲染、事件与同步；原生
  select 及旧双按钮 DOM/CSS/监听器已清除。
- 主要文件：本轮新增
  `docs/specs/ontology-layout-keyboard-and-toolbar-height-fixes.md`（Spec）、
  `docs/test-evidence/ontology-layout-keyboard-height-red.txt`、
  `docs/test-evidence/ontology-layout-keyboard-height-green.txt`、
  `docs/test-evidence/ontology-layout-browser-acceptance.json` 与截图
  `docs/test-evidence/k1..k5-*.png`；修改 `frontend/src/ontologyLayoutPickerState.js`、
  `frontend/src/runtime.js`、`frontend/src/workbench.css`、
  `frontend/tests/ontologyLayoutPickerState.test.mjs`、`tests/test_regressions.py`；
  构建产物 `bi_agent/web/static/vendor/antd/*` 同步更新。
- 验证：Red 证据非零退出码（单测 20 tests / 11 pass / 9 fail、回归 2 failed，退出码 1）；
  Green 后前端单测 66 passed（picker 文件 20 项）、`npm run build` 成功、共享包
  `npm test` 6 passed、`pytest tests/test_regressions.py -q` 217 passed（新增统一键盘/
  等高契约方法）、`git diff --check` 通过；真实 Chrome 桌面 1440px 与窄屏 700px 验收：
  键盘闭环、ARIA 同步、两个控件计算高度均 26px、menu/Tooltip 不被裁切、气泡箭头指向
  `?`。未部署、未发包。
