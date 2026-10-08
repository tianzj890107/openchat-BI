"""X360 只读客户端包（流程定义 AI 视图接口）。

契约：``docs/specs/x360-process-definition-integration.md``。
本包只做只读访问，不发送任何写请求。
"""

from .client import (
    X360Activity,
    X360ApiError,
    X360ProcessDefinition,
    X360ProcessDefinitionClient,
)

__all__ = [
    "X360Activity",
    "X360ApiError",
    "X360ProcessDefinition",
    "X360ProcessDefinitionClient",
]
