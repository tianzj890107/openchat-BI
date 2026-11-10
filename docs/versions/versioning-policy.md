# eimosp-ontology-agentic-analytics 语义化版本与正式发布规范

本文件是 eimosp-ontology-agentic-analytics 版本管理的唯一完整规范。`AGENTS.md`、`README.md`、
`docs/versions/README.md`、`docs/gitlab-push-workflow.md` 只保留必要摘要并
链接到本文件。

## 目标与适用范围

- 统一产品版本号含义，避免按日期、commit 数量或部署次数机械升级；
- 明确 Git commit、周 changelog、正式版本文档、Git tag、GitLab Release 与部署
  之间的边界；
- 适用于 eimosp-ontology-agentic-analytics 仓库内所有代码、前端、文档、配置与构建产物的版本管理。

## 版本格式

产品版本采用语义化版本格式，并使用本体产品族前缀 `ontology-`：

```text
ontology-vMAJOR.MINOR.PATCH
```

- `ontology-` 是产品族前缀：同一个本体产品线的应用、服务与镜像共用这一前缀；
- 目前处于 `ontology-v0.x` 快速迭代阶段，当前正式版本保持为：

```text
ontology-v0.1.14
```

### 与包管理清单的关系（两处强制例外）

`ontology-vX.Y.Z` 是**显示与发布名**，不能写进要求严格版本格式的包管理清单：

| 清单 | 约束 | 实际写入 |
| --- | --- | --- |
| `pyproject.toml` `[project] version` | 必须是合法 PEP 440 | `0.1.14` |
| `frontend/package.json` / `package-lock.json` `version` | 必须是合法 semver | `0.1.14` |

`scripts/run_analytics_eval.py` 的 `product_version()` 读取 `pyproject.toml` 后补
`ontology-v` 前缀，对外统一返回显示名；同文件 `_version_reached()` 会剥离
`ontology-v` / `v` 前缀后再比较 `X.Y.Z`，因此 tag、Release、报告与门禁口径一致。

### 版本族切换记录（v0.1.x → ontology-v0.0.x）

2026-09-29 按用户要求把历史版本族整体切换并重建（tag 仍指向原定版 commit）：

| 原版本 | 现版本 |
| --- | --- |
| `v0.1.0` … `v0.1.9` | `ontology-v0.0.1` … `ontology-v0.0.10` |

切换规则、映射表与一次性授权见 `docs/specs/ontology-version-rename-and-rebuild.md`。

### 版本推进记录（ontology-v0.0.10 → ontology-v0.1.0）

2026-09-29 用户明确指定把当前收口定为 **MINOR** `ontology-v0.1.0`（新增会话回收站、
X360 流程定义集成、本体/MAL 与元数据契约迁移等用户可感知能力，且向下兼容），并同时授权
从发布主线拉出 `release/ontology-v0.1.0` 分支：

- 授权范围包含版本号与 release 分支；tag 与 GitLab Release 随后在同日由用户单独授权
  （`ontology-v0.1.0`），tag 在收口 Merge Request 合入后在 `master` 的定版 commit 上创建；
- 已执行（2026-09-29）：收口 MR `!17` 合入 `master` 得到定版 commit `74fca80`；annotated tag
  `ontology-v0.1.0` 指向 `74fca80` 并推送 GitLab；同 tag 的 GitLab Release 已创建（只新建，
  未覆盖任何已有 Release）；
- 未授权、未执行部署：tag、Release、release 分支都不改变服务器上运行的服务；
- `master` 仍是唯一发布主线，`feature/branch-model-and-v0.1.0-cut` → `master` 按临时分支
  Merge Request 流程评审合并；`20260727` 已归档，不再作为交付分支。

### 版本推进记录（ontology-v0.1.0 → ontology-v0.1.1）

`ontology-v0.1.1` 是 `ontology-v0.1.0` 之后的第一个 PATCH，内容是分析逻辑剥离包
`ontology-analytics-skill`：把确定性路由 → L1–L5 分档 SOP → 交付前五道闸门的整套分析逻辑剥离为
自包含交付目录，并接入真实工具运行时（17 个真实工具、凭据外置）。对仓库现有代码是纯新增，因此
定级 PATCH。

- 内容于 2026-10-08 经 Merge Request 合入 `master`，定版 commit `c82221f`；
- 当时未创建版本文档、tag 与 Release；2026-10-15 用户明确要求补建（“肯定要补啊”），随后执行：
  新增 `docs/versions/ontology-v0.1.1.md`，annotated tag `ontology-v0.1.1` 指向原定版 commit
  `c82221f` 并推送 GitLab，同 tag 的 GitLab Release 已创建（只新建，未覆盖、未移动任何已有 tag
  或 Release）；
