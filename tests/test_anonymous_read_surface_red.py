"""RED tests for the anonymous read surface（内网字段 + 绝对工作目录收敛）.

Contract source: ``docs/specs/anonymous-read-surface-hardening.md``
（来源：2026-09-21 PDT / demo2 真实环境只读验收暴露的 P4 与 P2 根因）。

Every assertion drives the **real production** entry points — nothing here
re-implements a response builder:

* ``GET /api/sources`` / ``PUT /api/sources``（`TestClient(app)`，未带任何凭据）；
* ``GET /api/system-prompt``；
* ``bi_agent.web.session.WebSession.system_prompt``（也就是发给模型的那一段提示）。

Two audited exposures make this file RED today:

1. ``GET /api/sources`` returns the configured Doris connection verbatim:
   ``jdbc:mysql://172.16.6.163:9030/ontology_…``, the HTTP API URL and the account
   name.  The password is already blank, so no credential leaks — but an
   anonymous reader still learns the internal host:port, the account and the
   database name.
2. The session system prompt carries a ``# Environment`` block with
   ``- Working directory: <absolute path>``（`open_claude/prompt.py:203-204`,
   taken from the process cwd, i.e. ``/app`` in the container）, and
   ``GET /api/system-prompt`` hands that prompt to any anonymous caller — so the
   model quotes the working directory back to the user.

Offline and deterministic: fake STATE values, temp cwd, no service, no LLM, no
credentials, and **no delete/reset endpoint is ever called**.
"""

from __future__ import annotations

import json
import re
import socket
import unittest
from contextlib import contextmanager
from typing import Any, Iterable

from fastapi.testclient import TestClient

from bi_agent.ontology.store import OntologyStore
from bi_agent.web.app import STATE, app, get_sources_endpoint
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef


# Distinctive fakes: if any of them shows up in an anonymous response we know
# exactly which field leaked, without ever touching a real deployment value.
FAKE_JDBC = "jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po?useSSL=false"
FAKE_API_URL = "http://172.16.6.163:8030/api/query"
FAKE_USERNAME = "svc_biuser_pdt"
FAKE_CWD = "/tmp/accept-anonymous-read"
FAKE_PASSWORD = "must-never-appear"

TOOLS = ["Ontology-MetricQuery", "Ontology-FactQuery", "AskUser"]
SESSION_ID = "anonymous-read-surface-test"

#: 私网地址：完整四段（`10.0.0.0/8` / `172.16.0.0/12` / `192.168.0.0/16`）。
_PRIVATE_IPV4_FULL = (
    r"(?<![\d.])"
    r"(?:10(?:\.\d{1,3}){3}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|192\.168(?:\.\d{1,3}){2})"
    r"(?![\d.])"
)

#: 私网地址的“掩码”写法（`172.16.*.*`）：保留了网段指纹，同样按泄露处理。
_PRIVATE_IPV4_MASKED = (
    r"(?<![\d.*])"
    r"(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\."
    r"(?=[\d*]{1,3}(?:\.[\d*]{1,3}){0,3}(?![\d.*]))"
    r"(?=[\d.*]*\*)"
    r"[\d*]{1,3}(?:\.[\d*]{1,3}){0,3}"
)

#: 进程主机名：本机 hostname 一旦出现在匿名响应里即为 §2.2 的“主机指纹”泄露。
_HOSTNAME = socket.gethostname().strip()
_HOSTNAME_IS_MEANINGFUL = len(_HOSTNAME) >= 3 and _HOSTNAME.lower() not in {
    "localhost", "localhost.localdomain", "localhost6", "none"}

#: §2.2 —— 匿名响应里一律不得出现的模式。
LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ipv4_with_port", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}\b")),
    ("private_ipv4", re.compile(_PRIVATE_IPV4_FULL)),
    ("private_ipv4_masked", re.compile(_PRIVATE_IPV4_MASKED)),
    ("jdbc_url", re.compile(r"\bjdbc:[a-z0-9]+:", re.IGNORECASE)),
    ("http_private_url", re.compile(
        r"\bhttps?://(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)[\d.*]*")),
    ("absolute_path", re.compile(
        r"(?<![\w.:/])/(?:app|srv|home|Users|opt|var|etc|root|data)(?:/[\w.@+-]+)*")),
    ("working_directory_line", re.compile(r"Working directory", re.IGNORECASE)),
    ("platform_fingerprint", re.compile(r"^\s*-\s*(?:Platform|OS):\s*\S", re.MULTILINE)),
    ("hostname_line", re.compile(r"^\s*-\s*(?:Host|Hostname|Container):\s*\S", re.MULTILINE)),
    ("hostname_value", re.compile(re.escape(_HOSTNAME))) if _HOSTNAME_IS_MEANINGFUL else
    ("hostname_value_disabled", re.compile(r"(?!)")),
)


