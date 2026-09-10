# 环境隔离本体连接与未使用新会话复用规范

## 1. 背景

同一套分析 Agent 分别部署在：

- PDT：`http://pdt-dev.eimos.com/api/ontology-agentic-analytics`
- Demo：`http://demo2.eimos.com/api/ontology-agentic-analytics`

Agent 的公开地址和它调用的本体网关必须属于同一环境。Demo 不得继续通过 PDT 或
`172.16.5.181:30834` 直连本体服务；否则会读取 PDT 的完整本体库目录，而不是 demo2
环境仅有的 ECore 本体库及其数据库。

## 2. 环境本体网关契约

PDT 环境配置：

```text
ONTOLOGY_BASE_URL=http://pdt-dev.eimos.com/api/gateway2/ontology
DORIS_API_URL=http://pdt-dev.eimos.com/api/gateway2/ontology/agent/doris/query
```

Demo 环境配置：

```text
ONTOLOGY_BASE_URL=http://demo2.eimos.com/api/gateway2/ontology
DORIS_API_URL=http://demo2.eimos.com/api/gateway2/ontology/agent/doris/query
ONTOLOGY_REPOSITORY_ID=3
```

`ONTOLOGY_APP_ID`、`ONTOLOGY_AUTH_TOKEN` 使用各环境自己的凭据。代码不得新增
`ONTOLOGY_ALLOWED_REPOSITORY_IDS` 来掩盖跨环境连接错误。Dockerfile 和 Python 默认值
不得固定直连 `172.16.5.181:30834`；生产部署必须显式注入对应环境的两个网关地址。

验收 demo2 的 `/api/sources` 时：

- `ontology.production.base_url` 必须是 demo2 本体网关；
- `remote_repositories` 由 demo2 本体服务返回；
- 预期只包含 ECore 本体库及其配套数据库；
- 不通过前端过滤伪造“只有一个库”。

## 3. 未使用新会话复用契约

点击“新会话”后允许创建一个空白草稿。若用户尚未输入任何问题，再次点击“新会话”：

- 复用当前空白草稿，不再创建第二条；
- 不重复调用空草稿保存接口；
- 左侧“最近”最多显示一个未使用草稿；
- 不删除或覆盖已有真实会话；
- data 和 report 模式分别管理自己的草稿；
- 已经输入问题或产生内容后，再点击“新会话”必须归档当前会话并创建新草稿。

“未使用”的判定为：已有草稿 ID，`hasContent=false`、首问为空且 `turnCount=0`。
前端应使用独立、可测试的纯函数处理判定和历史列表中旧空草稿的折叠；只能隐藏重复的
未使用草稿，不能删除服务器历史文件。

## 4. 非目标

- 不在应用代码中写死 ECore repository ID 过滤；
- 不修改本体管理服务的数据；
- 不把真实 token 写入仓库；
- 不合并 data/report 草稿；
- 不删除历史真实会话。

## 5. 验收

```bash
.venv/bin/python -m unittest tests.test_environment_scoped_ontology_and_unused_session
.venv/bin/python -m unittest tests.test_regressions
cd frontend && npm run build
git diff --check
```