- 补建只增加版本记录，不改变任何 commit、不拉 release 分支、不部署；
- 命名注意：2026-09-02 曾有一个名字就是 `v0.1.1` 的旧 tag（commit `28bb1d6`），它在 2026-09-29
  的版本族切换中改名为 `ontology-v0.0.2`；`ontology-v0.1.1` 与该旧 tag 无关。

### 版本推进记录（ontology-v0.1.1 → ontology-v0.1.2）

2026-10-15 用户明确指定把当前交付收口为 **PATCH** `ontology-v0.1.2`：

- 本版本在 `ontology-v0.1.1` 的剥离包之上补齐 Fuxi 技能展示字段与 `CanvasGenerate` 整页 HTML
  交付，并加入多步分析中文过程播报、`20260727` 归档与交付口径改为「临时分支 → `master`」、
  取数证据与双环境对比归档；
- 收口通过 `feature/progress-narration-zh` → `master` 的 Merge Request `!23`（reviewer
  `tianzijing`）评审合并，合入后的 `master` merge commit `3c4de1e` 为定版 commit；
- 用户随后单独授权创建 tag 与 GitLab Release，已执行：annotated tag `ontology-v0.1.2` 指向
  `3c4de1e` 并推送 GitLab，同 tag 的 GitLab Release 已创建（只新建，未覆盖任何已有 Release）；
- 用户明确指示**不拉出** `release/ontology-v0.1.2` 分支；部署未授权、未执行。

### 版本推进记录（ontology-v0.1.2 → ontology-v0.1.3）

2026-10-20 用户明确指定把当前交付收口为 **PATCH** `ontology-v0.1.3`：

- 本版本把 Fuxi / 通用 Agent 的接入方式从本机 stdio 运行时切换为主服务内置的远程 MCP：
  `/api/mcp` 暴露 16 个受控真实工具，连接方不再携带本体平台凭据、Doris 凭据或输出目录配置；
- 同步完成 `CanvasGenerate` Artifact URL 交付、demo2 代理绕过与本体语义检索快路径修复，并把
  前端、Python 包、FastAPI、README、版本文档与契约测试统一到 `ontology-v0.1.3`；
- 交付方式为 `feature/mcp-server-policy` → `master` 的 Merge Request `!24`（reviewer
  `tianzijing`），合入后的 `master` merge commit `a805a66` 为定版 commit；
- 用户随后单独授权创建 tag 与 GitLab Release，已执行：annotated tag `ontology-v0.1.3` 指向
  `a805a66` 并推送 GitLab，同 tag 的 GitLab Release 已创建（只新建，未覆盖任何已有 Release）；
- 部署继续保持独立授权；本次版本收口不自动部署，也不拉 `release/ontology-v0.1.3` 分支。

### 版本推进记录（ontology-v0.1.3 → ontology-v0.1.4）

2026-10-23 用户明确指定把当前交付预收口为 **PATCH** `ontology-v0.1.4`：

- 本版本把 V3 经营驾驶舱从原型验证推进到独立的交付看板 POC：三个页面路由、交付 ProUI
  元数据、三节点穿透式分析、真实模型分析插槽、交付快照回放和对齐 mock 结构的风险卡片；
- 收口范围限定为 `feature/cockpit-v3-poc` 分支上的驾驶舱交付；同期其它并行修改不纳入本版本，
  也不写入版本说明或 MR 描述；
- 交付方式为 `feature/cockpit-v3-poc` → `master` 的 Merge Request（reviewer `tianzijing`）；
  MR 只负责评审与合并，不自动创建 tag 或 GitLab Release；
- 2026-10-27 用户明确授权补发 tag 与 GitLab Release；annotated tag `ontology-v0.1.4` 指向
  加载性能优化前的定版 commit `3287c91` 并推送 GitLab，同名 GitLab Release 已创建；
- 本次补发不部署，也不拉 `release/ontology-v0.1.4` 分支；加载优化另行收口为 `ontology-v0.1.5`。

### 版本推进记录（ontology-v0.1.4 → ontology-v0.1.5）

2026-10-27 用户明确指定把本次驾驶舱加载优化收口为 **PATCH** `ontology-v0.1.5`：

- 本版本在 `ontology-v0.1.4` 驾驶舱能力之上，新增整页完整版本缓存与后台更新、AP 短时复用与
  `individual` 拆批、生产版 Vue、gzip 与内容哈希静态发布、AI 插槽按页加载和初始化并行化；
- `ontology-v0.1.4` 保持为加载优化前的定版，annotated tag 指向 `3287c91`；`ontology-v0.1.5`
  的 tag 与 GitLab Release 在版本收口提交上创建；
- 本次不部署，也不拉 `release/ontology-v0.1.5` 分支。

## PATCH / MINOR / MAJOR 判定

### PATCH：补丁版本

