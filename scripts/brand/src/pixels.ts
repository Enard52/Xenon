/**
 * Single source of truth for the Xenon runner brand.
 *
 * Storyboard: a line draws across the middle, a pixel runner sprints along
 * it and — without ever stopping — sheds particles that assemble into the
 * blocky XENON wordmark behind him.  The track is absorbed under the letters
 * and retracts at the far right, leaving symmetric side lines; the runner's
 * last particles merge into the right-hand line as the mark settles.
 *
 * Every brand artifact is derived from this data:
 *   - xenon/utils/_brand_frames.py   (terminal animation frames, generated)
 *   - docs/logo.svg                  (vector mark)
 *   - docs/logo.png                  (512x512 repo avatar)
 *   - docs/logo-animated.gif         (README animation)
 *
 * Frame colors are SEMANTIC keys, not concrete colors: the Python player
 * resolves them against the REPL theme tokens (xenon/repl/theme.py, the
 * "logo.*" namespace), so the animation follows the active theme.  The RGB
 * palette below only feeds the rendered assets (SVG/PNG/GIF) and mirrors the
 * default theme values.
 */

export type ColorKey =
  | "hot" // bright flash: growth front, runner head, line tip
  | "track" // the middle line
  | "runner" // the runner's body
  | "letter-a" // letters X, N
  | "letter-b" // letters E, O
  | "letter-c" // letter N (middle)
  | "dash" // settled signature lines
  | "spark" // flying particles
  | "ghost"; // melting / trailing blocks

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
export const SIDE_DASH_W = 6; // symmetric line segments flanking the word
export const DASH_GAP = 2; // blank columns between word and each side line
export const MARK_W = SIDE_DASH_W + DASH_GAP + WORD_W + DASH_GAP + SIDE_DASH_W; // 45

/**
 * Runner sprites, 8 wide x 7 tall, facing right.  Rows 0-2 are the head and
 * torso (rendered "hot"), rows 3-6 are arms and legs (rendered "runner").
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
export const LEFT_DASH_LEFT = TRACK_LEFT; // 12
export const LEFT_DASH_RIGHT = TRACK_LEFT + SIDE_DASH_W - 1; // 17
export const RIGHT_DASH_LEFT = WORD_LEFT + WORD_W + DASH_GAP; // 51
export const RIGHT_DASH_RIGHT = RIGHT_DASH_LEFT + SIDE_DASH_W - 1; // 56
export const RUNNER_ROW = 1; // runner occupies rows 1..7, feet on the line
export const RUN_START_X = 6;
export const RUN_END_X = 18; // where the word zone begins
export const RUNNER_LEAD_OFFSET = 3; // runner head stays ahead of the growth front

// ── timeline (fractions of the full animation) ────────────────────────────
export const P_LINE_END = 0.15; // the middle line draws in
export const P_RUN_END = 0.45; // the runner sprints to the word zone
export const P_WORD_END = 0.85; // the word assembles from the runner's particles
export const P_DASH_END = 0.93; // the side lines settle

export const LETTER_COLOR: Record<string, ColorKey> = {
  X: "letter-a",
  E: "letter-b",
  N: "letter-c",
  O: "letter-b",
};

/**
 * RGB palette for raster/SVG rendering.  Mirrors the default theme values of
 * the xenon.repl.theme "logo.*" tokens (see DEFAULT_TOKEN_STYLES).
 */
export const RGB: Record<ColorKey, [number, number, number]> = {
  hot: [240, 249, 255], // #f0f9ff
  track: [51, 65, 85], // #334155
  runner: [103, 232, 249], // #67e8f9
  "letter-a": [103, 232, 249], // #67e8f9
  "letter-b": [129, 140, 248], // #818cf8
  "letter-c": [196, 181, 253], // #c4b5fd
  dash: [103, 232, 249], // #67e8f9
  spark: [103, 232, 249], // #67e8f9
  ghost: [148, 163, 184], // #94a3b8
};

export const BG_TOP: [number, number, number] = [24, 40, 75]; // #18284b
export const BG_BOTTOM: [number, number, number] = [7, 11, 22]; // #070b16
