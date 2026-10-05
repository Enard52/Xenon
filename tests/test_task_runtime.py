"""Unit and contract tests for the single-source TaskRuntime foundation."""

from __future__ import annotations

import pytest

from xenon.engine.context import AgentContext
from xenon.engine.task_runtime import (
    Capability,
    DeliveryStatus,
    InvalidTaskTransition,
    OutcomeCode,
    TaskRuntime,
    TaskState,
    canonical_outcome_code,
)
from xenon.repl.model_registry import ModelRegistry
from xenon.repl.repl import REPL
from xenon.repl.execution_policy import ExecutionLevel, ExecutionPolicy
from xenon.nodes.tool_executor import execution_policy_denial
from xenon.nodes.tool_registry import required_capabilities
from xenon.engine.react_engine import ReActEngine
from xenon.engine.evidence_gate import has_successful_write
from xenon.engine.tool_tracker import ToolExecutionTracker
from xenon.engine.combined_engines import _isolated_ctx


@pytest.mark.parametrize(
    ("level", "objective", "output_mode", "capabilities"),
    [
        (ExecutionLevel.ANSWER_ONLY, "answer", "answer_only", set()),
        (ExecutionLevel.READ_ONLY, "read", "informational", {"workspace_read"}),
        (
            ExecutionLevel.WRITE,
            "modify",
            "workspace_change",
            {
                "workspace_read",
                "workspace_write",
            },
        ),
        (
            ExecutionLevel.EXECUTE,
            "execute",
            "tested_change",
            {
                "workspace_read",
                "workspace_write",
                "process_execute",
            },
        ),
    ],
)
def test_runtime_contract_maps_legacy_policy_once(
    level, objective, output_mode, capabilities
):
    runtime = TaskRuntime.from_user_input(
        "请求",
        intent="write_code",
        policy=ExecutionPolicy(level, "test"),
    )

    assert runtime.contract.objective == objective
    assert runtime.contract.output_mode == output_mode
    assert set(runtime.contract.capabilities) == capabilities
    assert runtime.contract.policy_level == int(level)
    assert runtime.state is TaskState.INTAKE
    assert runtime.events[0].event_type == "contract_created"


def test_answer_only_contract_has_no_side_effect_capabilities():
    runtime = TaskRuntime.from_user_input(
        "只在回复区域输出",
        policy=ExecutionPolicy(ExecutionLevel.ANSWER_ONLY, "answer only", explicit_no_write=True, explicit_no_execute=True),
    )

    assert not runtime.allows(Capability.WORKSPACE_READ)
    assert not runtime.allows(Capability.WORKSPACE_WRITE)
    assert not runtime.allows(Capability.PROCESS_EXECUTE)


def test_contract_is_immutable_and_snapshot_is_serializable():
    runtime = TaskRuntime.from_user_input(
        "创建 hello.py",
        policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"),
    )

    with pytest.raises(AttributeError):
        runtime.contract.output_mode = "answer_only"
    snapshot = runtime.snapshot()
    assert snapshot["contract"]["capabilities"] == [
        "workspace_read",
        "workspace_write",
    ]


def test_state_machine_records_only_legal_transitions():
    runtime = TaskRuntime.from_user_input("读取文件")

    runtime.transition(TaskState.ROUTING, reason="route")
    runtime.transition(TaskState.EXECUTING, reason="tool_required")
    runtime.transition(TaskState.VERIFYING, reason="collect_evidence")
    runtime.transition(TaskState.DELIVERING, reason="ready")
    event = runtime.deliver(DeliveryStatus.DELIVERED, reason="verified")

    assert runtime.state is TaskState.COMPLETED
    assert runtime.delivery_status is DeliveryStatus.DELIVERED
    assert event.sequence == 6
    assert [item.state for item in runtime.events] == [
        TaskState.INTAKE,
        TaskState.ROUTING,
        TaskState.EXECUTING,
        TaskState.VERIFYING,
        TaskState.DELIVERING,
        TaskState.COMPLETED,
    ]

    with pytest.raises(InvalidTaskTransition):
        runtime.transition(TaskState.EXECUTING)


def test_blocked_delivery_is_a_legal_terminal_outcome():
    runtime = TaskRuntime.from_user_input("修复 bug")
    runtime.transition(TaskState.ROUTING)
    runtime.transition(TaskState.EXECUTING)
    runtime.transition(TaskState.DELIVERING)
    runtime.deliver(DeliveryStatus.BLOCKED, reason="missing evidence")
    assert runtime.state is TaskState.BLOCKED


