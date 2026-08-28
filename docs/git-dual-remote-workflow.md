# Git 双远端镜像工作流

## 远端映射

| Remote | Repository | Target branch | Purpose |
| --- | --- | --- | --- |
| origin | tianzj890107/openchat-BI | 20260727 | 主协作仓库 |
| personal | zhenzhang0408/openchat-BI | main | 个人私有镜像与版本归档 |

## 完成标准

```
HEAD == origin/20260727 == personal/main
```

## 日常流程

1. 修改
2. 测试
3. `git diff --check`
4. `git commit`
5. `python scripts/push_dual_remotes.py --check`
6. `python scripts/push_dual_remotes.py`
7. 验证两个远端 hash 与本地 HEAD 一致
8. 没有部署授权时结束（push 不等于部署）

## 首次设置

```bash
git remote add personal git@github.com:zhenzhang0408/openchat-BI.git
git config user.name "zhenzhan0408"
git config user.email "zhenzhan@kth.se"
```

个人仓库必须是 GitHub Private 仓库；初始化时不添加 README/.gitignore/License，
不创建 fork、不启用 Pages 或部署流程。

## 安全规则

- `personal` 必须是 Private；
- `personal/main` 不允许独立提交，只允许与 `origin/20260727` 保存同一个 commit；
- 禁止 force push（含 `--force-with-lease`）；
- 不自动 merge 或 rebase；
- 不自动推 tag；
- push 不代表部署；没有当前任务明确部署授权时，双 push 后任务结束；
- 双远端失败处理：
  - `origin` 成功、`personal` 失败：报告部分成功，保留已有 `origin` push，修复权限
    或网络后以相同 HEAD 重试，不生成补偿 commit、不 force push、不回滚 origin；
  - 个人远端或原远端出现独有提交：停止处理并报告，不覆盖。
- 完成前先运行 `python scripts/push_dual_remotes.py --check` 检查配置与三个 hash。

## 正式版本

- 普通 commit 只双推分支（`origin/20260727` 与 `personal/main`），不自动推 tag；
- 正式版本 tag（`vX.Y.Z`）需要用户在当前任务中单独授权，且必须推送到 origin 和
  personal 两个远端：

```bash
git push origin vX.Y.Z
git push personal vX.Y.Z
```

- 版本号变更必须遵循 [语义化版本与正式发布规范](./versions/versioning-policy.md)；
  只有用户明确指定目标版本时才能升级正式版本；
- push 不等于部署；GitHub Release 是否创建由用户在当前任务中明确要求；不要把真实
  访问 token、SSH 私钥或凭据写入文档。

## GitHub Release 双仓发布

正式版本完成标准扩展为：

1. 分支双推一致：`HEAD == origin/20260727 == personal/main`；
2. tag 双推一致：`vX.Y.Z` 同时存在于 origin 和 personal，且 peeled commit 相同；
3. 用户授权 Release 时，两个仓库均存在内容一致的正式 Release。

规则：

- 用户授权创建 GitHub Release 后，默认在 origin 和 personal 两个仓库各发布一个；
  除非用户明确限定单仓；
- 两个 Release 使用相同的版本号、tag、名称和正式版本说明，基于各自仓库中的同名
  tag；
- 幂等：先 `gh release view` 检查，只补缺失项；已存在且正确的 Release 保留，不覆盖
  已有 Release；
- 一个仓库成功、另一个失败时，保留已成功 Release，修复后只重试缺失仓库，不回滚、
  不 force push、不移动 tag；
- 创建 Release 使用本地 GitHub CLI/API，不在服务器上执行。
