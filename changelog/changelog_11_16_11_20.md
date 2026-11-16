# 变更记录（2026-11-16 至 2026-11-20）

按自然周维护，不创建日报。

> 2026-11-16 建立本周记录：上周（11-09 至 11-13）周文件缺失，`11-14`～`11-15` 的
> 商机获取连续提交未落盘；本文件按当前 Git 记录补齐 `2026-11-16` 的定版提交与客户镜像
> 重打包，并把该交付合并为最终状态描述（补齐说明见文末）。

### 2026-11-16 商机获取卡：V3 精简关联版、分析时间定格 2025 年 10 月与 2025-10-31 取数截止

- 按《亿纬锂能_本体_商机获取节点_V3_精简关联版》重建 `opportunity-v3` 卡片配置并定版为
  `opportunity-v3-rules-11`：51 指标 / 31 规则 / 8 风险 / 8 原因 / 10 建议 / 8 关联；
  按精简关联版取消储能客户范围规则（`storageCustomerScope.enabled=false`、`storage_join` 为空），
  RK08/RK09 投标类查询关闭（风险数 8），BR-Q06 改为 `completedOnly=false`。
- 右上角分析时间固定为 2025 年 10 月：`periods.DEFAULT_BUSINESS_YEAR='2025'`、
  `DEFAULT_BUSINESS_MONTH='2025-10'`，页面首帧通过 HTML `cockpit-business-period` 注入
  `2025-10`（`cockpit.js` 优先读取该 meta 作为默认期间，meta 缺失时才回退为「当前年份-10」）；
  期间下拉仍列出 2025 各月，但超出 10-31 的期间不再产生取数。
- 新增 `periods.DEFAULT_SNAPSHOT_DATE='2025-10-31'`、`snapshot_date()`（`COCKPIT_SNAPSHOT_DATE`
  可覆盖）与 `period_range()` 截断语义：年度粒度窗口为 `2025-01-01`～`2025-10-31`（YTD，
  指标 SQL 仍按全年口径计算进度），月度粒度保留各自月末但不超过 10-31，`2025-11` 及之后的
  期间返回 `None`，服务端不再为其发起 AP 查询。
- `opportunity_v2._measurement_date()` 把每个期间的测量日期收敛到 `min(期间末日, 快照日)`，
  显式传入的测量日期优先；`query_capabilities` 的期间 `bounds`、`refresh` 的期间请求同步使用
  `periods.period_range()`，保证 SQL 参数统一为 `2025-10-31`（此前年度请求仍出现 `2025-12-31`）。
- 规则补丁 SQL 的观测时间统一写为 `2025-10-31 23:59:59`，配置版本与卡片元数据同步更新。
- 主要文件：`bi_agent/cockpit/{periods,opportunity_v2,query_capabilities,refresh}.py`、
  `scripts/build_opportunity_v3_config.py`、`bi_agent/cockpit/assets/opportunity-v3/config.json`、
  `bi_agent/web/static/cockpit/{cockpit.js,metadata/runtime.json}`、
  `tests/test_cockpit_{business_year,query_capabilities,period_refresh,opportunity_v2}.py`。
- 验证：Cockpit Python 套件 593 项通过，`tests/test_cockpit_resource_contract.py` 有 1 项
  在基线 `8c5e3d4` 同样失败的既有用例（`test_delivered_insight_slots_use_live_analysis_instead_of_static_copy`）；
  前端 Node 套件 136 项通过；镜像内实测 `period_range('2025')='2025-01-01'..'2025-10-31'`、
  `'2025-10'='2025-10-01'..'2025-10-31'`、`'2025-11'=None`，AP 年度过滤为
  `2025-01-01~2025-10-31`，无 `CURRENT_TIMESTAMP` 残留。

### 2026-11-16 客户镜像重打包（`feature/20251031@7ffc324`）

- 以 `feature/20251031` 最新提交重打包客户镜像 `cockpit-process360:customer-20261103`
  （linux/amd64），输出 `cockpit-customer-20261103/images/cockpit-linux-amd64.tar`：
  `164,414,976` 字节，SHA256 `df61e0dad6baa0264374fb269675ccad4c8b091d1f2595e9fb6c62a855d53020`，
  `docker load -i` 后镜像 ID `sha256:3439318e43081469ea4e719a583bdcbb04c8103babd22d3bf5c93d7bc8e1db1d`。
- 镜像内 254 个受控文件与 `7ffc324` 逐文件 SHA256 一致；快照日期、期间截断、AP 年度过滤、
  卡片配置版本（`opportunity-v3-rules-11`：51 指标 / 8 风险）、页面默认期间 `2025-10`、
  预置种子年度期间 2025 与内置本体清单均校验通过。
- 同步交付目录 `cockpit-customer-20261103/SHA256SUMS`（仅 `images/cockpit-linux-amd64.tar` 行）、
  `release.json`（sourceCommit `7ffc324`、imageId、imageSha256、previousImage、tests）；
  `打包说明.md` 更新到 `7ffc324` 并修正其中遗留的旧主机路径、seed/wheels 路径与远端 detach 步骤；
  归档 `release.7ffc324.json`、`SHA256SUMS.7ffc324`、`打包说明.7ffc324.md` 到
  `.cockpit-build-20261115/20251031/`，原 `df562f5` tar 保留备份。
- 验证：tar 大小与 SHA256 和 `SHA256SUMS` 一致，`docker load` 与容器内 import 正常；
  仅打包，未部署、未重启服务、未改动服务器数据。

## 补齐说明

- 2026-11-16 补记：上周（2026-11-09 至 2026-11-13）周文件未创建，`11-14`～`11-15` 落在
  该周的提交（如 `48cbe04`、`8c5e3d4`、`df562f5`、`0daa8bb`）没有对应周记录；
  本文按规则从本周开始补齐 `2026-11-16` 完成的最终变更，并把 `11-14` 起在
  `feature/20251031` 上连续完成的商机获取交付合并为一条最终状态记录（不逐提交罗列）。