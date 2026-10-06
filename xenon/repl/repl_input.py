"""Terminal input handling for the REPL — extracted from repl.py."""

from __future__ import annotations

import sys

from xenon.repl.input_buffer import PastedTextStore, _ShiftTabSignal


def _read_input_windows(self) -> str:
    import ctypes
    import msvcrt
    import time
    import unicodedata

    VK_SHIFT = 0x10
    ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    STD_INPUT_HANDLE = -10
    STD_OUTPUT_HANDLE = -11

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    GetAsyncKeyState = user32.GetAsyncKeyState
    GetAsyncKeyState.argtypes = [ctypes.c_int]
    GetAsyncKeyState.restype = ctypes.c_short

    # 64 位句柄必须用 c_void_p，否则 GetStdHandle 的返回值会被截断成 32 位。
    kernel32.GetStdHandle.argtypes = [ctypes.c_int]
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetConsoleMode.restype = ctypes.c_bool
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.SetConsoleMode.restype = ctypes.c_bool

    kbhit = getattr(msvcrt, "kbhit", lambda: False)

    # ── 控制台模式：开启 VT 输入/输出，关闭快速编辑与鼠标输入 ──
    # 关键：ENABLE_VIRTUAL_TERMINAL_INPUT 与 ENABLE_LINE_INPUT / ENABLE_ECHO_INPUT
    # 互斥。默认 conhost 下行输入+回显都开着，直接 OR 进 VT_INPUT 会让
    # SetConsoleMode 失败——VT 输入、快速编辑关闭、鼠标输入关闭全部静默失效，
    # 这正是此前反复修不好的根因。这里显式设置一个最小化原始输入模式：
    #   - 保留 PROCESSED_INPUT（Ctrl+C 仍以 \x03 送达）；
    #   - 开启 VT_INPUT（括号粘贴/方向键以 \x1b[ 序列到达）；
    #   - EXTENDED_FLAGS 置位以控制快速编辑，并关闭 QUICK_EDIT（鼠标点选冻结
    #     控制台）与 MOUSE_INPUT（鼠标事件混进输入队列，导致 kbhit 误判、getwch 阻塞）。
    ENABLE_PROCESSED_INPUT = 0x0001
    ENABLE_QUICK_EDIT_MODE = 0x0040
    ENABLE_MOUSE_INPUT = 0x0010
    ENABLE_EXTENDED_FLAGS = 0x0080
    hin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    in_mode = ctypes.c_ulong()
    orig_in_mode = None
    if kernel32.GetConsoleMode(hin, ctypes.byref(in_mode)):
        orig_in_mode = in_mode.value
        # 只保留这三个标志；其余（LINE_INPUT 0x02 / ECHO_INPUT 0x04 /
        # MOUSE_INPUT 0x10 / QUICK_EDIT 0x40 / INSERT 0x20 / AUTO_POSITION 0x100）
        # 都被清零——它们要么与 VT 输入互斥，要么会把鼠标事件混进输入队列。
        desired = (
            ENABLE_PROCESSED_INPUT
            | ENABLE_EXTENDED_FLAGS
            | ENABLE_VIRTUAL_TERMINAL_INPUT
        )
        if in_mode.value != desired:
            kernel32.SetConsoleMode(hin, desired)
    hout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
    out_mode = ctypes.c_ulong()
    if kernel32.GetConsoleMode(hout, ctypes.byref(out_mode)):
        if not (out_mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING):
            kernel32.SetConsoleMode(
                hout, out_mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )

    def shift_held() -> bool:
        return bool(GetAsyncKeyState(VK_SHIFT) & 0x8000)

    # ── 显示宽度（CJK 字符占 2 列）────────────────────────
    def _char_width(ch: str) -> int:
        ea = unicodedata.east_asian_width(ch)
        return 2 if ea in ("W", "F") else 1

    def _display_width(s: str) -> int:
        return sum(_char_width(c) for c in s)

    PROMPT = "\033[1;36mYou\033[0m: "
    CONT = "\033[90m...\033[0m "

    # 开启括号粘贴模式：终端用 \x1b[200~ … \x1b[201~ 包裹粘贴内容。
    sys.stdout.write("\033[?2004h")
    sys.stdout.write("\n" + PROMPT)
    sys.stdout.flush()

    lines: list[str] = []
    current_line: list[str] = []
    cursor_pos: int = 0

    paste_mode = False
    paste_buffer: list[str] = []

    def _redraw_from_cursor() -> None:
        """从光标处重绘到行尾，并用 ANSI 清行清除残留的宽字符。"""
        tail = "".join(current_line[cursor_pos:])
        if tail:
            sys.stdout.write(tail)
        sys.stdout.write("\033[K")
        back = _display_width(tail)
        if back:
            sys.stdout.write(f"\033[{back}D")
        sys.stdout.flush()

    def _insert_text(text: str) -> None:
        """把一段文本（通常是粘贴内容）插入当前行，正确处理换行。"""
        nonlocal current_line, cursor_pos
        parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        before = current_line[:cursor_pos]
        after = current_line[cursor_pos:]
        if len(parts) == 1:
            inserted = list(parts[0])
            current_line = before + inserted + after
            cursor_pos += len(inserted)
            return
        lines.append("".join(before) + parts[0])
        lines.extend(parts[1:-1])
        current_line = list(parts[-1]) + after
        cursor_pos = len(parts[-1])

    def _finish_paste() -> None:
        nonlocal paste_mode, paste_buffer
        _insert_text("".join(paste_buffer))
        paste_buffer = []
        paste_mode = False
        _redraw_from_cursor()

    def _read_escape() -> str:
        """读完整的一段 ESC 序列（短轮询，避免与后续字节竞争）。

        CSI 结构为 ``\\x1b[`` + 参数字节 + 最终字节（0x40..0x7E）。不能把
        引入字节 ``[``（0x5B）当成最终字节，否则括号粘贴标记 ``\\x1b[200~``
        会被截成 ``\\x1b[``，``200~`` 泄漏进正文。
        """
        deadline = time.monotonic() + 0.05

        def _poll_next() -> str | None:
            while time.monotonic() < deadline:
                if kbhit():
                    return msvcrt.getwch()
                time.sleep(0.001)
            return None

        seq = "\x1b"
        second = _poll_next()
        if second is None:
            return seq  # 孤立 ESC
        seq += second
        if second == "[":  # CSI：参数/中间字节之后才是最终字节
            while True:
                c = _poll_next()
                if c is None:
                    break
                seq += c
                if 0x40 <= ord(c) <= 0x7E or len(seq) >= 16:
                    break
        elif second == "O":  # SS3：还有一个字节
            c = _poll_next()
            if c is not None:
                seq += c
        # 其余情况（ESC + 单字母）已完整
        return seq

    def _move_left() -> None:
        nonlocal cursor_pos
        if cursor_pos > 0:
            cursor_pos -= 1
            sys.stdout.write(f"\033[{_char_width(current_line[cursor_pos])}D")
            sys.stdout.flush()

    def _move_right() -> None:
        nonlocal cursor_pos
        if cursor_pos < len(current_line):
            w = _char_width(current_line[cursor_pos])
            cursor_pos += 1
            sys.stdout.write(f"\033[{w}C")
            sys.stdout.flush()

    def _move_home() -> None:
        nonlocal cursor_pos
        if cursor_pos > 0:
            prefix = _display_width("".join(current_line[:cursor_pos]))
            sys.stdout.write(f"\033[{prefix}D")
            cursor_pos = 0
            sys.stdout.flush()

    def _move_end() -> None:
        nonlocal cursor_pos
        if cursor_pos < len(current_line):
            suffix = _display_width("".join(current_line[cursor_pos:]))
            sys.stdout.write(f"\033[{suffix}C")
            cursor_pos = len(current_line)
            sys.stdout.flush()

    try:
        while True:
            ch = msvcrt.getwch()

            # ── 括号粘贴：缓冲内容，遇结束标记一次性插入 ──
            if paste_mode:
                if ch == "\x1b":
                    seq = _read_escape()
                    if seq == "\x1b[201~":
                        _finish_paste()
                    else:
                        paste_buffer.append(seq)  # 粘贴内容里的字面 ESC
                elif ch == "\x03":  # 粘贴期间 Ctrl+C
                    paste_mode = False
                    paste_buffer = []
                    sys.stdout.write("\n")
                    raise KeyboardInterrupt
                else:
                    paste_buffer.append(ch)
                continue

            if ch in ("\r", "\n"):
                if ch == "\n" and not current_line and not lines:
                    # 泄漏的 LF（CRLF 粘贴的后半）或空行回车：静默忽略。
                    # 不能用 kbhit()+getwch() 提前消费——kbhit() 对鼠标/窗口事件
                    # 也为真，而 getwch() 只读按键事件，会在鼠标事件上永久阻塞。
                    continue
                if shift_held():
                    if cursor_pos < len(current_line):
                        sys.stdout.write(
                            f"\033[{_display_width(''.join(current_line[cursor_pos:]))}C"
                        )
                        cursor_pos = len(current_line)
                    lines.append("".join(current_line))
                    current_line = []
                    cursor_pos = 0
                    sys.stdout.write("\n" + CONT)
                    sys.stdout.flush()
                else:
                    if cursor_pos < len(current_line):
                        sys.stdout.write(
                            f"\033[{_display_width(''.join(current_line[cursor_pos:]))}C"
                        )
                    break

            elif ch == "\x03":
                raise KeyboardInterrupt

            elif ch == "\x0f":  # Ctrl+O：展开/折叠最近一次执行详情
                self._toggle_thinking_details()
                _redraw_from_cursor()

            elif ch in ("\x08", "\x7f"):
                # Backspace：删除光标左侧字符，按字符宽度回退光标
                if cursor_pos > 0:
                    deleted = current_line.pop(cursor_pos - 1)
                    cursor_pos -= 1
                    sys.stdout.write(f"\033[{_char_width(deleted)}D")
                    _redraw_from_cursor()

            elif ch == "\x1b":
                seq = _read_escape()
                if seq == "\x1b[200~":
                    paste_mode = True
                    paste_buffer = []
                elif seq in ("\x1b[A", "\x1b[B"):  # 上/下：忽略
                    pass
                elif seq == "\x1b[C":
                    _move_right()
                elif seq == "\x1b[D":
                    _move_left()
                elif seq in ("\x1b[H", "\x1b[1~", "\x1bOH"):
                    _move_home()
                elif seq in ("\x1b[F", "\x1b[4~", "\x1bOF"):
                    _move_end()
                elif seq == "\x1b[3~":  # Delete
                    if cursor_pos < len(current_line):
                        current_line.pop(cursor_pos)
                        _redraw_from_cursor()
                elif seq == "\x1b[Z":  # Shift+Tab
                    self._handle_shift_tab()
                # 其他未知 ESC 序列静默丢弃

            elif ch in ("\x00", "\xe0"):
                # 扩展键（VT 输入未生效时的兜底）：前缀 + 扫描码。
                # kbhit 守卫：孤立的 0x00/0xe0（如粘贴内容里的 U+00E0）不阻塞。
                if not kbhit():
                    continue
                second = msvcrt.getwch()
                if second == "K":
                    _move_left()
                elif second == "M":
                    _move_right()
                elif second == "G":
                    _move_home()
                elif second == "O":
                    _move_end()
                elif second == "S":  # Delete
                    if cursor_pos < len(current_line):
                        current_line.pop(cursor_pos)
                        _redraw_from_cursor()
                elif second == "\x0f":  # Shift+Tab
                    self._handle_shift_tab()

            elif ch and ord(ch) >= 0x20:
                # 可见字符：在光标位置插入
                if cursor_pos >= len(current_line):
                    current_line.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
                else:
                    current_line.insert(cursor_pos, ch)
                    _redraw_from_cursor()
                    # 重绘后光标回到插入点，前移一位越过刚插入的字符。
                    sys.stdout.write(f"\033[{_char_width(ch)}C")
                    sys.stdout.flush()
                cursor_pos += 1

    finally:
        # 关闭括号粘贴模式。
        sys.stdout.write("\033[?2004l")
        sys.stdout.flush()
        # 恢复行输入 + 回显（供 Python ``input()`` 和 rich ``Prompt.ask`` 使用——
        # 它们依赖 ENABLE_LINE_INPUT/ECHO_INPUT，若一直留在原始模式，/set_model
        # 等交互命令会读不到输入），但保持快速编辑与鼠标输入关闭，避免点选冻结
        # 与鼠标事件污染输入队列。VT_INPUT 也一并清掉，交还给行输入路径。
        if orig_in_mode is not None:
            restore = orig_in_mode & ~(
                ENABLE_QUICK_EDIT_MODE | ENABLE_MOUSE_INPUT | ENABLE_VIRTUAL_TERMINAL_INPUT
            )
            kernel32.SetConsoleMode(hin, restore)

    if current_line:
        lines.append("".join(current_line))

    result = "\n".join(lines)
    sys.stdout.write("\n")
    return result.rstrip("\r\n")


