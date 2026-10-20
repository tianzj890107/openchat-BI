# ontology-analytics-mcp

主服务内置远程 MCP 的工具模块，不是独立部署的 MCP 服务。

`bi_agent/web/mcp_endpoint.py` 在 `bi_agent.web` 启动时挂载
`/api/mcp`，并从本目录加载：

- `fast_tools.py`：`MetricFactQuery` 指标快路径；
- `canvas_tool.py`：`CanvasGenerate` 整页自包含 HTML；
- `assets/echarts.min.js`：离线内联图表资源。

真实工具执行器复用主服务的 `build_source_executors`，与 Web 对话完全一致；本目录
不保存凭据，不启动本地服务，也不暴露原始 SQL 工具。`AnalysisRun`、`AskUser`、
`TodoWrite` 和表结构探测不在对外工具面内。

## 调用链

```text
Fuxi / 其他 MCP 客户端
  → POST /api/mcp
  → bi_agent.web.mcp_endpoint
  → build_source_executors
  → 本体 / Doris / 图表 / Canvas
```

客户端只需要：

```text
transport: http
url: http://<bi-agent-host>/api/mcp
headers: {}
```

`CanvasGenerate` 返回的 `Artifact URL` 指向
`/api/mcp/artifacts/<filename>`，由主服务只读提供 HTML 文件。

## 开发

```bash
.venv/bin/python -m pytest -q tests/test_mcp_endpoint_red.py
.venv/bin/python -m pytest -q tests/test_remote_ontology_fast_path_red.py
```

`_vendor/` 仅作为本地开发的历史副本，不参与主服务导入，也不提交到仓库。
