# `master` 唯一主线迁移 Spec（历史记录 · 已完成）

> 状态：本次迁移已完成；`20260727` 随后也已归档、不再接收新提交。
> 文中提到的“迭代分支 → 20260727 → MR → master”是迁移当时的口径，
> 现行为“临时分支（`feature/*`、`bugfix/*`、`hotfix/*`）→ 同名远端分支 →
> MR → master”，见 `docs/specs/master-mainline-delivery.md` 与
> `docs/gitlab-push-workflow.md`。

## 1. 目标

将分析 Agent 的唯一协作与发布主线从 `main` 迁移到 `master`，与 DevOps 平台“从 `master` 创建迭代分支并构建”的约定对齐：

```text
迭代分支 → 20260727 → Merge Request → master → DevOps 构建
```

`main` 仅作为历史保留分支，不再接收新功能 Merge Request。不得维持两个可独立演进的发布主线。

## 2. 不可破坏约束

- 不删除、重建、reset 或 force push `master`；
- 不删除或改写 `main` 历史；
- 必须保留 `master` 上 Administrator 的提交 `a7ebafaa0097655fdc2d8595e367f0b4adaca47d`；
- `Dockerfile` 必须继续使用 `swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim`；
- 普通开发提交仍只 push 到 `gitlab/20260727`；
- push 脚本不得直接 push `master` 或历史分支 `main`；
- MR 必须由 `20260727` 指向 `master`，reviewer 为 `tianzijing`（id 166），assignee 为 `zhangzhen`（id 245）；
- 不自动合并 MR，不因 push、MR 或切换默认分支而主动部署；
- 不创建 tag、Release，不修改正式版本号；
- 不操作部署服务器和历史会话数据。

## 3. 仓库口径

以下当前有效规则必须统一，不得残留“`main` 是发布分支”或“MR 指向 `main`”的零散口径：

- `AGENTS.md`：`master` 是唯一发布主线；`main` 是历史保留分支；
- `docs/gitlab-push-workflow.md`：日常 push 仍到 `20260727`，MR 为 `20260727 → master`；
- `docs/versions/versioning-policy.md`：发布分支为 `master`；
- `DEPLOYMENT.md`：项目清单标注开发分支 `20260727`、唯一发布主线 `master`，DevOps 从 `master` 构建；
- `scripts/push_gitlab.py`：开发 push 目标不变，但提示、受保护发布分支和拒绝信息统一为 `master`；同时拒绝误推历史 `main`；
- `tests/test_push_gitlab.py`：验证 `master` 和 `main` 均不能由开发 push 脚本直接推送。

历史 changelog、已归档版本说明中对当时事实的记载不做机械替换。

## 4. GitLab 配置终态

- 项目默认分支：`master`；
- `master`：保护规则至少与迁移前 `main` 等价，禁止普通直接 push 和 force push，通过 MR 合入；
- `main`：保留且继续保护，防止误推，不再作为新 MR 目标；
- 现有活动开发 MR 若目标为 `main`，确认无冲突后改向 `master`；历史已关闭/已合并 MR 不修改；
- CI、Webhook、Schedule、Trigger、外部集成逐项核对；发现切换会直接触发部署时，停止并报告，不得在本任务中部署。

GitLab 外部状态变更必须在仓库规则通过 review 并进入 `master` 后执行。若需要人工 review/merge，则任务停在等待状态，不得把“已创建 MR”报告成迁移完成。

## 5. 历史同步

迁移前验证 `main`、`master`、`20260727` 的 hash、merge-base、双向提交差异和 Dockerfile。只允许普通 merge/MR：

- 若 `main` 已是 `master` 祖先，不创建无意义同步提交；
- 若 `main` 有 `master` 未包含的提交，创建 `main → master` 同步 MR，等待 review；
- 若发生 Dockerfile 冲突，必须保留华为云镜像；
- 任何步骤若需要强推、丢弃 `a7ebafa` 或改写历史，立即停止。

## 6. TDD 验收

运行：

```bash
.venv/bin/python -m unittest tests.test_master_mainline_policy tests.test_push_gitlab
git diff --check
```

必须满足：

1. 仓库当前规则只有 `master` 一个发布主线；
2. `20260727` push 行为不变；
3. push 脚本拒绝 `master`、`main` 和其他非开发目标；
4. 华为云镜像契约有自动化保护；
5. 文档明确 MR、reviewer、assignee、保护和不自动部署约束；
6. 原有相关回归继续通过。
