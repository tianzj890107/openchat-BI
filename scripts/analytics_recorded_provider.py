#!/usr/bin/env python3
"""Deterministic recorded-provider replay for the analytics golden set.

Why this exists
---------------
The deterministic ``sql`` / ``policy`` / ``ontology`` evaluators in
``scripts/run_analytics_eval.py`` assert one layer each.  They cannot prove that
the *whole* agent turn works: policy -> tool plan -> tool arguments -> real tool
execution -> evidence -> render -> final answer -> session state.

This module drives the **production** turn loop
(``bi_agent.web.session.WebSession.generate_turn``) with a recorded provider
stream.  Nothing is faked except the model's token stream:

* the loop, the topology of iterations, the tool boundary, the recovery state
  machine, the claim/evidence validation and the SSE event shape are all the
  production implementations;
* tools are the production tool implementations, with SQL bound to the
  read-only eval SQLite fixture and the ontology bound to the eval workbook;
* every write lands in a per-case temporary workspace;
* no network call is possible: the SQL backend is a local SQLite file and the
  provider is the recorder below.

The recorder replays provider-level events (``text_delta`` / ``tool_use_*`` /
``message_end``) derived from a human-readable transcript that also carries the
expected tool order, tool inputs and result assertions.
"""

from __future__ import annotations

import copy
import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
FIXTURE_DIR = EVAL_ROOT / "fixtures"
SQLITE_DIR = FIXTURE_DIR / "sqlite"
PROVIDER_DIR = FIXTURE_DIR / "provider"
ONTOLOGY_XLSX = FIXTURE_DIR / "ontology" / "analytics_golden_ontology.xlsx"

# Deterministic model key used for every replay.  It advertises no extended
# thinking so the loop performs exactly one provider call per iteration.
RECORDED_MODEL_KEY = "sonnet4.6"

# SSE events that represent one executed (or policy-suppressed) tool call.
_TOOL_EVENT_TYPES = frozenset({"tool_result", "chart_suppressed", "tool_suppressed"})

_TOOL_SEQUENCE_LOCK = threading.Lock()
_REGISTERED = False


# ---------------------------------------------------------------------------
# transcript -> provider iterations
# ---------------------------------------------------------------------------
class TranscriptError(ValueError):
    """The recording is malformed or the replay diverged from it."""


