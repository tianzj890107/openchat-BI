"""TDD Red: repository server references must use a literal IP, never an SSH alias."""

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ALIAS = "company" + "-server"
SERVER_IP = "172.16.10.34"


class LiteralIpServerReferenceTests(unittest.TestCase):
    def test_no_tracked_text_file_uses_server_alias(self) -> None:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
        hits: list[str] = []
        for raw_path in paths:
            if not raw_path:
                continue
            relative = raw_path.decode("utf-8", errors="surrogateescape")
            data = (ROOT / relative).read_bytes()
            if b"\0" in data:
                continue
            for line_number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if FORBIDDEN_ALIAS in line.lower():
                    hits.append(f"{relative}:{line_number}")
        self.assertEqual(hits, [], "SSH alias remains in: " + ", ".join(hits))

    def test_server_env_integration_test_uses_literal_ip(self) -> None:
        contract = (ROOT / "tests/test_docker_defaults_and_local_secrets.py").read_text(encoding="utf-8")
        self.assertIn(f'"ssh", "{SERVER_IP}"', contract)


if __name__ == "__main__":
    unittest.main()
