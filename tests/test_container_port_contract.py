"""容器端口契约测试（TDD：先 Red 后 Green）。

Spec：docs/specs/container-port-8080.md
容器内 HTTP 服务统一监听 0.0.0.0:8080；对外维护只使用宿主机 8765；
非容器本地直接启动默认端口保持 8765；健康检查 port 字段反映实际监听端口。
"""

from __future__ import annotations

import importlib
import os
import re
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


DOCKERFILE = _read("Dockerfile")
README = _read("README.md")
DEPLOYMENT = _read("DEPLOYMENT.md")
MAIN_SRC = _read("bi_agent/web/__main__.py")


def _expose_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if re.match(r"^\s*EXPOSE\b", ln)]


def _cmd_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if re.match(r"^\s*CMD\b", ln)]


def _healthcheck_block(text: str) -> str:
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^\s*HEALTHCHECK\b", ln)), None)
    if start is None:
        return ""
    block = [lines[start].strip()]
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if not stripped.startswith("\\") and "urlopen" not in stripped and "sys.exit" not in stripped:
            if not ln.startswith((" ", "\t")):
                break
        block.append(ln.strip())
        if not ln.rstrip().endswith("\\"):
            break
    return " ".join(block)


class DockerfileContainerPortContractTests(unittest.TestCase):
    """Dockerfile 与文档的容器端口契约（容器内统一 8080）。"""

    def test_dockerfile_declares_app_port_8080(self) -> None:
        self.assertIn("APP_PORT=8080", DOCKERFILE)

    def test_dockerfile_cmd_listens_on_0_0_0_0_8080(self) -> None:
        cmd = " ".join(_cmd_lines(DOCKERFILE))
        self.assertIn("bi_agent.web", cmd)
        self.assertIn("--host", cmd)
        self.assertIn("0.0.0.0", cmd)
        self.assertIn("--port", cmd)
        self.assertIn("8080", cmd)
        self.assertNotIn("8765", cmd)

    def test_dockerfile_exposes_only_8080(self) -> None:
        self.assertEqual(_expose_lines(DOCKERFILE), ["EXPOSE 8080"])

    def test_dockerfile_healthcheck_probes_internal_8080_healthz(self) -> None:
        block = _healthcheck_block(DOCKERFILE)
        self.assertIn("HEALTHCHECK", block)
        self.assertIn("http://127.0.0.1:8080/healthz", block)


class DocsContainerPortContractTests(unittest.TestCase):
    """README / DEPLOYMENT 必须区分容器内部端口与宿主机端口。"""

    def test_readme_and_deployment_map_host_8765_to_container_8080(self) -> None:
        self.assertIn("-p 8765:8080", README)
        self.assertIn("-p 8765:8080", DEPLOYMENT)
        self.assertNotIn("-p 8765:8765", README)
        self.assertNotIn("-p 8765:8765", DEPLOYMENT)

    def test_readme_and_deployment_curl_healthz_via_host_8765(self) -> None:
        self.assertIn("http://127.0.0.1:8765/healthz", README)
        self.assertIn("http://127.0.0.1:8765/healthz", DEPLOYMENT)

    def test_docs_state_8080_is_container_internal_port(self) -> None:
        # 比对时忽略 Markdown 反引号（``8080`` 即 8080）。
        combined = (README + "\n" + DEPLOYMENT).replace("`", "")
        self.assertIn("容器内 8080", combined)
        self.assertIn("对外维护的唯一应用端口是 8765", combined)
        self.assertIn("不再作为本仓库部署或验收入口", combined)
        self.assertIn("不要把宿主机端口写成容器内部监听端口", combined)


class NonContainerDefaultPortTests(unittest.TestCase):
    """非容器本地直接启动默认端口保持 8765，不被容器 8080 破坏。"""

    def test_main_cli_default_port_is_8765_when_env_unset(self) -> None:
        from bi_agent.web import __main__ as web_main

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.reload(web_main)
            self.assertEqual(module.DEFAULT_PORT, 8765)

    def test_main_cli_default_port_follows_app_port_env_for_container(self) -> None:
        from bi_agent.web import __main__ as web_main

        with mock.patch.dict(os.environ, {"APP_PORT": "8080"}, clear=True):
            module = importlib.reload(web_main)
            self.assertEqual(module.DEFAULT_PORT, 8080)

    def test_main_source_keeps_local_default_8765(self) -> None:
        self.assertIn("8765", MAIN_SRC)
        self.assertIn("DEFAULT_PORT", MAIN_SRC)


class HealthPortContractTests(unittest.TestCase):
    """/healthz 的 port 字段必须反映实际监听端口，不能硬编码 8765。"""

    def test_health_port_field_reflects_runtime_port_8080(self) -> None:
        from fastapi.testclient import TestClient

        from bi_agent.web.app import STATE, app, set_runtime_port

        previous = (STATE.agent_def, STATE.ontology_store, STATE.conversation_store, set_runtime_port)
        try:
            set_runtime_port(8080)
            STATE.agent_def = None
            STATE.ontology_store = None
            STATE.conversation_store = None
            response = TestClient(app).get("/healthz")
            self.assertEqual(response.json()["port"], 8080)
        finally:
            STATE.agent_def, STATE.ontology_store, STATE.conversation_store = previous[:3]

    def test_health_port_default_stays_8765_outside_container(self) -> None:
        from bi_agent.web.app import _default_app_port

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_default_app_port(), 8765)


if __name__ == "__main__":
    unittest.main()
