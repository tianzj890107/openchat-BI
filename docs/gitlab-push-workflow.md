# GitLab 统一推送工作流

## 远端映射

| Remote | Repository | Target branch | Purpose |
| --- | --- | --- | --- |
| gitlab | ai-team/eimosp-ontology-agentic-analytics | 20260727 | 统一协作开发分支 |

`master` 是唯一发布主线，只通过 Merge Request 合并；MR 固定为 `20260727` →
`master`，合并前必须由 `tianzijing` code review，assignee 固定为 `zhangzhen`，
任何 Agent 或脚本都不得直接 push 到 `master`。`main` 是历史保留分支，不再接收
新功能 Merge Request。

## 完成标准

```
HEAD == gitlab/20260727
```

## 日常流程

1. 修改
2. 测试
3. `git diff --check`
4. `git commit`
5. `python scripts/push_gitlab.py --check`
6. `python scripts/push_gitlab.py`
7. 验证 gitlab 远端 hash 与本地 HEAD 一致
8. 没有部署授权时结束（push 不等于部署）

## 首次设置

```bash
git remote add gitlab git@gitlab.boulderaitech.com:ai-team/eimosp-ontology-agentic-analytics.git
git config user.name "zhenzhan0408"
git config user.email "zhenzhan@kth.se"
```

## 安全规则

- `gitlab/20260727` 是唯一默认开发分支目标；普通 commit 只推这个分支；
- 禁止 force push（含 `--force-with-lease`）；
- 不自动 merge 或 rebase；
- 不自动推 tag；
- push 不代表部署；没有当前任务明确部署授权时，push 后任务结束；
- 正式交付 MR 为 `20260727` → `master`，需要 `tianzijing` code review 后单独发起 Merge Request，本脚本不执行 master 合并、不执行 main 合并；
- 推送失败处理：报告失败，保留已有 push，修复权限或网络后以相同 HEAD 重试，不生成
  补偿 commit、不 force push、不回滚；
- 远端出现本地没有的独有提交：停止处理并报告，不覆盖。
- 完成前先运行 `python scripts/push_gitlab.py --check` 检查配置与 hash。

## 正式版本

- 普通 commit 只推开发分支（`gitlab/20260727`），不自动推 tag；
- 正式版本 tag（`vX.Y.Z`）需要用户在当前任务中单独授权，且必须推送到 GitLab；
- 版本号变更必须遵循 [语义化版本与正式发布规范](./versions/versioning-policy.md)；
  只有用户明确指定目标版本时才能升级正式版本；
- push 不等于部署；GitLab Release 是否创建由用户在当前任务中明确要求；不要把真实
  访问 token、SSH 私钥或凭据写入文档。

## GitLab Release

正式版本完成标准扩展为：

1. 分支推送一致：`HEAD == gitlab/20260727`；
2. tag 推送一致：`vX.Y.Z` 存在于 GitLab，且指向本地定版 commit；
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
