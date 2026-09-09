# Changelog 仅按周维护规范

自本规范生效后，仓库不再创建、更新或引用“当日日报/每日 changelog”作为现行流程。
所有当周已完成变更直接合并记录到唯一的周文件：

```text
changelog/changelog_M_D-D.md
```

## 规则

1. 当周文件不存在时，只创建周文件，不创建日报文件；
2. 同一功能的多次修改合并为一个最终状态条目，不按 commit 或日期机械重复；
3. 每个条目标注完成日期，必要时标注时间；
4. 版本号不按日 changelog 或日期机械升级；
5. 正式版本说明只保存在 `docs/versions/vX.Y.Z.md`，不在其中规定每日 PATCH 发布；
6. 历史日报、历史 changelog 中的“每日”字样属于过去事实，可以保留，不得改写历史；
7. 现行 README、AGENTS、版本规范、工作流和自动化脚本不得指导创建日报。

## 验收

```bash
.venv/bin/python -m unittest tests.test_weekly_changelog_only
git diff --check
```

