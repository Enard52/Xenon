"""Tests for the Windows prompt_toolkit bracketed-paste watchdog (paste_guard)."""

from __future__ import annotations

import asyncio

from prompt_toolkit.input.vt100_parser import Vt100Parser

from xenon.repl import paste_guard
from xenon.repl.paste_guard import (
    arm_paste_watchdog,
    find_vt_parser,
    reset_stuck_paste,
)


class _Collector:
    def __init__(self) -> None:
        self.keys = []

    def __call__(self, kp) -> None:
        self.keys.append(kp)


def _make_parser():
    collector = _Collector()
    return Vt100Parser(collector), collector


def _force_stuck(parser) -> None:
    """Paste start + content, but no end mark -> parser is wedged in paste mode."""
    parser.feed("\x1b[200~")
    parser.feed("abc")
    assert parser._in_bracketed_paste is True


class _Reader:
    def __init__(self, parser) -> None:
        self._vt100_parser = parser


class _Input:
    def __init__(self, parser) -> None:
        self.console_input_reader = _Reader(parser)


class _FakeApp:
    def __init__(self, parser) -> None:
        self.is_done = False
        self.input = _Input(parser)
        self.pre_run_callables = []
        self.spawned = []

    def create_background_task(self, coro):
        self.spawned.append(coro)
        return coro


class _FakeSession:
    def __init__(self, app) -> None:
        self.app = app


def _session(parser) -> _FakeSession:
    return _FakeSession(_FakeApp(parser))


def test_parser_swallows_keys_without_end_mark() -> None:
    """Documents the bug: without the end mark, letters and even Ctrl+C are eaten."""
    parser, collector = _make_parser()
    _force_stuck(parser)
    parser.feed("x")
    parser.feed("\x03")
    assert collector.keys == []


def test_parser_reset_recovers_input() -> None:
    parser, collector = _make_parser()
    _force_stuck(parser)
    parser.reset()
    assert parser._in_bracketed_paste is False
    parser.feed("z")
    assert [kp.data for kp in collector.keys] == ["z"]


def test_find_vt_parser() -> None:
    parser, _ = _make_parser()
    assert find_vt_parser(_session(parser)) is parser
    assert find_vt_parser(object()) is None


def test_reset_stuck_paste() -> None:
    parser, _ = _make_parser()
    session = _session(parser)
    assert reset_stuck_paste(session) is False  # not stuck yet
    assert reset_stuck_paste(object()) is False  # nothing to introspect
    _force_stuck(parser)
    assert reset_stuck_paste(session) is True
    assert parser._in_bracketed_paste is False


def test_feed_timestamp_tracks_and_is_idempotent() -> None:
    parser, _ = _make_parser()
    assert paste_guard._install_feed_timestamp(parser) is True
    assert getattr(parser, paste_guard._WRAPPED_ATTR) is True
    before = getattr(parser, paste_guard._LAST_ATTR)
    parser.feed("a")
    after = getattr(parser, paste_guard._LAST_ATTR)
    assert after >= before
    # Idempotent: a second install must not double-wrap.
    assert paste_guard._install_feed_timestamp(parser) is True


def test_watchdog_recovers_within_a_turn() -> None:
    parser, collector = _make_parser()
    app = _FakeApp(parser)
    session = _FakeSession(app)
    assert arm_paste_watchdog(session, idle_timeout=0.05, poll=0.02) is True
    assert len(app.pre_run_callables) == 1

    # Enter the wedged state via the (timestamp-wrapped) feed.
    parser.feed("\x1b[200~")
    parser.feed("abc")
    assert parser._in_bracketed_paste is True

    # Running the pre_run callback spawns the watchdog coroutine.
    app.pre_run_callables[0]()
    assert len(app.spawned) == 1
    coro = app.spawned[0]

    async def driver() -> None:
        task = asyncio.ensure_future(coro)
        await asyncio.sleep(0.15)  # exceeds idle_timeout -> watchdog resets
        assert parser._in_bracketed_paste is False
        app.is_done = True
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(driver())

    # After recovery, normal typing flows again.
    parser.feed("q")
    assert [kp.data for kp in collector.keys] == ["q"]