def _iterations_from_events(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Translate one turn's flat transcript into provider-level iterations.

    Consecutive ``tool_start`` ... ``tool_result`` blocks become one provider
    iteration ending with ``stop_reason="tool_use"``; consecutive ``text_delta``
    events become one iteration ending with ``stop_reason="end_turn"``.
    """
    iterations: list[list[dict[str, Any]]] = []
    pending_tools: list[tuple[str, dict[str, Any]]] = []
    pending_text: list[str] = []

    def flush_tools() -> None:
        if not pending_tools:
            return
        group = list(pending_tools)
        pending_tools.clear()
        out: list[dict[str, Any]] = []
        for name, payload in group:
            counter_local = len(out) + 1
            tool_id = f"rec-{len(iterations)}-{counter_local}"
            out.append({"type": "tool_use_start", "id": tool_id, "name": name})
            out.append({"type": "tool_use_end", "id": tool_id, "name": name,
                        "input": payload.get("input") or {}})
        out.append({"type": "message_end", "stop_reason": "tool_use",
                    "usage": {"input_tokens": 0, "output_tokens": 0}})
        iterations.append(out)

    def flush_text() -> None:
        if not pending_text:
            return
        parts = list(pending_text)
        pending_text.clear()
        out = [{"type": "text_delta", "text": part} for part in parts]
        out.append({"type": "message_end", "stop_reason": "end_turn",
                    "usage": {"input_tokens": 0, "output_tokens": 0}})
        iterations.append(out)

    for event in events:
        etype = str(event.get("type") or "")
        if etype == "tool_start":
            flush_text()
            pending_tools.append((str(event.get("name") or ""), event))
        elif etype == "tool_result":
            # The recorded result is an assertion, not an LLM event: the
            # production tool really executes and its real output is asserted
            # against this recording by the evaluator.
            pass
        elif etype == "text_delta":
            flush_tools()
            pending_text.append(str(event.get("text") or ""))
        elif etype in {"cognitive_policy", "done", "session_state", "recovery"}:
            # metadata / assertions, not provider events
            continue
        else:
            raise TranscriptError(f"unknown recorded event type: {etype!r}")
    flush_tools()
    flush_text()
    if not iterations:
        raise TranscriptError("recording produced no provider iterations")
    return iterations


def _declared_tools(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if str(e.get("type")) == "tool_start"]


def _declared_text(events: list[dict[str, Any]]) -> str:
    return "".join(str(e.get("text") or "") for e in events
                   if str(e.get("type")) == "text_delta")


def load_transcript(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TranscriptError("recording must be a JSON object")
    if int(data.get("version") or 0) != 1:
        raise TranscriptError("unsupported recording version")
    if str(data.get("provider") or "") != "recorded":
        raise TranscriptError("recording provider must be 'recorded'")
    turns = data.get("turns")
    if not isinstance(turns, list) or not turns:
        raise TranscriptError("recording needs a non-empty 'turns' list")
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict) or not isinstance(turn.get("events"), list):
            raise TranscriptError(f"turn {index} needs an 'events' list")
        _iterations_from_events(turn["events"])
    return data


# ---------------------------------------------------------------------------
# the recorder
# ---------------------------------------------------------------------------
class Recorder:
    """Stands in for ``bi_agent.llm.provider.stream_message``."""

    def __init__(self, iterations: list[list[dict[str, Any]]], turn_ref: str = "") -> None:
        self.iterations = [list(group) for group in iterations]
        self.turn_ref = turn_ref
        self.calls: list[dict[str, Any]] = []
        self.overrun = False

    # Signature mirrors bi_agent.llm.provider.stream_message.
    def __call__(self, messages, system_prompt, allowed_tools=None, model_key="",
                 max_tokens=0, temperature=0.0, thinking=False,
                 cancel_event=None):
        self.calls.append({
            "message_count": len(messages or []),
            "allowed_tools": list(allowed_tools or []),
            "model_key": model_key,
            "thinking": bool(thinking),
            "system_prompt_chars": len(system_prompt or ""),
        })
        if not self.iterations:
            self.overrun = True
            yield {"type": "error",
                   "error": f"recorded provider exhausted after {len(self.calls)} calls"}
            return
        for event in self.iterations.pop(0):
            yield copy.deepcopy(event)


# ---------------------------------------------------------------------------
# session construction / replay
# ---------------------------------------------------------------------------
def _ensure_registration(store, db_path: str, fixture_dir: Optional[Path] = None) -> dict:
    """Populate the global tool registry with the eval-bound BI tools."""
    global _REGISTERED
    from bi_agent.tools import build_source_executors, register_all

    with _TOOL_SEQUENCE_LOCK:
        if not _REGISTERED:
            register_all(store, db_path)
            _REGISTERED = True
    return build_source_executors(store, db_path)


def _pin_runtime_config() -> None:
    from bi_agent.llm import runtime_config

    cfg = runtime_config.get_config()
    cfg.model_key = RECORDED_MODEL_KEY
    cfg.max_tokens = 4096
    cfg.temperature = 0.0
    cfg.thinking = False


def _load_agent_def():
    from open_claude.agent_def import get_agent_def_registry, load_agent_defs

    load_agent_defs(str(REPO_ROOT))
    registry = get_agent_def_registry()
    for name in ("bi-analyst", "data-analyst"):
        agent = registry.get(name)
        if agent is not None:
            return agent
    candidates = registry.get_all()
    if not candidates:
        raise TranscriptError("no agent definition found under .claude/agents")
    return candidates[0]


def _load_ontology():
    from bi_agent.ontology.store import OntologyStore

    return OntologyStore.from_xlsx(ONTOLOGY_XLSX)


class RecordedRun:
    """Everything the recorded-provider evaluators assert against."""

    def __init__(self, case_id: str) -> None:
        self.case_id = case_id
        self.turn_events: list[list[dict[str, Any]]] = []
        self.events: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.provider_calls: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.session: Any = None
        self.workspace: Optional[Path] = None

    @property
    def tool_names(self) -> list[str]:
        return [str(call.get("name") or "") for call in self.tool_calls]

    @property
    def outputs(self) -> str:
        return "\n".join(str(call.get("output") or "") for call in self.tool_calls)

    @property
    def text(self) -> str:
        return "".join(str(e.get("text") or "") for e in self.events
                       if str(e.get("type")) == "text_delta")

    @property
    def done_stop_reason(self) -> str:
        reasons = [str(e.get("stop_reason") or "") for e in self.events
                   if str(e.get("type")) == "done"]
        return reasons[-1] if reasons else ""

    @property
    def superseded(self) -> bool:
        return any(str(e.get("type")) == "session_superseded" for e in self.events)


def run_recorded_turns(
    case_id: str,
    turns: list[dict[str, Any]],
    *,
    fixture_db: str,
    workspace: Path,
    tools_override: Optional[list[str]] = None,
) -> RecordedRun:
    """Replay a recorded transcript through the real WebSession turn loop."""
    from unittest.mock import patch

    import bi_agent.web.session as session_module
    from bi_agent.web.session import WebSession

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = SQLITE_DIR / fixture_db
    if not db_path.is_file():
        raise TranscriptError(f"fixture db missing: {db_path}")

    _pin_runtime_config()
    store = _load_ontology()
    executors = _ensure_registration(store, str(db_path))
    agent_def = _load_agent_def()

    session = WebSession(
        cwd=str(workspace),
        agent_def=agent_def,
        ontology_store=store,
        tools_override=tools_override,
        ontology_backend="local",
        tool_executors=executors,
    )

    run = RecordedRun(case_id)
    run.session = session
    run.workspace = workspace

    for index, turn in enumerate(turns):
        iterations = _iterations_from_events(turn["events"])
        recorder = Recorder(iterations, turn_ref=f"turn-{index}")
        question = str(turn.get("user") or turn.get("question") or "")
        start_events = len(run.events)
        start_records = len(session.tool_execution_records)
        with patch.object(session_module, "stream_message", recorder):
            for event in session.generate_turn(question):
                run.events.append(event)
        run.turn_events.append(run.events[start_events:])
        run.provider_calls.extend(recorder.calls)
        if recorder.overrun:
            run.errors.append(
                f"turn {index}: provider called more times than recorded"
            )
        statuses = {
            str(record.get("tool_use_id") or ""): record
            for record in list(session.tool_execution_records)[start_records:]
        }
        for event in run.events[start_events:]:
            kind = str(event.get("type") or "")
            if kind not in _TOOL_EVENT_TYPES:
                continue
            record = statuses.get(str(event.get("id") or ""), {})
            output = str(event.get("output") or event.get("message") or "")
            run.tool_calls.append({
                "turn": index,
                "name": str(event.get("name") or ""),
                "input": copy.deepcopy(event.get("input") or {}),
                "output": output,
                "status": str(record.get("status") or ("SUPPRESSED" if kind != "tool_result" else "")),
                "error_code": str(record.get("error_code") or ""),
                "event": kind,
            })

    run.errors.extend(
        str(e.get("message") or e.get("error") or "")
        for e in run.events if str(e.get("type")) == "error"
    )
    return run
