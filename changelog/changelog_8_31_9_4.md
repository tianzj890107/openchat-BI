# eimosp-ontology-agentic-analytics 变更记录（2026-08-31 至 2026-09-04）

> 本文档汇总 2026-08-31（周一）至 2026-09-04（周五）一周的最终变更，合并
> 8/31、9/1、9/2、9/3 每日记录为周颗粒度。9/4 未创建当日 changelog：经 git
> 提交记录核对，9/4 无代码、文档或发布提交，无可记录变更。

## 维护规则

- 周记录使用高于日报的颗粒度：按交付主题合并同类项，突出阶段性成果、用户价值
  与影响范围，不机械复制每日条目。
- 每条记录只描述最终状态与已验证事实；中间尝试、被后续版本取代的描述不写入。
- 周汇总依据：`changelog/changelog_8_31.md`、`changelog_9_1.md`、
  `changelog_9_2.md`、`changelog_9_3.md` 及 git 提交记录（截至 `f2a9614`，
  2026-09-03）。

## 2026-08-31 至 2026-09-04

### 1. 交付与版本流程固定为 GitLab 单仓规范（8/31–9/1）

- 日常交付收敛为只推送 `gitlab/20260727`：新增 `scripts/push_gitlab.py`
  （`--check` 只校验不推送；校验远端映射、工作区、祖先关系与推送后 hash；
  禁止 force push；不自动推 tag；成功标准 `HEAD == gitlab/20260727`），本地
  远端收敛为只保留 `gitlab` 一个。
- `main` 作为受保护发布分支：合并必须走 Merge Request（`20260727 → main`，
  reviewer 固定 `tianzijing`、assignee 固定 `zhangzhen`），Agent 只创建 MR、
  不自动合并、不直接 push `main`；该动作映射写入 `AGENTS.md`。
- 版本与 Release 规则改为 GitLab 单仓方式：用户授权后基于同名 tag 创建 Release，
  幂等（只补缺失项）、不覆盖已有 Release；凭据统一存放
  `~/.config/codex/gitlab_token`（权限 600），仓库内不保存明文。
- 历史治理：提交邮箱规范化为 `张真 <zhangzhen@boulderaitech.com>`（用户授权
  `--force-with-lease` 重写 174 个提交并恢复分支保护）；`main` 设为默认分支；
  9/2 再清除空内容 merge 带回的 172 个重复提交，`20260727` 与 `main` 收敛到
  同一条改写历史，避免后续 MR 带回旧历史；全仓旧托管平台痕迹清理完成
  （仅保留第三方 vendor 许可注释与历史 commit 文本）。
- 用户价值：从本周起，提交、推送、MR、正式版本、tag、Release 与部署有统一且
  可复核的交付链路与评审边界。

### 2. 本体图渲染核心抽为共享包并发布（8/31–9/1）

- `@boulderaitech/ontology-graph@0.1.0` 发布到 ai-team 组包 registry（托管项目
  `ai-team/ontology-graph`；GitLab 14 无纯组级 npm 端点，采用项目级 package
  registry）。共享包内含 Sigma + Graphology + ForceAtlas2 的布局纯函数与框架
  无关渲染器（hover/click 高亮、相机阈值、ResizeObserver、kill/relayout），
  并固化 graphology 图契约（`nodeType/label/color/size/parentId/highlighted/weight`）。
- 本仓保留自身图构建 `frontend/src/ontologyGraphModel.js`（`buildGraph` 把
  `/api/ontology/subgraph` 结果映射为契约图）与 11 类 `NODE_STYLE`，删除本地
  渲染副本，`runtime.js` 改从共享包引用；布局/渲染单测迁至共享包仓库。
- 影响：为 9/3“语义环形可视化”复用同一共享包、两种布局共用一套图数据契约打基础。

### 3. 容器化交付与统一运行规范（9/2）

- 新增 `Dockerfile`/`.dockerignore`/`.python-version`：官方 `python:3.13-slim`、
  非 root 用户、内置 `HEALTHCHECK`、前端构建产物随镜像（构建无需 Node.js）；
  容器内 HTTP 统一监听 `0.0.0.0:8080`，宿主机推荐映射 `8765:8080`。
- 健康检查统一为 `GET /healthz`（等价别名 `/health`）：就绪 200 / 未配置 503，
  不触发 LLM；响应字段固定（`app`/`version`/`port`/`configured`/`dependencies`
  等），其中 `port` 动态反映进程实际监听端口，非容器默认端口保持 `8765`。
