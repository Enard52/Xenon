"""Windows setup-wizard input regressions.

The real Windows console is not available to the Linux CI worker, so these
tests exercise the ``msvcrt`` byte stream contract with a small deterministic
fake.  They cover the two failure modes users see when pasting a credential:
bracketed-paste markers becoming part of the key and a pasted CRLF answering
the following confirmation prompt automatically.
"""

from __future__ import annotations

import sys

from xenon.repl.setup_wizard import _clean_api_key, _masked_input


class _FakeMsvcrt:
    def __init__(self, text: str) -> None:
        self._chars = list(text)

    def getwch(self) -> str:
        if not self._chars:
            raise AssertionError("fake msvcrt input exhausted")
        return self._chars.pop(0)

    def kbhit(self) -> bool:
        return bool(self._chars)


def _run_windows_input(monkeypatch, text: str) -> tuple[str, _FakeMsvcrt]:
    fake = _FakeMsvcrt(text)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    return _masked_input("请输入"), fake


def test_windows_paste_markers_are_not_saved(monkeypatch):
    value, fake = _run_windows_input(
        monkeypatch,
        "\x1b[200~sk-pasted-key\x1b[201~\r\n",
    )

    assert value == "sk-pasted-key"
    assert fake._chars == []


def test_windows_pasted_crlf_does_not_leak_to_next_prompt(monkeypatch):
    value, fake = _run_windows_input(monkeypatch, "sk-pasted-key\r\n")

    assert value == "sk-pasted-key"
    assert fake._chars == []


def test_clean_api_key_removes_leaked_bracketed_paste_markers():
    assert _clean_api_key("\x1b[200~sk-key\x1b[201~") == "sk-key"
