"""X360 流程定义接口的只读客户端。

契约来源：

* ``docs/specs/x360-process-definition-integration.md``（§5 目标设计）
* ``API/X360提供给AI的接口.md``（两个 GET 路径与响应形状）

本模块是 X360 接入的**唯一**传输边界：路径、鉴权头、归一化、缓存与错误语义都收敛在
这里，调用方（``bi_agent/web/app.py`` 的转督办解析）只看到
``X360ProcessDefinition`` / ``X360Activity``。

只读：只发送文档给出的两个 ``GET``，没有请求体、没有写接口。
配置缺失是常态，``from_env()`` 必须返回一个"未启用"客户端而不是抛异常。
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
from http.client import HTTPException as _HTTPException
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

__all__ = [
    "X360Activity",
    "X360ApiError",
    "X360ProcessDefinition",
    "X360ProcessDefinitionClient",
]

# 文档逐字给出的两个路径（``API/X360提供给AI的接口.md`` §1 / §2）。
PATH_BY_KEY = "/api/gateway2/x360/v1/process-definitions/ai/key/{selector}"
PATH_BY_ID = "/api/gateway2/x360/v1/process-definitions/ai/{selector}"

DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 0.5
MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_CACHE_TTL_SECONDS = 300.0
MAX_CACHE_TTL_SECONDS = 24 * 60 * 60.0
DEFAULT_FAILURE_COOLDOWN_SECONDS = 30.0
MAX_FAILURE_COOLDOWN_SECONDS = 60 * 60.0

# 与本体网关共用的非密 App ID：``X360_APP_ID`` 未配置时的回退值。
DEFAULT_APP_ID = "ApTH1EHKdRk58WhDQB"

ERROR_DETAIL_LIMIT = 200

_DISABLED_MESSAGE = "X360 流程定义接口未启用"
_SELECTOR_MISSING_MESSAGE = "X360 流程定义接口未配置流程定义 KEY 或 ID"


class X360ApiError(Exception):
    """X360 流程定义接口的唯一异常类型（HTTP / 业务 / 非 JSON / 超时 / 结构异常）。

    消息只包含"接口用途 + 失败类别 + 上游 message（截断）"，绝不包含 token 或
    ``X360_BASE_URL`` 全文/host。
    """


@dataclass
class X360Activity:
    """一个流程活动（文档 ``activities[]``）。"""

    id: str = ""
    name: str = ""
    code: str = ""
    responsible_person: str = ""
    tasks: list[dict[str, str]] = field(default_factory=list)
    process_definition_id: str = ""


@dataclass
class X360ProcessDefinition:
    """一个流程定义（文档 ``data``）。"""

    id: str = ""
    code: str = ""
    name: str = ""
    activities: list[X360Activity] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 配置读取（全部按调用时环境即时读取；缺省即"未启用"，不抛异常）
# ---------------------------------------------------------------------------

def _env_text(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = _env_text(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _as_text(value: Any) -> str:
    """把上游字段转成字符串；结构体一律丢弃为空串，不做 int 化。"""
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return ""
    return str(value).strip() if isinstance(value, str) else str(value)


def _as_tasks(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    tasks: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tasks.append({
            "id": _as_text(item.get("id")),
            "name": _as_text(item.get("name")),
            "code": _as_text(item.get("code")),
            "description": _as_text(item.get("description")),
        })
    return tasks


def _code_pattern(code: str) -> "re.Pattern[str]":
    """ASCII 词边界的大小写不敏感匹配（``HUIJUAN`` 不匹配 ``XHUIJUANX``）。"""
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _longest_name_match(activities: Iterable[X360Activity], text: str) -> Optional[X360Activity]:
    best: Optional[X360Activity] = None
    for activity in activities:
        if not activity.name or activity.name not in text:
            continue
        if best is None or len(activity.name) > len(best.name):
            best = activity
    return best


def _longest_code_match(activities: Iterable[X360Activity], text: str) -> Optional[X360Activity]:
    best: Optional[X360Activity] = None
    for activity in activities:
        if not activity.code:
            continue
        if not _code_pattern(activity.code).search(text):
            continue
        if best is None or len(activity.code) > len(best.code):
            best = activity
    return best


def _longest_task_match(
    activities: Iterable[X360Activity], text: str, *, by: str
) -> Optional[X360Activity]:
    best: Optional[X360Activity] = None
    best_len = 0
    for activity in activities:
        for task in activity.tasks:
            value = task.get(by) or ""
            if not value:
                continue
            hit = value in text if by == "name" else bool(_code_pattern(value).search(text))
            if not hit:
                continue
            if best is None or len(value) > best_len:
                best, best_len = activity, len(value)
    return best


def match_activity_in(definition: X360ProcessDefinition, text: str) -> Optional[X360Activity]:
    """§5.4 分级匹配：活动名 → 活动 code → 任务名 → 任务 code（同级取名称最长者）。

    任务命中时返回其**父活动**；都不命中返回 ``None``（调用方走静态回退，不得凭空造 ID）。
    """
    if definition is None or not text:
        return None
    activities = definition.activities
    if not activities:
        return None
    for finder in (
        lambda: _longest_name_match(activities, text),
        lambda: _longest_code_match(activities, text),
        lambda: _longest_task_match(activities, text, by="name"),
        lambda: _longest_task_match(activities, text, by="code"),
    ):
        matched = finder()
        if matched is not None:
            return matched
    return None


def _normalise(payload: Any, *, path: str) -> X360ProcessDefinition:
    """把文档响应体归一化成 ``X360ProcessDefinition``；非法结构抛 ``X360ApiError``。"""
    if not isinstance(payload, dict):
        raise X360ApiError("X360 流程定义接口返回结构无效")
    code = payload.get("code")
    if payload.get("success") is False or (code is not None and code not in (200, "200")):
        message = payload.get("message") or payload.get("msg") or f"code={code}"
        raise X360ApiError(
            f"X360 流程定义接口业务失败: {str(message)[:ERROR_DETAIL_LIMIT]}"
        )
    data = payload.get("data")
    if data is None:
        raise X360ApiError("X360 流程定义接口返回空数据")
    if not isinstance(data, dict):
        raise X360ApiError("X360 流程定义接口返回结构无效")
    definition_id = _as_text(data.get("id"))
    activities: list[X360Activity] = []
    for item in data.get("activities") or []:
        if not isinstance(item, dict):
            continue
        activities.append(X360Activity(
            id=_as_text(item.get("id")),
            name=_as_text(item.get("name")),
            code=_as_text(item.get("code")),
            responsible_person=_as_text(item.get("responsiblePerson")),
            tasks=_as_tasks(item.get("tasks")),
            process_definition_id=definition_id,
        ))
    return X360ProcessDefinition(
        id=definition_id,
        code=_as_text(data.get("code")),
        name=_as_text(data.get("name")),
        activities=activities,
    )


class X360ProcessDefinitionClient:
    """只读 X360 流程定义客户端（按 ``(base_url, selector)`` 缓存）。"""

    def __init__(
        self,
        *,
        base_url: str,
        enabled: bool = True,
        app_id: str = DEFAULT_APP_ID,
        auth_token: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        cache_ttl: float = DEFAULT_CACHE_TTL_SECONDS,
        failure_cooldown: float = DEFAULT_FAILURE_COOLDOWN_SECONDS,
        selector_key: str = "",
        selector_id: str = "",
        opener: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.enabled = bool(enabled) and bool(self.base_url)
        self.app_id = (app_id or "").strip()
        self.auth_token = (auth_token or "").strip()
        self.timeout = max(MIN_TIMEOUT_SECONDS, min(float(timeout), MAX_TIMEOUT_SECONDS))
        self.cache_ttl = max(0.0, min(float(cache_ttl), MAX_CACHE_TTL_SECONDS))
        self.failure_cooldown = max(0.0, min(float(failure_cooldown), MAX_FAILURE_COOLDOWN_SECONDS))
        self.selector_key = (selector_key or "").strip()
        self.selector_id = (selector_id or "").strip()
        self._opener = opener or urlopen
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str, str], tuple[float, X360ProcessDefinition]] = {}
        self._cooldown_until = 0.0

    # -- 构造 --------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "X360ProcessDefinitionClient":
        """按环境变量构造；配置缺失返回"未启用"客户端，不抛异常。"""
        return cls(
            base_url=_env_text("X360_BASE_URL"),
            enabled=_env_flag("X360_ENABLED", True),
            app_id=_env_text("X360_APP_ID") or _env_text("ONTOLOGY_APP_ID") or DEFAULT_APP_ID,
            auth_token=_env_text("X360_AUTH_TOKEN"),
            timeout=_env_float(
                "X360_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS,
                MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS,
            ),
            cache_ttl=_env_float(
                "X360_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS,
                0.0, MAX_CACHE_TTL_SECONDS,
            ),
            failure_cooldown=_env_float(
                "X360_FAILURE_COOLDOWN_SECONDS", DEFAULT_FAILURE_COOLDOWN_SECONDS,
                0.0, MAX_FAILURE_COOLDOWN_SECONDS,
            ),
            selector_key=_env_text("X360_PROCESS_DEFINITION_KEY"),
            selector_id=_env_text("X360_PROCESS_DEFINITION_ID"),
        )

    # -- 状态 --------------------------------------------------------------

    def in_failure_cooldown(self) -> bool:
        """刚刚失败过则不再回源（避免用户点一次转督办等满超时）。"""
        with self._lock:
            return self._cooldown_until > self._clock()

    def _note_failure(self) -> None:
        if self.failure_cooldown <= 0:
            return
        with self._lock:
            self._cooldown_until = self._clock() + self.failure_cooldown

    # -- 请求 --------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.app_id:
            headers["X-App-Id"] = self.app_id
        if self.auth_token:
            token = self.auth_token
            headers["Authorization"] = (
                token if token.lower().startswith(("bearer ", "basic "))
                else f"Bearer {token}"
            )
        return headers

    def _request(self, path: str, selector: str) -> X360ProcessDefinition:
        url = f"{self.base_url}{path.format(selector=quote(selector, safe=''))}"
        request = Request(url, headers=self._headers(), method="GET")
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raise X360ApiError(f"X360 流程定义接口 HTTP {exc.code}") from None
        except URLError:
            raise X360ApiError("X360 流程定义接口连接失败") from None
        except (TimeoutError, socket.timeout):
            raise X360ApiError("X360 流程定义接口超时") from None
        except _HTTPException:
            # 截断 / 畸形 HTTP 响应（例如 IncompleteRead）：必须归一化成 X360ApiError，
            # 不能让底层异常穿透成 5xx。
            raise X360ApiError("X360 流程定义接口响应异常") from None
        except (OSError, ValueError):
            raise X360ApiError("X360 流程定义接口请求失败") from None
        try:
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            raise X360ApiError("X360 流程定义接口返回非 JSON") from None
        return _normalise(payload, path=path)

    def _fetch(self, kind: str, selector: str) -> X360ProcessDefinition:
        if not self.enabled:
            raise X360ApiError(_DISABLED_MESSAGE)
        if not selector:
            raise X360ApiError(_SELECTOR_MISSING_MESSAGE)
        cache_key = (self.base_url, kind, selector)
        if self.cache_ttl > 0:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None and cached[0] > self._clock():
                    return cached[1]
        definition = self._request(PATH_BY_KEY if kind == "key" else PATH_BY_ID, selector)
        if self.cache_ttl > 0:
            with self._lock:
                self._cache[cache_key] = (self._clock() + self.cache_ttl, definition)
        return definition

    # -- 公开只读接口 ------------------------------------------------------

    def fetch_by_key(self, key: str) -> X360ProcessDefinition:
        return self._fetch("key", (key or "").strip())

    def fetch_by_id(self, definition_id: str) -> X360ProcessDefinition:
        return self._fetch("id", _as_text(definition_id))

    def load_definition(self) -> Optional[X360ProcessDefinition]:
        """按配置的 selector 取定义；任何失败都返回 ``None`` 并进入失败冷却。"""
        if not self.enabled:
            return None
        if not self.selector_key and not self.selector_id:
            return None
        if self.in_failure_cooldown():
            return None
        try:
            if self.selector_key:
                return self.fetch_by_key(self.selector_key)
            return self.fetch_by_id(self.selector_id)
        except X360ApiError as exc:
            logger.warning("x360 process-definition fetch failed: %s", exc)
            self._note_failure()
            return None

    def match_activity(self, text: str) -> Optional[X360Activity]:
        """在配置的流程定义里匹配活动；未启用/未命中/失败都返回 ``None``。"""
        definition = self.load_definition()
        if definition is None:
            return None
        return match_activity_in(definition, text)
