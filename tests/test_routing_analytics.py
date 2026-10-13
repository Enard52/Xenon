"""Tests for intelligent-router decision logging and exports (issue #88)."""

import csv
import json
from types import SimpleNamespace

from xenon.repl.commands import cmd_auto_route
from xenon.repl.feature_extractor import TaskFeatures
from xenon.repl.intelligent_router import IntelligentRouter
from xenon.repl.paradigm_selector import RoutingDecision
from xenon.repl.routing_history import DecisionHistory, RoutingDecisionRecord


def _features() -> TaskFeatures:
    return TaskFeatures(
        is_query=False,
        is_coding=True,
        is_exploratory=False,
        input_length=6,
        estimated_steps=1,
        estimated_tool_calls=1,
        complexity_score=0.2,
        has_file_operations=True,
        has_git_operations=False,
        needs_web_access=False,
        quality_critical=False,
    )


def _router(history=None) -> IntelligentRouter:
    router = IntelligentRouter(enabled=True, decision_history=history)
    router.extractor.extract = lambda user_input, context: _features()
    router.selector.select = lambda features: RoutingDecision(
        paradigm="react",
        confidence=0.8,
        reason="test",
        matched_rule="R7",
    )
    return router


def test_router_records_bounded_decision_with_feature_snapshot():
    history = DecisionHistory()
    router = _router(history)

    decision = router.route("x" * 200, object(), "direct")

    assert decision is not None
    record = history.all()[0]
    assert len(record.user_input_preview) == 120
    assert record.features["has_file_operations"] is True
    assert record.current_paradigm == "direct"
    assert record.switched is True


def test_stats_are_deterministic():
    history = DecisionHistory()
    router = _router(history)
    router.route("first", object(), "direct")
    router.route("second", object(), "react")

    stats = history.stats()

    assert stats["total_decisions"] == 2
    assert stats["switches"] == 1
    assert stats["rule_hits"] == {"R7": 2}
    assert stats["paradigms"] == {"react": 2}


def test_decision_history_persists_jsonl(tmp_path):
    path = tmp_path / "decisions.jsonl"
    history = DecisionHistory(persist_path=str(path))
    history.record(
        RoutingDecisionRecord(
            timestamp=1.0,
            user_input_preview="safe preview",
            features={"complexity_score": 0.2},
            matched_rule="R7",
            recommended_paradigm="react",
            confidence=0.8,
            current_paradigm="direct",
            switched=True,
        )
    )

    loaded = DecisionHistory(persist_path=str(path))

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert loaded.all()[0].recommended_paradigm == "react"


def test_stats_command_and_exports(tmp_path):
    history = DecisionHistory()
    _router(history).route("export me", object(), "direct")
    repl = SimpleNamespace(
        intelligent_router=SimpleNamespace(
            enabled=True,
            confidence_threshold=0.6,
            notify_user=True,
            switch_only_on_improvement=True,
            decision_history=history,
            get_stats=lambda: {"decision_log": history.stats()},
        )
    )
    state = {"_repl": repl}
    json_path = tmp_path / "decisions.json"
    csv_path = tmp_path / "decisions.csv"

    cmd_auto_route(
        args=f"export --format json --output {json_path}", session_state=state
    )
    cmd_auto_route(
        args=f"export --format csv --output {csv_path}", session_state=state
    )
    cmd_auto_route(args="stats", session_state=state)

    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["switched"] is True
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["recommended_paradigm"] == "react"


def test_logging_failure_does_not_break_routing():
    class BrokenHistory:
        def record(self, record):
            raise OSError("read-only")

    decision = _router(BrokenHistory()).route("continue", object(), "direct")

    assert decision is not None
