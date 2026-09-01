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
- 交付：commit `a4ed51e` 已推送 `gitlab/20260727`；未部署、未合并。