def test_workspace_baseline_excludes_preexisting_dirty_state(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    target = tmp_path / "value.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "value.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    target.write_text("preexisting\n", encoding="utf-8")

    runtime = TaskRuntime.from_user_input(
        "写入 value.txt",
        policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"),
        workspace_root=str(tmp_path),
    )
    tracker = ToolExecutionTracker()
    tracker.record("command", {"action": "echo inspect"}, True, "ok")
    assert not has_successful_write(
        tracker,
        workspace_root=tmp_path,
        baseline=runtime.workspace_baseline,
    )
    target.write_text("turn-change\n", encoding="utf-8")
    assert has_successful_write(
        tracker,
        workspace_root=tmp_path,
        baseline=runtime.workspace_baseline,
    )


def test_isolated_combined_context_reuses_same_runtime():
    context = AgentContext()
    runtime = TaskRuntime.from_user_input("写入文件", policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"))
    context.bind_runtime(runtime)
    assert _isolated_ctx(context).runtime is runtime


def test_recovery_can_return_to_execution_without_reclassifying_prompt():
    runtime = TaskRuntime.from_user_input(
        "保存文件",
        policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"),
    )
    runtime.transition(TaskState.ROUTING)
    runtime.transition(TaskState.EXECUTING)
    runtime.transition(TaskState.RECOVERING, reason="policy_denied")
    runtime.transition(TaskState.EXECUTING, reason="use_write_file")

    assert runtime.contract.policy_level == ExecutionLevel.WRITE
    assert runtime.events[-1].reason == "use_write_file"


def test_context_binds_one_runtime_and_rejects_replacement():
    context = AgentContext()
    runtime = TaskRuntime.from_user_input("hello")

    assert context.bind_runtime(runtime) is runtime
    assert context.runtime is runtime
    assert context.get_runtime() is runtime
    assert context.bind_runtime(runtime) is runtime

    with pytest.raises(RuntimeError, match="different task runtime"):
        context.bind_runtime(TaskRuntime.from_user_input("other"))

    replacement = TaskRuntime.from_user_input("next turn")
    assert context.bind_runtime(replacement, replace=True) is replacement
    assert context.runtime is replacement


def test_canonical_outcome_collapses_retry_labels_and_preserves_unknown_state():
    assert canonical_outcome_code("terminal") == OutcomeCode.TOOL_FAILED.value
    assert canonical_outcome_code("transient") == OutcomeCode.TOOL_FAILED.value
    assert (
        canonical_outcome_code(
            "transient", tool_class="WRITE", status_unknown=True
        )
        == OutcomeCode.STATUS_UNKNOWN.value
    )
    assert (
        canonical_outcome_code("permission_required")
        == OutcomeCode.PERMISSION_DENIED.value
    )


def test_runtime_records_one_bounded_tool_outcome_event():
    runtime = TaskRuntime.from_user_input(
        "写入文件", policy=ExecutionPolicy(ExecutionLevel.WRITE, "write")
    )
    runtime.transition(TaskState.ROUTING)
    runtime.transition(TaskState.EXECUTING)
    code = runtime.record_tool_outcome(
        "write_file",
        "transient",
        tool_class="WRITE",
        state="failed",
        status_unknown=True,
        error="secret-token=must-not-leak",
    )
    assert code == OutcomeCode.STATUS_UNKNOWN.value
    event = runtime.events[-1]
    assert event.event_type == "tool_outcome"
    assert event.data["tool"] == "write_file"
    assert event.data["outcome_code"] == "status_unknown"
    assert "secret-token=must-not-leak" in event.data["error"]
    assert runtime.metadata["outcome_counts"]["status_unknown"] == 1


def test_runtime_reconstructs_policy_without_reclassifying_prompt():
    runtime = TaskRuntime.from_user_input(
        "只在回复区域输出代码，文件已保存只是示例",
        policy=ExecutionPolicy(
            ExecutionLevel.ANSWER_ONLY,
            "locked",
            explicit_no_write=True,
            explicit_no_execute=True,
        ),
    )
    policy = runtime.execution_policy
    assert policy.level is ExecutionLevel.ANSWER_ONLY
    assert policy.locks_answer_only is True


def test_runtime_preserves_explicit_execute_constraint_for_write_turn():
    runtime = TaskRuntime.from_user_input(
        "写入文件但不要执行命令",
        policy=ExecutionPolicy(
            ExecutionLevel.WRITE,
            "write",
            explicit_no_execute=True,
        ),
    )
    assert runtime.execution_policy.explicit_no_execute is True
    assert runtime.contract.to_dict()["explicit_no_execute"] is True


def test_begin_delivery_closes_unresolved_recovery_as_warning():
    runtime = TaskRuntime.from_user_input(
        "写入文件", policy=ExecutionPolicy(ExecutionLevel.WRITE, "write")
    )
    runtime.transition(TaskState.ROUTING)
    runtime.transition(TaskState.EXECUTING)
    runtime.record_tool_outcome("command", "policy_denied")
    runtime.begin_delivery(reason="engine_result")
    runtime.deliver(DeliveryStatus.DELIVERED_WITH_WARNINGS)
    assert runtime.state is TaskState.COMPLETED_WITH_WARNINGS
    assert runtime.delivery_status is DeliveryStatus.DELIVERED_WITH_WARNINGS


def test_special_engine_tools_use_registry_capabilities():
    assert required_capabilities("list_skills") == frozenset({"workspace_read"})
    assert required_capabilities("create_skill") == frozenset({"workspace_write"})


def test_refusal_from_routing_also_enters_recovery():
    runtime = TaskRuntime.from_user_input(
        "写入文件", policy=ExecutionPolicy(ExecutionLevel.WRITE, "write")
    )
    runtime.transition(TaskState.ROUTING)
    runtime.record_tool_outcome("command", OutcomeCode.POLICY_DENIED)
    assert runtime.state is TaskState.RECOVERING


def test_repl_binds_one_runtime_at_turn_boundary(monkeypatch):
    registry = ModelRegistry()
    registry.add_model("openai/test", "test")
    registry.assign_role("planner", ["test"])
    repl = REPL(registry=registry, streaming=False, optimize_prompts=False)
    repl.intelligent_router.enabled = False
    monkeypatch.setattr(
        repl.auto_router,
        "route",
        lambda *args, **kwargs: ["openai/test"],
    )
    monkeypatch.setattr(
        repl,
        "_run_direct",
        lambda *args, **kwargs: None,
    )

    repl._handle_chat("只在回复区域输出代码")

    runtime = repl.agent_context.runtime
    assert runtime.contract.output_mode == "answer_only"
    assert runtime.state is TaskState.ROUTING
    assert runtime.contract.user_input == "只在回复区域输出代码"


def test_answer_only_direct_response_is_not_rerouted_by_file_words(monkeypatch):
    registry = ModelRegistry()
    registry.add_model("openai/test", "test")
    registry.assign_role("planner", ["test"])
    repl = REPL(registry=registry, streaming=False, optimize_prompts=False)
    repl.intelligent_router.enabled = False
    monkeypatch.setattr(
        repl.auto_router,
        "route",
        lambda *args, **kwargs: ["openai/test"],
    )
    rendered: list[str] = []
    rerouted: list[str] = []
    monkeypatch.setattr(
        repl,
        "_blocking_response",
        lambda *_args: '```python\nprint("文件已保存，但这里只是回复文本")\n```',
    )
    monkeypatch.setattr(
        repl,
        "_render_assistant_text",
        lambda content, **_kwargs: rendered.append(content),
    )
    monkeypatch.setattr(
        repl,
        "_run_react_engine",
        lambda *_args: rerouted.append("react"),
    )

    repl._handle_chat("只在回复区域输出代码")

    assert rerouted == []
    assert rendered and "文件已保存" in rendered[-1]
    assert repl.agent_context.runtime.state is TaskState.COMPLETED


def test_tool_policy_reads_runtime_contract_before_legacy_context_key():
    context = AgentContext({"_execution_level": int(ExecutionLevel.EXECUTE)})
    runtime = TaskRuntime.from_user_input(
        "只在回复区域输出",
        policy=ExecutionPolicy(ExecutionLevel.ANSWER_ONLY, "answer only", explicit_no_write=True, explicit_no_execute=True),
    )
    context.bind_runtime(runtime)

    reason = execution_policy_denial(
        "write_file",
        {"file_path": "x.py", "content": "pass"},
        context,
    )

    assert reason is not None
    assert "仅回答" in reason


def test_tool_policy_enforces_capability_even_when_legacy_level_would_pass():
    context = AgentContext()
    runtime = TaskRuntime.from_user_input(
        "修改本地文件",
        policy=ExecutionPolicy(ExecutionLevel.WRITE, "write"),
    )
    context.bind_runtime(runtime)
    reason = execution_policy_denial("web_fetch", {"url": "https://example.com"}, context)
    assert reason is not None
    assert "network_read" in reason


def test_react_consumes_bound_runtime_without_reclassifying_prompt(monkeypatch):
    context = AgentContext()
    runtime = TaskRuntime.from_user_input(
        "只在回复区域输出代码",
        intent="write_code",
        policy=ExecutionPolicy(ExecutionLevel.ANSWER_ONLY, "answer only", explicit_no_write=True, explicit_no_execute=True),
    )
    context.bind_runtime(runtime)
    engine = ReActEngine(["m1"], max_iterations=2, native_fc=False)

    monkeypatch.setattr(
        engine,
        "_input_requires_tools",
        lambda _text: pytest.fail("bound runtime must be authoritative"),
    )
    engine._call_llm = lambda *args, **kwargs: '{"final_answer":"代码"}'
    engine._parse_response = lambda _raw: {
        "thought": "",
        "action": "",
        "final_answer": "代码",
    }

    assert engine.run("请创建文件并运行命令", context) == "代码"
