/**
 * Single source of truth for the Xenon runner brand.
 *
 * Storyboard: a line draws across the middle, a pixel runner sprints along
 * it, dissolves block by block and reassembles into the blocky XENON
 * wordmark; the surviving right-hand segment of the line becomes the
 * signature dash.
 *
 * Every brand artifact is derived from this data:
 *   - xenon/utils/_brand_frames.py   (terminal animation frames, generated)
 *   - docs/logo.svg                  (vector mark)
 *   - docs/logo.png                  (512x512 repo avatar)
 *   - docs/logo-animated.gif         (README animation)
 */

export type ColorKey = "w" | "c" | "b" | "v" | "d" | "g";

/** Pixel font glyphs, 5 wide x 5 tall. "█" = lit, "." = empty. */
export const LETTERS: Record<string, string[]> = {
  X: ["█...█", ".█.█.", "..█..", ".█.█.", "█...█"],
  E: ["█████", "██...", "████.", "██...", "█████"],
  N: ["█...█", "██..█", "█.█.█", "█..██", "█...█"],
  O: [".███.", "█...█", "█...█", "█...█", ".███."],
};

export const WORD = "XENON";
export const LETTER_W = 5;
export const LETTER_H = 5;
export const LETTER_PITCH = LETTER_W + 1; // 1 blank column between letters
export const WORD_W = WORD.length * LETTER_PITCH - 1; // 29
export const DASH_W = 8; // signature dash, mid-height right of the word
export const DASH_GAP = 3; // blank columns between word and dash
export const MARK_W = WORD_W + DASH_GAP + DASH_W; // 40

/**
 * Runner sprites, 8 wide x 7 tall, facing right.  Rows 0-2 are the head and
 * torso (rendered white), rows 3-6 are arms and legs (rendered cyan).
 */
export const RUNNER_W = 8;
export const RUNNER_FRAMES: string[][] = [
  // A — full stride: right leg forward, left arm forward
  [
    "...██...",
    "..████..",
    "...██...",
    ".█.█.█..",
    "..██....",
    ".█..█...",
    ".█....█.",
  ],
  // B — passing: legs together under the body
  [
    "...██...",
    "..████..",
    "...██...",
    ".█.██.█.",
    "..██....",
    "..██....",
    "...██...",
  ],
  // C — opposite stride: left leg forward, right arm forward
  [
    "...██...",
    "..████..",
    "...██...",
    "...█.█.█",
    "....██..",
    "...█..█.",
    "....█..█",
  ],
  // D — recovery: front knee tucks up
  [
    "...██...",
    "..████..",
    "...██...",
    "..█.██..",
    "..██....",
    ".█..█...",
    "█....█..",
  ],
];

// ── stage layout (terminal cells) ─────────────────────────────────────────
export const WIDTH = 72;
export const HEIGHT = 11;
export const LINE_ROW = 7; // the middle line doubles as the runner's ground
export const TRACK_LEFT = 12;
export const TRACK_RIGHT = 64;
export const WORD_ROW = 5; // word occupies rows 5..9, centered on the line
export const WORD_LEFT = 20; // word occupies cols 20..48
export const DASH_LEFT = WORD_LEFT + WORD_W + DASH_GAP; // 52
export const DASH_RIGHT = DASH_LEFT + DASH_W - 1; // 59
export const RUNNER_ROW = 1; // runner occupies rows 1..7, feet on the line
export const RUN_START_X = 6;
export const RUN_END_X = 18; // final stop: overlaps the word's left edge

// ── timeline (fractions of the full animation) ────────────────────────────
export const P_LINE_END = 0.18; // the middle line draws in
export const P_RUN_END = 0.5; // the runner sprints to the word zone
export const P_WORD_END = 0.83; // the runner dissolves into XENON
export const P_DASH_END = 0.93; // the signature dash completes

export const LETTER_COLOR: Record<string, ColorKey> = {
  X: "c",
  E: "b",
  N: "v",
  O: "b",
};

/** RGB palette for raster/SVG rendering (matches the ANSI identity). */
export const RGB: Record<ColorKey, [number, number, number]> = {
  w: [244, 250, 255], // white bold
  c: [122, 224, 255], // cyan
  b: [118, 149, 255], // blue
  v: [167, 136, 255], // violet
  d: [64, 84, 160], // dim blue
  g: [122, 132, 154], // gray
};

export const BG_TOP: [number, number, number] = [24, 40, 75]; // #18284b
export const BG_BOTTOM: [number, number, number] = [7, 11, 22]; // #070b16
