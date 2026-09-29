# Git 分支与合并工作流规范

> 本文件是 eimosp-ontology-agentic-analytics 分支模型、PR（Pull Request / Merge Request）
> 合并流程与 release / hotfix 机制的唯一定义。版本号组成、MAJOR / MINOR / PATCH 判定与发布
> 授权规则见 [语义化版本与正式发布规范](./versions/versioning-policy.md)；推送与合并的硬约束
> 见仓库根 `AGENTS.md`，两者冲突时以 `AGENTS.md` 为准。

## 目标与适用范围

- 统一长期分支与临时分支的职责，让"日常开发"和"发布"两条节奏互不阻塞；
- 把合并动作显性化为 PR，任何分支回流长期分支都必须经过评审；
- 明确 release 分支的拉出时机与 hotfix 的双向合并路径，避免修复在某一侧丢失；
- 适用于本仓库内所有代码、前端、文档、配置与构建产物的分支管理与合并。

## 分支模型

### 长期分支（主分支）

| 分支 | 前缀 | 职责 | 管理者 | 来源 |
| --- | --- | --- | --- | --- |
| `master` | 无 | 归档全部功能的唯一发布主线 | 项目 Owner | — |
| `release/*` | `release/` | 每个版本一条，承载该版本的定版与测试 | 测试负责人 | 从 `master` 拉出 |

- `master` 拥有全部功能的提交，作为**归档分支**；
- `master` 不允许直接提交代码，只允许在合并时解决冲突；
- `release/*` 每个版本一条，命名 `release/ontology-vX.Y.Z`（例如 `release/ontology-v0.1.0`）；
  早期草稿里出现的 `release-v1.2.0`、`R4.1.0` 是同一含义的非规范写法，统一以
  `release/ontology-vX.Y.Z` 为准。

### 临时分支（开发分支）

| 分支 | 前缀 | 用途 | 来源 | 合并去向 |
| --- | --- | --- | --- | --- |
| `feature/*` | `feature/` | 日常需求开发 | 从 `master` 拉出 | `master` |
| `bugfix/*` | `bugfix/` | 日常缺陷修复 | 从 `master` 拉出 | `master` |
| `hotfix/*` | `hotfix/` | 紧急线上缺陷修复 | 从 `release/*` 拉出 | `release/*` 与 `master`（双向） |

## 标准工作流

### 1. 合并一律走 PR

所有临时分支回流长期分支，都必须通过 Pull Request（本仓库使用 GitLab Merge Request）
完成，不允许把临时分支直接推进长期分支：

- `feature/*` → `master`：提 PR；
- `bugfix/*` → `master`：提 PR；
- `hotfix/*` → `release/*`：提 PR；
- `hotfix/*` → `master`：再提一个 PR。

评审通过后才合并；`master` 与 `release/*` 上不应出现未经 PR 的直推提交。

### 2. release 分支的拉出时机

- `release/*` 从 `master` 的**稳定节点**拉出，而不是持续跟随 `master` 的每一次提交；
- 触发时机是"阶段性功能开发完成"（例如一个自然季度收口，或用户明确指定某个版本号）；
- 拉出后该 `release/*` 只接收本版本的 `hotfix/*` 合并；日常的 `feature/*`、`bugfix/*`
  继续进入 `master`，不进入已经拉出的 `release/*`；
- 下一个版本出现时，从 `master` 新的稳定节点再拉一条 `release/*`。

### 3. 日常开发与发布并行（master 作为归档）

- 已拉出的 `release/*` 与 `master` **平行存在**；
- 日常节奏：`feature/*` 与 `bugfix/*` 交替从 `master` 拉出，再提 PR 合回 `master`，
  `master` 因此持续累积并归档全部功能；
- 发布节奏：`release/*` 独立承载版本的定版与测试，只由 `hotfix/*` 更新，不被日常需求打断；
- 两条节奏并行推进，互不等待，也不需要冻结 `master`。

### 4. hotfix 的双向合并（双 PR）

线上紧急缺陷按以下路径处理，**两次 PR 缺一不可**：

1. 从 `release/*` 拉出 `hotfix/*`；
2. 在 `hotfix/*` 上完成修复；
3. 先向 `release/*` 提 PR 并合并，保证当前版本带上修复；
4. **再向 `master` 提 PR 并合并**，保证修复进入归档主干，不被下一个版本冲掉。

只合 `release/*`，修复会在下一个版本丢失；只合 `master`，当前版本会继续带缺陷。

### 5. 命名约定

- 分支名以**前缀**为准：`feature/`、`bugfix/`、`hotfix/`、`release/`；
- 示意图里的 `feature-1`、`bugfix-1`、`hotfix-1` 是简化写法，实际使用前缀形式，例如
  `feature/ontology-filter`、`bugfix/pg-reltuples-unknown`、`hotfix/v1.2.1-pk-recover`；
- 分支与其合并去向一一对应：`hotfix/*` 一定同时指向 `release/*` 和 `master`。

## 与当前仓库既有约定的关系

- 现阶段日常开发仍统一推送 `gitlab/20260727`（统一协作开发分支），由它按 `20260727` →
  `master` 的 Merge Request 合入 `master`；`master` 是唯一发布主线，merge 到 `master`
  必须由 `tianzijing` code review 后单独发起 MR；
- 本章描述的分支模型是本仓库的长期目标模型：`feature/*`、`bugfix/*`、`hotfix/*` 按需从
  `master` / `release/*` 拉出，最终仍以 MR 回流；
- 无论使用哪种分支，合并回长期分支的动作都必须经过 PR / MR，不得直接推送。

## 版本号与分支的关系

- `release/*` 的名称与该版本号一致，例如 `release/ontology-v0.1.0` 对应正式版本
  `ontology-v0.1.0`；
- 版本号组成、MAJOR / MINOR / PATCH 判定与升级授权以
  [语义化版本与正式发布规范](./versions/versioning-policy.md) 为准；
- 节奏建议（**人工建议，不自动触发**）：每个自然季度可由用户决定是否收口一个 MINOR；
  Agent 不按日期机械升级版本，不自动升级版本，也不会因为拉分支、提 PR 或部署而升级版本；
- 早期讨论稿曾提出"修订号不维护、归并入次版本号"；本仓库当前**未采纳**该口径，仍按既有
  规范正常使用 PATCH。是否调整由用户决定。

## 版本号判定摘要

| 位 | 触发条件 |
| --- | --- |
| MAJOR | 不兼容的重大功能调整；架构重构；核心业务逻辑变更；API 不向下兼容；模型模版升级且不兼容 |
| MINOR | 新增功能；功能增强且向下兼容；模型模版升级并新增一个元素 |
| PATCH | Bug 修复；安全补丁；不影响功能行为的改动；模型模版优化并新增一个元素的组成部分 |

判定细则、升级授权与发布节奏以 [语义化版本与正式发布规范](./versions/versioning-policy.md) 为准。

## 禁止事项

- 禁止直接向 `master` 提交代码或直接推送 `master`；
- 禁止跳过 PR，直接把临时分支合并回长期分支；
- 禁止 `git push --force`、`--force-with-lease` 及任何改写远端历史的推送；
- 禁止在没有用户明确授权时升级版本号、创建 tag、创建 GitLab Release 或执行部署。

## 相关文档

- [语义化版本与正式发布规范](./versions/versioning-policy.md)
- [GitLab 统一推送工作流](./gitlab-push-workflow.md)
- [图 13 · Git 分支模型](./diagrams/13-git-branch-model.md)
