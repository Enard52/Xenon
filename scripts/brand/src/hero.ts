/**
 * Terminal "hero" SVGs for the README.
 *
 * GitHub does not render repo SVGs as HTML, only as images, so this module
 * emits plain vector terminals (no emoji, explicit CJK fallbacks in the font
 * stack) — the same trick Reasonix and friends use for their README heroes.
 *
 * Rendered by scripts/brand/render.ts into:
 *   docs/hero-terminal.svg     (zh)
 *   docs/hero-terminal.en.svg  (en)
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

type Segment = [text: string, fill: string];

const WIDTH = 880;
const LINE_HEIGHT = 27;
const BODY_TOP = 78;

const BG = "#0a0c10";
const BAR = "#11141a";
const BORDER = "#1e2436";
const TEXT = "#e6edf3";
const DIM = "#8b949e";
const PROMPT = "#67e8f9";
const TOOL = "#67e8f9";
const OK = "#56d364";
const BAD = "#f85149";
const WARN = "#e3b341";
const ACCENT = "#c4b5fd";

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function line(x: number, y: number, segments: Segment[]): string {
  const inner = segments
    .map(([text, fill]) => `<tspan fill="${fill}">${esc(text)}</tspan>`)
    .join("");
  return `    <text x="${x}" y="${y}">${inner}</text>`;
}

interface Hero {
  file: string;
  title: string;
  aria: string;
  lines: Segment[][];
}

const HEROES: Hero[] = [
  {
    file: "docs/hero-terminal.svg",
    title: "xenon — 证据链",
    aria: "Xenon 终端：修复超时默认值的回合中，机器确认了什么、哪两项需要人工核验",
    lines: [
      [["❯ ", PROMPT], ["修复 config.py 里的超时默认值", TEXT]],
      [["", DIM]],
      [["  ▸ ", TOOL], ["edit_file", TEXT], ["  config.py", DIM], ["                     ✓", OK]],
      [["  ▸ ", TOOL], ["run", TEXT], ["        pytest", DIM], ["                        ✗ 2 failed", BAD]],
      [["  ▸ ", WARN], ["交付（降级）", TEXT], [" — 以下 2 项机器无法核实，请人工确认：", DIM]],
      [["       · ", DIM], ['"已覆盖所有调用点"（实际只确认 1/3 处引用）', DIM]],
      [["       · ", DIM], ["未运行集成测试", DIM]],
      [["  ▸ ", ACCENT], ["证据链", TEXT], ["：41 条事件，完整连续 · ", DIM], ["/evidence", PROMPT], [" 可随时复核", DIM]],
    ],
  },
  {
    file: "docs/hero-terminal.en.svg",
    title: "xenon — evidence chain",
    aria: "Xenon terminal: what the machine confirmed, and the two items it could not verify",
    lines: [
      [["❯ ", PROMPT], ["fix the default timeout in config.py", TEXT]],
      [["", DIM]],
      [["  ▸ ", TOOL], ["edit_file", TEXT], ["  config.py", DIM], ["                     ✓", OK]],
      [["  ▸ ", TOOL], ["run", TEXT], ["        pytest", DIM], ["                        ✗ 2 failed", BAD]],
      [["  ▸ ", WARN], ["delivered (degraded)", TEXT], [" — 2 items the machine could not verify:", DIM]],
      [["       · ", DIM], ['"updated every call site" (only 1 of 3 references confirmed)', DIM]],
      [["       · ", DIM], ["integration tests were not run", DIM]],
      [["  ▸ ", ACCENT], ["evidence chain", TEXT], [": 41 events, intact and continuous · ", DIM], ["/evidence", PROMPT], [" replays it", DIM]],
    ],
  },
];

function renderHero(hero: Hero): string {
  const height = BODY_TOP + hero.lines.length * LINE_HEIGHT + 26;
  const rows = hero.lines
    .map((segments, index) => line(28, BODY_TOP + index * LINE_HEIGHT, segments))
    .join("\n");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${WIDTH} ${height}" role="img" aria-label="${esc(hero.aria)}">
  <title>${esc(hero.title)}</title>
  <defs>
    <style>
      .mono { font-family: "JetBrains Mono", ui-monospace, "Cascadia Code", Menlo, Consolas, "Noto Sans Mono CJK SC", "Microsoft YaHei", monospace; font-weight: 500; }
    </style>
    <linearGradient id="ttl" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#67e8f9"/>
      <stop offset="55%" stop-color="#93c5fd"/>
      <stop offset="100%" stop-color="#c4b5fd"/>
    </linearGradient>
  </defs>

  <rect x="0.5" y="0.5" width="${WIDTH - 1}" height="${height - 1}" rx="10" ry="10" fill="${BG}" stroke="${BORDER}"/>

  <rect x="0.5" y="0.5" width="${WIDTH - 1}" height="34" rx="10" ry="10" fill="${BAR}"/>
  <rect x="0.5" y="24" width="${WIDTH - 1}" height="11" fill="${BAR}"/>
  <line x1="0.5" y1="34.5" x2="${WIDTH - 0.5}" y2="34.5" stroke="${BORDER}"/>

  <circle cx="22" cy="17.5" r="6" fill="#ff8b81"/>
  <circle cx="42" cy="17.5" r="6" fill="#f0b07d"/>
  <circle cx="62" cy="17.5" r="6" fill="#7ee787"/>
  <text x="${WIDTH / 2}" y="22" text-anchor="middle" class="mono" font-size="12" fill="url(#ttl)">${esc(hero.title)}</text>

  <g class="mono" font-size="14" xml:space="preserve">
${rows}
  </g>
</svg>
`;
}

export function emitHeroSvgs(rootDir: string): void {
  mkdirSync(resolve(rootDir, "docs"), { recursive: true });
  for (const hero of HEROES) {
    const target = resolve(rootDir, hero.file);
    writeFileSync(target, renderHero(hero));
    console.log(`wrote ${target}`);
  }
}