示例：`ontology-v0.0.1 → ontology-v0.0.2`、`ontology-v0.0.2 → ontology-v0.0.3`

适用于：

- Bug 修复；
- 稳定性修复；
- 性能优化；
- UI 小调整；
- 文案修正；
- 不改变主要能力边界的小型改进；
- 向后兼容的内部实现调整；
- 安全补丁；
- 模型模版优化：新增一个元素的组成部分；
- 不影响功能行为的其他改动。

### MINOR：次版本

示例：`ontology-v0.0.x → ontology-v0.1.0`、`ontology-v0.1.x → ontology-v0.2.0`

适用于：

- 新增一组用户可感知的完整能力；
- 新增重要业务流程；
- 新增主要页面、模块或交互模式；
- 明显扩展产品能力边界；
- 功能增强，并且保持向下兼容；
- 存在需要用户关注的兼容变化；
- 模型模版升级：新增一个元素。

升级 MINOR 后 PATCH 必须归零。

### MAJOR：主版本

适用于：

- 不兼容的重大功能调整；
- 架构重构；
- 核心业务逻辑变更；
- API 不向下兼容；
- 模型模版升级且不兼容。

当前 `v0.x` 阶段通常不使用 `v1.0.0` 以上规则。`v1.0.0` 只用于产品达到正式稳定
阶段，并且必须由用户明确决定，不能由 Agent 自动升级。

## 发布节奏规则

1. 每次 commit 不等于发布新版本。
2. 每次 push 不等于发布新版本。
3. 每次部署也不必然升级正式版本。
4. 版本号与 changelog 是否按日记录无关：工程变更统一按周维护，不逐日升级版本。
5. 只有确实形成可交付版本时才增加 PATCH，不要为了日期机械升级。
6. 每周可以发布 MINOR，但不能机械地每周升级。
7. 一周内只有修复和小优化时，应继续使用 PATCH，例如 `v0.2.0 → v0.2.1 →
   v0.2.2`。
8. 只有一周形成完整的新功能集合或明显能力升级时，才发布新的 MINOR，例如
   `ontology-v0.0.9 → ontology-v0.1.0`。
9. 纯文档修改、规则文字整理、测试补充、代码格式化，通常不单独发布正式产品版本。
10. 版本号由变更性质决定，不由日期、commit 数量或部署次数决定。

## 不同记录的职责

| 记录 | 路径/格式 | 职责 |
| --- | --- | --- |
| Git commit | 普通 commit | 记录每次工程修改，可以一天多个 commit |
| 周 changelog | `changelog/changelog_M_D-D.md`（如 `changelog_9_7_11.md`） | 只按周维护（2026-09-08 起），不创建日报文件，记录当周已经完成的最终工程变化，不等同于正式版本发布 |
| 正式版本文档 | `docs/versions/ontology-vX.Y.Z.md` | 只在正式发布新版本时创建，记录该版本最终用户可见能力、兼容变化、验证结论和升级说明 |
| Git tag | `ontology-vX.Y.Z` | 只在用户明确要求创建正式版本并明确允许创建 tag 时执行 |
| GitLab Release | GitLab Release | 只有用户在当前任务中明确要求时才创建，不能因为存在版本文档或 tag 自动创建 |
| 部署 | — | 与版本号相互独立，只有用户在当前任务中明确授权具体部署目标时才能部署 |

## 正式版本发布条件

Agent 不得自行判断并升级正式版本。只有用户明确说出类似以下指令时，才能改变正式
版本：

- “发布 ontology-v0.0.11”
- “版本升级到 ontology-v0.1.0”
- “创建 ontology-v0.0.11 正式版本”
- “给这次发布打 ontology-v0.0.11 tag”

以下指令不构成版本升级授权：

- “修复”“修改”“完成”“提交”“push”“验收”“部署”“发布到服务器”
- “今天的修改做完”“总结 changelog”

用户只要求部署但没有指定版本号时：

- 部署当前已经确定的版本；
- 不自动增加 PATCH；
- 不自动创建版本文档；
- 不自动创建 tag；
- 不自动创建 GitLab Release。

## 正式版本发布工作流

1. 用户明确指定目标版本。
2. 检查目标版本是否符合语义化版本规则。
3. 根据 Git diff、当周 changelog 和最终代码确认变更性质。
4. 同步所有产品版本入口：
   - `pyproject.toml`
   - `bi_agent/__init__.py`
   - FastAPI version
   - `frontend/package.json`
   - `frontend/package-lock.json`
   - 前端 UI 显示版本（`frontend/src/main.jsx` 的 `PRODUCT_VERSION`）
