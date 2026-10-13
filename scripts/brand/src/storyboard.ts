/**
 * Frame-by-frame storyboard for the runner startup animation.
 *
 * Timeline (fractions of the full animation):
 *   [0.00 .. 0.18]  the middle line draws in from the left
 *   [0.18 .. 0.50]  the pixel runner sprints along the line (line is
 *                   consumed behind him)
 *   [0.50 .. 0.83]  the runner stops inside the word zone and dissolves
 *                   right-to-left while the letters grow in left-to-right
 *   [0.83 .. 0.93]  the word flashes, the signature dash draws rightward and
 *                   the leftover line retracts
 *   [0.93 .. 1.00]  settled final mark: XENON + mid-right dash
 */

import {
  ColorKey,
  DASH_LEFT,
  DASH_RIGHT,
  HEIGHT,
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
  RUN_END_X,
  RUNNER_FRAMES,
  RUNNER_ROW,
  RUNNER_W,
  RUN_START_X,
  TRACK_LEFT,
  TRACK_RIGHT,
  WIDTH,
  WORD,
  WORD_LEFT,
  WORD_ROW,
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
  for (let c = l; c <= r; c++) put(g, LINE_ROW, c, "─", "d");
  if (head !== undefined && head >= TRACK_LEFT && head <= TRACK_RIGHT) {
    put(g, LINE_ROW, head, "─", "w");
  }
}

/** Stamp a runner sprite at column `x`. */
function drawRunner(g: Grid, x: number, frame: string[]): void {
  for (let r = 0; r < frame.length; r++) {
    const row = frame[r];
    for (let c = 0; c < row.length; c++) {
      if (row[c] === "█") put(g, RUNNER_ROW + r, x + c, "█", r < 3 ? "w" : "c");
    }
  }
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
      const color = bright ? "w" : LETTER_COLOR[WORD[li]];
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
    // 2. The runner sprints along the line; the line is consumed behind him.
    const p = (t - P_LINE_END) / (P_RUN_END - P_LINE_END);
    const x = Math.round(lerp(RUN_START_X, RUN_END_X, p));
    drawTrack(g, x + RUNNER_W, TRACK_RIGHT);
    drawRunner(g, x, RUNNER_FRAMES[Math.floor(i / 2) % RUNNER_FRAMES.length]);
    if (x > RUN_START_X) put(g, LINE_ROW, x - 1, "░", "d");
    return g;
  }

  if (t < P_WORD_END) {
    // 3. The runner dissolves into the letters.
    const q = (t - P_RUN_END) / (P_WORD_END - P_RUN_END);
    // The left line segment retracts toward the word while it dissolves.
    // Starts at the run-phase end (continuous with the sprint) and retracts
    // to the word's left edge.
    drawTrack(g, lerp(RUN_END_X + RUNNER_W, WORD_LEFT, q), TRACK_RIGHT);
    // Runner blocks break apart right-to-left as the letters consume him.
    const frame = RUNNER_FRAMES[Math.floor(i / 2) % RUNNER_FRAMES.length];
    const keep = Math.max(0, Math.floor(RUNNER_W * (1 - q * 1.15)));
    for (let r = 0; r < frame.length; r++) {
      const row = frame[r];
      for (let c = 0; c < row.length; c++) {
        if (row[c] !== "█") continue;
        if (c < keep) put(g, RUNNER_ROW + r, RUN_END_X + c, "█", r < 3 ? "w" : "c");
        else if (c < keep + 2) put(g, RUNNER_ROW + r, RUN_END_X + c, "░", "c");
      }
    }
    drawWord(g, Math.round(q * WORD.length * LETTER_W));
    // Sparks drift above the dissolve zone (deterministic pseudo-random).
    const span = Math.max(1, WORD_LEFT - (RUN_END_X + 2) + 4);
    for (let k = 0; k < 2; k++) {
      const c = RUN_END_X + 2 + ((i * 7 + k * 13) % span);
      const r = WORD_ROW - 2 + ((i * 3 + k * 5) % 3);
      if (g[r][c][0] === " ") put(g, r, c, k === 0 ? "░" : "·", "c");
    }
    return g;
  }

  if (t < P_DASH_END) {
    // 4. The word flashes, the dash draws rightward, the leftover line fades.
    const q = (t - P_WORD_END) / (P_DASH_END - P_WORD_END);
    drawWord(g, WORD.length * LETTER_W, q < 0.25);
    const right = Math.round(lerp(DASH_LEFT, DASH_RIGHT, easeOut(q)));
    for (let c = DASH_LEFT; c <= right; c++) put(g, LINE_ROW, c, "─", "c");
    put(g, LINE_ROW, right, "─", "w");
    drawTrack(g, lerp(DASH_RIGHT + 1, TRACK_RIGHT + 1, q), TRACK_RIGHT);
    return g;
  }

  // 5. Settled final mark.
  drawWord(g, WORD.length * LETTER_W);
  for (let c = DASH_LEFT; c <= DASH_RIGHT; c++) put(g, LINE_ROW, c, "─", "c");
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
