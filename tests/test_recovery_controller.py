from __future__ import annotations

from xenon.engine.context import AgentContext
from xenon.engine.recovery_controller import RecoveryController
from xenon.engine.task_runtime import TaskRuntime, TaskState
from xenon.nodes.tool_executor import ToolExecutor
from xenon.repl.execution_policy import ExecutionLevel, ExecutionPolicy


def _executing_context() -> tuple[AgentContext, TaskRuntime]:
    runtime = TaskRuntime.from_user_input(
        "写入文件",
        policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"),
    )
    runtime.transition(TaskState.ROUTING)
    runtime.transition(TaskState.EXECUTING)
    context = AgentContext()
    context.bind_runtime(runtime)
    return context, runtime


def test_policy_denial_enters_recovery_and_second_identical_refusal_is_bounded():
    context, runtime = _executing_context()
    executor = ToolExecutor()
    first = executor.execute(
        "command",
        {"action": "pytest -q"},
        context,
        tools={"command": {"name": "command"}},
    )
    second = executor.execute(
        "command",
        {"action": "pytest -q"},
        context,
        tools={"command": {"name": "command"}},
    )

    assert first.outcome_code == "policy_denied"
    assert runtime.state is TaskState.RECOVERING
    assert second.outcome_code == "policy_denied"
    assert "不要重复相同调用" in second.next_hint()
    assert runtime.metadata["last_recovery"]["repeated"] is True
    assert runtime.metadata["last_recovery"]["outcome_code"] == "policy_denied"


def test_recovery_controller_does_not_persist_raw_parameters():
    _, runtime = _executing_context()
    controller = RecoveryController(runtime)
    controller.record("command", "policy_denied", "secret-token=abc")
    assert "secret-token=abc" not in runtime.snapshot()["metadata"]["recovery_refusals"]


def test_tool_executor_publishes_canonical_outcome_to_runtime():
    context, runtime = _executing_context()
    result = ToolExecutor().execute(
        "command",
        {"action": "pytest -q"},
        context,
        tools={"command": {"name": "command"}},
    )
    assert result.outcome_code == "policy_denied"
    assert runtime.metadata["last_tool_outcome"]["outcome_code"] == "policy_denied"
    assert any(event.event_type == "tool_outcome" for event in runtime.events)
