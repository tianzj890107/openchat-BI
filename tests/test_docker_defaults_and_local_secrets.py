"""TDD Red: additive env synchronization and fixed Docker defaults."""

from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")

TEAM_MODELS = "mimo-v2.5,qwen3.5-397b-a17b,doubao-seed-2-0-code-preview-260215,Qwen/Qwen3-80B-AWQ,kimi-k2.6,doubao-seed-2-0-pro-260215,direct-deepseek-v4-pro,doubao-seed-2-0-lite-260428,glm-5.2,glm-5.1,qwen3.7-plus,glm-5v-turbo,mimo-v2.5-pro,doubao-seed-2-0-mini-260428,glm-5-turbo,doubao-seed-2-1-turbo-260628,qwen3-vl-plus,qwen3.5-122b-a10b,doubao-seed-2-1-pro-260628,qwen3-vl-flash,direct-deepseek-v4-flash,qwen3.8-2.4t-a95b,qwen3.8-27b,deepseek-v4-flash-0731"
NON_SECRET_DEFAULTS = {
    "APP_ROOT_PATH": "/api/ontology-agentic-analytics",
    "APP_NAME": "eimosp-ontology-agentic-analytics", "APP_HOST": "0.0.0.0", "APP_PORT": "8080",
    "LLM_PROVIDER": "team", "TEAM_BASE_URL": "http://172.16.10.34:4000/v1",
    "TEAM_MODEL": "direct-deepseek-v4-flash", "TEAM_MODELS": TEAM_MODELS,
    "TEAM_DEEPSEEK_ENABLE_THINKING": "true", "TEAM_QWEN_ENABLE_THINKING": "",
    "ONTOLOGY_BACKEND": "production", "ONTOLOGY_BASE_URL": "http://172.16.5.181:30834",
    "ONTOLOGY_REPOSITORY_ID": "3", "ONTOLOGY_APP_ID": "ApTH1EHKdRk58WhDQB",
    "ONTOLOGY_TIMEOUT_SECONDS": "30", "ONTOLOGY_CACHE_TTL_SECONDS": "30",
    "RETRIEVAL_MODE": "semantic",
    "DORIS_API_URL": "http://172.16.5.181:30834/agent/doris/query",
    "DORIS_DATABASE": "ontology_demometaerp_scm_po",
    "CONVERSATION_SYNC_URL": "http://172.16.10.34:8765",
    "CHATBI_MAX_ACTIVE_TURNS": "8", "CHATBI_MAX_ACTIVE_PER_PRINCIPAL": "2",
    "CHATBI_MAX_WAITING_TURNS": "32", "CHATBI_ADMISSION_WAIT_SECONDS": "2",
    "CHATBI_LLM_CONCURRENCY": "6", "CHATBI_DORIS_CONCURRENCY": "12",
    "CHATBI_ONTOLOGY_CONCURRENCY": "12", "CHATBI_SESSION_IDLE_TTL_SECONDS": "7200",
    "CHATBI_MAX_IN_MEMORY_SESSIONS": "500", "CHATBI_COORDINATION_MODE": "local",
    "CHATBI_COORDINATION_NAMESPACE": "chatbi", "CHATBI_COORDINATION_FAILURE_MODE": "closed",
    "TASK_ALERT_API_ENABLED": "true",
    "TASK_ALERT_API_URL": "http://pdt-dev.eimos.com/api/x360/v1/task-alert/manual-create",
    "TASK_ALERT_DEFAULT_ASSIGNEE": "400", "TASK_ALERT_DEFAULT_LEVEL": "WARNING",
    "TASK_ALERT_DEFAULT_BP_DEFINITION_ID": "", "TASK_ALERT_TIMEOUT_SECONDS": "10",
}
BASELINE_LOCAL_ENV_KEYS = {
    "CONVERSATION_SYNC_URL", "DASHSCOPE_API_KEY", "GITLAB_TOKEN", "LLM_PROVIDER",
    "ONTOLOGY_APP_ID", "ONTOLOGY_BACKEND", "ONTOLOGY_BASE_URL", "ONTOLOGY_REPOSITORY_ID",
    "QWEN_API_KEY", "QWEN_BASE_URL", "QWEN_ENABLE_THINKING", "QWEN_MODEL",
    "QWEN_PREFERRED_TEXT_MODEL", "QWEN_PREFERRED_VISION_MODEL", "QWEN_TEXT_MODEL",
    "QWEN_TEXT_MODELS", "QWEN_VISION_MODELS", "TASK_ALERT_API_ENABLED",
    "TASK_ALERT_API_URL", "TASK_ALERT_DEFAULT_ASSIGNEE", "TASK_ALERT_DEFAULT_BP_DEFINITION_ID",
    "TASK_ALERT_DEFAULT_LEVEL", "TASK_ALERT_TIMEOUT_SECONDS", "TEAM_API_KEY", "TEAM_BASE_URL",
    "TEAM_DEEPSEEK_ENABLE_THINKING", "TEAM_MODEL", "TEAM_MODELS", "TEAM_QWEN_ENABLE_THINKING",
}
RUNTIME_SECRET_KEYS = {"TEAM_API_KEY", "ONTOLOGY_AUTH_TOKEN", "DORIS_PASSWORD"}
ALL_ENV_KEYS = BASELINE_LOCAL_ENV_KEYS | set(NON_SECRET_DEFAULTS) | RUNTIME_SECRET_KEYS
BASELINE_SERVER_ENV_KEYS = BASELINE_LOCAL_ENV_KEYS - {"GITLAB_TOKEN"}
SERVER_ENV_PATH = "/home/data/zhangzhen_home/zhangzhen/eimosp-ontology-agentic-analytics-releases/v0.1.2/.env"
ALL_SECRET_KEYS = {
    "TEAM_API_KEY", "ONTOLOGY_AUTH_TOKEN", "DORIS_PASSWORD", "GITLAB_TOKEN",
    "DASHSCOPE_API_KEY", "QWEN_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
}


