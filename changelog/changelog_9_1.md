# openchat-BI 变更记录（2026-09-01）

> 本文档只记录 2026-09-01 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 变更

### 1. 本体图共享包发布到 ai-team 组包 registry

- `@boulderaitech/ontology-graph@0.1.0` 发布完成：GitLab 14.0.2 不支持纯组级 npm 端点，
  包托管在组内项目 `ai-team/ontology-graph`（id 1069）的项目级 package registry，
  聚合显示在 `http://gitlab.boulderaitech.com/groups/ai-team/-/packages`；
  已验证组/项目包 API 与 registry 元数据（200）。
- 确定包版本规则：任何发布变更默认升 `0.1.x`（PATCH），`0.2.0` 仅在用户明确指定时升级；
  规则与发布检查清单写入共享包 `docs/versions/`。
- 文档表述更正：`changelog/changelog_8_31.md` 与 `DEPLOYMENT.md` 中“新仓
  ai-team/ontology-graph”更正为“组包 registry 托管项目”。
- 主要文件：共享包源码目录 `/Users/sher/Boulderaitech/ontology-graph`（含
  `docs/versions/`）；本仓 `changelog/changelog_8_31.md`、`changelog/changelog_9_1.md`（新增）、
  `DEPLOYMENT.md`。
- 交付：commit `7e736bd` 已推送 `gitlab/20260727`；未部署、未合并。


### 2. 提交邮箱规范化与历史重写推送

- openchat-BI 仓库级 git config 此前残留旧邮箱 `zhenzhan0408 <zhenzhan@kth.se>`（全局 config 已是公司邮箱），导致 20260727 分支上 174 个提交的 author/committer 均为旧邮箱。
- 已用 `git filter-branch` 仅将上述 174 个提交的 author/committer 改为 `张真 <zhangzhen@boulderaitech.com>`；35 个田子敬提交未动，提交内容（tree）完全一致，提交总数仍为 209。
- 按用户显式授权重写远端历史：临时关闭 20260727 分支 force push 保护 → `--force-with-lease` 推送 → 恢复原保护规则（Maintainers push/merge，禁 force push）；推送后 `HEAD == gitlab/20260727`。
- 受影响 commit hash 已在 `changelog/changelog_8_31.md`、`changelog/changelog_9_1.md` 与共享包 `docs/versions/v0.1.0.md` 中同步更新为重写后的新 hash。
- 主要文件：仓库 git 历史元数据（无代码内容变化）、`changelog/changelog_8_31.md`、`changelog/changelog_9_1.md`。


### 3. GitLab 分支保护调整

- `20260727`（开发分支）取消 protected，恢复普通分支；
- `main`（发布分支）启用 protected：Maintainers 可 push/merge、`allow_force_push=false`，
  与 AGENTS 规则一致（merge 到 main 需 code review 后走 Merge Request）；
- 已通过 GitLab API 验证保护列表（当前仅 `main` 受保护），`HEAD == gitlab/20260727` 不变。


### 4. GitLab 默认分支切换与 MR 确认

- `main` 设为 GitLab 项目默认分支（原默认 `20260727`），已验证 `default_branch=main`；
- MR `!2`（`20260727` → `main`，opened）已确认：head 为最新 `6cf6f8d`，
  reviewer=`tianzijing`、assignee=`zhangzhen`；只创建/确认 MR，不自动合并、不直接 push `main`。
