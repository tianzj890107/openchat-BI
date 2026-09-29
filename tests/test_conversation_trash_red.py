"""RED tests for the conversation recycle bin（会话回收站）.

Contract source: ``docs/specs/conversation-trash-recycle-bin.md``
（来源：2026-09-21 需求「记忆管理页做成删除会话的回收站」）。

Every assertion drives the **real production** entry points — nothing here
re-implements a store or a response builder:

* ``DELETE /api/conversations/{cid}`` / ``GET /api/conversations``（`TestClient(app)`）；
* ``GET /api/conversations/trash``、``POST …/trash/{cid}/restore``、
  ``DELETE …/trash/{cid}``、``DELETE …/trash?confirm=1``（本批新增契约）；
* ``bi_agent.web.conversations.ConversationStore``（快照文件、`history_index.json`、保留期）；
* 「记忆管理」页的 DOM 契约：``frontend/src/shell.html`` 的 ``#view-memory``；
* 侧边栏与导航接线：``frontend/src/runtime.js``。

Offline and deterministic: ``TemporaryDirectory()`` + ``configure(tmp, …)``, so every
write lands in a throwaway workspace.  This file **never** reads, edits or deletes a
real user conversation, and it is the explicit "verify the delete feature" scope the
repository rules allow — nothing outside the temp dir is touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from unittest.mock import patch

from fastapi.testclient import TestClient

from bi_agent.ontology.store import OntologyStore
from bi_agent.web import app as web_app_module
from bi_agent.web.app import STATE, app
from bi_agent.web.conversations import MAX_CONVERSATIONS, ConversationStore
from open_claude.agent_def import AgentDef, get_agent_def_registry

ROOT = Path(__file__).resolve().parents[1]
SHELL_HTML = (ROOT / "frontend/src/shell.html").read_text(encoding="utf-8")
RUNTIME_JS = (ROOT / "frontend/src/runtime.js").read_text(encoding="utf-8")

#: §2.8 —— 回收站列表**只能**回这些键（元数据白名单）。
TRASH_METADATA_KEYS = frozenset({
    "id", "mode", "title", "first_user_question", "created_at", "updated_at",
    "deleted_at", "turn_count", "message_count", "expires_at", "days_left",
})

#: §2.8 —— 一旦出现在回收站列表里就说明匿名读取面被扩大了。
TRASH_FORBIDDEN_KEYS = frozenset({
    "messages", "chat_html", "dashboard_html", "ontology_html", "tools_html",
    "llm_html", "source_config", "recovery_state", "preview",
})

#: §2.2 —— 删除前必须逐字段保留的会话内容。
PRESERVED_KEYS = ("mode", "title", "first_user_question", "created_at", "updated_at",
                  "messages", "chat_html", "turn_count", "message_count")

RETENTION_ENV = "CONVERSATION_TRASH_RETENTION_DAYS"


# ---------------------------------------------------------------------------
# 共用检查器（红测与 Mutation Guard 用同一份，避免两套口径）
# ---------------------------------------------------------------------------

def metadata_violations(payload: Any) -> list[str]:
    """Return every §2.8 violation of a trash listing (empty list == clean)."""
    violations: list[str] = []
    entries = payload.get("trash") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return ["payload:trash 列表缺失"]
    for entry in entries:
        if not isinstance(entry, dict):
            violations.append("entry:非对象")
            continue
        unknown = set(entry) - TRASH_METADATA_KEYS
        if unknown:
            violations.append(f"{entry.get('id')}:多出字段 {sorted(unknown)}")
        leaked = set(entry) & TRASH_FORBIDDEN_KEYS
        if leaked:
            violations.append(f"{entry.get('id')}:泄露正文 {sorted(leaked)}")
    return violations


def active_ids(payload: Any) -> list[str]:
    """Ids visible on the active surface (`GET /api/conversations`)."""
    entries = payload.get("conversations") if isinstance(payload, dict) else payload
    return [str(item.get("id")) for item in (entries or []) if isinstance(item, dict)]


def ids_leaking_into_active(active: Iterable[str], trashed: Iterable[str]) -> list[str]:
    """Trashed ids that must never show up on the active surface (§2.1)."""
    return sorted(set(map(str, active)) & set(map(str, trashed)))


def field_drift(before: dict[str, Any], after: dict[str, Any],
                keys: Iterable[str] = PRESERVED_KEYS) -> list[str]:
    """Fields whose value changed across trash → restore (§2.3 第 4 条)."""
    return [key for key in keys if before.get(key) != after.get(key)]


def emptied_without_confirmation(status: int, remaining: int) -> bool:
    """True when an unconfirmed request managed to empty the bin (§2.3)."""
    return status < 400 and remaining == 0


def _summary_keys() -> frozenset[str]:
    return frozenset({
        "id", "mode", "title", "first_user_question", "updated_at", "created_at",
        "turn_count", "message_count", "schema_version", "title_version",
    })


def _view_section(view: str) -> str:
    """Return the HTML of one ``#view-…`` section from the shell."""
    start = SHELL_HTML.find(f'id="view-{view}"')
    if start < 0:
        return ""
    end = SHELL_HTML.find("</section>", start)
    return SHELL_HTML[start:end if end > 0 else len(SHELL_HTML)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 基类：临时工作区 + 真实应用
# ---------------------------------------------------------------------------

class TrashTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        get_agent_def_registry()._defs["bi-analyst"] = AgentDef("bi-analyst", tools=[])
        if STATE.conversation_store is not None:
            STATE.conversation_store = None
        with patch("bi_agent.web.app.OntologyStore.from_xlsx", return_value=OntologyStore()):
            web_app_module.configure(self.tmp, self.tmp, self.tmp, agent_name="bi-analyst")
        self.client = TestClient(app)
        self.store = STATE.conversation_store
        self.root = Path(self.tmp) / "dataset" / "conversations"
        self.index_path = self.root / "history_index.json"

    # -- helpers -----------------------------------------------------------
    def seed(self, title: str, *, mode: str = "data", question: str = "") -> str:
        question = question or f"{title} 是多少"
        rec = self.store.save(
            mode=mode,
            title=title,
            messages=[{"role": "user", "content": question},
                      {"role": "assistant", "content": "42"}],
            chat_html=f'<div class="msg msg-user">{question}</div>',
        )
        return str(rec["id"])

    def seed_at(self, title: str, updated_at: str, *, mode: str = "data") -> str:
        """同 ``seed()``，但把 ``updated_at`` 钉死。

        ``_now_iso()`` 只精确到秒，连续两次 ``save()`` 很可能落在同一秒，
        而 ``list()`` 的排序键是 ``(updated_at, id)``——同一秒时会退化成按
        ``id`` 倒序，使"较晚保存的一定排在前面"这一断言变得不稳定。
        要断言排序契约就必须先把时间钉死，而不是依赖墙钟。
        """
        with patch("bi_agent.web.conversations._now_iso", return_value=updated_at):
            return self.seed(title, mode=mode)

    def trash_paths(self) -> list[Path]:
        trash_dir = self.root / "trash"
        return sorted(trash_dir.glob("*.json")) if trash_dir.is_dir() else []

    def trash_file(self, cid: str) -> Path:
        return self.root / "trash" / f"{cid}.json"

    def active(self) -> list[dict[str, Any]]:
        response = self.client.get("/api/conversations")
        self.assertEqual(response.status_code, 200, msg=response.content[:200])
        return response.json().get("conversations") or []

    def trash(self) -> dict[str, Any]:
        response = self.client.get("/api/conversations/trash")
        self.assertEqual(response.status_code, 200, msg=(
            f"尚未实现：GET /api/conversations/trash 应可读取回收站，当前 {response.status_code}"
            f" {response.content[:160]!r}"))
        return response.json()

    def age(self, cid: str, days: float) -> None:
        """把已进回收站的记录 ``deleted_at`` 回拨 ``days`` 天。

        保留期与排序都按 ``deleted_at`` 判定，直接写死时间才能让断言与墙钟无关。
        """
        path = self.trash_file(cid)
        record = json.loads(path.read_text(encoding="utf-8"))
        stamp = _now() - timedelta(days=days)
        record["deleted_at"] = stamp.isoformat(timespec="seconds")
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. 软删除 / 恢复 / 彻底删除
# ---------------------------------------------------------------------------

class TrashLifecycleTests(TrashTestBase):
    def test_r1_delete_moves_the_snapshot_into_the_trash(self):
        """R1：删除 = 移入回收站（文件仍在、带 deleted_at、活跃面消失）。"""
        cid = self.seed("采购金额下降")
        before = self.store.get(cid)
        self.assertIsNotNone(before)

        response = self.client.delete(f"/api/conversations/{cid}")
        self.assertTrue(response.json().get("ok"), msg=f"删除响应应保持 ok:true：{response.text!r}")

        self.assertNotIn(cid, [row["id"] for row in self.active()],
                         msg="已删除会话不得出现在活跃列表里")
        self.assertTrue(self.trash_file(cid).exists(), msg=(
            "尚未实现：删除后快照必须进入 dataset/conversations/trash/，"
            "当前是直接物理删除（回收站无法恢复）"))
        record = json.loads(self.trash_file(cid).read_text(encoding="utf-8"))
        self.assertTrue(record.get("deleted_at"),
                        msg="回收站记录必须带 deleted_at 时间戳")
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertNotIn(cid, index["conversations"],
                         msg="已删除会话不得留在 history_index.json 里（否则列表/重建会复活它）")

    def test_r3_restore_returns_the_conversation_unchanged(self):
        """R3：恢复逐字段一致、updated_at 不变、deleted_at 被移除。"""
        cid = self.seed("库存账龄超180天")
        before = self.store.get(cid)
        self.client.delete(f"/api/conversations/{cid}")

        response = self.client.post(f"/api/conversations/trash/{cid}/restore")
        self.assertEqual(response.status_code, 200, msg=(
            f"尚未实现：恢复接口不可用（{response.status_code} {response.content[:160]!r}）"))
        self.assertTrue(response.json().get("ok"), msg=response.text[:200])

        after = ConversationStore(self.tmp).get(cid)
        self.assertIsNotNone(after, msg="恢复后必须回到活跃面")
        drift = field_drift(before, after)
        self.assertEqual(drift, [], msg=f"恢复不得改动会话内容（漂移字段：{drift}）")
        self.assertNotIn("deleted_at", after, msg="恢复必须移除 deleted_at")
        self.assertIn(cid, [row["id"] for row in self.active()],
                      msg="恢复后必须重新出现在「最近」列表")
        self.assertNotIn(cid, [row["id"] for row in self.trash()["trash"]],
                         msg="恢复后不得继续留在回收站列表")
        restored = next(row for row in self.active() if row["id"] == cid)
        self.assertEqual(restored["updated_at"], before["updated_at"],
                         msg="恢复不得刷新 updated_at（否则会话会跳到「最近」最前面）")

    def test_r4_purge_removes_one_record_for_good_and_is_idempotent(self):
        """R4：彻底删除真的删掉，且重复调用幂等。"""
        cid = self.seed("缺陷率")
        self.client.delete(f"/api/conversations/{cid}")

        response = self.client.delete(f"/api/conversations/trash/{cid}")
        self.assertEqual(response.status_code, 200, msg=(
            f"尚未实现：彻底删除接口不可用（{response.status_code}）"))
        self.assertTrue(response.json().get("ok"), msg=response.text[:200])
        self.assertFalse(self.trash_file(cid).exists(), msg="彻底删除后快照文件必须消失")
        self.assertEqual([row["id"] for row in self.trash()["trash"]], [])

        again = self.client.delete(f"/api/conversations/trash/{cid}")
        self.assertEqual(again.status_code, 200, msg="重复彻底删除不得报错")
        self.assertFalse(again.json().get("ok"), msg="重复彻底删除应返回 ok:false（幂等）")

    def test_r8_restore_of_an_id_that_is_active_again_does_not_duplicate(self):
        """R8：同 id 的活跃会话已存在时，恢复不得产生重复或覆盖活跃内容。"""
        cid = self.seed("旧快照")
        self.client.delete(f"/api/conversations/{cid}")
        self.store.save(cid=cid, mode="data", title="新快照",
                        messages=[{"role": "user", "content": "新的问题"}])

        response = self.client.post(f"/api/conversations/trash/{cid}/restore")
        self.assertEqual(response.status_code, 200, msg=(
            f"冲突恢复必须给出明确结果而不是 500：{response.status_code} {response.content[:160]!r}"))
        rows = [row for row in self.active() if row["id"] == cid]
        self.assertEqual(len(rows), 1, msg="恢复同 id 不得产生第二条记录")
        # 活跃记录必须是 ``save()`` 新写的那一份，而不是回收站里的旧快照。
        # 注意 ``save()`` 从不可信客户端传来的 ``title``（见
        # ``test_regressions.py::test_title_algorithm_skips_internal_messages_and_index_version``：
        # ``title="错误标题"`` 会被首问覆盖），所以这里用首问而不是 ``title`` 做归属判据。
        self.assertEqual(rows[0]["first_user_question"], "新的问题",
                         msg="活跃记录不得被回收站里的旧快照覆盖")
        self.assertTrue(response.json().get("already_active"),
                        msg="同 id 冲突必须显式告知「已在活跃面」（§2.3 第 3 条）")

    def test_r9_malformed_and_unknown_ids_never_return_a_server_error(self):
        """R9：非法 / 不存在 id 一律 4xx 或 ok:false，不得 500。"""
        cases = (
            ("POST", "/api/conversations/trash/not-a-hex-id/restore", (400,)),
            ("POST", "/api/conversations/trash/deadbeef/restore", (404,)),
            ("DELETE", "/api/conversations/trash/deadbeef", (200,)),
        )
        for method, path, allowed in cases:
            with self.subTest(path=path):
                response = self.client.request(method, path)
                self.assertLess(response.status_code, 500,
                                msg=f"{method} {path} 不得 500：{response.content[:160]!r}")
                self.assertIn(response.status_code, allowed, msg=(
                    f"{method} {path} 期望 {allowed}，实际 {response.status_code}"))
                if allowed == (200,):
                    self.assertFalse(response.json().get("ok"),
                                     msg="不存在的回收站条目应返回 ok:false")


# ---------------------------------------------------------------------------
# 2. 清空回收站必须显式确认
# ---------------------------------------------------------------------------

class TrashEmptyTests(TrashTestBase):
    def test_r5_emptying_the_trash_requires_an_explicit_confirmation(self):
        """R5：清空回收站必须 confirm=1；不带确认不得删除任何东西。"""
        keep = self.seed("保留的会话")
        for title in ("要清空的 A", "要清空的 B"):
            cid = self.seed(title)
            self.client.delete(f"/api/conversations/{cid}")
        self.assertEqual(len(self.trash_paths()), 2)
        before = sorted(p.name for p in self.trash_paths())

        response = self.client.delete("/api/conversations/trash")
        self.assertEqual(response.status_code, 400, msg=(
            "尚未实现：清空回收站必须要求显式确认（confirm=1），"
            f"当前返回 {response.status_code} {response.content[:160]!r}"))
        self.assertEqual(sorted(p.name for p in self.trash_paths()), before,
                         msg="未确认的请求不得删除任何回收站条目")
        self.assertFalse(emptied_without_confirmation(response.status_code,
                                                      len(self.trash_paths())))

        confirmed = self.client.delete("/api/conversations/trash?confirm=1")
        self.assertEqual(confirmed.status_code, 200, msg=confirmed.content[:200])
        self.assertEqual(confirmed.json().get("purged"), 2, msg="应报告永久删除的条数")
        self.assertEqual(self.trash_paths(), [], msg="确认后回收站应被清空")
        self.assertIn(keep, [row["id"] for row in self.active()],
                      msg="清空回收站不得影响活跃会话")
        self.assertEqual([row["id"] for row in self.trash()["trash"]], [])


# ---------------------------------------------------------------------------
# 3. 元数据白名单（匿名面不外扩）
# ---------------------------------------------------------------------------

class TrashMetadataTests(TrashTestBase):
    def test_r2_trash_list_returns_deleted_metadata_only(self):
        """R2：回收站列表只回元数据，不回正文与数据源配置。"""
        cid = self.seed("华东供应商")
        self.client.delete(f"/api/conversations/{cid}")
        payload = self.trash()

        entries = payload["trash"]
        self.assertEqual(len(entries), 1, msg="回收站应列出已删除的一条会话")
        entry = entries[0]
        self.assertEqual(entry["id"], cid)
        self.assertTrue(entry.get("deleted_at"), msg="列表必须带删除时间")
        self.assertIn("title", entry)
        self.assertIn("mode", entry)
        self.assertEqual(entry["turn_count"], 1, msg="保留轮次信息便于用户辨认")
        violations = metadata_violations(payload)
        self.assertEqual(violations, [], msg=f"回收站列表泄露了正文或多余字段：{violations}")
        self.assertEqual(payload.get("count"), 1, msg="count 必须与列表一致")
        self.assertIn("retention_days", payload, msg="列表必须暴露保留期，便于页面标注")

    def _seed_with_credential(self) -> str:
        cid = self.seed("凭据检查")
        self.store.save(cid=cid, mode="data", title="凭据检查",
                        messages=[{"role": "user", "content": "问题"}],
                        source_config={"ontology": "__metaerp_repository__:4",
                                       "doris_password": "must-not-persist"})
        return cid

    def test_r14_trash_list_is_newest_deleted_first(self):
        """R14：回收站按 ``deleted_at`` 倒序（最近删的排最前），便于用户辨认。"""
        oldest = self.seed("最早删的")
        middle = self.seed("其次删的")
        newest = self.seed("最近删的")
        for cid in (oldest, middle, newest):
            self.client.delete(f"/api/conversations/{cid}")
            self.assertTrue(self.trash_file(cid).exists(), msg=(
                "尚未实现：删除后快照必须进入 dataset/conversations/trash/，"
                "否则无法校验回收站排序"))
        self.age(oldest, 3)
        self.age(middle, 2)
        self.age(newest, 1)

        ids = [row["id"] for row in self.trash()["trash"]]
        self.assertEqual(ids, [newest, middle, oldest],
                         msg="回收站必须按 deleted_at 倒序（最近删除的排在最前）")

    def test_r13_trash_snapshot_never_carries_credentials(self):
        """R13：进回收站的快照同样不得带凭据（软删除不得绕过清洗）。"""
        cid = self._seed_with_credential()
        self.client.delete(f"/api/conversations/{cid}")
        self.assertTrue(self.trash_file(cid).exists(), msg=(
            "尚未实现：删除后快照必须进入回收站；在此之前无法校验回收站快照的清洗"))
        blob = self.trash_file(cid).read_text(encoding="utf-8")
        self.assertNotIn("must-not-persist", blob)
        self.assertNotIn("doris_password", json.loads(blob).get("source_config", {}))

    def test_g16_credentials_never_reach_the_active_snapshot(self):
        """G16（护栏）：活跃快照沿用既有清洗，凭据不落盘。"""
        cid = self._seed_with_credential()
        blob = (self.root / f"{cid}.json").read_text(encoding="utf-8")
        self.assertNotIn("must-not-persist", blob)
        self.assertNotIn("doris_password", json.loads(blob).get("source_config", {}))


# ---------------------------------------------------------------------------
# 4. 保留期与自动裁剪
# ---------------------------------------------------------------------------

class TrashRetentionTests(TrashTestBase):
    def test_r6_retention_window_purges_only_expired_records(self):
        """R6：过了保留期的自动清理；保留期内与"正好到期"的保留。"""
        with patch.dict(os.environ, {RETENTION_ENV: "7"}):
            fresh = self.seed("昨天删的")
            boundary = self.seed("正好七天")
            stale = self.seed("八天前删的")
            for cid in (fresh, boundary, stale):
                self.client.delete(f"/api/conversations/{cid}")
            self.age(fresh, 1)
            self.age(boundary, 7)
            self.age(stale, 8)

            payload = self.trash()
            ids = [row["id"] for row in payload["trash"]]
            self.assertEqual(payload.get("retention_days"), 7,
                             msg="列表必须反映环境变量配置的保留期")
            self.assertIn(fresh, ids, msg="保留期内的条目必须保留")
            self.assertIn(boundary, ids, msg="正好到期的当天必须保留（严格小于才清理）")
            self.assertNotIn(stale, ids, msg="尚未实现：过期条目必须被自动清理")
            self.assertFalse(self.trash_file(stale).exists(),
                             msg="过期条目的快照文件必须真的被删除")

    def test_r7_auto_pruned_conversations_are_recoverable(self):
        """R7：活跃超上限被自动移出的会话，必须能在回收站找回。"""
        oldest = self.seed("最早的一条")
        for i in range(MAX_CONVERSATIONS + 1):
            self.store.save(mode="data", title=f"批量 {i}",
                            messages=[{"role": "user", "content": f"问题 {i}"}])
        self.assertNotIn(oldest, [row["id"] for row in self.active()],
                         msg="超过上限的最旧会话应从活跃列表移出")
        ids = [row["id"] for row in self.trash()["trash"]]
        self.assertIn(oldest, ids, msg=(
            "尚未实现：自动裁剪仍直接物理删除；被裁掉的会话必须在保留期内可找回"))


# ---------------------------------------------------------------------------
# 5. 既有契约护栏
# ---------------------------------------------------------------------------

class ExistingContractTests(TrashTestBase):
    def test_g13_invalid_ids_are_still_rejected(self):
        """G13（护栏）：非法 id 仍被拒，且不动文件系统。"""
        self.seed("正常会话")
        before = sorted(p.name for p in self.root.glob("*.json"))
        self.assertFalse(ConversationStore(self.tmp).delete("../outside"))
        self.assertEqual(sorted(p.name for p in self.root.glob("*.json")), before)

    def test_g14_active_summary_shape_is_unchanged(self):
        """G14（护栏）：活跃列表字段与排序契约不变。"""
        self.seed_at("较早", "2026-09-21T09:00:00")
        cid = self.seed_at("较晚", "2026-09-21T10:00:00")
        rows = self.active()
        self.assertEqual(rows[0]["id"], cid, msg="活跃列表仍按更新时间倒序")
        self.assertTrue(_summary_keys() <= set(rows[0]),
                        msg=f"活跃列表字段被删：{_summary_keys() - set(rows[0])}")

    def test_g15_unknown_id_on_the_active_delete_contract(self):
        """G15（护栏）：活跃面删除未知 id 仍返回 ok:false（前端依赖该契约）。"""
        response = self.client.delete("/api/conversations/deadbeef")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json().get("ok"))


