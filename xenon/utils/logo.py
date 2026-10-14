"""Thin theme-aware player for the Xenon runner startup identity.

The animation frames are authored in TypeScript (scripts/brand/) and emitted
as xenon/utils/_brand_frames.py with SEMANTIC color keys.  This module
resolves those keys against the REPL theme at playback time ("logo.*" tokens
in xenon/repl/theme.py), so the startup animation follows the active theme —
including any future /theme override — instead of hardcoded colors.

Storyboard: a line draws across the middle, a pixel runner sprints along it
and, without stopping, sheds particles that assemble the blocky XENON
wordmark behind him; the line is absorbed under the letters, leaving
symmetric side lines (────── XENON ──────).
"""

from __future__ import annotations

import os
import sys
import time
from typing import Final, Mapping

from xenon.utils._brand_frames import FRAME_HEIGHT, FRAMES

RESET: Final = "\033[0m"

# Semantic color keys used by the generated frame data.
_COLOR_KEYS: Final = (
    "hot",
    "track",
    "runner",
    "letter-a",
    "letter-b",
    "letter-c",
    "dash",
    "spark",
    "ghost",
)

_FRAME_HEIGHT: Final = FRAME_HEIGHT


def _style_to_ansi(style) -> str:
    """Convert a Rich style (or style string) into raw ANSI escape codes."""
    if style is None:
        return ""
    if isinstance(style, str):
        from rich.style import Style

        style = Style.parse(style)
    parts: list[str] = []
    if getattr(style, "dim", False):
        parts.append("\033[2m")
    if getattr(style, "bold", False):
        parts.append("\033[1m")
    color = getattr(style, "color", None)
    if color is not None:
        rgb = color.get_truecolor()
        if rgb:
            parts.append(f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m")
    return "".join(parts)


def resolve_ansi_map(theme=None) -> dict[str, str]:
    """Map semantic frame colors to ANSI codes for the given theme source.

    Accepts anything theme-like: a Rich Theme, a Rich ThemeStack (the live
    console theme), or a plain styles mapping.  Falls back to the default
    token styles for any "logo.*" token the theme does not define, so the
    animation degrades gracefully.
    """
    from xenon.repl.theme import DEFAULT_TOKEN_STYLES

    styles: dict[str, object] = dict(DEFAULT_TOKEN_STYLES)
    if theme is not None:
        getter = getattr(theme, "get", None)
        if callable(getter):
            # Rich ThemeStack exposes .get(token) -> Style | None.
            for key in _COLOR_KEYS:
                style = getter(f"logo.{key}")
                if style is not None:
                    styles[f"logo.{key}"] = style
        else:
            theme_styles = getattr(theme, "styles", None)
            if isinstance(theme_styles, Mapping):
                for name, style in theme_styles.items():
                    if (
                        isinstance(name, str)
                        and name.startswith("logo.")
                        and style is not None
                    ):
                        styles[name] = style
    return {key: _style_to_ansi(styles.get(f"logo.{key}")) for key in _COLOR_KEYS}


def _render_frame(index: int, *, colored: bool, ansi_map: dict[str, str] | None = None) -> list[str]:
    """Render one frame: a tuple of (color, run) rows becomes text rows."""
    rows: list[str] = []
    for row in FRAMES[index]:
        if colored:
            ansi_map = resolve_ansi_map() if ansi_map is None else ansi_map
            parts: list[str] = []
            for color, run in row:
                parts.append(ansi_map.get(color, "") + run)
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


def _final_mark_rows(
    colored: bool = False, ansi_map: dict[str, str] | None = None
) -> list[str]:
    """Crop the settled final frame down to the bare mark (────── XENON ──────)."""
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
                ansi_map = resolve_ansi_map() if ansi_map is None else ansi_map
                parts.append(ansi_map.get(color, "") + ch)
                used_color = True
            else:
                parts.append(ch)
        if colored and used_color:
            parts.append(RESET)
        rows.append("".join(parts))
    return rows


_INDENT = " " * 4

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


def play_animation(duration: float = 3.0, fps: float = 12.0, theme=None) -> None:
    """Play the runner animation: line, sprint, particle assembly, settle."""
    frame_interval = 1.0 / max(1.0, fps)
    total_frames = max(1, int(max(0.0, duration) * max(1.0, fps)))
    last = len(FRAMES) - 1

    colored = not os.environ.get("NO_COLOR")
    ansi_map = resolve_ansi_map(theme) if colored else None

    sys.stdout.write("\n" * _FRAME_HEIGHT)
    _move_up()
    for frame_index in range(total_frames):
        source = round(frame_index * last / max(1, total_frames - 1))
        _draw_frame(_render_frame(source, colored=colored, ansi_map=ansi_map))
        _move_up()
        time.sleep(frame_interval)

    _draw_frame(_render_frame(last, colored=colored, ansi_map=ansi_map))
    sys.stdout.write("\n")
    sys.stdout.flush()


def print_logo(*, animated: bool = True, duration: float = 3.0, theme=None) -> None:
    """Print the runner identity, animating only on an interactive TTY."""
    if animated and sys.stdout.isatty():
        play_animation(duration=duration, theme=theme)
        return
    # Pipes, CI logs, and redirected output must not receive ANSI control codes.
    sys.stdout.write(LOGO_PLAIN)
    sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    print_logo(animated=True, duration=3.0)