- 应用与仓库统一改名 `eimosp-ontology-agentic-analytics`（上游建模仓库为
  `eimosp-ontology-agentic-modeling`）；Nacos 仅做文档与配置占位，未接入。
- TDD：`docs/specs/container-port-8080.md` + 12 项端口契约测试通过；全量 Python
  318 项中 1 项环境预置失败（历史备份 tag 相关，未删除该 tag）；Docker 镜像
  构建因拉取 `python:3.13-slim` 超时未完成，未声称容器运行验证通过。

### 4. 发布 v0.1.1 并部署 company-server（9/2）

- 用户明确授权正式版本 `v0.1.1`：版本入口 8 处同步 `0.1.1`，新增
  `docs/versions/v0.1.1.md`，同步版本索引、根 README、AGENTS.md、DEPLOYMENT.md
  与版本契约测试；创建并推送 annotated tag `v0.1.1`，GitLab 创建同名 Release。
- 部署：company-server（172.16.10.34）新目录
  `~/eimosp-ontology-agentic-analytics-releases/v0.1.1`；会话/图表/上传/日志/图数据
  目录符号链接指向 `openchat-BI-releases/a035df9` 数据目录（历史会话与运行产物
  不复制、不覆盖）；服务器缺 `python3-venv`，`.venv` 由旧 release 复制并改写
  可编辑安装引用；停旧实例切换，旧 release 目录保留可回滚。
- 验证：`/healthz` 返回 `version=0.1.1`、`port=8765`、`configured=true`；启动日志
  `history_root=.../dataset/conversations scanned=78`（历史会话接入）；`/workbench` 200。

### 5. 本体子图新增“语义环形可视化”（9/3，完整 TDD 闭环）

- 本体子图弹窗新增 `radial` 展示模式：当前锚点居中，其余节点按与锚点的最短关系
  距离（无向 BFS）分环（`distance:0..N` / `unrelated`）；`buildRadialGraph(data)`
  为分析端纯数据转换，环形算法只从共享包 `@boulderaitech/ontology-graph/radial`
  导入（`prepareRadialLayout`/`radialGraphOption`），分析仓库无算法副本、共享包
  未修改未升版。
- 默认布局仍为“关系聚类可视化”（Sigma + ForceAtlas2，行为不变）；布局切换与
  “重新布局”只复用已加载子图数据，不重新请求 `/api/ontology/subgraph`、不调用
  LLM、不写聊天历史、不推进 Agent SOP；Context/Expand 请求完成后保持当前布局
  偏好；空图、无关系边、ECharts 加载失败、环形契约错误均有可读提示且不关闭弹窗。
- 异步与生命周期硬化：子图请求与渲染期间 strategy/layout/relayout 三类控件统一
  禁用；`requestEpoch`/`renderToken` 状态机让旧请求与迟到渲染不能解锁新任务或
  覆盖新状态；Sigma `kill()` 与 ECharts `dispose()` 收敛为幂等 renderer handle，
  关闭弹窗、切换策略/布局、失败路径统一先销毁旧实例；跨弹窗打开时异步身份从
  上一状态单调递增，实体 A 的迟到任务不会误判为实体 B。
- 验证：radial 模型/视图状态/renderer handle 前端单测新增通过；`tests/test_regressions.py`
  新增契约断言；Spec：`ontology-radial-visualization.md` 及验收修复 Spec。

### 6. 本体布局控件体验收敛（9/3，Spec 系列验收）

- 布局控件由双按钮/原生 `<select>` 收敛为页面自绘自定义 combobox + listbox：
  trigger 为真实 button（`role="combobox"`、`aria-expanded`/`aria-controls`/
  `aria-activedescendant`），option 稳定唯一 id、`role="option"`、`tabIndex=-1`、
  `aria-selected` 只表示已提交布局；键盘闭环统一走 trigger 纯键盘转换
  （Enter/Space 打开或提交、ArrowDown/Up 循环、Home/End 首末、Escape 取消、
  Tab 正常离开），纯键盘可完成 cluster → radial → cluster 且网络请求增量为 0。
- 工具栏：layout trigger 与“重新布局”按钮显式 `26px` 等高（`box-sizing:border-box`），
  disabled 前后与 720px 以下换行后仍等高；下拉选项改为无边框列表行，hover/键盘
  活动项整行浅蓝，已选行蓝色文字与勾选。