# ---------------------------------------------------------------------------
# 6. 「记忆管理」页与前端接线
# ---------------------------------------------------------------------------

class MemoryPageContractTests(unittest.TestCase):
    def test_r10_memory_page_carries_the_trash_section(self):
        """R10：记忆管理页含回收站区块（id + 文案）。"""
        section = _view_section("memory")
        self.assertTrue(section, msg="找不到 #view-memory 区块")
        for element_id in ("memory-trash", "memory-trash-count", "memory-trash-list",
                           "memory-trash-empty", "memory-trash-status"):
            self.assertIn(f'id="{element_id}"', section,
                          msg=f"尚未实现：记忆管理页缺少 #{element_id}")
        for control in ("memory-trash-restore", "memory-trash-purge"):
            self.assertIn(control, section, msg=f"尚未实现：行内缺少 {control} 操作")
        for copy in ("回收站", "恢复", "彻底删除", "不可恢复", "保留"):
            self.assertIn(copy, section, msg=f"尚未实现：回收站文案缺少「{copy}」")
        self.assertIn("trash", section, msg="区块应带上回收站数据属性/容器")

    def test_r11_runtime_loads_the_trash_when_opening_memory(self):
        """R11：runtime 为 memory 视图提供加载函数，并挂在导航上。"""
        self.assertIn("openMemory", RUNTIME_JS,
                      msg="尚未实现：runtime 缺少 openMemory() 加载入口")
        self.assertIn('api/conversations/trash', RUNTIME_JS,
                      msg="尚未实现：runtime 没有拉取回收站列表")
        self.assertRegex(RUNTIME_JS, r'view\s*===\s*["\']memory["\']',
                         msg="尚未实现：导航未把 memory 视图接到 openMemory()")
        for pattern in (r'openSources\(\)', r'openRoles\(\)'):
            self.assertRegex(RUNTIME_JS, pattern,
                             msg="既有导航模式（openSources/openRoles）被破坏")

    def test_r12_sidebar_delete_is_labelled_as_moving_to_the_trash(self):
        """R12：侧边栏 ✕ 文案改为「移入回收站」，仍打同一个 DELETE。"""
        self.assertIn("移入回收站", RUNTIME_JS,
                      msg="尚未实现：侧边栏删除入口仍需提示「移入回收站」")
        self.assertEqual(RUNTIME_JS.count('api/conversations/" + id'), 1,
                         msg="侧边栏删除必须继续调用 DELETE /api/conversations/{id}")

    def test_g17_memory_page_keeps_the_existing_reset_control(self):
        """G17（护栏）：既有「重置当前对话」控件不得被回收站改造挤掉。"""
        section = _view_section("memory")
        self.assertIn('id="btn-reset"', section)
        self.assertIn('id="memory-status"', section)

    def test_g18_sidebar_delete_button_and_handler_survive(self):
        """G18（护栏）：侧边栏删除按钮与处理函数仍存在。"""
        self.assertIn("recent-del", RUNTIME_JS)
        self.assertIn("deleteRecent", RUNTIME_JS)


