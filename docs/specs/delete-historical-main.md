# 删除历史 `main` 分支 Spec

## 1. 目标

在 `master` 已成为唯一默认发布主线、已受保护且完整包含旧 `main` 历史后，退役并删除 GitLab 远端 `main` 分支，消除双主线名称歧义。

删除对象仅为：

```text
项目：ai-team/eimosp-ontology-agentic-analytics（id 1065）
远端：gitlab
分支：refs/heads/main
删除前预期 SHA：4c20b6f798568598d7480ea4ac19e83ea3700e76
```

不得删除 `master`、`20260727`、tag、本地备份引用、其他仓库或任何业务数据。

## 2. 删除前硬门禁

以下条件必须同时成立：

1. GitLab 默认分支为 `master`；
2. `master` 已保护，禁止 force push，push/merge 最低为 Maintainer；
3. 远端 `main` 精确等于预期 SHA；若 SHA 改变必须停止并重新审计；
4. 旧 `main` 提交 `4c20b6f` 是当前 `master` 的祖先；
5. Administrator 镜像提交 `a7ebafa` 是当前 `master` 的祖先；
6. `master` 的 Dockerfile 仍使用华为云镜像；
7. 没有 open MR 以 `main` 为 source 或 target；
8. 仓库当前规则已通过正常 `20260727 → master` MR 更新为“`main` 已退役删除”，不再要求保留 `main`；
9. 操作不会触发部署。

任何门禁失败均不得解除保护或删除。

## 3. 仓库规则迁移

删除前更新以下当前有效规则：

- `AGENTS.md`
- `docs/gitlab-push-workflow.md`
- `docs/versions/versioning-policy.md`
- `DEPLOYMENT.md`
- `scripts/push_gitlab.py` 及相关测试

统一口径：

- `master` 是唯一默认发布主线；
- `main` 已退役并删除，不得重新创建、push 或作为 MR source/target；
- 普通开发仍只 push `gitlab/20260727`；
- 正式 MR 固定 `20260727 → master`；
- push/MR 不等于部署。

历史 changelog、已归档版本文档及一次性历史清理记录可以保留当时事实，不做机械改写，但必须明确相关授权已失效，不得据此重建 `main`。

规则修改必须先提交到 `20260727`，经 `tianzijing` review 的 MR 合入 `master`，再执行远端删除。不得先删分支后补规则。

## 4. 删除过程

1. 最后一次重新读取远端 `main` SHA并匹配预期值；
2. 重新验证旧 `main` SHA 是 `master` 祖先；
3. 记录 `main` 当前保护规则作为审计证据；
4. 仅对精确分支名 `main` 临时解除保护；
5. 立即通过 GitLab API 删除 `main`；
6. 验证分支 API 返回 404、`ls-remote refs/heads/main` 为空；
7. 验证 `master`、`20260727` 和所有 tag 未改变；
8. 验证 `master` 默认分支及保护规则未改变；
9. 不恢复 `main` 保护规则，因为分支已删除；绝不重新创建 `main`。

保护解除后若删除失败，必须优先恢复 `main` 原保护规则并报告；不得留下存在但未保护的 `main`。

## 5. 禁止事项

- 禁止 `git push --delete` 使用变量、glob 或模糊 ref；
- 禁止删除默认分支 `master`；
- 禁止 force push、reset、rebase、历史重写；
- 禁止删除 tag、Release、MR、提交对象、本地备份引用或用户分支；
- 禁止部署、登录服务器、重启服务；
- 禁止删除历史会话或用户数据；
- 禁止输出或提交访问令牌。

## 6. 只读验收

```bash
RUN_GITLAB_MAIN_DELETION_TESTS=1 \
.venv/bin/python -m unittest tests.test_main_branch_retirement
```

测试只读取本地 Git、仓库规则和 GitLab API。删除前必须为 RED，删除并完成全部验证后必须为 GREEN。
