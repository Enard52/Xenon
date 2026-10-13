"""Regression tests for the runner terminal startup identity.

The animation frames are authored by scripts/brand (TypeScript) and emitted
as xenon/utils/_brand_frames.py; these tests pin the contract between the
generated frame data and the Python player.
"""

from __future__ import annotations

import io

from xenon.utils import logo
from xenon.utils._brand_frames import FRAME_COUNT, FRAME_HEIGHT, FRAMES


def test_plain_logo_is_pixel_wordmark_with_signature_dash():
    assert "█" in logo.LOGO_PLAIN
    assert "────────" in logo.LOGO_PLAIN  # mid-right signature dash
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
    assert sum(row.count("─") for row in final) == 8  # signature dash


def test_final_mark_crops_to_word_and_dash():
    rows = logo._final_mark_rows(colored=False)
    assert len(rows) == 5
    assert all(len(row) == len(rows[0]) for row in rows)
    assert rows[2].endswith("────────")  # dash sits mid-height on the right
    # Colored mark keeps the ANSI palette but stays a valid 5-row mark.
    colored = logo._final_mark_rows(colored=True)
    assert len(colored) == 5
    assert any("\x1b[" in row for row in colored)
