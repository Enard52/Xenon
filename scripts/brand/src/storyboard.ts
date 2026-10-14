/**
 * Frame-by-frame storyboard for the runner startup animation.
 *
 * Timeline (fractions of the full animation):
 *   [0.00 .. 0.15]  the middle line draws in from the left
 *   [0.15 .. 0.45]  the pixel runner sprints along the intact line
 *   [0.45 .. 0.85]  the runner keeps running — never stopping — while
 *                   particles shed from his body (limbs first, head last)
 *                   and assemble the XENON wordmark behind him; the line is
 *                   absorbed under the letters and retracts at the far right
 *   [0.85 .. 0.93]  the word flashes, the last particles fly into the
 *                   right-hand line, and both side lines settle
 *   [0.93 .. 1.00]  settled final mark: ────── XENON ──────
 */

import {
  ColorKey,
  DASH_GAP,
  HEIGHT,
  LEFT_DASH_LEFT,
  LEFT_DASH_RIGHT,
  LETTER_COLOR,
  LETTER_H,
  LETTER_W,
  LETTER_PITCH,
  LETTERS,
  LINE_ROW,
  P_DASH_END,
  P_LINE_END,
  P_RUN_END,
  P_WORD_END,
  RIGHT_DASH_LEFT,
  RIGHT_DASH_RIGHT,
  RUN_END_X,
  RUNNER_FRAMES,
  RUNNER_LEAD_OFFSET,
  RUNNER_ROW,
  RUNNER_W,
  RUN_START_X,
  TRACK_LEFT,
  TRACK_RIGHT,
  WIDTH,
  WORD,
  WORD_LEFT,
  WORD_ROW,
  WORD_W,
} from "./pixels.ts";

export type Cell = [string, ColorKey | ""];
export type Grid = Cell[][];
export type RowRuns = [ColorKey | "", string][];
export type FrameRuns = RowRuns[];

export const FRAME_COUNT = 36; // 3.0s @ 12fps

function emptyGrid(): Grid {
  return Array.from({ length: HEIGHT }, () =>
    Array.from({ length: WIDTH }, (): Cell => [" ", ""]),
  );
}

function put(g: Grid, r: number, c: number, ch: string, color: ColorKey | ""): void {
  if (r >= 0 && r < HEIGHT && c >= 0 && c < WIDTH) g[r][c] = [ch, color];
}

