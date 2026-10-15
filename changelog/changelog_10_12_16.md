# eimosp-ontology-agentic-analytics 变更记录（2026-10-12 至 2026-10-16）

> 本文档记录 2026-10-12（周一）至 2026-10-16（周五）当周的最终变更，
> 按周直接维护，不再创建日报。

## 维护规则

- 当周变更直接写入本文档，不创建日报文件。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件，并注明改动时间。
- 未完成、未验证的事项不要写成已完成。

## 本周变更

（文件于 2026-10-15 建立：本周 10-12、10-15 的修改集中在分析逻辑剥离包、分析过程可见性、
取数证据归档与版本收口，故按主题合并记录。）

### 2026-10-12 · 剥离包整页交付工具 `CanvasGenerate` 与 Fuxi 技能字段对齐

- 背景：通用 Agent（内置到 Fuxi / Codex 等）跑剥离包时，前端不再是站点内的卡片，而是直接
  生成整页画布；原渲染工具只有 schema、未接进 CLI 运行时，导致「能发现工具、不能真正出图」。
- 交付：`ontology-analytics-skill/tools/canvas_tool.py` 新增 `CanvasGenerate`，把结论、表格与图
  一次性产出为**单文件 HTML**（内联样式 + 本地 `tools/assets/echarts.min.js`，无需外网）；同时按
  包内真实实现把渲染类工具注册进 `tools/serve.py` 运行时，可用工具数 17 → 18。
- 展示字段：`SKILL.md` 补齐中文名、中文描述与 `runtime: python` 依赖声明，使其在 Fuxi 技能列表里
  有中文标题与说明，并声明 Python 运行依赖。
- 同步更新包内 `README.md`、`references/08-tools-and-sources.md`、`tools/README.md`、`tools/selftest.py`。
- 验证（2026-10-12）：`tools/serve.py --list-tools` 列出 18 个工具；`CanvasGenerate` 本地实测产出
  可直接打开的单文件 HTML；`tools/selftest.py` 通过。
- 边界：仅新增工具与文档，不改仓库现有实现方式；未改版本号、未部署。

### 2026-10-15 · 多步分析新增中文过程播报（中间过程对业务可见）

- 问题：多步分析中间状态对业务用户不可见（此前要求「工具调用过程保持静默」），且可见思考
  依赖模型能力与开关，DeepSeek 等模型下几乎没有中文过程说明。
- 变化：`bi_agent/web/session.py` 新增常驻 `PROGRESS_NARRATION_RULE`，每次请求最后注入系统
  提示词，要求「首次调用工具前、以及每次进入新分析阶段」用**一句业务化中文**说明接下来做什么；
  规则不依赖「可见思考」开关与模型思考能力，因此任意模型下都生效。
- 同时修正 `.claude/agents/bi-analyst.md`：解除「过程保持静默」与「禁止技术旁白」的冲突表述，
  明确允许一句话过程播报，继续禁止技术旁白、工具参数原文与 SOP/模板复述。
- 用户可见效果：多步提问时正文先出现一句中文进度说明（如「我先确认『采购金额』在本体里的权威
  口径，再核对 2025 年的取数数据源」），随后才是结论与图表；单步取数不强制播报。
- 验证（2026-10-15）：新增回归用例断言「思考关闭且模型不支持思考时规则仍注入」；本地服务实测
  播报按阶段出现，7 个工具全部 SUCCEEDED（2025 年采购金额 854,057,481.11 元）并产出图表与表格。

### 2026-10-15 · 管理单元 2800 / 101701 取数证据与双环境对比归档

- 新增 `docs/specs/executed-sql-management-units-2800-101701.md`：把管理单元 `2800` 与 `101701`
  实际执行的原始 SQL（**全口径**与**已审批口径**分别列出）与 `demometaerp`、`demo2` 两个环境
  的 ecore 实际输出对比归档，便于核对口径差异与结果一致性。
- 方式：只读提取当轮实际执行的 SQL 与结果，不改动历史会话与用户数据。

### 2026-10-15 · 交付口径：`20260727` 归档，改为临时分支 → `master`

- `20260727` 归档分支退役、停止接收新提交；日常开发在 `feature/*` / `bugfix/*` / `hotfix/*` 临时
  分支上进行，正式交付通过「临时分支 → `master`」的 Merge Request（reviewer `tianzijing`）完成。
- 同步 `AGENTS.md`、`debug.md`、`.claude/agents/devops.md`、`docs/git-dual-remote-workflow.md`、
  `docs/specs/master-mainline-delivery.md`、`docs/specs/repository-wide-master-branch-consistency.md`；
  `docs/specs/master-mainline-migration.md` 标注为已完成的历史记录。
- `scripts/push_gitlab.py` 收敛为「归档分支 20260727 的核对/补推」辅助脚本，日常交付使用
  `git push gitlab <branch>`；新增守卫测试，现行文档不得再把 `20260727` 当成交付分支。

### 2026-10-15 · 版本收口 `ontology-v0.1.2`（PATCH）并创建 tag 与 Release

- 版本号：按用户明确指定收口为 `ontology-v0.1.2`，覆盖两个补丁窗口（剥离包收尾 + 过程播报/交付
  口径收口）；`v0.1.1` 未单独发布、号码作废。
- 版本入口与显示名统一为 `ontology-v0.1.2`：`pyproject.toml`、`frontend/package.json`、
  `frontend/package-lock.json`（`0.1.2`）；`bi_agent/__init__.py`、`bi_agent/web/app.py` `APP_VERSION`、
  `open_claude/__init__.py`、剥离包内 `tools/_vendor/open_claude/__init__.py`、前端 `PRODUCT_VERSION`
  与首屏版本 chip（`ontology-v0.1.2`）；前端构建产物 `workbench.js` 重建（重复构建无额外 diff）。
- 版本文档：新增 `docs/versions/ontology-v0.1.2.md`；更新 `docs/versions/README.md` 索引、
  根 `README.md` 当前版本与发布清单、`docs/versions/versioning-policy.md`（当前正式版本、包管理
  清单例外、版本推进记录）、`AGENTS.md` 当前版本口径；契约测试同步（tag 白名单同步放行
  `ontology-v0.1.2`）。
- 交付：`feature/progress-narration-zh` → `master` 的 Merge Request `!23` 已由代码评审合并，定版
  commit `3c4de1e`；annotated tag `ontology-v0.1.2` 已创建并推送 GitLab，同 tag 的 GitLab Release
  已创建（只新建、未覆盖已有 Release）。按用户指示**不拉** `release/ontology-v0.1.2` 分支。
- 验证：全量测试 `1285 passed / 25 skipped / 1070 subtests passed`；`git diff --check` 通过。
- 边界：未部署、未重启服务，tag 与 Release 创建不触发部署。
