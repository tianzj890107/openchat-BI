# `master` 主线交付：提交、推送与 MR Spec

> 状态：`20260727` 已归档，不再作为交付分支（历史迁移过程见
> `master-mainline-migration.md`）。当前交付口径以本节与
> `docs/gitlab-push-workflow.md` 为准。

## 1. 交付目标

将已经通过本地 GREEN 验证的改动，以一个普通提交推送到 GitLab 上与本地同名的临时分支，随后创建或更新一个开放的 Merge Request：

```text
source_branch=<当前临时分支 feature/*│bugfix/*│hotfix/*> → target_branch=master
reviewer=tianzijing（id 166）
assignee=zhangzhen（id 245）
```

本阶段只交付供 review 的 MR，不自动合并、不切换 GitLab 默认分支、不修改分支保护、不触发部署。

## 2. 提交范围

提交必须包含且完整包含本次主线迁移相关文件：

- `AGENTS.md`
- `DEPLOYMENT.md`
- `Dockerfile`
- `docs/gitlab-push-workflow.md`
- `docs/versions/versioning-policy.md`
- `scripts/push_gitlab.py`
- `docs/specs/master-mainline-migration.md`
- `docs/specs/master-mainline-delivery.md`
- `tests/test_master_mainline_policy.py`
- `tests/test_master_mr_delivery.py`
- `tests/test_push_gitlab.py`

不得使用 `git add -A`。工作区中现存的 changelog 删除、整理或其他任务修改不属于本次主线迁移，除非用户另行确认，不得混入本提交。

提交前必须对上述文件运行 `git diff --check`，并通过主线策略、push 脚本、版本和容器测试。

## 3. 推送约束

- 当前分支必须是本次交付的临时分支（`feature/*`、`bugfix/*`、`hotfix/*`），不得在 `master`、`main` 或归档分支 `20260727` 上直接推送；
- 使用普通 push，将本地 `HEAD` 推到同名远端分支 `gitlab/<branch>`；
- 推送后必须满足 `HEAD == gitlab/<branch>`；
- 禁止 force push、`--force-with-lease`、直接 push `master` 或 `main`；
- 推送前若远端同名分支有本地未包含的独有提交，停止并报告，不自动 merge/rebase；
- 归档分支 `gitlab/20260727` 只保留历史审计，需要核对它的远端一致性时用 `python scripts/push_gitlab.py --check`，不再用于新提交；
- push 不等于部署。

## 4. MR 契约

创建前读取 `git log --no-merges master..<branch>` 和完整 diff（`<branch>` 为当前临时分支），标题及描述覆盖该范围的全部真实主题。

开放 MR 必须满足：

- source：当前临时分支（`feature/*`、`bugfix/*`、`hotfix/*`）；
- target：`master`；
- reviewer：用户 id `166`；
- assignee：用户 id `245`；
- source SHA 等于本地和远端同名分支的 HEAD；
- 标题不得只是“<branch> → master”“Merge <branch> into master”等泛化分支关系；
- 描述至少说明：唯一主线迁移、push/MR 安全边界、华为云 Docker 基础镜像、测试结果、不自动部署；
- MR 必须保持 open，等待 `tianzijing` review；
- 若已有同 source/target 的开放 MR，幂等更新其标题、描述、reviewer 和 assignee，不重复创建。

## 5. 历史与镜像保护

- MR 必须合入现有 `master`，不得用开发分支覆盖或重建 `master`；
- `master` 当前的 Administrator 提交 `a7ebafaa0097655fdc2d8595e367f0b4adaca47d` 必须仍可达；
- MR 合并结果必须保留 `Dockerfile` 中：
  `FROM swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim`；
- 出现冲突、不可合并状态或需要 force push 时停止并报告。

## 6. 只读 RED/验收测试

`tests.test_master_mr_delivery` 是显式启用的 GitLab 只读集成测试，默认跳过，避免普通离线回归依赖网络。执行：

```bash
RUN_GITLAB_DELIVERY_TESTS=1 \
.venv/bin/python -m unittest tests.test_master_mr_delivery
```

该测试只读取本地 Git 和 GitLab API，不执行 commit、push、MR 创建、合并、默认分支修改、保护规则修改或部署。被检查的 source 分支默认为当前分支，可用 `MR_SOURCE_BRANCH` 覆盖。交付前应为 RED；提交、推送并创建正确 MR 后应为 GREEN。