function erase(g: Grid, r: number, c: number): void {
  if (r >= 0 && r < HEIGHT && c >= 0 && c < WIDTH) g[r][c] = [" ", ""];
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function easeOut(t: number): number {
  return 1 - (1 - t) * (1 - t);
}

/** Draw the middle line from `left` to `right`; `head` is the bright tip. */
function drawTrack(g: Grid, left: number, right: number, head?: number): void {
  const l = Math.max(TRACK_LEFT, Math.round(left));
  const r = Math.min(TRACK_RIGHT, Math.round(right));
  for (let c = l; c <= r; c++) put(g, LINE_ROW, c, "─", "track");
  if (head !== undefined && head >= TRACK_LEFT && head <= TRACK_RIGHT) {
    put(g, LINE_ROW, head, "─", "hot");
  }
}

/** Stamp a runner sprite at column `x`. */
function drawRunner(g: Grid, x: number, frame: string[]): void {
  for (let r = 0; r < frame.length; r++) {
    const row = frame[r];
    for (let c = 0; c < row.length; c++) {
      if (row[c] === "█") put(g, RUNNER_ROW + r, x + c, "█", r < 3 ? "hot" : "runner");
    }
  }
}

/** Column of the latest grown letter pixel (0-based filled index). */
function growthFrontCol(grown: number): number {
  if (grown <= 0) return WORD_LEFT - 1;
  const idx = Math.min(grown, WORD.length * LETTER_W) - 1;
  const li = Math.floor(idx / LETTER_W);
  const c = idx % LETTER_W;
  return WORD_LEFT + li * LETTER_PITCH + c;
}

/**
 * Runner melt schedule: blocks shed from the extremities toward the core
 * (columns far from the head/torso axis go first), so the figure stays
 * visible — running — until the word is essentially complete.
 * Returns "solid", "ghost" (melting) or "gone" for a sprite column at time q.
 */
function runnerMelt(q: number, c: number): "solid" | "ghost" | "gone" {
  const dist = Math.abs(c - 3.5); // sprite core axis
  const melt = 0.25 + 0.75 * (1 - dist / 3.5);
  if (q < melt) return "solid";
  if (q < Math.min(1, melt + 0.06)) return "ghost";
  return "gone";
}

/**
 * Grow the word column by column, left to right.  The three most recent
 * columns stay white-hot, then settle into each letter's color.
 */
function drawWord(g: Grid, grown: number, allBright = false): void {
  let filled = 0;
  for (let li = 0; li < WORD.length; li++) {
    for (let c = 0; c < LETTER_W; c++) {
      if (filled >= grown) return;
      const bright = allBright || filled >= grown - 3;
      const color = bright ? "hot" : LETTER_COLOR[WORD[li]];
      for (let r = 0; r < LETTER_H; r++) {
        if (LETTERS[WORD[li]][r][c] === "█") {
          put(g, WORD_ROW + r, WORD_LEFT + li * LETTER_PITCH + c, "█", color);
        }
      }
      filled++;
    }
  }
}

export function composeFrame(i: number, total: number): Grid {
  const g = emptyGrid();
  const t = i / Math.max(1, total - 1);

  if (t < P_LINE_END) {
    // 1. The middle line draws in from the left, bright tip first.
    const p = easeOut(t / P_LINE_END);
    const right = lerp(TRACK_LEFT, TRACK_RIGHT, p);
    drawTrack(g, TRACK_LEFT, right, Math.round(right));
    return g;
  }

  if (t < P_RUN_END) {
    // 2. The runner sprints along the intact line with a particle trail.
    const p = (t - P_LINE_END) / (P_RUN_END - P_LINE_END);
    const x = Math.round(lerp(RUN_START_X, RUN_END_X, p));
    drawTrack(g, TRACK_LEFT, TRACK_RIGHT);
    drawRunner(g, x, RUNNER_FRAMES[Math.floor(i / 2) % RUNNER_FRAMES.length]);
    if (x > RUN_START_X) {
      put(g, LINE_ROW, x - 1, "░", "ghost");
      put(g, LINE_ROW - 1, x - 2, "·", "spark");
    }
    return g;
  }

  if (t < P_WORD_END) {
    // 3. The runner keeps running while his particles assemble the word.
    const q = (t - P_RUN_END) / (P_WORD_END - P_RUN_END);
    const grown = Math.round(q * WORD.length * LETTER_W);
    const frame = RUNNER_FRAMES[Math.floor(i / 2) % RUNNER_FRAMES.length];

    // The runner leads the growth front: his tail overlaps the newest
    // letters, his head stays visible ahead of them.
    const x = Math.max(RUN_END_X, growthFrontCol(grown) - RUNNER_LEAD_OFFSET);

    // Track: drawn full, then absorbed under/around the word.
    drawTrack(g, TRACK_LEFT, TRACK_RIGHT);
    // Runner blocks shed from the extremities toward the core.
    for (let r = 0; r < frame.length; r++) {
      const row = frame[r];
      for (let c = 0; c < row.length; c++) {
        if (row[c] !== "█") continue;
        const state = runnerMelt(q, c);
        if (state === "solid") {
          put(g, RUNNER_ROW + r, x + c, "█", r < 3 ? "hot" : "runner");
        } else if (state === "ghost") {
          put(g, RUNNER_ROW + r, x + c, "░", "ghost");
        }
      }
    }
    // The word assembles behind him from the shed particles.
    drawWord(g, grown);
    // The line retracts from the far right end.
    const outerEnd = Math.round(lerp(TRACK_RIGHT, RIGHT_DASH_RIGHT, q));
    for (let c = outerEnd + 1; c <= TRACK_RIGHT; c++) erase(g, LINE_ROW, c);
    // Gap cells between word and side lines fade as the letters arrive.
    if (q >= 0.4) {
      erase(g, LINE_ROW, LEFT_DASH_RIGHT + 1);
      erase(g, LINE_ROW, LEFT_DASH_RIGHT + 2);
    }
    if (q >= 0.75) {
      erase(g, LINE_ROW, RIGHT_DASH_LEFT - 2);
      erase(g, LINE_ROW, RIGHT_DASH_LEFT - 1);
    }
    // Particle stream: shed blocks fly from the runner toward the letters.
    const from = x + RUNNER_W - 2;
    const to = Math.max(from + 1, growthFrontCol(grown) + 1);
    for (let k = 0; k < 2; k++) {
      const pos = Math.round(lerp(from, to, 0.3 + k * 0.35));
      const r = LINE_ROW - 1 - (k % 2);
      if (g[r][pos][0] === " ") put(g, r, pos, k === 0 ? "░" : "·", "spark");
    }
    return g;
  }

  if (t < P_DASH_END) {
    // 4. The word flashes; the last particles fly into the right-hand line
    //    and both side lines settle.
    const q = (t - P_WORD_END) / (P_DASH_END - P_WORD_END);
    const flash = q < 0.2;
    drawWord(g, WORD.length * LETTER_W, flash);
    const lineColor = flash ? "hot" : "dash";
    for (let c = LEFT_DASH_LEFT; c <= LEFT_DASH_RIGHT; c++) {
      put(g, LINE_ROW, c, "─", lineColor);
    }
    for (let c = RIGHT_DASH_LEFT; c <= RIGHT_DASH_RIGHT; c++) {
      put(g, LINE_ROW, c, "─", lineColor);
    }
    // The runner's last particles merge into the right-hand line.
    for (let k = 0; k < 2; k++) {
      const pos = Math.round(lerp(WORD_LEFT + WORD_W + 1, RIGHT_DASH_LEFT + 2, q));
      const r = LINE_ROW - 1 + (k % 2);
      if (g[r][pos][0] === " ") put(g, r, pos, "·", "spark");
    }
    return g;
  }

  // 5. Settled final mark.
  drawWord(g, WORD.length * LETTER_W);
  for (let c = LEFT_DASH_LEFT; c <= LEFT_DASH_RIGHT; c++) {
    put(g, LINE_ROW, c, "─", "dash");
  }
  for (let c = RIGHT_DASH_LEFT; c <= RIGHT_DASH_RIGHT; c++) {
    put(g, LINE_ROW, c, "─", "dash");
  }
  return g;
}

/** Encode one grid row as (color, run) pairs — compact and ANSI-friendly. */
function encodeRow(row: Cell[]): RowRuns {
  const runs: RowRuns = [];
  let color: ColorKey | "" = row[0][1];
  let run = "";
  for (const [ch, col] of row) {
    if (col !== color) {
      runs.push([color, run]);
      color = col;
      run = "";
    }
    run += ch;
  }
  runs.push([color, run]);
  return runs;
}

export function encodeFrame(g: Grid): FrameRuns {
  return g.map(encodeRow);
}

export function composeAll(count: number = FRAME_COUNT): FrameRuns[] {
  return Array.from({ length: count }, (_, i) => encodeFrame(composeFrame(i, count)));
}
