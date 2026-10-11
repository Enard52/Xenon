"""Additive session event log.

The authoritative conversation/session formats are untouched: this log is a
best-effort sidecar (JSONL) that records durable facts for replay,
projections and read-only retrieval.  Every write is failure-tolerant — a
read-only home, a full disk or a corrupt line must never break a turn.

Fact events (safe to index for retrieval):

* ``turn/user``      — user request + resolved contract summary
* ``turn/assistant`` — assistant answer preview
* ``tool/result``    — tool receipt (tool, success, canonical paths)
* ``goal/opened`` / ``goal/paused`` / ``goal/closed``
* ``plan_mode/set``  — logged plan-mode state

Authority events (never indexed, never retrieved):

* ``gate/opened`` / ``gate/resolved`` — pending approvals are facts about a
  specific past turn, but letting retrieval resurface them would resurrect
  stale authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# L0 证据层：每条会话事件带内容哈希 + 前驱哈希（append-only 哈希链）。
HASH_FIELD = "h"
PREV_FIELD = "prev"
GENESIS = "genesis"


def canonical_event_json(record: dict) -> str:
    """事件正文的规范化 JSON（哈希字段本身不参与）。"""
    body = {k: v for k, v in record.items() if k not in (HASH_FIELD, PREV_FIELD)}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_hash_hex(record: dict) -> str:
    """事件内容哈希（sha256 全文十六进制）。"""
    return hashlib.sha256(canonical_event_json(record).encode("utf-8")).hexdigest()


@dataclass
class ChainReport:
    """哈希链核验结果。"""

    total: int = 0
    verified: int = 0  # 带哈希且链路连续的事件数
    legacy: int = 0  # 旧格式事件（无哈希，无法自证）
    broken_at: int | None = None  # 首次断裂的索引（None=无断裂）
    head_hash: str | None = None  # 最新可验事件哈希

    @property
    def status(self) -> str:
        """ok | partial | broken | legacy | empty"""
        if self.total == 0:
            return "empty"
        if self.broken_at is not None:
            return "broken"
        if self.verified == 0:
            return "legacy"  # 全部旧格式：无法自证
        if self.legacy:
            return "partial"  # 可验区完整，但有旧格式事件不在链上
        return "ok"


def verify_event_chain(events: list[dict]) -> ChainReport:
    """重新计算每条事件的哈希并检查前驱链接（append-only 自证）。"""
    report = ChainReport(total=len(events))
    prev_expected: str | None = None
    chain_started = False
    for idx, event in enumerate(events):
        stored = event.get(HASH_FIELD)
        if not isinstance(stored, str) or not stored:
            report.legacy += 1
            continue
        if event_hash_hex(event) != stored:
            report.broken_at = idx
            return report
        expected = event.get(PREV_FIELD)
        if chain_started:
            # prev 必须指向前一条可验事件（genesis 不可能等于 sha256，
            # 因此链上无法“重启”）。
            if expected != prev_expected:
                report.broken_at = idx
                return report
        else:
            if expected != GENESIS:
                report.broken_at = idx
                return report
            chain_started = True
        prev_expected = stored
        report.head_hash = stored
        report.verified += 1
    return report

FACT_EVENT_TYPES = frozenset(
    {
        "turn/user",
        "turn/assistant",
        "tool/result",
        "goal/opened",
        "goal/paused",
        "goal/closed",
    }
)
AUTHORITY_EVENT_TYPES = frozenset({"gate/opened", "gate/resolved"})
KNOWN_EVENT_TYPES = FACT_EVENT_TYPES | AUTHORITY_EVENT_TYPES | {"plan_mode/set"}


def session_events_dir() -> Path:
    override = os.environ.get("XENON_SESSION_EVENTS_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".xenon" / "sessions" / "events"


class SessionEventLog:
    """Append-only JSONL writer/reader for one session.

    L0 证据层：每条记录带 ``h``（内容哈希）与 ``prev``（前驱哈希），
    文件本身就是 append-only 哈希链；``verify_event_chain`` 可随时重算自证。
    """

    def __init__(
        self,
        session_id: str | None = None,
        *,
        directory: str | os.PathLike[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.session_id = session_id or self._new_session_id()
        self.directory = Path(directory) if directory else session_events_dir()
        self.enabled = enabled and os.environ.get("XENON_SESSION_EVENTS") != "0"
        self._tail_hash: str | None = None

    @staticmethod
    def _new_session_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    @property
    def path(self) -> Path:
        return self.directory / f"{self.session_id}.jsonl"

    def _read_tail_hash(self) -> str | None:
        """读取文件末尾最后一条可验事件的哈希（跨重启保持链连续）。"""
        try:
            with open(self.path, "rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                if size == 0:
                    return None
                handle.seek(max(0, size - 16384))
                lines = (
                    handle.read().decode("utf-8", errors="replace").strip().splitlines()
                )
        except OSError:  # pragma: no cover - platform dependent
            return None
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get(HASH_FIELD):
                return str(record[HASH_FIELD])
            return None  # 旧格式尾部：新链从 genesis 重新起
        return None

    def append(self, event_type: str, **data: object) -> str | None:
        """Append one event; returns its id, or ``None`` when best-effort IO fails."""

        if not self.enabled:
            return None
        event_id = uuid.uuid4().hex[:12]
        record = {
            "id": event_id,
            "type": event_type,
            "at": time.time(),
            **data,
        }
        prev = (
            self._tail_hash
            if self._tail_hash is not None
            else self._read_tail_hash()
        )
        record[HASH_FIELD] = event_hash_hex(record)
        record[PREV_FIELD] = prev or GENESIS
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover - platform dependent
            logger.debug("会话事件写入失败（已忽略）: %s", exc)
            return None
        self._tail_hash = record[HASH_FIELD]
        return event_id

    def read(self) -> list[dict]:
        """Read all parseable events; corrupt lines are skipped."""

        if not self.path.exists():
            return []
        events: list[dict] = []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and record.get("type"):
                        events.append(record)
        except OSError as exc:  # pragma: no cover - platform dependent
            logger.debug("会话事件读取失败（已忽略）: %s", exc)
        return events
