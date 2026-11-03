# Workbench 本地Excel + ywln_crm

新增一个固定可选组合，不引入环境profile框架，不修改客户Process360连接。

## 使用

本机私有 `.env` 已单独配置公司PG和本地PG版Excel。Workbench“数据源”中选择 **PostgreSQL · ywln_crm** 后保存，服务端原子绑定配置的本地Excel，不保留远程本体平台连接。其他会话及原SQLite／Doris选项保持各自绑定。

也支持完全不依赖远程本体／Doris的启动方式：

```bash
.venv/bin/python -m bi_agent.web --db postgres --host 127.0.0.1 --port 8765
```

启动前需配置以下变量；不会从 `PROCESS360_PG_*` 回退继承，避免客户库和公司库串用：

- `WORKBENCH_LOCAL_ONTOLOGY_PATH`：项目内Excel路径。
- `WORKBENCH_PG_HOST`、`WORKBENCH_PG_PORT`、`WORKBENCH_PG_DATABASE`、`WORKBENCH_PG_SCHEMA`。
- `WORKBENCH_PG_USER`、`WORKBENCH_PG_PASSWORD`：仅存在私有env，不经HTTP或历史记录返回。
- `WORKBENCH_PG_CONNECT_TIMEOUT`、`WORKBENCH_PG_STATEMENT_TIMEOUT_MS`。
- `WORKBENCH_PG_ONTOLOGY_SCHEMA_ALIAS`：可选的明确schema前缀映射，只作用于新建本地本体副本，不改写原Excel或其他会话。

配置缺少、Excel越出项目目录或不存在时，不出现可选项；显式请求时返回错误，不回退到SQLite／Doris。环境变量变更需要重新启动服务；已创建的SQL执行器保留当时的PG连接配置。

## 实现

- `Ontology-FactQuery`、`ListTables`、`DescribeTable` 对此选项使用独立的PostgreSQL执行器；事务只读、设置明确search_path、语句超时和返回行数限制，SQL只允许SELECT／CTE，拒绝多语句及已登记的危险函数。
- 本地Excel读取支持“逻辑实体映射”“业务属性映射”，并识别V3.1实体关系的“关系编码／源逻辑实体编码／目标逻辑实体编码”。显式缺失来源的属性不再提供可用于SQL的旧字段名。
- 模型会获得PostgreSQL方言及当前schema说明，取证元数据标明PostgreSQL来源；不再按SQLite执行该数据源。
- 继续使用现有会话切换、历史记录逻辑；只保存非敏感的本体文件标识及数据库选项名称。

## 本次实际验证

只读检查公司PG当前 `ywln_crm` 后确认：原 `v_ods_*` 视图与LE视图不存在，真实业务表是 `p_fm_edw_*`。因此准备了本地PG版本体副本，2354个属性中的2319个真实映射字段均与information_schema逐项匹配，35个缺失属性继续标记blocked；不填造字段、不改业务公式和阈值。

本地PG版Excel读取30个实体、40条关系；连接实测transaction_read_only=on，current_schema=ywln_crm。没有扫描或修改业务数据。

- 新增配置、独立数据源、只读SQL、同会话绑定／跨会话隔离、Excel映射与CLI启动回归。
- 新增11项及原回归222项（合计233项、12个子测试）通过，Process360 catalog／MCP回归15项通过。
- 本地隔离浏览器验证数据源下拉显示并选中“PostgreSQL · ywln_crm”，本体源是本地Excel。

原本体、客户部署本体和已交付ZIP未覆盖；新本地Excel及实际env不提交Git。未部署、未重启现有服务。