# ---------------------------------------------------------------------------
# 7. Mutation guards：这些检查器必须能杀死对应变异
# ---------------------------------------------------------------------------

class MutationGuardTests(unittest.TestCase):
    def test_leaked_body_is_caught_and_metadata_only_passes(self):
        """杀死"回收站列表顺手回吐正文"的变异（§2.8）。"""
        leaky = {"trash": [{"id": "a" * 8, "mode": "data", "title": "t",
                            "deleted_at": "2026-09-21T10:00:00",
                            "chat_html": "<div>对话正文</div>"}]}
        self.assertTrue(metadata_violations(leaky))
        leaked_messages = {"trash": [{"id": "b" * 8, "messages": [{"role": "user"}]}]}
        self.assertTrue(metadata_violations(leaked_messages))
        clean = {"trash": [{"id": "c" * 8, "mode": "data", "title": "t",
                            "deleted_at": "2026-09-21T10:00:00", "turn_count": 1}]}
        self.assertEqual(metadata_violations(clean), [])
        self.assertEqual(metadata_violations({"trash": []}), [])

    def test_trashed_id_in_the_active_list_is_caught(self):
        """杀死"软删除只搬文件、不从索引移除"的变异（§2.1）。"""
        self.assertEqual(ids_leaking_into_active(["deadbeef", "cafebabe"], ["cafebabe"]),
                         ["cafebabe"])
        self.assertEqual(ids_leaking_into_active(["deadbeef"], ["cafebabe"]), [])

    def test_updated_at_drift_is_caught(self):
        """杀死"恢复走 save()、把会话顶到最前"的变异（§2.3 第 4 条）。"""
        before = {"updated_at": "2026-09-01T09:00:00", "title": "旧标题"}
        bumped = {"updated_at": "2026-09-21T09:00:00", "title": "旧标题"}
        self.assertEqual(field_drift(before, bumped, keys=("updated_at",)), ["updated_at"])
        self.assertEqual(field_drift(before, dict(before), keys=("updated_at",)), [])

    def test_unconfirmed_emptying_is_caught(self):
        """杀死"清空回收站不校验 confirm"的变异（§2.3）。"""
        self.assertTrue(emptied_without_confirmation(200, 0))
        self.assertFalse(emptied_without_confirmation(400, 2))
        self.assertFalse(emptied_without_confirmation(200, 1))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