def _read_input_unix(self) -> str:
    """Linux/macOS 原始终端输入：支持 Alt+Enter 换行，方向键编辑。

    使用时将终端设为原始模式，逐字节读取并解析 ANSI 转义序列。
    粘贴多行文本会被自动检测并正确处理。
    """
    import sys
    import codecs
    import os
    import termios
    import tty
    import unicodedata
    from select import select

    PROMPT = "\033[1;36mYou\033[0m: "
    CONTINUATION = "\033[90m...\033[0m "

    # ── 显示宽度计算（CJK 字符占 2 列）────────────────
    def _char_width(ch: str) -> int:
        """返回单个字符的终端显示宽度。"""
        ea = unicodedata.east_asian_width(ch)
        if ea in ("W", "F"):
            return 2
        return 1

    def _display_width(s: str) -> int:
        """计算字符串的终端显示宽度。"""
        return sum(_char_width(ch) for ch in s)

    def _prompt_printable(prompt_str: str) -> str:
        """剥离 ANSI 转义序列，得到 prompt 的可打印文本。"""
        import re

        return re.sub(r"\033\[[0-9;]*[a-zA-Z]", "", prompt_str)

    def _line_width_upto(chars: list[str], upto: int) -> int:
        """计算 current_line 中前 upto 个字符的终端显示宽度。"""
        return _display_width("".join(chars[:upto]))

    fd = sys.stdin.fileno()
    decoder = codecs.getincrementaldecoder(sys.stdin.encoding or "utf-8")(
        errors="replace"
    )
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        # ── 启用终端粘贴括号模式 ────────────────────
        # 粘贴时终端发送 \x1b[200~ 开始 / \x1b[201~ 结束，
        # 从而在粘贴期间批量处理字符，避免每字符一次重绘。
        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()

        lines: list[str] = []
        current_line: list[str] = []
        cursor_pos: int = 0
        prompt_active = True
        paste_store = PastedTextStore()

        # ── 粘贴模式状态 ─────────────────────────────
        paste_mode = False
        paste_buffer: list[str] = []
        # v0.3.0 修复（Bug：粘贴结束信号丢失时 paste_mode 死锁）：
        # 某些终端/网络/SSH 会把 \x1b[201~ 结束信号切碎或丢失，导致 paste_mode 永远 True，
        # 后续用户按键（空格/字母）进入 paste_mode 分支被插入 current_line 但不重绘，
        # 表现为"按空格不显示 + 字符累积成重复粘贴"。超时退出机制：paste_mode 期间
        # select 0.3s 无新字节 → 自动退出 paste_mode + 强制 _redraw_line()。
        # 通用机制改进，不针对特定任务/终端加白名单。
        import time as _time

        paste_last_byte_at: float | None = None
        PASTE_TIMEOUT_S = 0.3

        def _insert_text(text: str) -> None:
            """Insert text at the cursor without turning lines into turns."""
            nonlocal current_line, cursor_pos
            parts = text.split("\n")
            before = current_line[:cursor_pos]
            after = current_line[cursor_pos:]
            if len(parts) == 1:
                inserted = list(parts[0])
                current_line = before + inserted + after
                cursor_pos += len(inserted)
                return

            lines.append("".join(before) + parts[0])
            lines.extend(parts[1:-1])
            current_line = list(parts[-1]) + after
            cursor_pos = len(parts[-1])

        def _finish_paste() -> None:
            """Commit a paste to the editor as full text or one UI token."""
            nonlocal paste_mode, paste_buffer, paste_last_byte_at
            pasted = "".join(paste_buffer)
            occupied = "\n".join([*lines, "".join(current_line)])
            _insert_text(paste_store.compact(pasted, occupied_text=occupied))
            paste_buffer = []
            paste_mode = False
            paste_last_byte_at = None
            _redraw_line()

        def _redraw_line() -> None:
            """清除当前行并重绘（正确处理 CJK 宽字符）。"""
            nonlocal prompt_active
            prompt_str = PROMPT if (prompt_active and not lines) else CONTINUATION
            # 光标移到行首并清除到行尾
            sys.stdout.write("\r\033[K")
            # 打印提示符和当前行内容
            sys.stdout.write(prompt_str)
            sys.stdout.write("".join(current_line))
            # 光标定位：回到行首 + 提示符宽度 + 光标前内容的显示宽度
            pw = _display_width(_prompt_printable(prompt_str))
            prefix_w = _display_width("".join(current_line[:cursor_pos]))
            sys.stdout.write(f"\r\033[{pw + prefix_w}C")
            sys.stdout.flush()

        def _prompt_width() -> int:
            """当前提示符的可打印宽度。"""
            prompt_str = PROMPT if (prompt_active and not lines) else CONTINUATION
            return _display_width(_prompt_printable(prompt_str))

        def _move_cursor_to(target: int) -> None:
            """移动光标到目标字符位置（正确处理 CJK 宽字符列偏移）。"""
            nonlocal cursor_pos
            cursor_pos = max(0, min(target, len(current_line)))
            pw = _prompt_width()
            prefix_w = _display_width("".join(current_line[:cursor_pos]))
            sys.stdout.write(f"\r\033[{pw + prefix_w}C")
            sys.stdout.flush()

        # 显示初始提示符
        sys.stdout.write(PROMPT)
        sys.stdout.flush()

        # 缓冲区，用于累积多字节序列
        seq_buffer = ""

        while True:
            # 用 select 检查是否有输入（超时处理粘贴检测 + paste_mode 超时退出）
            if select([sys.stdin], [], [], 0.01)[0]:
                # Do not combine select(fd) with TextIOWrapper.read(1): the
                # wrapper may prefetch the remaining bytes, leaving them in
                # Python's private buffer while select waits forever on an
                # already-empty fd.  Read the fd itself and decode Unicode
                # incrementally so batched paste/key sequences cannot hang.
                raw = os.read(fd, 1)
                if not raw:
                    raise KeyboardInterrupt
                ch = decoder.decode(raw)
                if not ch:
                    continue
            else:
                # v0.3.0 修复：paste_mode 期间 select 0.3s 无新字节 → 自动退出
                # 解决"结束信号 \x1b[201~ 丢失导致 paste_mode 死锁"问题。
                if (
                    paste_mode
                    and paste_last_byte_at is not None
                    and _time.monotonic() - paste_last_byte_at > PASTE_TIMEOUT_S
                ):
                    _finish_paste()
                continue

            # 处理转义序列
            # v0.3.0+ 修复（C-1）：转义序列累积器**总是**累积。
            # 但有双守卫保证 paste_mode 状态机不死锁：
            #   ① paste end \x1b[201~ **总是**优先识别并关闭 paste_mode
            #      （否则粘贴内容里的 ESC 字节会让累积器错位、最终丢失
            #      paste end → paste_mode 永远 True → REPL 挂死）
            #   ② paste_mode 期间累积到 8 字节**子串搜索** paste end：
            #      - 含 paste end → 前部分追加 buffer + 关闭 paste_mode
            #      - 不含 → 整批追加 buffer（保留用户主动复制的 ESC 字节）
            if seq_buffer or ch == "\x1b":
                seq_buffer += ch
                # 守卫 ①：paste end 总是截留（精确 6 字符匹配）
                if seq_buffer == "\x1b[201~":
                    seq_buffer = ""
                    _finish_paste()
                    continue
                if paste_mode:
                    # 守卫 ②：累积 8 字节时子串搜索 paste end
                    if "\x1b[201~" in seq_buffer:
                        idx = seq_buffer.index("\x1b[201~")
                        paste_buffer.extend(seq_buffer[:idx])
                        seq_buffer = ""
                        _finish_paste()
                        continue
                    if len(seq_buffer) >= 8:
                        paste_buffer.extend(seq_buffer)
                        seq_buffer = ""
                        paste_last_byte_at = _time.monotonic()
                    continue
                if len(seq_buffer) == 1 and ch == "\x1b":
                    continue  # 等待更多字节

                # ── 粘贴括号模式 ────────────────────
                if seq_buffer == "\x1b[200~":
                    # 开始粘贴 — 暂停逐字符重绘
                    paste_mode = True
                    paste_buffer = []
                    paste_last_byte_at = _time.monotonic()
                    seq_buffer = ""
                    continue
                if seq_buffer == "\x1b[201~":
                    # 粘贴结束 — 一次性重绘
                    seq_buffer = ""
                    _finish_paste()
                    continue

                # 尝试匹配已知序列
                # Alt+Enter: \x1b\r
                if seq_buffer == "\x1b\r":
                    # 插入换行
                    lines.append("".join(current_line))
                    current_line = []
                    cursor_pos = 0
                    sys.stdout.write("\r\n")
                    sys.stdout.write(CONTINUATION)
                    sys.stdout.flush()
                    seq_buffer = ""
                    continue

                # Shift+Enter（kitty 键盘协议）: \x1b[13;2u
                if seq_buffer == "\x1b[13;2u":
                    lines.append("".join(current_line))
                    current_line = []
                    cursor_pos = 0
                    sys.stdout.write("\r\n")
                    sys.stdout.write(CONTINUATION)
                    sys.stdout.flush()
                    seq_buffer = ""
                    continue

                # Shift+Enter（xterm modifyOtherKeys）: \x1b[27;2;13~
                if seq_buffer == "\x1b[27;2;13~":
                    lines.append("".join(current_line))
                    current_line = []
                    cursor_pos = 0
                    sys.stdout.write("\r\n")
                    sys.stdout.write(CONTINUATION)
                    sys.stdout.flush()
                    seq_buffer = ""
                    continue
                if "\x1b[27;2;13~".startswith(seq_buffer):
                    continue

                # 方向键: \x1b[A (上), \x1b[B (下), \x1b[C (右), \x1b[D (左)
                if seq_buffer == "\x1b[A":  # Up — 忽略
                    seq_buffer = ""
                    continue
                if seq_buffer == "\x1b[B":  # Down — 忽略
                    seq_buffer = ""
                    continue
                if seq_buffer == "\x1b[C":  # Right
                    if cursor_pos < len(current_line):
                        cursor_pos += 1
                        _move_cursor_to(cursor_pos)
                    seq_buffer = ""
                    continue
                if seq_buffer == "\x1b[D":  # Left
                    if cursor_pos > 0:
                        cursor_pos -= 1
                        _move_cursor_to(cursor_pos)
                    seq_buffer = ""
                    continue

                # Home: \x1b[H 或 \x1b[1~
                if seq_buffer in ("\x1b[H", "\x1b[1~", "\x1bOH"):
                    _move_cursor_to(0)
                    seq_buffer = ""
                    continue

                # End: \x1b[F 或 \x1b[4~ 或 \x1bOF
                if seq_buffer in ("\x1b[F", "\x1b[4~", "\x1bOF"):
                    _move_cursor_to(len(current_line))
                    seq_buffer = ""
                    continue

                # Delete: \x1b[3~
                if seq_buffer == "\x1b[3~":
                    if cursor_pos < len(current_line):
                        current_line.pop(cursor_pos)
                        _redraw_line()
                    seq_buffer = ""
                    continue

                # Shift+Tab: \x1b[Z → 切换思考范式
                if seq_buffer == "\x1b[Z":
                    seq_buffer = ""
                    raise _ShiftTabSignal()

                # 未知转义序列 — 静默丢弃或超时后当作普通字符
                # 如果序列长度 >= 8 或超时，丢弃
                if len(seq_buffer) >= 8:
                    seq_buffer = ""
                    continue
                # 否则继续累积
                continue

            # ── 粘贴模式：缓冲修改，不重绘 ──
            if paste_mode:
                if ch in ("\r", "\n"):
                    paste_buffer.append(ch)
                elif ch == "\x03":  # Ctrl+C during paste
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise KeyboardInterrupt
                elif ch in ("\x7f", "\x08"):  # Backspace
                    if paste_buffer:
                        paste_buffer.pop()
                elif ch == "\x1b":
                    # v0.3.0+ 修复（C-1 配套）：粘贴期间遇到 ESC 字节
                    # 不再走转义序列累积器（已在上方 if 屏蔽），改当普通
                    # 字符插入 buffer——用户主动复制粘贴含 ANSI 转义序列
                    # 的代码（如 `echo -e "\033[31m红色\033[0m"`）应保留 ESC
                    paste_buffer.append(ch)
                elif ord(ch) >= 0x20:
                    paste_buffer.append(ch)
                # v0.3.0 修复：每次粘贴期间字节都要刷新 last_byte_at，
                # 否则 select 0.3s 超时检查会误判 paste_mode 空闲
                paste_last_byte_at = _time.monotonic()
                continue

            # ── 普通字符处理 ──

            if ch in ("\r", "\n"):
                # Enter → 提交
                # 将光标移到行尾
                _move_cursor_to(len(current_line))
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                break

            elif ch == "\x03":  # Ctrl+C
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                raise KeyboardInterrupt

            elif ch == "\x04":  # Ctrl+D
                if not current_line and not lines:
                    # 空行 Ctrl+D → EOF
                    sys.stdout.write("\r\n")
                    sys.stdout.flush()
                    raise KeyboardInterrupt
                # 否则当 Delete 处理
                if cursor_pos < len(current_line):
                    current_line.pop(cursor_pos)
                    _redraw_line()

            elif ch == "\x0f":  # Ctrl+O：展开/折叠最近一次执行详情
                # This path is used when prompt_toolkit is unavailable or
                # disabled.  Previously Ctrl+O was only registered in the
                # prompt_toolkit key map, so the fallback editor silently
                # ignored it.  Render above the raw editor and redraw the
                # current prompt so input is not lost.
                self._toggle_thinking_details()
                _redraw_line()

            elif ch in ("\x7f", "\x08"):  # Backspace
                if cursor_pos > 0:
                    current_line.pop(cursor_pos - 1)
                    _move_cursor_to(cursor_pos - 1)
                    _redraw_line()

            elif ch == "\t":  # Tab → 4 空格
                for _ in range(4):
                    current_line.insert(cursor_pos, " ")
                cursor_pos += 4
                _move_cursor_to(cursor_pos)
                _redraw_line()

            elif ord(ch) >= 0x20:
                # 可见字符
                current_line.insert(cursor_pos, ch)
                cursor_pos += 1
                _redraw_line()

        if current_line:
            lines.append("".join(current_line))

        return paste_store.expand("\n".join(lines))

    finally:
        # 禁用粘贴括号模式，恢复终端设置
        sys.stdout.write("\x1b[?2004l")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
