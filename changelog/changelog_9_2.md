# eimosp-ontology-agentic-analytics 变更记录（2026-09-02）

> 本文档只记录 2026-09-02 当天完成的最终变更。

## 维护规则

- 今天的变更只追加到本文档，不写入其他 changelog。
- 每次发布或一组相关修改合并为一条记录，不记录中间尝试。
- 每条记录说明用户可见变化、涉及页面/场景和主要文件。
- 未完成、未验证的事项不要写成已完成。

## 变更

### 1. 容器化交付清单落地（Dockerfile + 运行参数）

- 新增根目录 `Dockerfile` 与 `.dockerignore`：镜像基于官方 `python:3.13-slim`，
  容器内部统一端口 `8080`（`ENV APP_PORT=8080`、`EXPOSE 8080`、默认 CMD
  `--port 8080`），内置 `HEALTHCHECK` 探测容器内 `/healthz`；前端构建产物随镜像
  提供，构建无需 Node.js；容器以非 root 用户运行，会话/图表/上传/日志目录保持可写。
- 应用运行参数固化：应用名 `eimosp-ontology-agentic-analytics`（产品名“智能分析”）、标准 Python 版本
  `3.13.x`（`pyproject.toml` 约束 `>=3.10,<3.14`）；新增 `.python-version`（3.13）。
- 主要文件：`Dockerfile`、`.dockerignore`、`.python-version`、`pyproject.toml`、
  `bi_agent/web/app.py`（应用元信息常量）、`README.md`、`DEPLOYMENT.md`。

### 2. 统一健康检查接口

- 健康检查统一为 `GET /healthz`（新增等价别名 `GET /health`）：就绪返回 `200`，
  未完成配置返回 `503`，不依赖且不触发任何 LLM 调用（保持原契约 `llm_call=false`）。
- 响应字段固定：`ok`/`status`/`app`/`name`/`version`/`host`/`port`/`uptime_seconds`/
  `configured`/`llm_call`/`dependencies`（含 agent、ontology、conversation_store 状态）。
- 主要文件：`bi_agent/web/app.py`；回归测试 `tests/test_regressions.py` 中
  `/healthz` 契约用例已通过。

### 3. Nacos 配置中心预留（未接入）

- 按要求暂不实现 Nacos 对接，仅做文档与配置占位：`DEPLOYMENT.md` 新增
  “应用信息清单”与“Nacos 对接（待办）”章节，明确后续 `dataId=eimosp-ontology-agentic-analytics`、
  命名空间按环境隔离、密钥不进配置中心等约定；`.env.example` 追加注释占位变量
  （`NACOS_SERVER_ADDR`/`NACOS_NAMESPACE`/`NACOS_GROUP`/`NACOS_DATA_ID` 等）。
- 当前模型、本体、Doris、并发治理等中间件配置仍由 `.env`/环境变量注入，行为不变。
- 主要文件：`DEPLOYMENT.md`、`.env.example`、`README.md`。

### 4. 项目统一改名与 Git 历史去重

- 本地仓库、GitLab path、应用名、容器与 systemd 标识、Nacos dataId、前端包名、静态制品名、当前文档及工作流脚本统一为 `eimosp-ontology-agentic-analytics`；上游建模仓库引用统一为 `eimosp-ontology-agentic-modeling`。
- 清除 `9b91801` 空内容 merge 重新引入的 172 个 `zhenzhan@kth.se` 重复提交；`20260727` 与 `main` 最终指向同一条仅保留公司邮箱改写历史的提交链，避免后续 MR 再次带回旧历史。
- 验证：`.venv/bin/python -m unittest discover -s tests` 306 项通过；前端 `npm run build` 成功；`git diff --check` 通过。未部署、未改写历史会话和运行数据。
### 5. 统一容器内部端口 8080（宿主机推荐映射 8765:8080）

- 按两个仓库统一的容器端口规范，容器内 HTTP 服务统一监听 `0.0.0.0:8080`：
  `Dockerfile` `ENV APP_PORT=8080` + `EXPOSE 8080` + 默认 CMD `--port 8080`，
  `HEALTHCHECK` 探测容器内 `http://127.0.0.1:8080/healthz`；宿主机推荐映射
  `-p 8765:8080`。
- `/healthz`（别名 `/health`）响应中的 `port` 字段不再硬编码 8765，改为反映进程
  实际监听端口：`bi_agent/web/__main__.py` 新增 `DEFAULT_PORT`（优先 `APP_PORT`
  环境变量，缺省 `8765`），启动后调用 `bi_agent/web/app.py` 新增的
  `set_runtime_port` 同步实际端口。
- 非容器本地直接启动默认端口保持 `8765`（不带 `--port`/`APP_PORT` 时不变）；
  systemd 等非容器部署不迁移。Nacos 仍未接入，`dataId=eimosp-ontology-agentic-analytics`
  占位不变，端口配置属于应用级配置、不同步到 Nacos。
- README/DEPLOYMENT 明确端口约定：`8080` 是统一容器内部端口；
  `8765`/`47313`/`47314` 是推荐宿主机映射端口或非容器直接运行端口，不要把宿主机
  端口写成容器内部监听端口；`.env.example` 增加端口说明注释。
- TDD：新增 Spec `docs/specs/container-port-8080.md` 与契约测试
  `tests/test_container_port_contract.py`（先 Red：7 FAIL + 4 ERROR，后 Green 12 项通过）。
- 验证：契约测试 12 项通过；`.venv/bin/python -m unittest discover -s tests`
  共 318 项，其中 1 项失败为环境预置
  `test_no_unexpected_git_tags`（本地存在历史备份 tag
  `backup-analytics-main-before-dedup-20260902`，与本次改动无关，未删除该 tag）；
  前端无测试文件，`npm run build` 成功且构建产物无漂移；真实进程验证：容器同款
  启动参数 `--port 8080` 下 `/healthz` 返回 `port=8080`，不带参数默认启动返回
  `port=8765`。Docker 构建因拉取 `python:3.13-slim` 超时
  （`registry-1.docker.io ... context deadline exceeded`，重试仍失败）未完成，
  未声称 Docker 运行验证通过；未部署、未创建 Release、未改正式版本号。
- 主要文件：`Dockerfile`、`bi_agent/web/app.py`、`bi_agent/web/__main__.py`、
  `.env.example`、`README.md`、`DEPLOYMENT.md`、`tests/test_container_port_contract.py`（新增）、
  `docs/specs/container-port-8080.md`（新增）。
