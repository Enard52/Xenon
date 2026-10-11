"""单一语义通道：观察文本的成功/失败只由工具回执决定，不再靠关键词猜。

回归背景：github_fetch 降级路径返回 content + success=True 但观察文本前缀含
"ConnectError"，旧实现按关键词把该步骤标为失败 → 面板显示「13 个错误」、
session 事件 success=False，污染证据账本与宣称审计。
"""

from __future__ import annotations

from xenon.engine.callbacks import ThinkingPanel
from xenon.nodes.tool_executor import ToolExecuteResult


def _result(text: str, success: bool, degraded: bool = False) -> ToolExecuteResult:
    return ToolExecuteResult(
        tool_name="github_fetch",
        success=success,
        observation=text,
        raw={"action_type": "github_fetch", "success": success, "degraded": degraded},
    )


def test_degraded_fallback_content_is_not_an_error():
    """降级成功（有内容）→ step.is_error 必须为 False。"""

    panel = ThinkingPanel()
    panel.add_action("github_fetch", {"repo": "a/b"})
    obs = _result(
        "[GitHub API 不可达，已降级读取公开网页：ConnectError]\n来源: https://github.com/a/b\n\n# README ...",
        success=True,
        degraded=True,
    ).format_observation()
    assert isinstance(obs, str)  # 兼容所有字符串下游
    assert getattr(obs, "success", None) is True
    assert getattr(obs, "degraded", None) is True
    step = panel.add_observation(obs)
    assert step.is_error is False  # 旧实现会被 ConnectError 误判为失败


def test_real_failure_still_marked():
    panel = ThinkingPanel()
    panel.add_action("github_fetch", {"repo": "a/b"})
    obs = _result(
        "工具执行失败: fetch_issue 需要编号", success=False
    ).format_observation()
    step = panel.add_observation(obs)
    assert step.is_error is True


def test_synthetic_text_keyword_fallback_preserved():
    """无工具回执的合成观察仍用关键词探测兜底。"""

    panel = ThinkingPanel()
    panel.add_action("command", {"cmd": "pytest"})
    step = panel.add_observation("执行失败: exit 1")
    assert step.is_error is True
    panel2 = ThinkingPanel()
    panel2.add_action("command", {"cmd": "pytest"})
    assert panel2.add_observation("12 passed").is_error is False


def test_plain_str_is_not_mistaken_for_structured():
    """普通 str 无 success 属性 → 走关键词探测，不影响兼容。"""

    panel = ThinkingPanel()
    panel.add_action("web_fetch", {"url": "https://x"})
    step = panel.add_observation("请求失败: 403 Forbidden")
    assert step.is_error is True


def test_observation_string_behaves_like_str():
    """str 子类：拼接/切片/比较等既有用法不破坏。"""

    obs = _result("hello world", success=True).format_observation()
    assert obs[:5] == "hello"
    assert "world" in obs
    assert f"prefix-{obs}" == "prefix-hello world"
    assert len(obs) == 11