- 说明文案最终口径：删除布局控件右侧“?”按钮、旧 Tooltip DOM/CSS/监听器与原生
  `title`；白色说明气泡只在布局菜单展开后鼠标悬浮 option 时显示（白底、深色文字、
  浅灰边框、圆角、轻阴影、`max-width:280px`、`pointer-events:none`，默认 option
  右侧、窄屏自动翻转）；两段文案只存在于 `ontologyLayoutOptions.js`。
- 验收证据可重复化：新增 `scripts/verify_ontology_layout_borderless_ui.mjs`
  （仓库内、真实 Chrome、任一断言失败非零退出）与证据契约测试
  `tests/test_ontology_layout_browser_evidence.py`，同一次运行生成 JSON 与
  `g1..g4` 截图，修正此前 g3/g4 哈希相同的无效窄屏 hover 证据；真实 Chrome
  桌面 1440px / 窄屏 700px 验收 21/21。
- 验证：前端单测 76 passed；`npm run build` 成功；Python 回归 219 passed；
  Spec：`ontology-layout-selector-white-tooltip` → 验收修复 → 键盘与工具栏等高 →
  option 悬浮说明 → 无边框选项 → 窄屏 hover 证据（均已标已完成）。

### 7. 发布 v0.1.2 并部署 company-server（9/3）

- 用户明确授权正式版本 `v0.1.2`：版本入口同步 `0.1.2`，新增
  `docs/versions/v0.1.2.md`；创建 Merge Request !4（`20260727 → main`，
  reviewer `tianzijing`、assignee `zhangzhen`，标题与描述归纳 main..20260727
  全部 13 个提交主题，opened 等待 code review）；创建并推送 annotated tag
  `v0.1.2`（指向定版 commit `c8454d8`），GitLab 创建同名 Release。
- 部署：company-server 新目录 `releases/v0.1.2`，数据目录符号链接沿用 v0.1.1
  同一组目标、`exports` 指向 v0.1.1 导出目录；`.venv` 由 v0.1.1 复制并改写 3 处
  可编辑安装引用；停 v0.1.1 进程切换（旧目录保留可回滚）。验证：`/healthz`
  `version=0.1.2`、`port=8765`、`configured=true`、dependencies 全 true；
  `history_root ... scanned=78`；`/workbench` 200；远端静态产物 SHA-256 与本地
  定版构建一致。
- 工程补记：`AGENTS.md` 明确 MR 标题与描述必须归纳完整提交范围（禁止只写分支
  关系），并定义任务终态后“继续”指令只等待新命令、不重开已关闭任务。

### 8. 周度验证与交付全景

- 测试与构建：全量 Python 测试 306 → 318 项（含 12 项容器端口契约）；
  前端 `node --test` 76 passed；`pytest tests/test_regressions.py -q`
  219 passed；`npm run build` 成功；`git diff --check` 通过。
- 版本：`v0.1.1`（9/2）、`v0.1.2`（9/3）均完成 tag + GitLab Release +
  company-server 部署；`main` 经 MR !3 合入至 `a7e4365`，MR !4 承载
  v0.1.2 交付待 review 合入。
- 数据与安全：两轮部署均通过数据目录符号链接保留全部历史会话与运行产物，旧
  release 目录保留可回滚；未删除/改写历史会话与用户数据；共享包只发布未修改
  算法与版本规则。
- 9/4（周五）：git 提交记录显示无代码、文档或发布提交；当日 changelog 未创建，
  经核对无可记录变更。

> 说明：本汇总基于本地 git 记录（截至 `f2a9614`，2026-09-03 15:11）与四份日报；
> 汇总时 GitLab 远端网络暂不可达，9/4 之后远端若出现新提交或 MR 合入，以最新
> git 记录为准并同步修订本文件。

## 相关记录

- 日 changelog：`changelog/changelog_8_31.md`、`changelog/changelog_9_1.md`、
  `changelog/changelog_9_2.md`、`changelog/changelog_9_3.md`
- 正式版本：`docs/versions/v0.1.0.md`、`docs/versions/v0.1.1.md`、
  `docs/versions/v0.1.2.md`、`docs/versions/README.md`、`docs/versions/versioning-policy.md`
- 流程与部署：`AGENTS.md`、`docs/gitlab-push-workflow.md`、`DEPLOYMENT.md`
- Spec：`docs/specs/container-port-8080.md`、`docs/specs/ontology-radial-visualization.md`
  及验收修复、`docs/specs/ontology-layout-*.md` 系列、证据目录 `docs/test-evidence/`
