"""Regression tests for the runner terminal startup identity.

The animation frames are authored by scripts/brand (TypeScript) and emitted
as xenon/utils/_brand_frames.py with semantic color keys; the Python player
resolves those keys against the REPL theme ("logo.*" tokens).
"""

from __future__ import annotations

import io

from rich.theme import Theme

from xenon.utils import logo
from xenon.utils._brand_frames import FRAME_COUNT, FRAME_HEIGHT, FRAMES


def test_plain_logo_is_pixel_wordmark_with_symmetric_side_lines():
    assert "█" in logo.LOGO_PLAIN
    assert logo.LOGO_PLAIN.count("──────") == 2  # both signature side lines
    assert "╭" not in logo.LOGO_PLAIN
    assert "✶" not in logo.LOGO_PLAIN  # Star Core identity is retired
    lines = [line for line in logo.LOGO_PLAIN.splitlines() if line]
    assert len(lines) == 5  # 5-row pixel wordmark
    assert "\x1b" not in logo.LOGO_PLAIN


def test_redirected_logo_has_no_ansi_sequences(monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(logo.sys, "stdout", output)

    logo.print_logo(animated=True)

    rendered = output.getvalue()
    assert "█" in rendered
    assert "\x1b[" not in rendered


def test_generated_frames_match_player_contract():
    assert len(FRAMES) == FRAME_COUNT
    first = logo._render_frame(0, colored=False)
    assert len(first) == FRAME_HEIGHT == logo._FRAME_HEIGHT
    # The first beat draws the middle line; the last is the settled mark.
    assert "─" in "".join(first)
    final = logo._render_frame(FRAME_COUNT - 1, colored=False)
    assert sum(row.count("█") for row in final) == 65  # X E N O N pixels
    assert sum(row.count("─") for row in final) == 12  # 6 + 6 side lines


def test_final_mark_crops_to_word_and_both_side_lines():
    rows = logo._final_mark_rows(colored=False)
    assert len(rows) == 5
    assert all(len(row) == len(rows[0]) for row in rows)
    assert len(rows[0]) == 45  # 6 + 2 + 29 + 2 + 6
    assert rows[2].startswith("──────")  # left line, mid-height
    assert rows[2].endswith("──────")  # right line, mid-height
    # Colored mark keeps the ANSI palette but stays a valid 5-row mark.
    colored = logo._final_mark_rows(colored=True)
    assert len(colored) == 5
    assert any("\x1b[" in row for row in colored)


def test_animation_colors_follow_the_theme():
    # Default resolution maps every semantic key to the default palette.
    default = logo.resolve_ansi_map()
    assert set(default) == {
        "hot",
        "track",
        "runner",
        "letter-a",
        "letter-b",
        "letter-c",
        "dash",
        "spark",
        "ghost",
    }
    assert all(ansi == "" or "\x1b[" in ansi for ansi in default.values())
    assert "38;2;103;232;249" in default["dash"]  # #67e8f9

    # A theme override on a logo.* token re-colors the animation.
    themed = logo.resolve_ansi_map(Theme({"logo.dash": "bold #ff0000"}))
    assert "38;2;255;0;0" in themed["dash"]
    assert "1m" in themed["dash"]  # bold carried over
    # Untouched tokens fall back to the defaults.
    assert themed["track"] == default["track"]