def leaks_in(blob: str, *, secrets: Iterable[str] = ()) -> list[str]:
    """Return every §2.2 violation found in *blob* (empty list == clean).

    Shared by the red assertions and the mutation guards, so the guards exercise
    exactly the check the red tests rely on.
    """
    violations: list[str] = []
    for name, pattern in LEAK_PATTERNS:
        found = pattern.search(blob)
        if found:
            violations.append(f"{name}:{found.group(0)[:60]}")
    for secret in secrets:
        if secret and secret in blob:
            violations.append(f"secret_value:{secret[:24]}")
    return violations


def prompt_leaks(prompt: str) -> list[str]:
    """Absolute path / cwd line / host fingerprint violations of §2.4."""
    return [item for item in leaks_in(prompt)
            if item.split(":", 1)[0] in (
                "absolute_path", "working_directory_line",
                "platform_fingerprint", "hostname_line")]


def _source_fields() -> tuple[str, ...]:
    return ("cwd", "doris_jdbc_url", "doris_api_url", "doris_username",
            "doris_password", "doris_database", "doris_driver", "use_doris",
            "ontology_backend", "ontology_path", "db_path", "remote_ontology",
            "remote_catalog_error", "remote_catalog_last_attempt")


@contextmanager
def fake_source_state():
    """Install fake (never-real) source values and always restore them."""
    previous = {name: getattr(STATE, name) for name in _source_fields()}
    session = STATE.sessions.get(SESSION_ID)
    try:
        STATE.cwd = FAKE_CWD
        STATE.doris_jdbc_url = FAKE_JDBC
        STATE.doris_api_url = FAKE_API_URL
        STATE.doris_username = FAKE_USERNAME
        STATE.doris_password = FAKE_PASSWORD
        STATE.doris_database = "ontology_demometaerp_scm_po"
        STATE.doris_driver = "com.mysql.cj.jdbc.Driver"
        STATE.use_doris = True
        STATE.remote_ontology = None
        STATE.remote_catalog_error = ""
        STATE.remote_catalog_last_attempt = 0.0
        yield STATE
    finally:
        for name, value in previous.items():
            setattr(STATE, name, value)
        if session is None:
            STATE.sessions.pop(SESSION_ID, None)
        else:
            STATE.sessions[SESSION_ID] = session


def _client() -> TestClient:
    return TestClient(app)


def _sources_payload() -> dict[str, Any]:
    return json.loads(get_sources_endpoint().body)


def _session_prompt() -> str:
    return WebSession(FAKE_CWD, AgentDef("bi-analyst", tools=TOOLS), OntologyStore()).system_prompt


# ---------------------------------------------------------------------------
# 1. /api/sources 不得回吐内网物理标识
# ---------------------------------------------------------------------------

class SourcesExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = fake_source_state()
        self.state.__enter__()
        self.addCleanup(lambda: self.state.__exit__(None, None, None))
        self.payload = _sources_payload()
        self.blob = json.dumps(self.payload, ensure_ascii=False)

    def _doris(self) -> dict[str, Any]:
        return self.payload["doris"]

    def test_r1_sources_never_exposes_an_internal_host_and_port(self):
        """R1：匿名响应不得出现内网 host:port（含私网段前缀）。"""
        violations = [item for item in leaks_in(self.blob)
                      if item.split(":", 1)[0] in ("ipv4_with_port", "private_ipv4")]
        self.assertEqual(violations, [], msg=(
            "尚未实现：GET /api/sources 原样返回了内网 Doris 地址。"
            f"当前 doris 块：{json.dumps(self._doris(), ensure_ascii=False)}"
        ))

    def test_r2_sources_never_exposes_connection_urls(self):
        """R2：匿名响应不得出现 jdbc: 连接串或内网 http 地址。"""
        self.assertNotIn(FAKE_JDBC.split("?")[0], self.blob)
        self.assertNotIn(FAKE_API_URL, self.blob)
        violations = [item for item in leaks_in(self.blob)
                      if item.split(":", 1)[0] == "jdbc_url"]
        self.assertEqual(violations, [], msg=(
            f"尚未实现：连接串仍可见（jdbc_url={self._doris().get('jdbc_url')!r}，"
            f"api_url={self._doris().get('api_url')!r}）"
        ))

    def test_r3_sources_never_exposes_the_database_account(self):
        """R3：匿名响应不得出现数据库账号名。"""
        self.assertNotIn(FAKE_USERNAME, self.blob, msg=(
            f"尚未实现：账号名仍可见（username={self._doris().get('username')!r}）"
        ))

    def test_r4_sources_reports_configured_flags_instead(self):
        """R4：改为给出"已配置"布尔标志，设置页仍能显示状态。"""
        for name in ("jdbc_configured", "api_url_configured", "username_configured"):
            self.assertIn(name, self._doris(), msg=(
                f"尚未实现：doris.{name} 缺失；收敛后必须用布尔标志表达「已配置/未配置」。"
            ))
            self.assertIs(self._doris()[name], True)

    def test_r5_sources_returns_a_stable_placeholder_for_configured_fields(self):
        """R5：已配置字段返回占位符（非空、非真值、不含内网指纹、稳定）。"""
        for field, real in (("jdbc_url", FAKE_JDBC), ("api_url", FAKE_API_URL),
                            ("username", FAKE_USERNAME)):
            value = self._doris().get(field)
            self.assertNotEqual(value, real, msg=f"{field} 不得回吐真值")
            self.assertTrue(str(value or "").strip(),
                            msg=f"{field} 已配置时必须给出非空占位符（便于设置页显示）")
            self.assertEqual(leaks_in(str(value)), [], msg=f"{field} 的占位符本身含内网指纹")
        again = _sources_payload()["doris"]
        self.assertEqual(again.get("jdbc_url"), self._doris().get("jdbc_url"),
                         "占位符必须稳定，否则设置页会出现「每次刷新都变」的假值")

    def test_g6_sources_password_stays_blank(self):
        """G6（护栏）：口令仍然只返回空串。"""
        self.assertEqual(self._doris().get("password"), "")
        self.assertNotIn(FAKE_PASSWORD, self.blob)

    def test_g7_get_put_round_trip_has_no_side_effect(self):
        """G7（护栏）：把 GET 的值原样 PUT 回去不得改变配置、不得误清空。"""
        before = (STATE.doris_jdbc_url, STATE.doris_api_url, STATE.doris_username)
        response = _client().put("/api/sources", json={
            "database": self.payload["doris"]["value"],
            "doris_jdbc_url": self._doris().get("jdbc_url"),
            "doris_api_url": self._doris().get("api_url"),
            "doris_username": self._doris().get("username"),
        })
        self.assertLess(response.status_code, 400, msg=(
            f"设置页原样保存必须成功，当前返回 {response.status_code}: {response.content[:200]!r}"
        ))
        self.assertEqual(
            (STATE.doris_jdbc_url, STATE.doris_api_url, STATE.doris_username), before,
            msg="GET→PUT 往返不得改变已配置的连接值（占位符必须按「保持原值」处理）",
        )

    def test_g8_sources_keeps_the_logical_identifiers(self):
        """G8（护栏）：产品需要的逻辑标识仍然可读。"""
        self.assertEqual(self._doris().get("driver"), "com.mysql.cj.jdbc.Driver")
        self.assertEqual(self._doris().get("database"), "ontology_demometaerp_scm_po")
        self.assertIn("ontology", self.payload)
        self.assertIn("database", self.payload)
        self.assertIn("active", self.payload["ontology"])


# ---------------------------------------------------------------------------
# 2. 系统提示不得带绝对工作目录与主机指纹
# ---------------------------------------------------------------------------

class SystemPromptExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = fake_source_state()
        self.state.__enter__()
        self.addCleanup(lambda: self.state.__exit__(None, None, None))
        self.prompt = _session_prompt()

    def _endpoint_prompt(self) -> str:
        session = WebSession(FAKE_CWD, AgentDef("bi-analyst", tools=TOOLS), OntologyStore())
        STATE.sessions[SESSION_ID] = session
        self.addCleanup(lambda: STATE.sessions.pop(SESSION_ID, None))
        response = _client().get(f"/api/system-prompt?session_id={SESSION_ID}")
        self.assertEqual(response.status_code, 200, msg=response.content[:200])
        return json.loads(response.content)["system_prompt"]

    def test_r9_session_prompt_has_no_absolute_path(self):
        """R9：发给模型的提示不得含绝对文件系统路径。"""
        violations = [item for item in prompt_leaks(self.prompt)
                      if item.startswith(("absolute_path", "working_directory_line"))]
        self.assertEqual(violations, [], msg=(
            "尚未实现：系统提示里的 # Environment 块仍带绝对工作目录"
            f"（open_claude/prompt.py:203）：{violations}"
        ))

    def test_r10_session_prompt_drops_the_working_directory_line(self):
        """R10：不得出现 `Working directory:` 行。"""
        self.assertNotIn("Working directory", self.prompt, msg=(
            "尚未实现：提示里仍有 `- Working directory: <abs>` 行；本 Agent 没有文件/shell 工具，"
            "这一行只会把容器路径送给模型并让模型回吐给用户。"
        ))

    def test_r11_system_prompt_endpoint_is_equally_clean(self):
        """R11：`GET /api/system-prompt` 出口同样不得泄露路径与主机指纹。"""
        endpoint_prompt = self._endpoint_prompt()
        self.assertEqual(prompt_leaks(endpoint_prompt), [], msg=(
            "尚未实现：/api/system-prompt 未做收敛，匿名调用即可读到环境信息"
        ))

    def test_r12_session_prompt_hides_the_host_fingerprint(self):
        """R12：不得暴露 `Platform:` / `OS:` 取值等主机指纹。"""
        self.assertNotIn("- Platform:", self.prompt)
        self.assertNotIn("- OS:", self.prompt)

    def test_g13_session_prompt_keeps_its_sections_and_tools(self):
        """G13（护栏）：收敛不得把提示砍掉 —— 段落与工具清单必须保留。"""
        for header in ("# Tools", "# Guidelines", "# AnalysisContext"):
            self.assertIn(header, self.prompt, msg=f"{header} 段落丢失")
        for tool in TOOLS:
            self.assertIn(tool, self.prompt, msg=f"工具清单里缺少 {tool}")

    def test_g14_session_keeps_the_real_cwd_for_tools(self):
        """G14（护栏）：工具执行仍使用真实工作目录。"""
        session = WebSession(FAKE_CWD, AgentDef("bi-analyst", tools=TOOLS), OntologyStore())
        self.assertEqual(session.cwd, FAKE_CWD)


# ---------------------------------------------------------------------------
# 3. 匿名 GET 面统一扫描
# ---------------------------------------------------------------------------

class AnonymousSurfaceAuditTests(unittest.TestCase):
    ANONYMOUS_GETS = ("/healthz", "/api/sources", "/api/system-prompt")

    def setUp(self) -> None:
        self.state = fake_source_state()
        self.state.__enter__()
        self.addCleanup(lambda: self.state.__exit__(None, None, None))
        STATE.sessions[SESSION_ID] = WebSession(
            FAKE_CWD, AgentDef("bi-analyst", tools=TOOLS), OntologyStore())
        self.addCleanup(lambda: STATE.sessions.pop(SESSION_ID, None))
        self.client = _client()

    def test_r15_every_anonymous_get_is_free_of_infrastructure_fields(self):
        """R15：三个匿名 GET 统一按 §2.2 扫描，逐端点归因。"""
        secrets = (FAKE_JDBC, FAKE_API_URL, FAKE_USERNAME, FAKE_PASSWORD, FAKE_CWD)
        for path in self.ANONYMOUS_GETS:
            with self.subTest(path=path):
                query = f"?session_id={SESSION_ID}" if "system-prompt" in path else ""
                response = self.client.get(path + query)
                # 离线环境未配置依赖时 /healthz 走既有 not_ready 分支（503），
                # 这也是 `test_healthz_never_requires_a_model_call` 的契约；
                # 这里只要求“匿名可读”，401/403 才表示被凭据拦截。
                self.assertIn(response.status_code, (200, 503), msg=(
                    f"{path} 应可匿名读取（200/503 均可，401/403 表示需要凭据）"))
                violations = leaks_in(response.text, secrets=secrets)
                self.assertEqual(violations, [], msg=(
                    f"尚未实现：{path} 泄露基础设施字段 {violations}"
                ))

    def test_r16_healthz_does_not_reveal_the_machine_hostname(self):
        """R16：`/healthz` 不得回吐主机名（§2.2 的“主机指纹”）。"""
        response = self.client.get("/healthz")
        self.assertIn(response.status_code, (200, 503), msg="匿名健康检查不应要求凭据")
        payload = response.json()
        host = payload.get("host")
        self.assertNotEqual(str(host or ""), _HOSTNAME, msg=(
            f"尚未实现：/healthz 的 host 字段仍是主机名 {host!r}；"
            "匿名健康检查可删除该字段或返回常量占位符，不得带主机指纹。"
        ))
        self.assertEqual(leaks_in(response.text, secrets=(_HOSTNAME,)), [], msg=(
            f"尚未实现：/healthz 响应体里出现主机名 {_HOSTNAME!r}"
        ))


