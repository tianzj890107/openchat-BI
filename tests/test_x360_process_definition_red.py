"""RED tests for the X360 流程定义接口接入（第一批：只读客户端 + 转督办换真）。

契约来源：``docs/specs/x360-process-definition-integration.md``；
接口文档：``API/X360提供给AI的接口.md``。

本文件在迁移前必须是 **RED**：它描述"按 API 文档实现之后必须成立的行为"，而不是
"今天代码做了什么"。全部断言都跑**真实生产入口**：

* ``bi_agent.x360.client``（本批要新增的只读客户端）——今天不存在，因此相关用例
  以明确的"尚未实现"失败，而不是静默跳过；
* ``bi_agent.web.app._resolve_task_alert_target`` 与
  ``bi_agent.web.app.task_alert_manual_create``（真实的转督办入口）——今天仍然用
  硬编码关键词表，因此"按文档取流程定义 ID""责任人来自 X360 活动"等断言会真实失败。

离线、确定性：只连 127.0.0.1 上的假 X360 / 假任务令服务，没有真实凭据、没有真实
服务、没有 LLM、不碰任何用户数据。
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from unittest import mock
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException

from bi_agent.web import app as web_app

# ---------------------------------------------------------------------------
# 文档里给出的真实形状（截取自 API/X360提供给AI的接口.md 的示例体）
# ---------------------------------------------------------------------------

PROCESS_DEFINITION_ID = "2081949112647405570"
PROCESS_DEFINITION_KEY = "MOCK_0728"
ACTIVITY_HUIJUAN_ID = "2081949636213985282"      # 活动「回款」
ACTIVITY_HUIJUAN_PERSON = "224"
ACTIVITY_KAIPIAO_ID = "2081949636205596674"      # 活动「开票」
ACTIVITY_KAIPIAO_PERSON = "336"
ACTIVITY_XINSUO_ID = "2081949636092350465"       # 活动「线索」
ACTIVITY_XINSUO_PERSON = "242"
ACTIVITY_DINGDAN_ID = "2081949636146876418"      # 活动「订单」
ACTIVITY_DINGDAN_PERSON = "250"
TASK_LUYUE_NAME = "履约单生成"                    # 订单活动下的任务（文档 §1 示例）

X360_PATH_BY_KEY = f"/api/gateway2/x360/v1/process-definitions/ai/key/{PROCESS_DEFINITION_KEY}"
X360_PATH_BY_ID = f"/api/gateway2/x360/v1/process-definitions/ai/{PROCESS_DEFINITION_ID}"
TASK_ALERT_PATH = "/api/x360/v1/task-alert/manual-create"


def _payload() -> dict:
    """和文档一致的两层结构：流程定义 data.id + 活动 activities[].id。"""
    return {
        "success": True,
        "code": 200,
        "message": "success",
        "data": {
            "id": PROCESS_DEFINITION_ID,
            "code": PROCESS_DEFINITION_KEY,
            "name": "mock流程",
            "description": "线索到回款（LTC）端到端流程",
            "activities": [
                {
                    "id": ACTIVITY_XINSUO_ID, "name": "线索", "code": "XINSUO",
                    "responsiblePerson": ACTIVITY_XINSUO_PERSON,
                    "description": "线索获取与分发",
                    "tasks": [
                        {"id": "2091704984995954689", "name": "获取",
                         "code": "HUOQU", "description": "收集并录入销售线索"},
                    ],
                },
                {
                    "id": ACTIVITY_KAIPIAO_ID, "name": "开票", "code": "KAIPAIO",
                    "responsiblePerson": ACTIVITY_KAIPIAO_PERSON,
                    "description": "开票与发票管理",
                    "tasks": [
                        {"id": "2091704985100812801", "name": "开票申请",
                         "code": "KPAPPLY", "description": "提交开票申请"},
                    ],
                },
                {
                    "id": ACTIVITY_HUIJUAN_ID, "name": "回款", "code": "HUIJUAN",
                    "responsiblePerson": ACTIVITY_HUIJUAN_PERSON,
                    "description": "回款登记与核销",
                    "tasks": [
                        {"id": "2091704985205670913", "name": "回款登记",
                         "code": "HKREG", "description": "登记客户回款"},
                    ],
                },
                {
                    "id": ACTIVITY_DINGDAN_ID, "name": "订单", "code": "DINGDAN",
                    "responsiblePerson": ACTIVITY_DINGDAN_PERSON,
                    "description": "订单阶段，生成并下达履约单",
                    "tasks": [
                        {"id": "2091704985300000001", "name": TASK_LUYUE_NAME,
                         "code": "LYUDAN", "description": "根据订单生成履约执行单"},
                        {"id": "2091704985300000002", "name": "履约单下达",
                         "code": "LYUDAXIA", "description": "将履约单下达至生产/交付部门"},
                    ],
                },
            ],
        },
    }


def _business_failure() -> dict:
    return {"success": False, "code": 500, "message": "流程定义不存在", "data": None}


def _task_alert_ok(task_id: str = "3f1c9d0e-0000-4000-8000-000000000001") -> dict:
    return {"success": True, "code": 200, "data": task_id}


# ---------------------------------------------------------------------------
# loopback：同时扮演 X360 与任务令服务
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep pytest output clean
        pass

    def _dispatch(self, method: str) -> None:
        fake = self.server.fake  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        fake.calls.append({
            "method": method,
            "path": parsed.path,
            "query": {k: v[0] for k, v in parse_qs(parsed.query).items()},
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })
        responder = fake.routes.get(parsed.path)
        if responder is None:
            status, payload = 404, {"success": False, "code": 404, "msg": "no fake route"}
        else:
            status, payload = responder(fake.calls[-1])
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802 - http.server hook
        self._dispatch("DELETE")


class _FakeServices:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.routes: dict[str, Any] = {}
        self.lock = threading.Lock()

    def route(self, path: str, responder) -> None:
        self.routes[path] = responder

    @property
    def x360_calls(self) -> list[dict]:
        return [c for c in self.calls if c["path"].startswith("/api/gateway2/x360")]

    @property
    def task_alert_calls(self) -> list[dict]:
        return [c for c in self.calls if c["path"] == TASK_ALERT_PATH]


class _Harness(unittest.TestCase):
    """起一个 loopback 服务，并把生产代码指向它。"""

    def setUp(self) -> None:
        self.fake = _FakeServices()
        self.fake.route(X360_PATH_BY_KEY, lambda _c: (200, _payload()))
        self.fake.route(X360_PATH_BY_ID, lambda _c: (200, _payload()))
        self.fake.route(TASK_ALERT_PATH, lambda _c: (200, _task_alert_ok()))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.fake = self.fake  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    # -- env helpers -------------------------------------------------------
    def env(self, **overrides: Any) -> dict:
        values = {
            "X360_ENABLED": "true",
            "X360_BASE_URL": self.base,
            "X360_PROCESS_DEFINITION_KEY": PROCESS_DEFINITION_KEY,
            "X360_APP_ID": "ApTH1EHKdRk58WhDQB",
            "X360_AUTH_TOKEN": "s3cr3t-token",
            "X360_TIMEOUT_SECONDS": "10",
            "X360_CACHE_TTL_SECONDS": "300",
            "TASK_ALERT_API_ENABLED": "true",
            "TASK_ALERT_API_URL": f"{self.base}{TASK_ALERT_PATH}",
            "TASK_ALERT_DEFAULT_ASSIGNEE": "400",
            "TASK_ALERT_TIMEOUT_SECONDS": "10",
        }
        values.update(overrides)
        return values

    def patch_env(self, **overrides: Any):
        env = self.env(**overrides)
        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    # -- implementation guards --------------------------------------------
    def require_x360_module(self):
        try:
            return importlib.import_module("bi_agent.x360.client")
        except ModuleNotFoundError as exc:
            self.fail(
                "尚未实现 bi_agent.x360.client —— 本批必须新增只读 X360 客户端，"
                f"见 docs/specs/x360-process-definition-integration.md §4.1（{exc}）"
            )

    def require_resolver(self):
        resolver = getattr(web_app, "_resolve_task_alert_target", None)
        if resolver is None:
            self.fail(
                "尚未实现 bi_agent.web.app._resolve_task_alert_target —— 转督办必须改为"
                "按 X360 解析流程定义与责任人，见 Spec §4.5"
            )
        return resolver

    def new_request(self, **kwargs: Any):
        model = getattr(web_app, "TaskAlertCreateRequest")
        payload = {"title": "回款超期督办", "content": "建议对回款环节发起督办"}
        payload.update(kwargs)
        return model(**payload)


# ---------------------------------------------------------------------------
# §1 客户端：路径、归一化、匹配
# ---------------------------------------------------------------------------

class X360ClientContractTests(_Harness):
    def test_module_exposes_documented_entry_points(self) -> None:
        module = self.require_x360_module()
        for name in ("X360ApiError", "X360Activity", "X360ProcessDefinition",
                     "X360ProcessDefinitionClient"):
            self.assertTrue(hasattr(module, name), f"缺少公开符号 {name}")

    def test_fetch_by_key_uses_documented_path(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        definition = client.fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(definition.id, PROCESS_DEFINITION_ID)
        self.assertEqual(definition.code, PROCESS_DEFINITION_KEY)
        self.assertTrue(
            any(c["path"] == X360_PATH_BY_KEY for c in self.fake.x360_calls),
            "必须按文档路径 /api/gateway2/x360/v1/process-definitions/ai/key/{key} 发起请求",
        )

    def test_fetch_by_id_uses_documented_path(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        definition = client.fetch_by_id(PROCESS_DEFINITION_ID)
        self.assertEqual(definition.id, PROCESS_DEFINITION_ID)
        self.assertTrue(any(c["path"] == X360_PATH_BY_ID for c in self.fake.x360_calls))

    def test_activities_and_tasks_are_normalised(self) -> None:
        module = self.require_x360_module()
        definition = module.X360ProcessDefinitionClient.from_env().fetch_by_key(
            PROCESS_DEFINITION_KEY
        )
        names = [a.name for a in definition.activities]
        self.assertEqual(names, ["线索", "开票", "回款", "订单"])
        huijuan = [a for a in definition.activities if a.name == "回款"][0]
        self.assertEqual(huijuan.id, ACTIVITY_HUIJUAN_ID)
        self.assertEqual(huijuan.code, "HUIJUAN")
        self.assertEqual(huijuan.responsible_person, ACTIVITY_HUIJUAN_PERSON)
        self.assertEqual([t["name"] for t in huijuan.tasks], ["回款登记"])

    def test_match_activity_by_name(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        matched = client.match_activity("先做回款登记，再做客户核销")
        self.assertIsNotNone(matched, "按活动名称必须能命中")
        self.assertEqual(matched.name, "回款")

    def test_match_activity_by_code_is_case_insensitive(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        matched = client.match_activity("check HUIJUAN stage")
        self.assertIsNotNone(matched, "按活动 code 必须能命中，且大小写不敏感")
        self.assertEqual(matched.code, "HUIJUAN")

    def test_match_activity_returns_none_when_nothing_matches(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        self.assertIsNone(client.match_activity("今天天气不错"))


# ---------------------------------------------------------------------------
# §2 鉴权与只读
# ---------------------------------------------------------------------------

class X360AuthTests(_Harness):
    def _first_x360_call(self) -> dict:
        calls = self.fake.x360_calls
        self.assertTrue(calls, "必须真的向 X360 发起过请求")
        return calls[0]

    def test_sends_app_id_header(self) -> None:
        module = self.require_x360_module()
        module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(
            self._first_x360_call()["headers"].get("x-app-id"), "ApTH1EHKdRk58WhDQB"
        )

    def test_sends_bearer_token_when_configured(self) -> None:
        module = self.require_x360_module()
        module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(
            self._first_x360_call()["headers"].get("authorization"), "Bearer s3cr3t-token"
        )

    def test_does_not_duplicate_bearer_prefix(self) -> None:
        self.patch_env(X360_AUTH_TOKEN="Bearer already-prefixed")
        module = self.require_x360_module()
        module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(
            self._first_x360_call()["headers"].get("authorization"),
            "Bearer already-prefixed",
        )

    def test_omits_authorization_when_token_is_empty(self) -> None:
        self.patch_env(X360_AUTH_TOKEN="")
        module = self.require_x360_module()
        module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertNotIn("authorization", self._first_x360_call()["headers"])

    def test_client_is_read_only(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        client.fetch_by_key(PROCESS_DEFINITION_KEY)
        client.match_activity("回款")
        methods = {c["method"] for c in self.fake.x360_calls}
        self.assertEqual(methods, {"GET"}, "X360 接入只允许只读 GET")


# ---------------------------------------------------------------------------
# §3 错误语义与凭据保护
# ---------------------------------------------------------------------------

class X360ErrorTests(_Harness):
    def test_http_error_raises_x360_api_error(self) -> None:
        module = self.require_x360_module()
        self.fake.route(X360_PATH_BY_KEY, lambda _c: (500, {"success": False, "code": 500}))
        with self.assertRaises(module.X360ApiError):
            module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)

    def test_business_failure_raises_x360_api_error(self) -> None:
        module = self.require_x360_module()
        self.fake.route(X360_PATH_BY_KEY, lambda _c: (200, _business_failure()))
        with self.assertRaises(module.X360ApiError):
            module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)

    def test_non_json_body_raises_x360_api_error(self) -> None:
        module = self.require_x360_module()

        class _Raw(_Handler):
            def _dispatch(self, method: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", "11")
                self.end_headers()
                self.wfile.write(b"<html>oops")

        with mock.patch.object(_Handler, "_dispatch", _Raw._dispatch):
            with self.assertRaises(module.X360ApiError):
                module.X360ProcessDefinitionClient.from_env().fetch_by_key(
                    PROCESS_DEFINITION_KEY
                )

    def test_timeout_raises_x360_api_error(self) -> None:
        module = self.require_x360_module()
        self.patch_env(X360_TIMEOUT_SECONDS="0.5")

        def _slow(_call):
            import time
            time.sleep(3)
            return 200, _payload()

        self.fake.route(X360_PATH_BY_KEY, _slow)
        with self.assertRaises(module.X360ApiError):
            module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)

    def test_errors_never_leak_token_or_base_url(self) -> None:
        module = self.require_x360_module()
        self.fake.route(X360_PATH_BY_KEY, lambda _c: (500, {"success": False, "code": 500}))
        try:
            module.X360ProcessDefinitionClient.from_env().fetch_by_key(PROCESS_DEFINITION_KEY)
        except module.X360ApiError as exc:
            message = str(exc)
            self.assertNotIn("s3cr3t-token", message, "错误信息不得回显凭据")
            self.assertNotIn(self.base, message, "错误信息不得回显内部地址")
        else:
            self.fail("HTTP 500 必须抛 X360ApiError")


# ---------------------------------------------------------------------------
# §4 缓存
# ---------------------------------------------------------------------------

class X360CacheTests(_Harness):
    def test_second_lookup_is_served_from_cache(self) -> None:
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        client.fetch_by_key(PROCESS_DEFINITION_KEY)
        client.fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(len(self.fake.x360_calls), 1, "TTL 内重复查询必须命中缓存")

    def test_ttl_zero_disables_cache(self) -> None:
        self.patch_env(X360_CACHE_TTL_SECONDS="0")
        module = self.require_x360_module()
        client = module.X360ProcessDefinitionClient.from_env()
        client.fetch_by_key(PROCESS_DEFINITION_KEY)
        client.fetch_by_key(PROCESS_DEFINITION_KEY)
        self.assertEqual(len(self.fake.x360_calls), 2, "TTL=0 时必须每次回源")


# ---------------------------------------------------------------------------
# §5 转督办接线（真实生产入口）
# ---------------------------------------------------------------------------

class TaskAlertTargetResolutionTests(_Harness):
    def test_bp_id_defaults_to_process_definition_id_per_documented_contract(self) -> None:
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(
            target["bpDefinitionId"], int(PROCESS_DEFINITION_ID),
            "按 API 文档 bpDefinitionId 是流程定义 ID（data.id），不是活动 ID",
        )
        self.assertNotEqual(target["bpDefinitionId"], int(ACTIVITY_HUIJUAN_ID))

    def test_activity_level_switch_is_honoured(self) -> None:
        self.patch_env(X360_BP_ID_LEVEL="activity")
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(target["bpDefinitionId"], int(ACTIVITY_HUIJUAN_ID))

    def test_assignee_comes_from_matched_activity(self) -> None:
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(target["assignee"], ACTIVITY_HUIJUAN_PERSON)
        self.assertEqual(target["activityName"], "回款")
        self.assertEqual(target["source"], "x360")

    def test_activity_id_is_always_reported_even_at_process_definition_level(self) -> None:
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(target["activityId"], ACTIVITY_HUIJUAN_ID)

    def test_fallback_keeps_static_table_but_marks_source(self) -> None:
        self.patch_env(X360_ENABLED="false")
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(target["source"], "static_fallback")
        self.assertEqual(target["bpDefinitionId"], int(ACTIVITY_HUIJUAN_ID))
        self.assertEqual([c for c in self.fake.x360_calls], [], "关闭时不得调用 X360")

    def test_unmatched_text_has_no_bp_id_and_uses_default_assignee(self) -> None:
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve("今天天气不错")
        self.assertIsNone(target["bpDefinitionId"])
        self.assertEqual(target["source"], "default")
        self.assertEqual(target["assignee"], "400")

    def test_client_is_rebuilt_when_environment_changes(self) -> None:
        self.patch_env()
        resolve = self.require_resolver()
        resolve("建议对回款环节发起督办")
        first = len(self.fake.x360_calls)
        self.assertGreater(first, 0)
        # 换一个 base_url（另一个环境）后必须重新构造客户端，不能沿用旧签名
        self.patch_env(X360_BASE_URL=f"{self.base}/other")
        resolve("建议对回款环节发起督办")
        self.assertGreater(len(self.fake.calls), first)


class TaskAlertEndpointTests(_Harness):
    def test_response_exposes_source_and_activity(self) -> None:
        self.patch_env()
        result = web_app.task_alert_manual_create(self.new_request())
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "x360")
        self.assertEqual(result["activityName"], "回款")
        self.assertEqual(result["bpDefinitionId"], int(PROCESS_DEFINITION_ID))

    def test_endpoint_sends_resolved_bp_id_upstream(self) -> None:
        self.patch_env()
        web_app.task_alert_manual_create(self.new_request())
        calls = self.fake.task_alert_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["body"]["bpDefinitionId"], int(PROCESS_DEFINITION_ID))
        self.assertEqual(calls[0]["body"]["assignee"], ACTIVITY_HUIJUAN_PERSON)

    def test_endpoint_still_creates_task_when_x360_unavailable(self) -> None:
        self.patch_env(X360_BASE_URL="http://127.0.0.1:9")
        result = web_app.task_alert_manual_create(self.new_request())
        self.assertTrue(result["ok"], "X360 不可用时必须降级到静态表，而不是失败")
        self.assertEqual(result["source"], "static_fallback")

    def test_endpoint_does_not_call_x360_when_disabled(self) -> None:
        self.patch_env(X360_ENABLED="false")
        web_app.task_alert_manual_create(self.new_request())
        self.assertEqual(self.fake.x360_calls, [])

    def test_endpoint_response_never_contains_token(self) -> None:
        self.patch_env()
        result = web_app.task_alert_manual_create(self.new_request())
        self.assertNotIn("s3cr3t-token", json.dumps(result, ensure_ascii=False))

    def test_endpoint_still_reports_upstream_failure_honestly(self) -> None:
        self.patch_env()
        self.fake.route(TASK_ALERT_PATH, lambda _c: (200, {"success": False, "code": 500,
                                                           "message": "上游拒绝"}))
        with self.assertRaises(HTTPException) as ctx:
            web_app.task_alert_manual_create(self.new_request())
        self.assertEqual(ctx.exception.status_code, 502)


# ---------------------------------------------------------------------------
# §6 变异守卫：每条都验证真实行为，不检查源码里是否存在某关键词
#
# 这些守卫描述"实现若退化成下面任一种偷懒写法就必须变红"：
#   * 任务名命中却当成新的活动（履约单 是订单活动下的任务，父活动是 订单）；
#   * 显式传入的 bpDefinitionId 仍被 X360 结果覆盖（用户明确指定必须优先）；
#   * X360 命中后又被静态关键词表覆盖（等于白接 X360）。
# ---------------------------------------------------------------------------

class MutationGuardTests(_Harness):
    def test_mutant_task_name_must_resolve_to_its_parent_activity(self) -> None:
        """变异：把任务当活动，或继续用凭空的 履约单 硬编码 ID。"""
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve(f"{TASK_LUYUE_NAME}的进度异常，请督办")
        self.assertEqual(
            target["activityName"], "订单",
            "「履约单生成」是 订单 活动下的任务，必须归属到父活动 订单",
        )
        self.assertEqual(target["activityId"], ACTIVITY_DINGDAN_ID)
        self.assertEqual(target["assignee"], ACTIVITY_DINGDAN_PERSON)
        self.assertEqual(target["source"], "x360")

    def test_mutant_x360_hit_must_not_be_overridden_by_static_keyword_table(self) -> None:
        """变异：静态关键词表仍优先，X360 形同虚设。"""
        self.patch_env()
        resolve = self.require_resolver()
        target = resolve("建议对回款环节发起督办")
        self.assertEqual(target["source"], "x360")
        self.assertEqual(
            target["bpDefinitionId"], int(PROCESS_DEFINITION_ID),
            "X360 命中时必须以流程定义结果为准，不能退回硬编码的活动 ID",
        )

    def test_mutant_explicit_bp_id_must_not_be_overridden_by_x360(self) -> None:
        """变异：显式指定被解析结果覆盖，或解析仍然白跑一次 X360。"""
        self.patch_env()
        result = web_app.task_alert_manual_create(self.new_request(bpDefinitionId="55"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "request")
        self.assertEqual(
            self.fake.x360_calls, [],
            "显式指定 bpDefinitionId 时不得再查询 X360（既不覆盖用户意图，也不白跑网络）",
        )
        self.assertEqual(self.fake.task_alert_calls[0]["body"]["bpDefinitionId"], 55)