def assignments(text: str) -> dict[str, str]:
    found = re.findall(r"(?m)^\s*(?:ENV\s+)?([A-Z][A-Z0-9_]*)=(.*?)\s*(?:\\)?$", text)
    return dict(found)


class DockerDefaultsAndLocalSecretsTests(unittest.TestCase):
    def test_dockerfile_contains_all_fixed_non_secret_defaults(self) -> None:
        actual = assignments(DOCKERFILE)
        for name, value in NON_SECRET_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(actual.get(name), value)

    def test_qwen_model_catalogs_are_baked_and_consistent(self) -> None:
        """Qwen catalogs are fixed non-secret defaults baked into the image."""
        docker = assignments(DOCKERFILE)
        example = assignments((ROOT / ".env.example").read_text(encoding="utf-8"))
        catalogs = ("QWEN_TEXT_MODELS", "QWEN_VISION_MODELS")
        for name in catalogs:
            with self.subTest(name=name, source="Dockerfile"):
                self.assertTrue(docker.get(name), f"Dockerfile must bake {name}")
            with self.subTest(name=name, source=".env.example"):
                self.assertEqual(example.get(name), docker.get(name))
        env_path = ROOT / ".env"
        if env_path.exists():
            local = assignments(env_path.read_text(encoding="utf-8"))
            for name in catalogs:
                with self.subTest(name=name, source=".env"):
                    self.assertEqual(local.get(name), docker.get(name))

    def test_dockerfile_never_bakes_secrets_or_env_file(self) -> None:
        for name in ALL_SECRET_KEYS:
            with self.subTest(name=name):
                self.assertNotRegex(DOCKERFILE, rf"(?m)^\s*(?:ENV\s+|ARG\s+)?{name}\s*=")
        self.assertNotRegex(DOCKERFILE, r"(?mi)^\s*(?:COPY|ADD)\s+[^\n]*\.env(?:\s|$)")

    def test_local_env_preserves_every_preexisting_key(self) -> None:
        env_path = ROOT / ".env"
        if not env_path.exists():
            self.skipTest("CI checkout intentionally has no ignored .env")
        keys = set(assignments(env_path.read_text(encoding="utf-8")))
        self.assertTrue(BASELINE_LOCAL_ENV_KEYS <= keys, BASELINE_LOCAL_ENV_KEYS - keys)

    def test_local_env_adds_complete_runtime_contract_without_deletion(self) -> None:
        env_path = ROOT / ".env"
        if not env_path.exists():
            self.skipTest("CI checkout intentionally has no ignored .env")
        actual = assignments(env_path.read_text(encoding="utf-8"))
        self.assertTrue(ALL_ENV_KEYS <= set(actual), ALL_ENV_KEYS - set(actual))
        for name, value in NON_SECRET_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(actual.get(name), value)

    def test_local_runtime_secrets_are_present(self) -> None:
        """Local .env must carry every runtime secret key.

        TEAM_API_KEY is required non-empty because the agent cannot reach the
        LLM gateway without it.  ONTOLOGY_AUTH_TOKEN/DORIS_PASSWORD have no
        derivable value (they are empty on the 10.34 server too), so the spec
        keeps them as explicit empty placeholders until ops injects real
        values through .env or the platform secret; this gate only keeps the
        keys from silently disappearing.
        """
        env_path = ROOT / ".env"
        if not env_path.exists():
            self.skipTest("CI checkout intentionally has no ignored .env")
        actual = assignments(env_path.read_text(encoding="utf-8"))
        for name in RUNTIME_SECRET_KEYS:
            with self.subTest(secret=name):
                self.assertIn(name, actual, f"{name} key must exist in .env")
        self.assertTrue(
            actual["TEAM_API_KEY"].strip(), "TEAM_API_KEY must not be empty",
        )

    def test_example_is_complete_server_env_template(self) -> None:
        example = assignments((ROOT / ".env.example").read_text(encoding="utf-8"))
        self.assertTrue(ALL_ENV_KEYS <= set(example), ALL_ENV_KEYS - set(example))
        for name, value in NON_SECRET_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(example.get(name), value)
        for name in ALL_SECRET_KEYS & ALL_ENV_KEYS:
            with self.subTest(secret=name):
                value = example[name].strip()
                self.assertTrue(not value or value.startswith("<") or value.startswith("${"))

    @unittest.skipUnless(
        os.getenv("RUN_SERVER_ENV_SYNC_TESTS") == "1",
        "set RUN_SERVER_ENV_SYNC_TESTS=1 for read-only 10.34 verification",
    )
    def test_company_server_env_is_additively_synchronized(self) -> None:
        key_output = subprocess.check_output(
            [
                "ssh", "172.16.10.34", "awk", "-F=",
                "/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}", SERVER_ENV_PATH,
            ],
            text=True,
        )
        server_keys = set(key_output.splitlines())
        self.assertTrue(BASELINE_SERVER_ENV_KEYS <= server_keys, BASELINE_SERVER_ENV_KEYS - server_keys)
        self.assertTrue((set(NON_SECRET_DEFAULTS) | RUNTIME_SECRET_KEYS) <= server_keys,
                        (set(NON_SECRET_DEFAULTS) | RUNTIME_SECRET_KEYS) - server_keys)

        values = subprocess.check_output(
            ["ssh", "172.16.10.34", "awk", "-F=",
             "/^TEAM_API_KEY=/{print $1 \"=\" $2}", SERVER_ENV_PATH],
            text=True,
        )
        for line in values.splitlines():
            name, _, value = line.partition("=")
            self.assertTrue(value.strip(), f"server secret {name} must not be empty")

    def test_local_env_is_ignored_by_git_and_docker(self) -> None:
        for text, label in ((GITIGNORE, ".gitignore"), (DOCKERIGNORE, ".dockerignore")):
            with self.subTest(file=label):
                self.assertRegex(text, r"(?m)^/?\.env$")
                self.assertRegex(text, r"(?m)^/?\.env\.\*$")

    def test_no_local_env_file_is_tracked(self) -> None:
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z", ".env", ".env.*"], cwd=ROOT,
        ).decode("utf-8", errors="replace").split("\0")
        tracked = [item for item in tracked if item and item != ".env.example"]
        self.assertEqual(tracked, [])

    def test_internal_healthcheck_remains_unprefixed(self) -> None:
        self.assertIn("http://127.0.0.1:8080/healthz", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
