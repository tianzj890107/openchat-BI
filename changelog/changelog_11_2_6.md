# 变更记录（2026-11-02 至 2026-11-06）

按自然周维护，不创建日报。

### 2026-11-02 单一源码主目录约定

- 在 AGENTS.md 固定用户要求：未经明确授权不创建 worktree、额外 clone 或 POC/集成源码副本；已合并工作区核对线上路径及独有数据后清理。
- 允许测试框架自动清理的隔离 fixture；目录清理不授权线上重启、部署或删除历史数据。
- 验证：规则内容已核对，git diff --check 通过；仅工程约定变更，无业务行为变化。

### 2026-11-02 17:05 Cockpit 同步 iba-demo be99db5 品牌色板

- 用户可见变化：经营看板、运营页和穿透页的 KPI 数值色、图表色板与对比色更新为上游品牌色
  （`#4C8BF3` / `#63AD73` / `#5CBBD5` / `#E7B550` / `#DD8142` / `#DE5A60` / `#D751AD` 等），
  页面布局、15 个 AI 插槽和三张订单表结构保持不变。
- 运行包：`vendor/pro-bi-ui.min.js` 更新为 `iba-demo feature/demo_1021` `be99db5` 的 UMD；
  `index.html` 缓存参数改为 `?v=e152acd8`，`resources.json` 提交号、哈希和字节数同步。
  上游 UMD 未带头盔图销毁后的空实例保护，同步后重新补回 `fitView` 守卫；`pro-ui.min.css`
  与 Vue 运行时未变化。
- 配置同步：`metadata/iba-demo-1021/template-registry.json` 按上游色板更新并重新生成
  `metadata/runtime.json`；`components.json` 上游仅移除了宿主适配的默认期间，已重新写回
  `YWLN_D044=2025-10`，因此文件内容与上一版一致。
- 上游数据修复：新模板配置有 4 处中文标签以 U+FFFD 乱码交付（进行中超期电量、报价办理状态、
  投标状态分布、销售订单编号），同步时恢复为上一版正确文案，没有按乱码入库。
- 主要文件：`bi_agent/web/static/cockpit/vendor/{pro-bi-ui.min.js,resources.json}`、
  `index.html`、`metadata/iba-demo-1021/{template-registry,source}.json`、`metadata/runtime.json`、
  `tests/test_cockpit_{metadata,resource_contract}.py`。
- 验证：Cockpit 相关 Python 257 项、前端 Node 88 项通过；UMD `node --check` 通过；
  资源清单与 `source.json` 哈希一致；`git diff --check` 通过。

### 2026-11-02 17:20 Cockpit 合并客户覆盖、核查交付与宿主面板修复

- 用户可见变化：运营页商机覆盖提示可使用已核验 AP 客户覆盖数，报价状态口径修正；
  穿透页的核查建议必须有证据支撑，阶段策略支持缓存预热，任务令下发前要求确认具体
  日历期限；看板不再显示宿主自绘的“元数据缺失与渲染限制”面板。
- 交付契约：核查类动作与改善类动作分开校验，假设只能生成核查任务；责任角色和期限
  未确认时保持“待确认”，不写成已下发安排。
- 评测与修复：合入 40 条 Cockpit 业务评测用例及运行器；任务令 POC 测试改用具体日期，
  与“工作日建议不是可下发日期”的期限校验保持一致。
- 验证：全量 Python 与前端 Node 测试通过；`git diff --check` 通过。
