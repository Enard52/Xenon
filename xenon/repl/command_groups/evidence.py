"""``/evidence`` — L0 证据层自证视图。

默认展示当前会话的 append-only 哈希链（事件统计 + 链完整核验 + 最近条目）；
``/evidence all``（或 ``global``）列出全局会话目录；``/evidence <会话ID>``
查看某个历史会话。所有核验都是确定性的（重算哈希 + 前驱链接），无 LLM 调用。
"""

from __future__ import annotations

from typing import Any

from xenon.repl.command_registry import command_handler, register_command

register_command(
    "/evidence",
    "查看 L0 证据账本（append-only 哈希链自证）",
    "/evidence [all|global|<会话ID>]",
)

_CHAIN_LABELS = {
    "ok": "✅ 完整（全部事件可验）",
    "partial": "⚠️ 部分（可验区完整，另有旧格式事件）",
    "legacy": "⚠️ 旧格式（无哈希字段，无法自证）",
    "broken": "❌ 断裂（哈希链不连续，可能被修改）",
    "empty": "（空）",
}

_STATUS_STYLES = {
    "ok": "green",
    "partial": "yellow",
    "legacy": "yellow",
    "broken": "red",
    "empty": "dim",
}


def _summary(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        etype = str(event.get("type") or "?")
        counts[etype] = counts.get(etype, 0) + 1
    return counts


def _render_chain_report(report: Any, counts: dict[str, int]) -> str:
    lines = [
        f"事件总数 {report.total}",
        _CHAIN_LABELS.get(report.status, report.status),
    ]
    if report.verified:
        lines.append(f"可验事件 {report.verified}（head {report.head_hash[:16]}…）")
    if report.legacy:
        lines.append(f"旧格式事件 {report.legacy}（在哈希链之前，不可自证）")
    if report.broken_at is not None:
        lines.append(f"首次断裂: 第 {report.broken_at} 条")
    for etype, n in sorted(counts.items()):
        lines.append(f"{etype} × {n}")
    return "\n".join(lines)


@command_handler("/evidence")
def _cmd_evidence(*, args: str, session_state: dict, **kwargs: Any) -> str:
    from xenon.session.events import (
        SessionEventLog,
        session_events_dir,
        verify_event_chain,
    )

    repl = session_state.get("_repl")
    arg = (args or "").strip().lower()

    # ── 全局视图：列出事件目录里的所有会话文件 ──
    if arg in {"all", "global", "--global"}:
        directory = session_events_dir()
        if not directory.exists():
            return "（会话事件目录不存在，暂无证据账本）"
        files = sorted(
            directory.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return "（会话事件目录为空，暂无证据账本）"
        lines = [f"📒 全局证据账本（{directory}）", ""]
        for i, path in enumerate(files[:20]):
            events = SessionEventLog(path.stem, directory=directory).read()
            report = verify_event_chain(events)
            status = report.status
            icon = {"ok": "🟢", "partial": "🟡", "legacy": "🟡", "broken": "🔴", "empty": "⚪"}[
                status
            ]
            turns = sum(1 for e in events if e.get("type") == "turn/user")
            lines.append(
                f"{icon} {path.stem}  ·  事件 {report.total} / 轮次 {turns} / "
                f"可验 {report.verified}  [{status}]"
            )
        if len(files) > 20:
            lines.append(f"\n… 另有 {len(files) - 20} 个会话；"
                         f"/evidence <会话ID> 查看详情")
        lines.append("\n默认 /evidence 查看当前会话。")
        return "\n".join(lines)

    # ── 指定会话 / 当前会话 ──
    log = getattr(repl, "_session_events", None)
    if arg and arg not in {"self", "current", "this"}:
        log = SessionEventLog(arg, directory=session_events_dir())
    if log is None:
        return "（无会话事件日志）"

    events = log.read()
    report = verify_event_chain(events)
    counts = _summary(events)
    header = "当前会话" if arg in {"", "self", "current", "this"} else f"会话 {log.session_id}"
    lines = [
        f"🔗 L0 证据账本 · {header}",
        f"文件: {log.path}",
        "",
        _render_chain_report(report, counts),
    ]
    if events:
        lines.append("")
        lines.append("最近条目（哈希链自尾向前）:")
        for event in reversed(events[-12:]):
            h = str(event.get("h", "（旧格式无哈希）"))
            lines.append(
                f"  {event.get('type')}  h={h[:12]}  "
                f"prev={str(event.get('prev', '-'))[:12]}"
            )
    lines.append("\n核验方式：逐条重算 sha256(事件正文) 并校验 prev 链接，"
                 "全程确定性、无 LLM。")
    return "\n".join(lines)
