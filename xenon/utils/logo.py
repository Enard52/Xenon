"""Thin player for the Xenon runner startup identity.

The animation frames are authored in TypeScript (scripts/brand/) and emitted
as xenon/utils/_brand_frames.py; this module only plays them on a TTY and
derives the static plain/colored marks from the final frame.

Storyboard: a line draws across the middle, a pixel runner sprints along it,
dissolves block by block and reassembles into the blocky XENON wordmark; the
surviving right-hand line segment becomes the signature dash.
"""

from __future__ import annotations

import sys
import time
from typing import Final

from xenon.utils._brand_frames import FRAME_HEIGHT, FRAMES

GRAY: Final = "\033[90m"
WHITE: Final = "\033[97m"
BLUE: Final = "\033[94m"
CYAN: Final = "\033[96m"
VIOLET: Final = "\033[95m"
DIM_BLUE: Final = "\033[34m"
RESET: Final = "\033[0m"
BOLD: Final = "\033[1m"

_ANSI: Final = {
    "": "",
    "w": f"{WHITE}{BOLD}",
    "c": CYAN,
    "b": BLUE,
    "v": VIOLET,
    "d": DIM_BLUE,
    "g": GRAY,
}

_FRAME_HEIGHT: Final = FRAME_HEIGHT


def _render_frame(index: int, *, colored: bool) -> list[str]:
    """Render one frame: a tuple of (color, run) rows becomes text rows."""
    rows: list[str] = []
    for row in FRAMES[index]:
        if colored:
            parts: list[str] = []
            for color, run in row:
                parts.append(_ANSI.get(color, "") + run)
            if row and row[-1][0]:
                parts.append(RESET)
            rows.append("".join(parts).rstrip())
        else:
            rows.append("".join(run for _, run in row).rstrip())
    return rows


def _expand(index: int) -> list[list[tuple[str, str]]]:
    """Expand one frame into per-cell (char, color) pairs."""
    return [
        [(ch, color) for color, run in row for ch in run] for row in FRAMES[index]
    ]


def _final_mark_rows(colored: bool = False) -> list[str]:
    """Crop the settled final frame down to the bare mark (word + dash)."""
    cells = _expand(-1)
    lit_rows = [r for r, row in enumerate(cells) if any(ch != " " for ch, _ in row)]
    lit_cols = [c for row in cells for c, (ch, _) in enumerate(row) if ch != " "]
    if not lit_rows or not lit_cols:  # pragma: no cover - frame data is static
        return []
    rows: list[str] = []
    for r in range(min(lit_rows), max(lit_rows) + 1):
        parts: list[str] = []
        used_color = False
        for c in range(min(lit_cols), max(lit_cols) + 1):
            ch, color = cells[r][c]
            if colored and color:
                parts.append(_ANSI.get(color, "") + ch)
                used_color = True
            else:
                parts.append(ch)
        if colored and used_color:
            parts.append(RESET)
        rows.append("".join(parts))
    return rows


_INDENT = " " * 8

LOGO_PLAIN: Final = (
    "\n".join(_INDENT + row.rstrip() for row in _final_mark_rows(colored=False)) + "\n"
)
LOGO_COLORED: Final = (
    "\n".join(_INDENT + row.rstrip() for row in _final_mark_rows(colored=True)) + "\n"
)


def _move_up(lines: int = _FRAME_HEIGHT) -> None:
    sys.stdout.write(f"\033[{lines}A")
    sys.stdout.flush()


def _draw_frame(lines: list[str]) -> None:
    for line in lines:
        sys.stdout.write("\033[2K\r" + line + "\n")
    sys.stdout.flush()


def play_animation(duration: float = 3.0, fps: float = 12.0) -> None:
    """Play the runner animation: line, sprint, dissolve into XENON, dash."""
    frame_interval = 1.0 / max(1.0, fps)
    total_frames = max(1, int(max(0.0, duration) * max(1.0, fps)))
    last = len(FRAMES) - 1

    sys.stdout.write("\n" * _FRAME_HEIGHT)
    _move_up()
    for frame_index in range(total_frames):
        source = round(frame_index * last / max(1, total_frames - 1))
        _draw_frame(_render_frame(source, colored=True))
        _move_up()
        time.sleep(frame_interval)

    _draw_frame(_render_frame(last, colored=True))
    sys.stdout.write("\n")
    sys.stdout.flush()


def print_logo(*, animated: bool = True, duration: float = 3.0) -> None:
    """Print the runner identity, animating only on an interactive TTY."""
    if animated and sys.stdout.isatty():
        play_animation(duration=duration)
        return
    # Pipes, CI logs, and redirected output must not receive ANSI control codes.
    sys.stdout.write(LOGO_PLAIN)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    print_logo(animated=True, duration=3.0)
