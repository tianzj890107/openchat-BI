# 仓库级 master 主线口径统一规范

## 目标

`master` 是仓库唯一默认分支和发布主线。所有当前有效的开发、推送、Merge Request、
构建、版本和部署指令必须指向 `master`，不得继续把已删除的 `main` 描述成可操作分支。

## 当前规则

- 开发提交推送到 `gitlab/20260727`；
- 正式交付使用 `20260727 → master` Merge Request；
- `master` 受保护，禁止 Agent 直接 push 或自动合并；
- `main` 已退役并删除，只允许在防止重建的保护逻辑或明确标记的历史审计记录中出现；
- 不得重新创建 `main`，不得将其用作 push、MR、CI、构建或部署目标。

## 全局检查边界

检查所有 Git tracked 的当前有效文本文件，包括代码、脚本、配置、测试、根文档及现行
工作流文档。以下内容可保留真实的 `main` 字样：

1. `changelog/` 中已经发生的历史记录；
2. `docs/versions/v*.md` 中已发布版本当时的事实；
3. 分支迁移、切换和删除 Spec 中描述的前置状态与审计证据；
4. `AGENTS.md`、push 脚本及测试中“main 已退役并删除、禁止重建”的负向保护。

不得把历史记录中的分支名机械替换为 `master`，否则会伪造历史。即使在上述历史文件
中，也不得留下会被理解为当前操作指令的无时间限定表述。

## 禁止的当前口径

- `20260727 → main` 或等价 MR 指令；
- `target_branch=main`、`source_branch=main`；
- `origin/main`、`gitlab/main`、`refs/heads/main` 作为当前命令目标；
- 把 `main` 称为当前默认、发布、保护或历史保留分支；
- `HISTORICAL_BRANCH = "main"` 等仍把已删除分支建模为现存分支的代码/测试；
- CI、构建、部署或版本步骤从 `main` 取代码。

## 验收

```bash
.venv/bin/python -m unittest tests.test_repository_wide_master_consistency
.venv/bin/python -m unittest tests.test_master_mainline_policy tests.test_push_gitlab
git diff --check
```
