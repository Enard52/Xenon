"""Single-source task runtime for one Xenon user turn.

The runtime is deliberately small and independent from any particular engine.
It turns the user's request into one immutable :class:`TurnContract`, owns the
task state machine, and exposes capability checks to every execution layer.
During the migration period older ``_execution_level`` fields remain valid;
new code should consume this module instead of classifying the raw prompt a
second time.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Any, Mapping


class Capability(str, Enum):
    """Side-effect capabilities understood by the runtime."""

    WORKSPACE_READ = "workspace_read"
    WORKSPACE_WRITE = "workspace_write"
    PROCESS_EXECUTE = "process_execute"
    NETWORK_READ = "network_read"
    NETWORK_WRITE = "network_write"
    GIT_MUTATE = "git_mutate"
    SPAWN_AGENT = "spawn_agent"


class TaskState(str, Enum):
    """Lifecycle states for one user turn."""

    INTAKE = "intake"
    ROUTING = "routing"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    VERIFYING = "verifying"
    DELIVERING = "delivering"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    """User-visible outcome of a task."""

    DELIVERED = "delivered"
    DELIVERED_WITH_WARNINGS = "delivered_with_warnings"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"
    FAILED = "failed"


class OutcomeCode(str, Enum):
    """Canonical result categories shared by tools, recovery and delivery."""

    SUCCESS = "success"
    POLICY_DENIED = "policy_denied"
    PERMISSION_DENIED = "permission_denied"
    EVIDENCE_DENIED = "evidence_denied"
    GATE_DENIED = "gate_denied"
    INVALID_PARAMETERS = "invalid_parameters"
    UNKNOWN_TOOL = "unknown_tool"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    STATUS_UNKNOWN = "status_unknown"
    TOOL_FAILED = "tool_failed"


_CANONICAL_OUTCOMES = frozenset(item.value for item in OutcomeCode)


def canonical_outcome_code(
    raw: str | None = None,
    *,
    success: bool = False,
    tool_class: str = "",
    state: str = "",
    status_unknown: bool = False,
) -> str:
    """Normalize legacy executor labels into one bounded outcome vocabulary.

    ``terminal`` and ``transient`` describe retry mechanics, not user-visible
    outcomes.  They are intentionally collapsed here so every consumer sees
    the same distinction: refusal, real failure, or unknown side effect state.
    """

    if success:
        return OutcomeCode.SUCCESS.value
    value = str(raw or "").strip().lower()
    aliases = {
        "canceled": OutcomeCode.CANCELLED.value,
        "cancelled": OutcomeCode.CANCELLED.value,
        "timed_out": OutcomeCode.TIMEOUT.value,
        "timeout": OutcomeCode.TIMEOUT.value,
        "permission_required": OutcomeCode.PERMISSION_DENIED.value,
    }
    value = aliases.get(value, value)
    if value in _CANONICAL_OUTCOMES:
        if (
            value == OutcomeCode.TIMEOUT.value
            and tool_class
            and tool_class != "INFO"
        ):
            return OutcomeCode.STATUS_UNKNOWN.value
        return value
    if status_unknown or (
        tool_class
        and tool_class != "INFO"
        and value in {"transient", "timeout", "timed_out"}
    ):
        return OutcomeCode.STATUS_UNKNOWN.value
    return OutcomeCode.TOOL_FAILED.value


class InvalidTaskTransition(ValueError):
    """Raised when an engine attempts an impossible lifecycle transition."""


@dataclass(frozen=True, slots=True)
class TurnContract:
    """Immutable authorization and delivery contract for one user turn."""

    turn_id: str
    user_input: str
    intent: str | None
    objective: str
    capabilities: frozenset[str]
    output_mode: str
    verification_mode: str
    workspace_root: str | None = None
    workspace_scope: tuple[str, ...] = ()
    policy_level: int = 0
    policy_reason: str = ""
    locked_answer_only: bool = False
    explicit_no_write: bool = False
    explicit_no_execute: bool = False
    # Captured at turn intake when a workspace is known.  A later git status
    # is only evidence of this turn when it differs from this baseline.
    workspace_baseline_status: str = ""
    workspace_baseline_diff: str = ""

    def allows(self, capability: str | Capability) -> bool:
        """Return whether this turn authorizes one capability."""

        value = capability.value if isinstance(capability, Capability) else str(capability)
        return value in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        """Return a stable, JSON-compatible contract snapshot."""

        return {
            "turn_id": self.turn_id,
            "user_input": self.user_input,
            "intent": self.intent,
            "objective": self.objective,
            "capabilities": sorted(self.capabilities),
            "output_mode": self.output_mode,
            "verification_mode": self.verification_mode,
            "workspace_root": self.workspace_root,
            "workspace_scope": list(self.workspace_scope),
            "policy_level": self.policy_level,
            "policy_reason": self.policy_reason,
            "locked_answer_only": self.locked_answer_only,
            "explicit_no_write": self.explicit_no_write,
            "explicit_no_execute": self.explicit_no_execute,
            "workspace_baseline_status": self.workspace_baseline_status,
            "workspace_baseline_diff": self.workspace_baseline_diff,
        }


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Append-only lifecycle event used for diagnostics and later evidence binding."""

    sequence: int
    event_type: str
    state: TaskState
    reason: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "state": self.state.value,
            "reason": self.reason,
            "data": dict(self.data),
            "timestamp": self.timestamp,
        }


