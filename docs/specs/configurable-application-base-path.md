# 可配置应用 Base Path 适配规范

## 目标

智能分析 Agent 必须既能部署在域名根路径，也能完整部署在网关保留的子路径下。本次
生产目标前缀为：

```text
/api/ontology-agentic-analytics
```

配置 `APP_ROOT_PATH=/api/ontology-agentic-analytics` 后，对外入口统一为：

- `/api/ontology-agentic-analytics/workbench`
- `/api/ontology-agentic-analytics/static/*`
- `/api/ontology-agentic-analytics/api/*`
- `/api/ontology-agentic-analytics/healthz`

网关负责把此前缀流量转发给应用，并在 ASGI 层按 `root_path` 语义处理前缀；应用内部
路由仍保持 `/workbench`、`/static/*`、`/api/*`、`/healthz`，不得复制注册一套带固定
生产前缀的路由。

## 配置契约

1. 新增环境变量 `APP_ROOT_PATH`，缺省值为空字符串，保证现有根路径部署完全兼容。
2. 接受空值、`/`、`api/foo/`、`/api/foo/`，规范化结果分别为 `""`、`""`、
   `"/api/foo"`、`"/api/foo"`。
3. 非空前缀必须以 `/` 开头、不得以 `/` 结尾，不允许查询串、fragment、协议、域名、
   `.`/`..` 路径段或重复斜杠；非法配置必须在启动/导入时快速失败并给出明确错误，不能
   静默回退。
4. FastAPI 的 `root_path` 必须使用规范化值；不得用 `FastAPI(root_path_in_servers=False)`
   等方式隐藏真实部署前缀。

## URL 生成契约

所有浏览器可见或浏览器主动请求的站内 URL 必须经过唯一的 base-path URL 生成机制，
不得再直接依赖以 `/api`、`/static`、`/charts` 或 `/workbench` 开头的域名根路径：

- `/` 重定向到带前缀的 workbench，并保留原 query string；
- workbench HTML 中 CSS、JS、preload 资源地址带前缀；
- 前端所有 `fetch`、动态 script、下载/预览、图表和导航地址带前缀；
- 后端返回或注入 HTML 的站内静态资源地址带前缀；
- 不能使用字符串全局替换响应体这种脆弱方案。

推荐由后端在 workbench HTML 中注入一个 JSON 安全编码的运行时 base path，再由前端
集中 helper 生成 URL。helper 必须避免双前缀，并正确保留 query string。不得把生产
前缀硬编码进源码或前端构建产物。

## 兼容与运维契约

- 未设置 `APP_ROOT_PATH` 时，原有 `/workbench`、`/static/*`、`/api/*`、`/healthz`
  行为和测试不得回归。
- Docker 容器内部 HEALTHCHECK 仍探测 `http://127.0.0.1:8080/healthz`；base path 是
  外部代理契约，不能破坏容器内健康检查。
- `README.md`、`.env.example`（若存在）和 `DEPLOYMENT.md` 必须说明变量、完整生产 URL、
  代理转发约定，以及外部带前缀/容器内部不带前缀的健康检查差异。
- 不修改版本号，不部署，不修改 GitLab 配置。

## 验收

```bash
.venv/bin/python -m unittest tests.test_application_base_path
.venv/bin/python -m unittest tests.test_regressions tests.test_container_port_contract
git diff --check
```

第一条测试在实现前必须失败（RED），实现后全部通过（GREEN）。
