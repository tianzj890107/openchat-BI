# `master` 默认分支与保护规则切换 Spec

## 1. 当前事实

`20260727` 曾分别合入 `main` 和 `master`：两者当前 tree 内容完全一致，但各自拥有不同的 merge commit，因而互不为祖先。`master` 不是内容落后，而是提交拓扑尚未收口。

当前外部状态：

- GitLab 默认分支仍为 `main`；
- `main` 已保护：Maintainers 可 push/merge，禁止 force push；
- `master` 尚未保护；
- `master` 保留 Administrator 的镜像提交 `a7ebafaa0097655fdc2d8595e367f0b4adaca47d`；
- MR !6（`20260727 → master`）已合并。

## 2. 目标终态

- 通过普通 `main → master` 同步 MR 使 `main` 成为 `master` 的祖先；
- 同步不得产生内容变化，合并前后 `master` tree 必须一致；
- `master` 继续包含 Administrator 的 `a7ebafa`，Dockerfile 继续使用华为云镜像；
- GitLab 默认分支切换为 `master`；
- `master` 保护规则至少与切换前 `main` 等价：禁止 force push，push/merge 均至少要求 Maintainer；
- `main` 保留且继续保护，不删除、不改写、不再接收新功能 MR；
- 不触发或执行部署。

## 3. 操作顺序

1. 记录 `main`、`master` hash、tree、merge-base和保护规则；
2. 确认两分支 tree 相同；若内容不同，停止并人工审查差异；
3. 创建 `main → master` 同步 MR，标题明确为提交拓扑收口，不伪装成功能发布；
4. reviewer=`tianzijing`（id 166），assignee=`zhangzhen`（id 245）；
5. 等待 review 后通过 GitLab 正常 merge；不得直接 push 或自动绕过 review；
6. 验证 `main` 已是 `master` 祖先、tree 未变、华为云镜像未变；
7. 给 `master` 创建至少等价于原 `main` 的保护规则；
8. 验证保护生效后将项目默认分支切换为 `master`；
9. 保留 `main` 保护，不删除分支；
10. 复查没有开放 MR 继续以 `main` 为目标。

若用户已经明确授权本次“切换默认分支、保护”，可在同步 MR 获得规定 review 并合并后执行第 7～9 步；授权不包含部署、force push、删除分支或自动批准 review。

## 4. 安全边界

- 禁止 force push、`--force-with-lease`、reset、rebase 或重建 `master`；
- 禁止把 `master` 覆盖为 `main`；
- 禁止删除或取消保护 `main`；
- 禁止降低原有保护等级；
- 禁止在同步前直接切默认分支；
- 禁止自行冒充 `tianzijing` approval；
- 若同步 MR 产生实际文件 diff、冲突、Pipeline/Hook 自动部署或 `a7ebafa` 丢失，立即停止；
- 不操作服务器、tag、Release、历史会话或用户数据。

## 5. 只读验收

```bash
RUN_GITLAB_CUTOVER_TESTS=1 \
.venv/bin/python -m unittest tests.test_master_default_protection
```

该测试只读取 Git/GitLab，不修改分支、MR、默认分支、保护规则或服务器。切换前必须为 RED；全部收尾完成后必须为 GREEN。
