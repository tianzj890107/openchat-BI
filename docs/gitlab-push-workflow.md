# GitLab 推送与合并工作流

## 远端映射

| Remote | Repository | Target branch | Purpose |
| --- | --- | --- | --- |
| gitlab | ai-team/eimosp-ontology-agentic-analytics | 与本地同名的临时分支 | `feature/*`、`bugfix/*`、`hotfix/*` 日常开发 |
| gitlab | ai-team/eimosp-ontology-agentic-analytics | 20260727 | 已归档的统一协作开发分支，停止接收新提交 |

`master` 是唯一发布主线，只通过 Merge Request 合并。MR 映射为 `source_branch=<当前临时分支>`
→ `target_branch=master`（`feature/*`、`bugfix/*`）；`hotfix/*` 需要两条 MR：先
`source_branch=hotfix/*` → `target_branch=release/*`，再 `source_branch=hotfix/*`
→ `target_branch=master`。合并前必须由 `tianzijing` code review，assignee 固定为
`zhangzhen`，任何 Agent 或脚本都不得直接 push 到 `master`。`main` 已退役并删除，
不得重新创建、不得 push、不得作为 Merge Request 的 source/target。分支模型见 [Git 分支与合并工作流规范](./git-branch-workflow.md)。

## 完成标准

```
HEAD == gitlab/<branch>
```

即远端同名分支的 hash 与本地 `HEAD` 一致。

## 日常流程

1. 从 `master` 拉出 `feature/<topic>` 或 `bugfix/<topic>`（紧急线上缺陷从 `release/*`
   拉 `hotfix/<topic>`）
2. 修改
3. 测试
4. `git diff --check`
5. `git commit`
6. `git push gitlab <branch>`（新建或快进同名远端分支）
7. 验证 gitlab 远端同名分支 hash 与本地 HEAD 一致
8. 提 MR：`<branch>` → `master`（reviewer `tianzijing`、assignee `zhangzhen`）
9. 没有部署授权时结束（push 不等于部署）

归档分支 `20260727` 不再接收新提交；如需核对该分支的远端一致性，仍可用
`python scripts/push_gitlab.py --check`，但新分支不经过该脚本。

## 首次设置

```bash
git remote add gitlab git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git
git config user.name "zhenzhan0408"
git config user.email "zhenzhan@kth.se"
```

## 安全规则

- 推送目标是本地当前工作分支在 GitLab 上的同名分支（`feature/*`、`bugfix/*`、
  `hotfix/*`）；不得把临时分支直接推进 `master`；
- 禁止 force push（含 `--force-with-lease`）；
- 不自动 merge 或 rebase；
- 不自动推 tag；
- push 不代表部署；没有当前任务明确部署授权时，push 后任务结束；
- 正式交付 MR 的 target 为 `master`，需要 `tianzijing` code review 后单独发起；
  本流程不执行 master 合并，也不执行 main 合并；`main` 已退役并删除，不存在 main
  合并流程；
- 推送失败处理：报告失败，保留已有 push，修复权限或网络后以相同 HEAD 重试，不生成
  补偿 commit、不 force push、不回滚；
- 远端出现本地没有的独有提交：停止处理并报告，不覆盖。

## 正式版本

- 普通 commit 只推当前临时分支（`feature/*`、`bugfix/*`、`hotfix/*`），不自动推 tag；
- 正式版本 tag（`ontology-vX.Y.Z`）需要用户在当前任务中单独授权，且必须推送到 GitLab；
- 版本号变更必须遵循 [语义化版本与正式发布规范](./versions/versioning-policy.md)；
  只有用户明确指定目标版本时才能升级正式版本；
- push 不等于部署；GitLab Release 是否创建由用户在当前任务中明确要求；不要把真实
  访问 token、SSH 私钥或凭据写入文档。

## GitLab Release

正式版本完成标准扩展为：

1. 分支推送一致：远端同名分支的 hash 与本地 `HEAD` 一致（`HEAD == gitlab/<branch>`）；
2. tag 推送一致：`ontology-vX.Y.Z` 存在于 GitLab，且指向本地定版 commit；
3. 用户授权 Release 时，GitLab 仓库存在对应的正式 Release。

规则：

- 用户授权创建 GitLab Release 后，在 `ai-team/eimosp-ontology-agentic-analytics` 仓库基于同名 tag 发布
  一个 Release；
- Release 使用与 tag 相同的版本号、名称和正式版本说明；
- 幂等：创建前先检查 Release 是否存在，只补缺失项；已存在且正确的 Release 保留，
  不覆盖已有 Release；
- 创建失败时保留已有状态，修复后以相同 tag 重试，不回滚、不 force push、不移动
  tag；
- 创建 Release 使用本地 GitLab CLI/API，不在服务器上执行。
