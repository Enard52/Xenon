"""流式路径在 finish_reason=length 时自动续写的验收（与非流式 B12 对齐）。

通过脚本化的 SSE 帧序列（_FakeClient 每次调用返回下一段帧）验证：
- length 且有可见内容 → 追加 assistant + “继续/缺失片段”，无缝拼接；
- length 但本段无可见内容（推理吃掉预算）→ 扩大 max_tokens 重发同一请求；
- 续写次数耗尽 → ResponseTruncatedError；
- usage 跨段累计、结束时一次性发出；
- 不修改调用方 messages。
"""

from __future__ import annotations

import json

import pytest

import xenon.utils.llm_client as lc
from xenon.utils.llm_client import (
    LLMUsage,
    ModelEndpoint,
    ResponseTruncatedError,
    register_usage_callback,
)


def _ep(provider: str = "openai") -> ModelEndpoint:
    return ModelEndpoint(
        provider=provider, model_name="m", base_url="http://x", api_key="k"
    )


class _Resp:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self) -> None:
        pass

    def iter_lines(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Client:
    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []

    def stream(self, method, url, **kw):
        self.requests.append({"method": method, "url": url, **kw})
        return _Resp(self.script.pop(0))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _frame(content=None, finish=None, usage=None):
    choices = []
    if content is not None or finish is not None:
        choice = {"delta": {"content": content} if content is not None else {}}
        if finish is not None:
            choice["finish_reason"] = finish
        else:
            choice["finish_reason"] = None
        choices = [choice]
    obj = {"choices": choices}
    if usage is not None:
        obj["usage"] = usage
    return "data: " + json.dumps(obj)


def _segment(content, finish=None, usage=None):
    lines = [_frame(content=content, finish=None)]
    if usage is not None:
        lines.append(_frame(usage=usage))
    if finish is not None:
        lines.append(_frame(finish=finish))
    lines.append("data: [DONE]")
    return lines


def _no_content_segment(finish="length"):
    return [_frame(finish=finish), "data: [DONE]"]


def _patch(monkeypatch, client):
    monkeypatch.setattr(lc, "_create_http_client", lambda timeout=120: client)
    monkeypatch.setattr(lc, "build_endpoint", lambda mid, c=None, b=None: _ep())


def test_stream_length_auto_continues_and_concatenates(monkeypatch):
    client = _Client(
        [_segment("part1", finish="length"), _segment("part2", finish="stop")]
    )
    _patch(monkeypatch, client)

    chunks = list(
        lc.chat_completion_stream(
            "openai/m", [{"role": "user", "content": "hi"}]
        )
    )

    assert "".join(chunks) == "part1part2"
    assert len(client.requests) == 2
    msgs2 = client.requests[1]["json"]["messages"]
    assert msgs2[-2] == {"role": "assistant", "content": "part1"}
    assert msgs2[-1] == {"role": "user", "content": "继续"}


def test_stream_exhausted_continuations_raises(monkeypatch):
    client = _Client([_segment("x", finish="length") for _ in range(6)])
    _patch(monkeypatch, client)

    with pytest.raises(ResponseTruncatedError, match="finish_reason=length"):
        list(
            lc.chat_completion_stream(
                "openai/m", [{"role": "user", "content": "hi"}]
            )
        )

    # Initial request + exactly MAX_CONTINUATIONS continuation requests.
    assert len(client.requests) == 1 + lc.MAX_CONTINUATIONS


def test_stream_reasoning_only_length_expands_budget_and_retries(monkeypatch):
    client = _Client(
        [
            _no_content_segment("length"),
            _segment('{"answer":"ok"}', finish="stop"),
        ]
    )
    _patch(monkeypatch, client)

    chunks = list(
        lc.chat_completion_stream(
            "openai/m", [{"role": "user", "content": "hi"}]
        )
    )

    assert json.loads("".join(chunks)) == {"answer": "ok"}
    mts = [r["json"]["max_tokens"] for r in client.requests]
    assert mts == [4096, 8192]  # expanded, same request retried
    retried_msgs = client.requests[1]["json"]["messages"]
    assert all(m["role"] != "assistant" for m in retried_msgs)
    assert retried_msgs[-1] == {"role": "user", "content": "hi"}


def test_stream_json_continuation_requests_only_missing_fragment(monkeypatch):
    client = _Client(
        [
            _segment('{"a":"1', finish="length"),
            _segment('"}', finish="stop"),
        ]
    )
    _patch(monkeypatch, client)

    chunks = list(
        lc.chat_completion_stream(
            "openai/m", [{"role": "user", "content": "hi"}]
        )
    )

    assert json.loads("".join(chunks)) == {"a": "1"}
    msgs2 = client.requests[1]["json"]["messages"]
    assert "只输出缺失内容" in msgs2[-1]["content"]


def test_stream_usage_accumulated_and_emitted_once(monkeypatch):
    u1 = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
    u2 = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    client = _Client(
        [
            _segment("p1", finish="length", usage=u1),
            _segment("p2", finish="stop", usage=u2),
        ]
    )
    _patch(monkeypatch, client)
    seen: list[tuple[str, LLMUsage, float]] = []
    unsub = register_usage_callback(
        lambda m, u, lat: seen.append((m, u, lat))
    )
    try:
        chunks = list(
            lc.chat_completion_stream(
                "openai/m", [{"role": "user", "content": "hi"}]
            )
        )
    finally:
        unsub()

    assert "".join(chunks) == "p1p2"
    assert len(seen) == 1
    usage = seen[0][1]
    assert usage.prompt_tokens == 20
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 27


def test_stream_continuation_does_not_mutate_caller_messages(monkeypatch):
    client = _Client(
        [_segment("p1", finish="length"), _segment("p2", finish="stop")]
    )
    _patch(monkeypatch, client)
    original = [{"role": "user", "content": "hi"}]

    list(lc.chat_completion_stream("openai/m", original))

    assert original == [{"role": "user", "content": "hi"}]
