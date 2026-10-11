"""证据链收敛（R 收尾）：引擎不再阻断交付，版本号不再被当文件。

背景（用户实测崩溃）：只读调研任务回答里出现「.github/workflows/ci.yml」
与 Python 版本矩阵「3.10/3.11/3.12」，旧 FileClaimGate 在 finalize_evidence
里 raise → 引擎裸崩。旧设计与新设计脱节：

- 引擎内残留的交付门（finalize raise + PlanExecute 补救块）已移除；
- 校验统一由回合级 TurnGate 判定（fail → 反馈重试 → 熔断）；
- 版本号类 token 不再被 _extract_claimed_files 当作文件声称。
"""

from __future__ import annotations

from types import SimpleNamespace

from xenon.engine.context import AgentContext
from xenon.engine.evidence_gate import _extract_claimed_files, verify_file_claims
from xenon.engine.react_engine import ReActEngine


def test_version_tokens_are_not_claimed_files():
    out = _extract_claimed_files(
        "CI 覆盖 Python 3.10/3.11/3.12；改动在 .github/workflows/ci.yml。"
    )
    assert "3.10/3.11/3.12" not in out
    assert any("ci.yml" in f for f in out)  # 真实路径仍被提取


def test_version_only_claims_pass_verification():
    passed, unverified = verify_file_claims(
        "已创建 3.10/3.11/3.12 版本矩阵文件",
        tracker=None,
    )
    assert passed is True
    assert unverified == []


def test_finalize_evidence_never_raises_for_unverified_claims():
    """引擎不再阻断交付：file-claim verdict 只记录不 raise。"""

    eng = ReActEngine(["m1"])
    eng._begin_run()
    ctx = AgentContext()
    eng._bind_evidence_ledger(ctx)

    class _Tracker:
        calls = [
            SimpleNamespace(
                tool_name="read_file",
                params={"file_path": "ci.yml"},
                success=True,
                error=None,
                result_summary="ok",
                attempts=1,
                elapsed_seconds=0.1,
            )
        ]

    pack = eng.finalize_evidence(
        context=ctx,
        output="已创建 .github/workflows/ci-v99.yml（分析报告）",
        tracker=_Tracker(),
    )
    assert pack is not None
    assert pack.gate_failures >= 1  # 失败被记录（审计），而非抛异常


def test_engine_run_research_answer_completes_without_runtime_error(monkeypatch):
    """只读调研回合：回答引用文件与版本号 + 声称动词 → 引擎正常返回，
    由回合级 TurnGate 接续判定（fail → 反馈重试 → 熔断）。"""

    eng = ReActEngine(["m1"], max_iterations=3)
    monkeypatch.setattr(
        eng,
        "_call_llm_for_phase",
        lambda phase, messages, **kw: (
            '{"thought": "t", "final_answer": "已分析并创建了 '
            '.github/workflows/ci.yml 与 3.10/3.11/3.12 版本矩阵报告"}'
        ),
    )
    ctx = AgentContext()
    ctx.set_conversation_messages([])
    result = eng.run("调研这个项目", context=ctx)
    assert "3.10" in str(result)  # 正常返回回答，不抛 RuntimeError


def test_plan_execute_has_no_delivery_remediation_left():
    """PlanExecute 引擎内不再有交付补救块（校验统一回合级 TurnGate）。"""

    import pathlib

    import xenon.engine.plan_execute_engine as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert "落盘补救" not in src
    assert "delivery_gate_verdict" not in src
