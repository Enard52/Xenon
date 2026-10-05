"""One recovery policy for tool refusals and non-replayable failures."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from xenon.engine.task_runtime import TaskState


_RECOVERY_CODES = frozenset(
    {"policy_denied", "permission_denied", "evidence_denied", "gate_denied"}
)


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """Decision returned after one tool outcome."""

    allow_retry: bool
    repeated: bool = False
    hint: str = ""


class RecoveryController:
    """Track one refusal reason and move the shared runtime into recovery.

    The controller stores only bounded hashes and counters in ``TaskRuntime``;
    raw parameters never enter the durable session state.
    """

    def __init__(self, runtime: Any | None) -> None:
        self.runtime = runtime

    @property
    def _counts(self) -> dict[str, int]:
        if self.runtime is None:
            return {}
        counts = self.runtime.metadata.setdefault("recovery_refusals", {})
        if not isinstance(counts, dict):
            counts = {}
            self.runtime.metadata["recovery_refusals"] = counts
        return counts

    @staticmethod
    def _key(tool_name: str, reason: str) -> str:
        digest = sha256(str(reason).encode("utf-8", "replace")).hexdigest()[:16]
        return f"{tool_name}:{digest}"

    def check(self, tool_name: str, reason: str) -> RecoveryDecision:
        """Return whether another identical refusal may be attempted."""

        if not self.runtime or not reason:
            return RecoveryDecision(True)
        count = int(self._counts.get(self._key(tool_name, reason), 0))
        if count <= 0:
            return RecoveryDecision(True)
        return RecoveryDecision(
            False,
            repeated=True,
            hint=(
                f"已拒绝过相同的 {tool_name} 操作；请改用允许的替代工具，"
                "不要重复相同调用，也不要要求用户重新授权。"
            ),
        )

    def record(
        self,
        tool_name: str,
        outcome_code: str,
        reason: str = "",
    ) -> RecoveryDecision:
        """Record a refusal and enter the shared runtime recovery state."""

        if not self.runtime or outcome_code not in _RECOVERY_CODES:
            return RecoveryDecision(True)
        key = self._key(tool_name, reason or outcome_code)
        previous = int(self._counts.get(key, 0))
        self._counts[key] = min(previous + 1, 3)
        self.runtime.metadata["last_recovery"] = {
            "tool": tool_name,
            "outcome_code": outcome_code,
            "reason": str(reason)[:300],
            "repeated": previous > 0,
        }
        if self.runtime.state is TaskState.EXECUTING:
            self.runtime.transition(TaskState.RECOVERING, reason=outcome_code)
        hint = (
            f"工具 {tool_name} 被拒绝（{outcome_code}）。请根据拒绝原因改用允许的替代工具，"
            "不要重复相同调用。"
        )
        return RecoveryDecision(previous == 0, previous > 0, hint)


def controller_for(context: Any) -> RecoveryController:
    """Return the controller bound to the context's single TaskRuntime."""

    runtime = context.get_runtime() if context is not None and hasattr(context, "get_runtime") else None
    # The controller is intentionally transient.  All durable state lives in
    # runtime.metadata, so a fresh facade is safe and session serialization
    # never sees a Python object.
    return RecoveryController(runtime)


__all__ = ["RecoveryController", "RecoveryDecision", "controller_for"]
