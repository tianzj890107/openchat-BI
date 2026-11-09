# 容器端口统一规范（Spec）— eimosp-ontology-agentic-analytics

> 状态：TDD 中（Red → Green）。本文档与 `tests/test_container_port_contract.py` 同步维护。

## 背景与目标

本仓库（智能分析）与建模仓库（eimosp-ontology-agentic-modeling）的容器镜像此前分别把
宿主机习惯端口（8765 / 47313 / 47314）用作**容器内部监听端口**，导致不同服务镜像的
容器内端口不一致、运维映射易错。本次统一约定：

- 所有容器内 HTTP 服务统一监听 `0.0.0.0:8080`；
- 宿主机到容器的端口映射保持原习惯端口：
  - 智能分析：推荐 `-p 8765:8080`；
- 非容器本地直接启动的默认端口保持不变（本仓库为 `8765`），不迁移本地启动约定。

一句话契约（README/DEPLOYMENT 必须写明）：

> `8080` 只在容器内部使用；本仓库对外维护的唯一应用端口是 `8765`。不要把宿主机端口
> 写成容器内部监听端口，也不要把 `8876`、`18765`、`47313`、`47314` 当作本仓库入口。

## 验收清单（Analytics）

1. Dockerfile 包含 `APP_PORT=8080`（ENV 显式注入）。
2. Dockerfile `CMD` 使用 exec 形式启动 `python -m bi_agent.web`，参数含
   `--host 0.0.0.0 --port 8080`，即容器内实际监听 `0.0.0.0:8080`。
3. Dockerfile 只 `EXPOSE 8080`，不再 EXPOSE 8765。
4. Dockerfile `HEALTHCHECK` 探测容器内 `http://127.0.0.1:8080/healthz`。
5. README.md 与 DEPLOYMENT.md 的 Docker 示例统一使用 `-p 8765:8080`，
   `curl http://127.0.0.1:8765/healthz`；必须区分：
   - 容器内部端口 `8080`；
   - 推荐宿主机端口 `8765`；
   - 非容器本地运行默认端口 `8765`。
6. 健康接口 `/healthz` 响应中的 `port` 字段必须反映进程**实际监听端口**
   （容器内为 `8080`），不能始终硬编码 `8765`；由启动参数/`APP_PORT` 环境变量控制，
   Dockerfile 显式传 `8080`，非容器本地默认仍是 `8765`。
7. Nacos 未接入：端口配置属于应用级配置，不向 Nacos 过度同步；不新增 dataId，
   保持 `dataId=eimosp-ontology-agentic-analytics` 占位不变。

## 非目标

- 不部署、不创建 Release、不改正式版本号（当前 `v0.1.0`）。
- 不迁移非容器本地/服务器部署（systemd、`--port 8765` 本地启动）到 8080。
