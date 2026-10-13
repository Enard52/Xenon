# Xenon

[![CI](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml/badge.svg)](https://github.com/xianyu-sheng/Xenon/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xianyu-sheng/Xenon)](https://github.com/xianyu-sheng/Xenon/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

[English](README.en.md) | [简体中文](README.md)

<p align="center">
  <img src="docs/logo-animated.gif" alt="Xenon — a pixel runner sprints along the middle line and dissolves into the blocky XENON wordmark" width="666">
</p>

**A terminal AI coding agent that shows you exactly how much was actually verified.**

Other agents say "done" and you take their word for it. Xenon splits the result in two: what the machine confirmed, and what you should check yourself.

```text
❯ fix the default timeout in config.py

  🔧 edit_file  config.py                     ✓
  🔧 run        pytest                        ✗ 2 failed
  🏁 delivered (degraded) — 2 items the machine could not verify:
     · "updated every call site" (only 1 of 3 references confirmed)
     · integration tests were not run
  🧾 evidence chain: 41 events, intact and continuous · /evidence replays it
```

<sub>Simplified illustration; the real UI shows the full record of every tool call.</sub>

```bash
# 30-second install (no PyPI required)
pip install https://github.com/xianyu-sheng/Xenon/releases/download/v0.9.3/xenon_harness-0.9.3-py3-none-any.whl
xenon   # first run walks you through setup (API key, model, engine)
```

> **Windows:** if you get `'xenon' is not recognized`, the Scripts directory is not on `PATH` — pip usually prints `WARNING: The script xenon.exe is installed in '...' which is not on PATH`; run that path, add it to `PATH`, or use `python -m xenon` (v0.9.4+). Mixing conda with a standalone Python? Use a dedicated venv: `python -m venv .venv`.

## What it actually does

- **Every tool call goes into an evidence chain.** Session events are written to an append-only hash chain (content hash + predecessor hash); `/evidence` recomputes and self-checks it at any time, catching corruption, single-point tampering and reordering.
- **Exactly one blocking check.** "Hollow answers" (no work done, non-answers) are deterministic — caught, fed back for a retry, and fused if the same cause repeats. Semantic doubts never block delivery; they ship as a manual-verification checklist next to the answer.
- **Every turn is a node in a tree.** `/rewind` goes back, `/fork` branches; after an interruption or fuse, typing "continue" resumes from that node without re-explaining context.
- **Boundary actions ask first.** In-workspace writes don't interrupt you; out-of-boundary writes and commands open a unified panel with a diff preview, and approvals can be scoped by target and TTL. Subagents are read-only by default.
- **Truncation and context limits are labeled honestly** instead of being papered over.

## How a turn runs

```text
your input
  → intent contract (LLM classifier first, conservative regex fallback)
  → engine execution (budget checkpoints / loop detection / circuit breaker)
  → turn gate (the single verdict point)
      pass    → deliver
      remind  → deliver + manual-verification checklist (non-blocking)
      fail    → retry in the same turn; budget exhausted → degraded delivery
      fuse    → fuse on repeated same-cause structural failure
  → turn tree persisted + hash chain appended + turn archived
```

## What is verified, and what is not

| Layer | What it checks | How it surfaces |
|---|---|---|
| **L0 Evidence** | Whether the process is real and replayable | Hash-chained event log; `/evidence` recomputes it |
| **L1 Structural** | Whether the answer skipped the work | The only blocking check: retry / same-cause fuse |
| **L2 Semantic** | Whether claims, criteria and file references hold up | Never blocks; produces a "manual verification checklist", or a degraded delivery after retries run out |

Semantic judgement lives in exactly one place (`xenon/turn/gate.py`); engines do no semantic evaluation. Tool success/failure comes only from the tool's own receipt — never from keyword guessing.

`/evidence` output (structured turn summary + a one-line chain self-check):

<img src="docs/evidence-chain.png" alt="/evidence output example" width="720">

## Install

```bash
# Option 1 — install the wheel from GitHub Releases (recommended)
pip install https://github.com/xianyu-sheng/Xenon/releases/download/v0.9.3/xenon_harness-0.9.3-py3-none-any.whl

# Option 2 — from source (editable; shallow clone saves bandwidth)
git clone --depth 1 https://github.com/xianyu-sheng/Xenon.git
cd Xenon && python -m venv .venv
.venv/Scripts/python -m pip install -e .        # Windows
source .venv/bin/activate && pip install -e .   # Linux / macOS
```

`uv tool install <wheel URL>` and `pipx install <wheel URL>` work too and handle the entry point for you.

## Common commands

```
/evidence   evidence chain (current / all / one session)   /plan   plan mode
/goal       set the goal for this session                  /review review edits with .bak revert
/rewind     go back to an earlier turn                     /fork   branch from a turn
/sessions   list sessions                                  /compact compact long conversations
/permissions show current approvals                        /tools  list tools
```

On start, `xenon` shows a session picker first (pick a history entry by number, or a fresh session); `xenon resume` restores the most recent one and replays the conversation.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `XENON_APPROVAL_TTL` | TTL for session-level `a` approval rules (seconds) | 1800 |
| `XENON_VERIFY_RETRIES` | Same-turn retries after a structural failure | 2 |
| `XENON_RETRY_BUDGET_MIN/MAX` | Step-budget clamp for retry turns | 10 / 40 |
| `XENON_GATE_FUSE_THRESHOLD` | Same-cause structural failure fuse threshold | 2 |
| `XENON_MAX_ITERATIONS` | Steps per run | 40 |
| `XENON_MAX_TOKENS` | Output cap per model call | 8192 |
| `XENON_MAX_CONTINUATIONS` | Auto-continuations after truncation | 3 |
| `NO_COLOR` | Standard flag; disables color in output and prompt | unset |
| `XENON_READ_ONLY` | Read-only mode (all write/exec tools disabled) | off |
| `XENON_COMMAND_ALLOWLIST` | Command first-word allowlist (comma-separated) | empty = unrestricted |
| `XENON_SESSION_EVENTS(_DIR)` | Event log toggle / directory | on |
| `XENON_HOOKS` | Local hooks toggle | on |
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub tool auth (raises API limits) | empty |

## Windows notes

- Full support on Windows Terminal (ConPTY) + PowerShell (paste, CJK IME, arrow keys).
- `XENON_TERMINAL_ANIMATION=0` disables animations.

## Honest boundaries

- **The machine does not verify semantics.** When L2 hits it only warns — judge content correctness yourself with the checklist.
- **The hash chain proves process, not conclusions.** It shows the event stream was not tampered with; it does not prove the model was right.
- **The chain is an unkeyed integrity check.** It detects accidental corruption, single-point tampering and reordering; it cannot stop someone with write access from recomputing the whole chain. Put the event directory on controlled storage for stronger guarantees. (Optional HMAC anchor: see #106.)
- **The sandbox is detection + a software boundary, not real isolation.** Run untrusted code inside WSL/Docker.
- `/review`'s revert only covers edits with `.bak` backups; git is still the version history.
- The intent classifier uses the fastest model available (~1s); if unavailable it falls back to conservative regexes.

## Featured in

<!-- Ordered by list prominence; insert new entries in place once merged. -->

- [awesome-mcp-lists](https://github.com/collabnix/awesome-mcp-lists) — Collabnix community list of MCP servers, clients and toolkits (MCP Clients → Command Line Tools)

## License

MIT