_CAPABILITIES_BY_LEVEL: dict[int, frozenset[str]] = {
    0: frozenset(),
    1: frozenset({Capability.WORKSPACE_READ.value}),
    2: frozenset(
        {Capability.WORKSPACE_READ.value, Capability.WORKSPACE_WRITE.value}
    ),
    3: frozenset(
        {
            Capability.WORKSPACE_READ.value,
            Capability.WORKSPACE_WRITE.value,
            Capability.PROCESS_EXECUTE.value,
        }
    ),
}


_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.INTAKE: frozenset(
        {TaskState.ROUTING, TaskState.CANCELLED, TaskState.FAILED}
    ),
    TaskState.ROUTING: frozenset(
        {
            TaskState.EXECUTING,
            TaskState.RECOVERING,
            TaskState.DELIVERING,
            TaskState.WAITING_USER,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.EXECUTING: frozenset(
        {
            TaskState.RECOVERING,
            TaskState.VERIFYING,
            TaskState.DELIVERING,
            TaskState.WAITING_USER,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.RECOVERING: frozenset(
        {
            TaskState.EXECUTING,
            TaskState.VERIFYING,
            TaskState.DELIVERING,
            TaskState.WAITING_USER,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.VERIFYING: frozenset(
        {
            TaskState.RECOVERING,
            TaskState.DELIVERING,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.DELIVERING: frozenset(
        {
            TaskState.COMPLETED,
            TaskState.COMPLETED_WITH_WARNINGS,
            TaskState.BLOCKED,
            TaskState.FAILED,
        }
    ),
    TaskState.WAITING_USER: frozenset(
        {TaskState.ROUTING, TaskState.EXECUTING, TaskState.CANCELLED}
    ),
    TaskState.COMPLETED: frozenset(),
    TaskState.COMPLETED_WITH_WARNINGS: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.BLOCKED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def _policy_details(level: int) -> tuple[str, str, str]:
    """Map the existing ExecutionLevel value to runtime semantics."""

    if level >= 3:
        return "execute", "tested_change", "tests"
    if level == 2:
        return "modify", "workspace_change", "workspace"
    if level == 1:
        return "read", "informational", "none"
    return "answer", "answer_only", "none"


def _workspace_snapshot(root: str | None) -> tuple[str, str]:
    """Capture a bounded, read-only git baseline for the current workspace."""

    if not root:
        return "", ""
    try:
        path = Path(root).resolve()
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        diff = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--unified=3"],
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if status.returncode != 0:
            return "", ""
        return status.stdout.strip(), diff.stdout.strip() if diff.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return "", ""


def _request_capabilities(
    user_input: str, level: int, intent: str | None = None
) -> frozenset[str]:
    """Add capabilities explicitly requested by this turn.

    A write or execute policy is intentionally not a blanket grant for network,
    git, or agent spawning.  Those capabilities are opt-in evidence from the
    request itself and remain visible in the immutable contract.
    """

    capabilities = set(_CAPABILITIES_BY_LEVEL.get(level, _CAPABILITIES_BY_LEVEL[3]))
    text = str(user_input or "").lower()
    if intent in {"query", "research"}:
        capabilities.add(Capability.NETWORK_READ.value)
    if any(token in text for token in ("http://", "https://", "网页", "网络", "抓取", "下载", "fetch")):
        capabilities.add(Capability.NETWORK_READ.value)
    if any(token in text for token in ("git ", "git/", "提交", "推送", "合并", "commit", "push", "merge")):
        capabilities.add(Capability.GIT_MUTATE.value)
    if any(token in text for token in ("post", "publish", "deploy", "发送到", "发布到")):
        capabilities.add(Capability.NETWORK_WRITE.value)
    if any(token in text for token in ("子 agent", "子agent", "subagent", "spawn_agent", "委派")):
        capabilities.add(Capability.SPAWN_AGENT.value)
    return frozenset(capabilities)


@dataclass
class TaskRuntime:
    """Mutable per-turn owner of the contract and lifecycle state."""

    contract: TurnContract
    state: TaskState = TaskState.INTAKE
    delivery_status: DeliveryStatus | None = None
    events: list[RuntimeEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.events:
            self.events.append(
                RuntimeEvent(
                    sequence=1,
                    event_type="contract_created",
                    state=self.state,
                    data=MappingProxyType(self.contract.to_dict()),
                )
            )

    @classmethod
    def from_user_input(
        cls,
        user_input: str,
        *,
        intent: str | None = None,
        policy: Any | None = None,
        workspace_root: str | None = None,
        workspace_scope: tuple[str, ...] | list[str] = (),
        turn_id: str | None = None,
    ) -> "TaskRuntime":
        """Create the sole contract for a user turn.

        ``policy`` is accepted as an object so the existing classifier can be
        used during migration.  Once a runtime exists, downstream code must
        read the contract and must not classify ``user_input`` again.
        """

        if policy is None:
            from xenon.repl.execution_policy import classify_execution_policy

            policy = classify_execution_policy(user_input, intent=intent)
        level = int(getattr(policy, "level", 0))
        objective, output_mode, verification_mode = _policy_details(level)
        capabilities = _request_capabilities(user_input, level, intent)
        baseline_status, baseline_diff = _workspace_snapshot(workspace_root)
        contract = TurnContract(
            turn_id=turn_id or uuid.uuid4().hex,
            user_input=user_input,
            intent=intent,
            objective=objective,
            capabilities=frozenset(capabilities),
            output_mode=output_mode,
            verification_mode=verification_mode,
            workspace_root=workspace_root,
            workspace_scope=tuple(workspace_scope),
            policy_level=level,
            policy_reason=str(getattr(policy, "reason", "")),
            locked_answer_only=bool(getattr(policy, "locks_answer_only", False)),
            explicit_no_write=bool(getattr(policy, "explicit_no_write", False)),
            explicit_no_execute=bool(getattr(policy, "explicit_no_execute", False)),
            workspace_baseline_status=baseline_status,
            workspace_baseline_diff=baseline_diff,
        )
        return cls(contract)

    def allows(self, capability: str | Capability) -> bool:
        return self.contract.allows(capability)

    @property
    def execution_policy(self) -> Any:
        """Return the policy object reconstructed from the immutable contract."""

        from xenon.repl.execution_policy import ExecutionLevel, ExecutionPolicy

        return ExecutionPolicy(
            ExecutionLevel(self.contract.policy_level),
            self.contract.policy_reason,
            explicit_no_write=self.contract.explicit_no_write,
            explicit_no_execute=self.contract.explicit_no_execute,
        )

    def record_tool_outcome(
        self,
        tool_name: str,
        outcome_code: str | OutcomeCode,
        *,
        success: bool = False,
        tool_class: str = "",
        state: str = "",
        error: str = "",
        status_unknown: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> str:
        """Publish one canonical tool outcome to the shared runtime.

        The event is deliberately bounded and never stores tool parameters.
        Recovery and UI code can therefore consume this method without
        re-parsing observation text or maintaining another per-engine ledger.
        """

        raw_code = (
            outcome_code.value
            if isinstance(outcome_code, OutcomeCode)
            else str(outcome_code)
        )
        code = canonical_outcome_code(
            raw_code,
            success=success,
            tool_class=tool_class,
            state=state,
            status_unknown=status_unknown,
        )
        payload: dict[str, Any] = {
            "tool": str(tool_name)[:120],
            "outcome_code": code,
            "success": bool(success),
            "state": str(state)[:40],
        }
        if error:
            payload["error"] = str(error)[:300]
        if data:
            for key, value in data.items():
                if key not in payload:
                    payload[str(key)] = value
        counts = self.metadata.setdefault("outcome_counts", {})
        if not isinstance(counts, dict):
            counts = {}
            self.metadata["outcome_counts"] = counts
        counts[code] = int(counts.get(code, 0)) + 1
        self.metadata["last_tool_outcome"] = dict(payload)
        if code == OutcomeCode.STATUS_UNKNOWN.value:
            self.metadata["status_unknown"] = True
        self.events.append(
            RuntimeEvent(
                sequence=len(self.events) + 1,
                event_type="tool_outcome",
                state=self.state,
                reason=code,
                data=MappingProxyType(payload),
            )
        )
        if code in {
            OutcomeCode.POLICY_DENIED.value,
            OutcomeCode.PERMISSION_DENIED.value,
            OutcomeCode.EVIDENCE_DENIED.value,
            OutcomeCode.GATE_DENIED.value,
        } and self.state in {
            TaskState.ROUTING,
            TaskState.EXECUTING,
            TaskState.VERIFYING,
        }:
            self.transition(TaskState.RECOVERING, reason=code)
        elif code == OutcomeCode.SUCCESS.value and self.state is TaskState.RECOVERING:
            self.transition(TaskState.EXECUTING, reason="recovery_succeeded")
        return code

    @property
    def workspace_baseline(self) -> dict[str, str]:
        """Return the immutable workspace snapshot captured at intake."""

        return {
            "status": self.contract.workspace_baseline_status,
            "diff": self.contract.workspace_baseline_diff,
        }

    def bind_workspace_root(self, workspace_root: str | Path) -> None:
        """Bind the trusted workspace before execution starts.

        REPL routing may happen before project discovery.  This late binding
        fills the same intake baseline just before the first tool call while
        preserving the immutable contract object seen by all later consumers.
        """

        root = str(Path(workspace_root).resolve())
        if self.contract.workspace_root and self.contract.workspace_root != root:
            raise ValueError("task runtime workspace root cannot be replaced")
        if self.contract.workspace_root == root and (
            self.contract.workspace_baseline_status
            or self.contract.workspace_baseline_diff
        ):
            return
        status, diff = _workspace_snapshot(root)
        self.contract = replace(
            self.contract,
            workspace_root=root,
            workspace_baseline_status=status,
            workspace_baseline_diff=diff,
        )
        self.events.append(
            RuntimeEvent(
                sequence=len(self.events) + 1,
                event_type="workspace_baseline_captured",
                state=self.state,
                data=MappingProxyType(
                    {
                        "workspace_root": root,
                        "status": status,
                        "diff_chars": len(diff),
                    }
                ),
            )
        )

    def transition(
        self,
        new_state: TaskState,
        *,
        reason: str = "",
        data: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Move to a legal state and append exactly one lifecycle event."""

        target = TaskState(new_state)
        if target not in _TRANSITIONS[self.state]:
            raise InvalidTaskTransition(
                f"invalid task transition: {self.state.value} -> {target.value}"
            )
        self.state = target
        event = RuntimeEvent(
            sequence=len(self.events) + 1,
            event_type="state_transition",
            state=target,
            reason=reason,
            data=MappingProxyType(dict(data or {})),
        )
        self.events.append(event)
        return event

    def deliver(
        self,
        status: DeliveryStatus,
        *,
        reason: str = "",
        data: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Record the final delivery status through the state machine."""

        status = DeliveryStatus(status)
        target = (
            TaskState.COMPLETED_WITH_WARNINGS
            if status is DeliveryStatus.DELIVERED_WITH_WARNINGS
            else TaskState.COMPLETED
            if status is DeliveryStatus.DELIVERED
            else TaskState.BLOCKED
            if status is DeliveryStatus.BLOCKED
            else TaskState.FAILED
        )
        if self.state is not TaskState.DELIVERING:
            raise InvalidTaskTransition(
                f"delivery requires delivering state, got {self.state.value}"
            )
        self.delivery_status = status
        return self.transition(target, reason=reason, data=data)

    def begin_delivery(self, *, reason: str = "") -> RuntimeEvent:
        """Enter the delivery phase from any still-live execution state."""

        if self.state is TaskState.DELIVERING:
            return self.events[-1]
        if self.state not in {
            TaskState.ROUTING,
            TaskState.EXECUTING,
            TaskState.RECOVERING,
            TaskState.VERIFYING,
        }:
            raise InvalidTaskTransition(
                f"delivery cannot start from {self.state.value}"
            )
        return self.transition(TaskState.DELIVERING, reason=reason)

    @property
    def delivery_needs_warning(self) -> bool:
        """Whether the latest execution fact makes delivery provisional."""

        latest = self.metadata.get("last_tool_outcome")
        if not isinstance(latest, dict):
            return False
        return str(latest.get("outcome_code", "")) != OutcomeCode.SUCCESS.value

    def snapshot(self) -> dict[str, Any]:
        """Return a serialisable diagnostic snapshot."""

        return {
            "contract": self.contract.to_dict(),
            "state": self.state.value,
            "delivery_status": (
                self.delivery_status.value if self.delivery_status else None
            ),
            "events": [event.to_dict() for event in self.events],
            "metadata": dict(self.metadata),
        }


__all__ = [
    "Capability",
    "DeliveryStatus",
    "InvalidTaskTransition",
    "OutcomeCode",
    "RuntimeEvent",
    "TaskRuntime",
    "TaskState",
    "TurnContract",
    "canonical_outcome_code",
]