5. 创建 `docs/versions/ontology-vX.Y.Z.md`。
6. 更新 `docs/versions/README.md`。
7. 更新根 `README.md` 当前版本链接。
8. 更新当周 changelog（若当周文件尚未创建，则按本周 git 记录补齐）。
9. 运行完整测试、前端 build 和 `git diff --check`。
10. 创建普通 commit。
11. GitLab 推送：把当前临时分支（`feature/*`、`bugfix/*`、`hotfix/*`）推送到 GitLab 同名分支。
12. 验证 `HEAD == gitlab/<branch>`（远端同名分支 hash 与本地一致）。
13. 只有用户明确授权 tag 时才创建并推送 tag。
14. 只有用户明确授权 GitLab Release 时才创建 Release。
15. 只有用户明确授权部署时才执行部署。

授权彼此独立：

- 指定版本号不等于授权 tag；
- 授权 tag 不等于授权 GitLab Release；
- 授权 Release 不等于授权部署；
- 授权部署不等于授权升级版本。

## GitLab 统一推送规则

- 分支模型、PR 合并流程与 release / hotfix 机制见 [Git 分支与合并工作流规范](../git-branch-workflow.md)。
- `master` 是唯一发布主线；`main` 已退役并删除，不得重新创建、不得 push、不得作为
  Merge Request 的 source/target。
- eimosp-ontology-agentic-analytics 推送到 GitLab 仓库 `ai-team/eimosp-ontology-agentic-analytics` 上与
  本地同名的临时分支（`feature/*`、`bugfix/*`、`hotfix/*`）；归档分支 `gitlab/20260727`
  只保留历史，停止接收新提交。
- 普通 commit 只推送当前临时分支；
- 正式交付 MR 的 source 为当前临时分支，`target_branch=master`；`hotfix/*` 需要两条
  MR（先 `release/*`，再 `master`），由 `tianzijing` code review 后单独发起
  （reviewer `tianzijing`，assignee `zhangzhen`）；任何 Agent 或脚本不得直接
  push 到 `master`，也不得自动合并；
- 正式版本 tag 需要用户单独授权，且必须推送到 GitLab；
- push 不等于部署。

## GitLab Release 规则

- GitLab Release 在统一协作仓库 `ai-team/eimosp-ontology-agentic-analytics`（GitLab）上创建，日常开发 push
  走当前临时分支（`feature/*`、`bugfix/*`、`hotfix/*`）。
- 只有用户在当前任务中明确授权创建 GitLab Release 时才能执行。
- 用户明确授权某个正式版本创建 Release 后，在 `ai-team/eimosp-ontology-agentic-analytics` 上基于同名 tag
  创建一个 Release，tag 指向定版 commit。
- Release 必须与 tag 使用相同的版本号、名称和正式版本说明。
- 幂等：创建前先检查 Release 是否已存在；已存在且内容正确的 Release 保留，不重复
  创建；已存在 Release 的 tag、名称或目标 commit 不正确时，不得自动删除、覆盖或
  重建，遇到冲突必须停止并报告。
- GitLab Release 与其他动作相互独立：指定版本号不等于授权 tag；授权 tag 不等于授权
  GitLab Release；授权 GitLab Release 不等于授权部署；创建 Release 不自动触发部署；
  部署也不自动创建 Release。
- GitLab Release 使用本地 GitLab CLI/API 执行，不在服务器上执行；不允许为了创建
  Release 登录或修改部署服务器。

## 回滚与历史保护

1. 已发布版本文档不得覆盖或重写。
2. 已存在的版本号不得重复用于不同代码。
3. 不得删除历史版本文档。
4. 不得强制移动已经发布的 tag。
5. 发现版本号错误时：停止自动处理；报告当前版本、目标版本和冲突；等待用户决定。
6. 回滚部署默认不降低或修改仓库版本号。
7. 回滚到旧 release 不等于重新发布旧版本。
8. 禁止 force push、强制修改 tag 或改写远端历史；`v0.1.x` → `ontology-v0.0.x` 的
   版本族切换是本仓库唯一一次经用户逐项授权、且不改变 tag 指向的重建，不构成后续先例。
9. 版本操作不得删除、迁移或覆盖历史会话和用户数据。

## 示例

- 本周只做了 Bug 修复与文案修正：保持当前版本或发布 `ontology-v0.0.11`（由用户决定）。
- 本周新增“报表模式”完整能力：用户明确授权后发布 `ontology-v0.1.0`，PATCH 归零。
- 纯文档与测试补充：不发布正式版本，只 commit + GitLab 统一推送。

## 2026-11-03 历史阶段补发

用户明确指定补发 ontology-v0.1.6 至 ontology-v0.1.10，逐一创建 annotated tag 和同名 GitLab Release；对应提交依次为 3b1bc1e、4c63e4d、8f673fc、c5ce139、179a0cf。原有 tag、历史文档及历史提交不改写，不另行部署。当前源码版本标识由独立收口分支推进至 0.1.10。
