# Xenon

[![CI](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml/badge.svg)](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xianyu-sheng/Xenon)](https://github.com/xianyu-sheng/Xenon/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

An interactive **AI coding agent (agent harness)** for the terminal: work with multiple model providers to read and write code, run commands, and verify results — with deterministic checks and auditable permission boundaries at every step.

[English](README.en.md) | [简体中文](README.md)

```bash
# 30-second install (no PyPI required)
pip install https://github.com/xianyu-sheng/Xenon/releases/download/v0.9.3/xenon_harness-0.9.3-py3-none-any.whl
xenon   # first run walks you through setup (/setup: API key, model, engine)
```

> **Windows troubleshooting — `'xenon' is not recognized`:**
> - The entry script landed in a Scripts directory that is not on `PATH`. pip usually prints
>   `WARNING: The script xenon.exe is installed in '...' which is not on PATH` — run that full
>   path directly (`<dir>\Scripts\xenon.exe`) or add the directory to `PATH`.
> - **PATH-independent entry point:** `python -m xenon` (v0.9.4+).
> - Or use `uv tool install <same wheel URL>` / `pipx install <same wheel URL>` (they manage the entry point for you).
> - Mixing conda with a standalone Python? Use a dedicated venv:
>   `python -m venv .venv` then `.venv\Scripts\python -m pip install <wheel URL>`.

> **Positioning: the only agent harness that tells you *how much was actually machine-verified* and how much is left for you to check.**
> Claude Code / Codex say "we don't verify semantics — trust us." Xenon says
> **"the machine manages the evidence; you judge the truth."** The machine is
> only responsible for *process truth* (what was done, what succeeded, whether
> the evidence chain is intact); it discloses *content correctness* in tiers.
> This is not "yet another LLM client" — it is an agent skeleton built around
> **an evidence hash chain, a single semantic channel, and a replayable turn tree**.

Actual `/evidence` output (structured turn summary + one-line chain self-check):

<img src="docs/evidence-chain.png" alt="/evidence output example" width="720">

## Three-layer trust model (the core difference)

| Layer | Mechanism | Machine responsibility |
|---|---|---|
| **L0 Evidence** | The session event log is an append-only hash chain: every event carries a content hash + predecessor hash. The `/evidence` command recomputes and verifies it at any time (current session / all sessions / a specific session). | Proves **process truth** (what happened, success/failure, whether the chain is intact and continuous) |
| **L1 Structural** | Hollow answers (deterministic, no semantic blind spots) are the only *blocking* class of check: on hit, feedback-then-retry within the same turn (half budget), fuse on repeats of the same cause. | Blocks **answers that didn't do the work** |
| **L2 Semantic** | Claim audit / completion criteria / file claims / post-write verification: **never blocks delivery**; on hit, a yellow "manual verification checklist" panel ships alongside the answer. Retry exhaustion → degraded release. | Flags **what the machine could not verify** for you to check |

Semantic judgment (claim audit / completion criteria / file claims / post-write verification) lives in exactly one place (`xenon/turn/gate.py`); engines only do deterministic structural correction (rewriting incomplete answers, retrying tool-less completion claims) — never LLM-based semantic judgment. Tool success/failure is decided solely by the `success` field of the tool's receipt (single semantic channel), never guessed from keywords.

## Other core capabilities

| Capability | Description |
|---|---|
| **Turn tree (TurnTree)** | Every user turn is a node (state / artifacts / verdict / event pointer). `/rewind` goes back, `/fork` branches, a bare "continue" resumes automatically from the **interrupted/fused node** |
| **Budget checkpoints (not fixed steps)** | When the window is exhausted: progress → suspended with an approval prompt "continue?"; spinning in place → LoopDetector fuses; the same infrastructure error twice in a row → fast fuse with guidance |
| **Structured turn archive** | Long conversations auto-compact: old turns deterministically fold into intent / tool outcomes / failure log / decisions / artifact blocks at zero LLM cost; also the retrieval summary source |
| **Boundary approvals** | In-workspace writes are not asked about; out-of-boundary writes and commands go through a unified panel with diff preview and an `a` command that registers TTL-bound session rules. Approvals use a closed vocabulary, fail closed, and authorizations never come back to life via retrieval/session restore |
| **Read-only subagents by default** | Subagents spawned via `spawn_agent` are capped at READ_ONLY; `read_only=false` is an explicit opt-in |
| **Sandbox seam** | Read-only mode + command allowlist + WSL/Docker detection (honest disclaimer: a software boundary, not real isolation) |
| **Honest truncation marking** | When output is cut off by length limits, the reply carries a visible marker instead of pretending to be complete |
| **Hooks** | User/project `.xenon/hooks.yaml`: PreToolUse / PostToolUse / Stop / SubagentStop (exit 2 blocks, JSON on stdin) |

## Quick start

Current version: **v0.9.3** (single source of truth `xenon.__version__`; see [CHANGELOG](CHANGELOG.md) for history).

```bash
# Install straight from GitHub Releases (no PyPI account needed)
# uv users: uv tool install <same URL>
pip install https://github.com/xianyu-sheng/Xenon/releases/download/v0.9.3/xenon_harness-0.9.3-py3-none-any.whl
```

```bash
# Or clone and install editable (repo is a shallow-friendly ~16 MB)
git clone --depth 1 https://github.com/xianyu-sheng/Xenon.git
cd Xenon
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # Windows
source .venv/bin/activate && pip install -e .   # Linux/macOS

# Run
xenon
# First run walks you through setup (/setup: key, model, engine)
```

Common commands: `/evidence` (L0 evidence ledger self-check) `/plan` `/goal` `/review` `/rewind <n>` `/fork [n]` `/compact` `/sessions` `/permissions` `/tools` `/help`

Resume on start: running `xenon` first shows a **session picker** (pick a historical session by number, or start fresh); you can also use `xenon resume` (most recent), `xenon resume <index>`, or `xenon --resume` (list). Non-interactive terminals skip the picker.

## Session state machine (per turn)

```
user input → single semantic channel (TurnContract: LLM intent classifier + regex guardrails)
  → engine execution (pure executor: budget checkpoint guard + interrupt + loop detection)
  → TurnGate turn verification (the only verdict point)
      pass   → deliver
      remind → deliver + manual verification checklist (L2 semantic, non-blocking)
      fail   → feedback-retry within the same turn (budget = first attempt steps / 2, clamped [10,40]);
               exhausted → degraded delivery (degraded + checklist)
      fuse   → fuse on repeated same-cause structural failure; deliver as incomplete
  → node state persisted + hash-chain event appended + turn archived
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `XENON_APPROVAL_TTL` | TTL (seconds) for session-level `a` approval rules | 1800 |
| `XENON_VERIFY_RETRIES` | Same-turn retries after a structural failure | 2 |
| `XENON_RETRY_BUDGET_MIN/MAX` | Retry budget clamp | 10 / 40 |
| `XENON_GATE_FUSE_THRESHOLD` | Fuse threshold for same-cause structural failures | 2 |
| `XENON_MAX_ITERATIONS` | Steps per run (checkpoint window basis) | 40 |
| `XENON_CHECKPOINT_STEPS` | Checkpoint window size | = step cap |
| `XENON_MAX_TOKENS` | Max output tokens per LLM call | 8192 |
| `XENON_MAX_CONTINUATIONS` | Auto-continuations after truncation | 3 |
| `XENON_READ_ONLY` | Read-only mode (all write/exec tools disabled) | off |
| `XENON_COMMAND_ALLOWLIST` | Command first-word allowlist (comma-separated) | empty = unrestricted |
| `XENON_SESSION_EVENTS(_DIR)` | Event log (hash chain) toggle/directory | on |
| `XENON_HOOKS` | Hooks toggle | on |
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub tool auth (raises API limits, used for git clone) | empty |
| `XENON_INTENT_CLASSIFIER_ENABLED` | LLM intent classifier | on |

## Architecture

```
xenon/
├── repl/        Interface: REPL loop, engine host, rendering, turn contract,
│                task state, command groups
├── turn/        Turn layer: TurnGate — the single verification point (L1 structural / L2 semantic reminders)
├── session/     Structural layer: tree (turn tree) / events (hash-chain log)
│                / archive (turn archive) / projection (goal projection) / query
├── engine/      Engine layer: react / plan_execute / combined engines (pure executors)
├── nodes/       Tool layer: tool_executor / approval_policy / path_targets
├── hooks/       Local hooks runner
└── sandbox/     Sandbox seam: read-only mode + command allowlist + WSL/Docker detection
```

## Windows notes

- Full support on Windows Terminal (ConPTY) + PowerShell (paste, CJK IME, arrow keys).
- `XENON_TERMINAL_ANIMATION=0` disables animations.
- If git push fails on flaky networks: `git -c http.proxy= -c https.proxy= -c http.sslBackend=openssl push` (or use a proxy via `http://127.0.0.1:3067`).

## Honest boundaries

- **The machine does not verify semantics**: when L2 (claims/criteria/file claims) hits, it only warns — it never blocks. Judge content correctness yourself with the "manual verification checklist".
- **The hash chain proves process, not conclusions**: `/evidence` proves the event stream was not tampered with; it does not prove the model's answers are correct.
- **The hash chain is an unkeyed integrity check**: it detects accidental corruption, single-point tampering, and reordering; it cannot stop someone with write access from recomputing the whole chain. Keep the event directory on controlled storage for stronger guarantees.
- **The sandbox is detection + a software boundary, not real isolation**: run Xenon inside a WSL/Docker container for untrusted code.
- `/review`'s revert only covers edits that have `.bak` backups; git remains irreplaceable.
- The intent classifier uses the fastest available model with ~1s latency; if unavailable it falls back to conservative regexes.

## Featured in

<!-- Ordered by list prominence; insert new entries in place once merged. -->

- [awesome-mcp-lists](https://github.com/collabnix/awesome-mcp-lists) — Collabnix community list of MCP servers, clients and toolkits (MCP Clients → Command Line Tools)

## License

MIT
