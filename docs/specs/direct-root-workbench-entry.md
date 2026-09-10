# 分析工作台根入口直出规范

## 目标

分析 Agent 的应用根入口必须直接返回工作台 HTML，不再先以 307 跳转到
`/workbench`。生产环境配置：

```text
APP_ROOT_PATH=/api/ontology-agentic-analytics
```

因此访问 `/api/ontology-agentic-analytics` 时，浏览器地址应保持不变并直接得到工作台。

## 行为契约

1. 配置 `APP_ROOT_PATH=/api/ontology-agentic-analytics` 时：
   - `GET /api/ontology-agentic-analytics` 返回 `200 text/html`；
   - 不返回 `Location`，不发生 3xx；
   - HTML 注入正确的 `window.APP_ROOT_PATH`；
   - HTML 内静态资源仍指向 `/api/ontology-agentic-analytics/static/*`。
2. `GET /api/ontology-agentic-analytics/workbench` 继续返回相同工作台，兼容已有书签和外部集成。
3. 未配置 `APP_ROOT_PATH` 时，`GET /` 同样直接返回工作台，`GET /workbench` 保持兼容。
4. 不复制工作台 HTML 生成逻辑；根入口和 `/workbench` 必须复用同一个响应构造函数。
5. 不修改现有网关路径、静态资源挂载、健康检查和 API 路由。

## 非目标

- 不删除 `/workbench`；
- 不修改 Vane、Ingress 或 OpenResty 配置；
- 不改变 `/static/*`、`/api/*`、`/healthz` 的路径；
- 不引入新的前端构建产物。

## 验收

```bash
.venv/bin/python -m unittest tests.test_direct_root_workbench_entry
.venv/bin/python -m unittest tests.test_application_base_path
git diff --check
```

