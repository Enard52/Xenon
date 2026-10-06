"""Correctness coverage for multiline and compact pasted input."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.keys import Keys

from xenon.repl.context_manager import ContextManager
from xenon.repl.input_buffer import PastedTextStore, normalize_input_newlines
from xenon.repl.repl import REPL


def _binding(repl: REPL, keys: tuple[Keys, ...]):
    return next(
        binding
        for binding in repl._pt_session.key_bindings.bindings
        if binding.keys == keys
    )


def test_normalize_input_newlines_changes_only_line_endings():
    assert normalize_input_newlines(" a\r\nb\rc\n ") == " a\nb\nc\n "


def test_long_paste_compacts_and_expands_losslessly():
    store = PastedTextStore(threshold=10)
    original = "  第一行\r\nsecond\r  "

    visible = store.compact(original)

    assert visible == "[Pasted #1 +15 chars]"
    assert original not in visible
    assert store.expand(visible) == "  第一行\nsecond\n  "


def test_short_and_multiple_pastes_preserve_order():
    store = PastedTextStore(threshold=5)
    assert store.compact("tiny") == "tiny"
    first = store.compact("abcdef")
    second = store.compact("uvwxyz")

    assert store.expand(f"before {first} middle {second} after") == (
        "before abcdef middle uvwxyz after"
    )


def test_paste_token_avoids_existing_visible_text_and_is_atomic():
    store = PastedTextStore(threshold=1)
    occupied = "already [Pasted #1 +3 chars]"
    token = store.compact("abc", occupied_text=occupied)

    assert token == "[Pasted #2 +3 chars]"
    combined = f"x{token}y"
    end = 1 + len(token)
    assert store.token_after_cursor(combined, 1) == token
    assert store.token_before_cursor(combined, end) == token


def test_prompt_toolkit_paste_binding_folds_only_visible_buffer():
    repl = REPL()
    repl._paste_store.reset()
    buffer = Buffer()
    payload = "开头\r\n" + "x" * 1200 + "\r结尾"
    event = SimpleNamespace(current_buffer=buffer, data=payload)

    _binding(repl, (Keys.BracketedPaste,)).handler(event)

    assert buffer.text == "[Pasted #1 +1,206 chars]"
    assert repl._paste_store.expand(buffer.text) == normalize_input_newlines(payload)


def test_prompt_toolkit_folded_paste_backspace_deletes_whole_block():
    repl = REPL()
    repl._paste_store.reset()
    buffer = Buffer()
    token = repl._paste_store.compact("x" * 1200)
    buffer.text = f"prefix{token}"
    buffer.cursor_position = len(buffer.text)

    event = SimpleNamespace(current_buffer=buffer)
    _binding(repl, (Keys.Backspace,)).handler(event)

    assert buffer.text == "prefix"


def test_shift_enter_encodings_remain_distinct_from_plain_enter():
    repl = REPL()

    expected = (Keys.Escape, Keys.ControlM)
    assert ANSI_SEQUENCES["\x1b[13;2u"] == expected
    assert ANSI_SEQUENCES["\x1b[27;2;13~"] == expected
    assert ANSI_SEQUENCES["\r"] == Keys.ControlM

    buffer = Buffer()
    event = SimpleNamespace(current_buffer=buffer)
    _binding(repl, expected).handler(event)
    assert buffer.text == "\n"


def test_read_input_restores_paste_before_returning_to_repl(monkeypatch):
    repl = REPL()
    payload = "  def f():\r\n    return 1\r\n"
    payload += "#" * 1200

    def fake_prompt(_message):
        return repl._paste_store.compact(payload)

    monkeypatch.setattr(repl._pt_session, "prompt", fake_prompt)

    assert repl._read_input_pt() == normalize_input_newlines(payload)


def test_read_input_preserves_editor_spaces(monkeypatch):
    repl = REPL()

    monkeypatch.setattr(repl._pt_session, "prompt", lambda _message: "  keep me  ")

    assert repl._read_input_pt() == "  keep me  "


def test_multiline_request_is_one_cache_friendly_user_turn():
    manager = ContextManager()
    multiline = "请修改：\n```python\nprint('ok')\n```"

    manager.add_request_message(multiline)

    assert len(manager.history) == 1
    assert manager.history[0].role == "user"
    assert manager.history[0].content == multiline
    assert manager.get_messages() == [{"role": "user", "content": multiline}]


# ── 原始 Windows 输入路径（msvcrt）的行为回归 ────────────────────────────
# 该路径此前无任何单测覆盖；这里通过 mock msvcrt / ctypes.windll 验证：
# 粘贴（含括号粘贴标记与 CRLF）整体插入、CJK 退格不残留空格。


def _run_windows_input(chars: list[str]) -> str:
    """用脚本化字符序列驱动 _read_input_windows，返回提交的文本。"""
    import ctypes
    import msvcrt

    from xenon.repl import repl_input

    chunks = list(chars)

    def fake_getwch():
        return chunks.pop(0) if chunks else "\x03"

    def fake_kbhit():
        return len(chunks) > 0

    class _Self:
        def _handle_shift_tab(self):
            pass

    import sys

    # 手动打补丁并还原（避免依赖 pytest monkeypatch 处理模块级导入）
    orig_getwch, orig_kbhit = msvcrt.getwch, msvcrt.kbhit
    orig_gstd, orig_gcm, orig_scm = (
        ctypes.windll.kernel32.GetStdHandle,
        ctypes.windll.kernel32.GetConsoleMode,
        ctypes.windll.kernel32.SetConsoleMode,
    )
    orig_gaks = ctypes.windll.user32.GetAsyncKeyState

    msvcrt.getwch = fake_getwch
    msvcrt.kbhit = fake_kbhit
    ctypes.windll.kernel32.GetStdHandle = lambda n: 100
    ctypes.windll.kernel32.GetConsoleMode = lambda h, p: True
    ctypes.windll.kernel32.SetConsoleMode = lambda h, m: True
    ctypes.windll.user32.GetAsyncKeyState = lambda k: 0

    real_write = sys.stdout.write
    sys.stdout.write = lambda s: None
    try:
        return repl_input._read_input_windows(_Self())
    finally:
        sys.stdout.write = real_write
        msvcrt.getwch, msvcrt.kbhit = orig_getwch, orig_kbhit
        ctypes.windll.kernel32.GetStdHandle = orig_gstd
        ctypes.windll.kernel32.GetConsoleMode = orig_gcm
        ctypes.windll.kernel32.SetConsoleMode = orig_scm
        ctypes.windll.user32.GetAsyncKeyState = orig_gaks


try:
    import msvcrt  # noqa: F401

    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False


@pytest.mark.skipif(not _HAS_MSVCRT, reason="Windows-only (msvcrt)")
def test_windows_raw_bracketed_paste_inserts_content():
    chars = list("\x1b[200~你好\r\n第二行\x1b[201~") + ["\r"]
    assert _run_windows_input(chars) == "你好\n第二行"


@pytest.mark.skipif(not _HAS_MSVCRT, reason="Windows-only (msvcrt)")
def test_windows_raw_cjk_backspace_leaves_no_stray_space():
    # 输入 "你好a"，左移一格，退格删除 "好"，提交应为 "你a"
    chars = list("你好a") + ["\x1b", "[", "D"] + ["\x7f"] + ["\r"]
    assert _run_windows_input(chars) == "你a"


@pytest.mark.skipif(not _HAS_MSVCRT, reason="Windows-only (msvcrt)")
def test_windows_raw_crlf_paste_is_not_ghost_enter():
    # conhost 粘贴不带括号标记，直接按 \r\n 到达：提交 "abc"，\n 不泄漏成幽灵回车。
    chars = list("abc\r\n") + ["\r"]
    assert _run_windows_input(chars) == "abc"


@pytest.mark.skipif(not _HAS_MSVCRT, reason="Windows-only (msvcrt)")
def test_windows_console_mode_raw_vt_then_restored_line_mode():
    """控制台模式：读取期设为最小原始模式，读完恢复行输入+回显。

    之前反复修不好的根因：ENABLE_VIRTUAL_TERMINAL_INPUT 与 LINE_INPUT/ECHO_INPUT
    互斥，默认 conhost 模式带 LINE+ECHO，直接 OR 进 VT_INPUT 会让 SetConsoleMode
    失败，导致快速编辑/鼠标输入关不掉。同时，若读完不恢复行输入/回显，input()
    与 rich Prompt.ask（/set_model 用）会读不到输入。这里断言两次 SetConsoleMode：
    读取期 = PROCESSED|EXTENDED_FLAGS|VT_INPUT；恢复期 = 原模式去掉 QUICK_EDIT/
    MOUSE/VT，保留 LINE_INPUT/ECHO_INPUT。
    """
    import ctypes
    import msvcrt

    from xenon.repl import repl_input

    captured: list[int] = []
    # 默认 conhost 模式：LINE_INPUT + ECHO_INPUT + MOUSE_INPUT + QUICK_EDIT 全开。
    initial = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0040 | 0x0080

    def fake_gcm(h, p):
        # p 是 byref(in_mode) 的轻量指针，._obj 即 in_mode 本身
        p._obj.value = initial
        return True

    msvcrt.getwch = lambda: "\r"
    msvcrt.kbhit = lambda: False
    ctypes.windll.kernel32.GetStdHandle = lambda n: 100
    ctypes.windll.kernel32.GetConsoleMode = fake_gcm
    ctypes.windll.kernel32.SetConsoleMode = lambda h, m: (captured.append(m), True)[1]
    ctypes.windll.user32.GetAsyncKeyState = lambda k: 0

    class _Self:
        def _handle_shift_tab(self):
            pass

    import sys

    real_write = sys.stdout.write
    sys.stdout.write = lambda s: None
    try:
        repl_input._read_input_windows(_Self())
    finally:
        sys.stdout.write = real_write

    assert len(captured) == 2, f"应调用两次 SetConsoleMode，实际 {captured}"
    # 读取期：最小原始模式
    assert captured[0] == 0x0001 | 0x0080 | 0x0200
    # 恢复期：保留行输入+回显（供 input()/Prompt.ask），关掉快速编辑/鼠标/VT
    restore = captured[1]
    assert restore & 0x0002  # LINE_INPUT
    assert restore & 0x0004  # ECHO_INPUT
    assert not (restore & 0x0040)  # 快速编辑关
    assert not (restore & 0x0010)  # 鼠标输入关
    assert not (restore & 0x0200)  # VT 输入交还
