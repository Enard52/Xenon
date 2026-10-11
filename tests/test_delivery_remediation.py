"""发布门规则回归测试。

背景：SWE-bench 最大失分点「贴 diff 不落盘」——LLM 声称修改/创建了
文件，但工具执行记录里没有对应写操作证据。此前 FileClaimGate 在引擎内
拦截（交付闸门补救循环），验证统一到回合级 TurnGate 后，该规则由
TurnGate 的文件声称审计承接；写入后验证失败（原 VerificationLoop）与
空洞回答（原 HollowDetector）同样上移。
"""

from __future__ import annotations

from xenon.turn.gate import VERDICT_FAIL, VERDICT_PASS, VERDICT_REMIND, TurnGate


class TestTurnGateFileClaims:
    """原引擎交付闸门语义 → 回合级 TurnGate 文件声称审计。"""

    def test_unverified_file_claim_fails_gate(self, tmp_path):
        """声称创建 x.py 但只写过 a.py → TurnGate fail。"""

        gate = TurnGate()
        target = tmp_path / "x.py"
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": str(tmp_path / "a.py")},
            }
        ]
        answer = (
            f"已创建 {target}，内容如下：\n```python\nprint(1)\n```\n"
            f"共 12 行，已完成写入流程。\n"
        )
        verdict = gate.evaluate(answer, tool_events=events)
        assert verdict.outcome == VERDICT_REMIND  # L2 语义层：提醒不阻断
        assert any("未经工具验证" in r for r in verdict.reasons)

    def test_verified_claim_passes_gate(self, tmp_path):
        target = tmp_path / "x.py"
        gate = TurnGate()
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": str(target)},
            }
        ]
        verdict = gate.evaluate(f"已创建 {target}，内容已写入", tool_events=events)
        assert verdict.outcome == VERDICT_PASS

    def test_semantic_claims_never_fuse(self, tmp_path):
        """L2 语义层不进入重试轮次：同因提醒两次仍为 remind（不熔断）。"""

        gate = TurnGate(max_same_cause_failures=2)
        target = tmp_path / "x.py"
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": str(tmp_path / "a.py")},
            }
        ]
        answer = (
            f"已创建 {target}，内容如下：\n```python\nprint(1)\n```\n"
            f"共 12 行，已完成写入流程。\n"
        )
        first = gate.evaluate(answer, tool_events=events)
        second = gate.evaluate(answer, tool_events=events)
        assert first.outcome == VERDICT_REMIND
        assert second.outcome == VERDICT_REMIND  # 语义层永不熔断


class TestTurnGateWriteVerify:
    """原引擎 VerificationLoop 语义 → 回合级写入后验证规则。"""

    def test_write_then_failed_test_without_disclosure_fails(self):
        gate = TurnGate()
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": "x.py"},
            },
            {"tool": "command", "success": False, "error": "assert 失败"},
        ]
        answer = (
            "修复完成：已修改 x.py 中的函数逻辑，新增边界检查。\n"
            "```python\ndef f(): return 1\n```\n"
        )
        verdict = gate.evaluate(answer, tool_events=events)
        assert verdict.outcome == VERDICT_REMIND  # L2 提醒不阻断
        assert any("写入后验证" in r for r in verdict.reasons)

    def test_disclosed_failure_passes(self):
        gate = TurnGate()
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": "x.py"},
            },
            {"tool": "command", "success": False, "error": "assert 失败"},
        ]
        verdict = gate.evaluate(
            "写入完成，但测试仍失败：assert 失败（需要进一步排查）",
            tool_events=events,
        )
        assert verdict.outcome == VERDICT_PASS

    def test_successful_test_passes(self):
        gate = TurnGate()
        events = [
            {
                "tool": "write_file",
                "success": True,
                "params": {"file_path": "x.py"},
            },
            {"tool": "command", "success": True, "error": ""},
        ]
        verdict = gate.evaluate("已修改 x.py 并运行测试，全部通过。", tool_events=events)
        assert verdict.outcome == VERDICT_PASS


class TestTurnGateHollow:
    """原引擎空洞回答拦截 → 回合级空洞规则。"""

    def test_hollow_after_tools_fails(self):
        gate = TurnGate()
        events = [{"tool": "read_file", "success": True}]
        verdict = gate.evaluate("好的", tool_events=events)
        assert verdict.outcome == VERDICT_FAIL
        assert any("空洞" in r for r in verdict.reasons)

    def test_short_chat_without_tools_passes(self):
        gate = TurnGate()
        verdict = gate.evaluate("好的", tool_events=[])
        assert verdict.outcome == VERDICT_PASS

    def test_completion_claim_without_tools_is_hollow(self):
        """宣称完成但无任何工具与产物结构 → 空洞（即使无工具回执）。"""

        gate = TurnGate()
        verdict = gate.evaluate("已完成修复", tool_events=[])
        assert verdict.outcome == VERDICT_FAIL
        assert any("空洞" in r for r in verdict.reasons)


def test_windows_backslash_path_is_not_hollow():
    """回归：省略号模式曾把 Windows 反斜杠路径误判为空洞回答。"""

    from xenon.engine.hollow_detector import HollowDetector

    path = "C:" + chr(92) + "Users" + chr(92) + "Admin" + chr(92) + "x.py"
    answer = f"已修改 {path}，共 3 处，验证通过。\n```python\nprint(1)\n```\n"
    result = HollowDetector().detect(answer, 1)
    assert result.is_hollow is False
