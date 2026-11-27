"""360 conversation history survives a refresh/process restart (customer-safe)."""
from pathlib import Path

from fastapi.testclient import TestClient

from bi_agent.web import app as web

ROOT = Path(__file__).resolve().parents[1]


def test_analysis360_history_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(web.STATE, "cwd", str(tmp_path))
    client = TestClient(web.app)
    turns = [{"id": "turn-1", "user": "商机覆盖风险", "assistant": {"text": "结论", "tools": []}}]
    saved = client.post("/api/analysis360/history",
                        json={"session_id": "a360-test", "title": "商机覆盖风险", "turns": turns})
    assert saved.status_code == 200
    assert saved.json()["id"] == "a360-test"

    listed = client.get("/api/analysis360/history")
    assert listed.status_code == 200
    items = listed.json()["conversations"]
    assert any(item["id"] == "a360-test" and item["title"] == "商机覆盖风险" for item in items)

    record = client.get("/api/analysis360/history/a360-test")
    assert record.status_code == 200
    assert record.json()["turns"][0]["user"] == "商机覆盖风险"
    assert (tmp_path / "dataset" / "analysis360-history" / "a360-test.json").is_file()


def test_analysis360_history_rejects_bad_ids_and_missing_records(tmp_path, monkeypatch):
    monkeypatch.setattr(web.STATE, "cwd", str(tmp_path))
    client = TestClient(web.app)
    assert client.get("/api/analysis360/history/a360-missing").status_code == 404
    assert client.post("/api/analysis360/history",
                       json={"session_id": "../escape", "turns": []}).status_code == 400