# ---------------------------------------------------------------------------
# 4. Mutation guards：这些检查器必须能杀死对应变异
# ---------------------------------------------------------------------------

class MutationGuardTests(unittest.TestCase):
    def test_real_doris_block_is_caught(self):
        blob = json.dumps({"doris": {"jdbc_url": FAKE_JDBC, "api_url": FAKE_API_URL,
                                     "username": FAKE_USERNAME}})
        violations = leaks_in(blob, secrets=(FAKE_USERNAME,))
        self.assertTrue(any(item.startswith("ipv4_with_port") for item in violations))
        self.assertTrue(any(item.startswith("private_ipv4") for item in violations))
        self.assertTrue(any(item.startswith("jdbc_url") for item in violations))
        self.assertTrue(any(item.startswith("secret_value") for item in violations))

    def test_masked_but_range_preserving_value_is_still_caught(self):
        self.assertTrue(leaks_in("jdbc:mysql://172.16.*.*:****/db"))
        self.assertTrue(any(item.startswith("private_ipv4")
                            for item in leaks_in("host 192.168.*.* api 10.*.*.*")))

    def test_hostname_value_in_a_response_is_caught(self):
        """杀掉“把主机名留在匿名响应里”的变异。"""
        if not _HOSTNAME_IS_MEANINGFUL:
            self.skipTest("本机 hostname 无区分度，该变异在此环境不可测量")
        blob = json.dumps({"host": _HOSTNAME, "status": "ok",
                           "message": f"served by {_HOSTNAME}"})
        violations = leaks_in(blob, secrets=(_HOSTNAME,))
        self.assertTrue(any(item.startswith("hostname_value") for item in violations))
        self.assertTrue(any(item.startswith("secret_value") for item in violations))

    def test_clean_placeholder_is_accepted(self):
        self.assertEqual(leaks_in("（已配置，见服务端环境变量）"), [])
        self.assertEqual(leaks_in(""), [])

    def test_prompt_with_absolute_cwd_is_caught(self):
        prompt = "# Environment\n- Working directory: /app\n- Platform: linux\n- OS: Ubuntu 22.04\n"
        violations = prompt_leaks(prompt)
        self.assertTrue(any(item.startswith("absolute_path") for item in violations))
        self.assertTrue(any(item.startswith("working_directory_line") for item in violations))
        self.assertTrue(any(item.startswith("platform_fingerprint") for item in violations))

    def test_prompt_with_a_container_only_path_is_caught(self):
        self.assertTrue(any(item.startswith("absolute_path")
                            for item in prompt_leaks("- Working directory: /srv/agent/app")))

    def test_relative_working_directory_line_is_still_caught(self):
        """把值换成相对路径也得删行：该行本身对无 shell 工具的 Agent 无用途。"""
        self.assertTrue(any(item.startswith("working_directory_line")
                            for item in prompt_leaks("# Environment\n- Working directory: .\n")))

    def test_deleting_the_whole_prompt_is_caught_by_the_guard(self):
        """护栏检查必须能发现"为了收敛把提示砍掉"的变异。"""
        prompt = ""
        self.assertNotIn("# Tools", prompt)
        self.assertNotIn("# AnalysisContext", prompt)

    def test_real_prompt_profile_is_caught_but_sanitised_one_passes(self):
        violated = ("# Environment\n- Working directory: /Users/dev/repo\n"
                    "- Platform: darwin\n- OS: Darwin 25.5.0\n- Date: 2026-09-21\n")
        self.assertTrue(prompt_leaks(violated))
        sanitised = "# Environment\n- Date: 2026-09-21\n"
        self.assertEqual(prompt_leaks(sanitised), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
