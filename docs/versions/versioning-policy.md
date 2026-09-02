# eimosp-ontology-agentic-analytics 语义化版本与正式发布规范

本文件是 eimosp-ontology-agentic-analytics 版本管理的唯一完整规范。`AGENTS.md`、`README.md`、
`docs/versions/README.md`、`docs/gitlab-push-workflow.md` 只保留必要摘要并
链接到本文件。

## 目标与适用范围

- 统一产品版本号含义，避免按日期、commit 数量或部署次数机械升级；
- 明确 Git commit、每日 changelog、正式版本文档、Git tag、GitLab Release 与部署
  之间的边界；
- 适用于 eimosp-ontology-agentic-analytics 仓库内所有代码、前端、文档、配置与构建产物的版本管理。

## 版本格式

产品版本采用语义化版本格式：

```text
vMAJOR.MINOR.PATCH
```

当前项目仍处于 `v0.x` 快速迭代阶段，当前正式版本保持为：

```text
v0.1.1
```

## PATCH / MINOR / MAJOR 判定

### PATCH：补丁版本

示例：`v0.1.0 → v0.1.1`、`v0.1.1 → v0.1.2`

适用于：

- Bug 修复；
- 稳定性修复；
- 性能优化；
- UI 小调整；
- 文案修正；
- 不改变主要能力边界的小型改进；
- 向后兼容的内部实现调整。

### MINOR：次版本

示例：`v0.1.x → v0.2.0`、`v0.2.x → v0.3.0`

适用于：

- 新增一组用户可感知的完整能力；
- 新增重要业务流程；
- 新增主要页面、模块或交互模式；
- 明显扩展产品能力边界；
- 存在需要用户关注的兼容变化。

升级 MINOR 后 PATCH 必须归零。

### MAJOR：主版本

当前 `v0.x` 阶段通常不使用 `v1.0.0` 以上规则。`v1.0.0` 只用于产品达到正式稳定
阶段，并且必须由用户明确决定，不能由 Agent 自动升级。

## 发布节奏规则

1. 每次 commit 不等于发布新版本。
2. 每次 push 不等于发布新版本。
3. 每次部署也不必然升级正式版本。
4. 每日可以发布一个 PATCH 版本，例如周一 `v0.1.1`、周二 `v0.1.2`。
5. 只有当天确实形成可交付版本时才增加 PATCH，不要为了日期机械升级。
6. 每周可以发布 MINOR，但不能机械地每周升级。
7. 一周内只有修复和小优化时，应继续使用 PATCH，例如 `v0.2.0 → v0.2.1 →
   v0.2.2`。
8. 只有一周形成完整的新功能集合或明显能力升级时，才发布新的 MINOR，例如
   `v0.1.4 → v0.2.0`。
9. 纯文档修改、规则文字整理、测试补充、代码格式化，通常不单独发布正式产品版本。
10. 版本号由变更性质决定，不由日期、commit 数量或部署次数决定。

## 不同记录的职责

| 记录 | 路径/格式 | 职责 |
| --- | --- | --- |
| Git commit | 普通 commit | 记录每次工程修改，可以一天多个 commit |
| 每日 changelog | `changelog/changelog_M_D.md` | 记录当天已经完成的最终工程变化，不等同于正式版本发布 |
| 正式版本文档 | `docs/versions/vX.Y.Z.md` | 只在正式发布新版本时创建，记录该版本最终用户可见能力、兼容变化、验证结论和升级说明 |
| Git tag | `vX.Y.Z` | 只在用户明确要求创建正式版本并明确允许创建 tag 时执行 |
| GitLab Release | GitLab Release | 只有用户在当前任务中明确要求时才创建，不能因为存在版本文档或 tag 自动创建 |
| 部署 | — | 与版本号相互独立，只有用户在当前任务中明确授权具体部署目标时才能部署 |

## 正式版本发布条件

Agent 不得自行判断并升级正式版本。只有用户明确说出类似以下指令时，才能改变正式
版本：

- “发布 v0.1.1”
- “版本升级到 v0.2.0”
- “创建 v0.1.2 正式版本”
- “给这次发布打 v0.1.3 tag”

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
3. 根据 Git diff、每日 changelog 和最终代码确认变更性质。
4. 同步所有产品版本入口：
   - `pyproject.toml`
   - `bi_agent/__init__.py`
   - FastAPI version
   - `frontend/package.json`
   - `frontend/package-lock.json`
   - 前端 UI 显示版本（`frontend/src/main.jsx` 的 `PRODUCT_VERSION`）
5. 创建 `docs/versions/vX.Y.Z.md`。
6. 更新 `docs/versions/README.md`。
7. 更新根 `README.md` 当前版本链接。
8. 更新当天已启用的日 changelog。
9. 运行完整测试、前端 build 和 `git diff --check`。
10. 创建普通 commit。
11. GitLab 统一推送：`gitlab/20260727`。
12. 验证 `HEAD == gitlab/20260727`。
13. 只有用户明确授权 tag 时才创建并推送 tag。
14. 只有用户明确授权 GitLab Release 时才创建 Release。
15. 只有用户明确授权部署时才执行部署。

授权彼此独立：

- 指定版本号不等于授权 tag；
- 授权 tag 不等于授权 GitLab Release；
- 授权 Release 不等于授权部署；
- 授权部署不等于授权升级版本。

## GitLab 统一推送规则

- eimosp-ontology-agentic-analytics 统一推送到 GitLab 仓库 `ai-team/eimosp-ontology-agentic-analytics` 的 `20260727` 分支
  （`gitlab/20260727`）。
- 普通 commit 只推送统一开发分支：`gitlab/20260727`；
- merge 到 `main` 需要 `tianzijing` code review 后单独发起 Merge Request，任何
  Agent 或脚本不得直接 push 到 `main`，也不得自动合并；
- 正式版本 tag 需要用户单独授权，且必须推送到 GitLab；
- push 不等于部署。

## GitLab Release 规则

- GitLab Release 在统一协作仓库 `ai-team/eimosp-ontology-agentic-analytics`（GitLab）上创建，日常开发 push
  仍只走 `gitlab/20260727`。
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
8. 禁止 force push、强制修改 tag 或改写远端历史。
9. 版本操作不得删除、迁移或覆盖历史会话和用户数据。

## 示例

- 本周只做了 Bug 修复与文案修正：保持 `v0.1.0` 或发布 `v0.1.1`（由用户决定）。
- 本周新增“报表模式”完整能力：用户明确授权后发布 `v0.2.0`，PATCH 归零。
- 纯文档与测试补充：不发布正式版本，只 commit + GitLab 统一推送。
