"""auto_route 配置键打通的测试（issue #92）。

覆盖：
- config.yaml 的 auto_route 段 → AutoRouteConfig 字段
- XENON_AUTO_ROUTE_CONFIDENCE 等环境变量覆盖配置文件
- 阈值 / switch_only_on_improvement 改变 → 路由行为随之改变（确定性，无需真实 LLM）
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xenon.repl import system_config
from xenon.repl.intelligent_router import IntelligentRouter

_ENV_KEYS = (
    "XENON_AUTO_ROUTE",
    "XENON_AUTO_ROUTE_CONFIDENCE",
    "XENON_AUTO_ROUTE_NOTIFY_USER",
    "XENON_AUTO_ROUTE_SWITCH_ONLY_ON_IMPROVEMENT",
    "XENON_AUTO_ROUTE_LOG_DECISIONS",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _use_config_file(monkeypatch, tmp_path, yaml_text: str) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(system_config, "CONFIG_PATH", cfg_file)
    system_config.reload_config()


def test_auto_route_defaults_when_section_missing(monkeypatch, tmp_path):
    _use_config_file(monkeypatch, tmp_path, "")

    cfg = system_config.get_config().auto_route

    assert cfg.enabled is False
    assert cfg.confidence_threshold == 0.6
    assert cfg.notify_user is True
    assert cfg.switch_only_on_improvement is True
    assert cfg.log_decisions is False


def test_auto_route_keys_read_from_config_file(monkeypatch, tmp_path):
    _use_config_file(
        monkeypatch,
        tmp_path,
        """
auto_route:
  enabled: true
  confidence_threshold: 0.9
  notify_user: false
  switch_only_on_improvement: false
  log_decisions: true
""",
    )

    cfg = system_config.get_config().auto_route

    assert cfg.enabled is True
    assert cfg.confidence_threshold == 0.9
    assert cfg.notify_user is False
    assert cfg.switch_only_on_improvement is False
    assert cfg.log_decisions is True


def test_confidence_env_overrides_config_file(monkeypatch, tmp_path):
    _use_config_file(
        monkeypatch,
        tmp_path,
        """
auto_route:
  confidence_threshold: 0.9
""",
    )
    monkeypatch.setenv("XENON_AUTO_ROUTE_CONFIDENCE", "0.8")

    cfg = system_config.get_config().auto_route

    assert cfg.confidence_threshold == 0.8


def test_notify_user_env_overrides_config_file(monkeypatch, tmp_path):
    _use_config_file(
        monkeypatch,
        tmp_path,
        """
auto_route:
  notify_user: true
""",
    )
    monkeypatch.setenv("XENON_AUTO_ROUTE_NOTIFY_USER", "false")

    assert system_config.get_config().auto_route.notify_user is False


def _router_with_stub_selector(
    *, confidence: float, paradigm: str = "plan-execute", **router_kwargs
) -> IntelligentRouter:
    router = IntelligentRouter(enabled=True, **router_kwargs)
    router.extractor = SimpleNamespace(
        extract=lambda user_input, context: SimpleNamespace()
    )
    router.selector = SimpleNamespace(
        select=lambda features: SimpleNamespace(
            paradigm=paradigm,
            confidence=confidence,
            matched_rule="stub",
            reason="stub decision",
        )
    )
    return router


def test_confidence_threshold_blocks_switch_when_raised():
    # 0.75 >= 默认阈值 0.6 → 切换
    decision = _router_with_stub_selector(confidence=0.75).route(
        "u", None, "react"
    )
    assert decision is not None

    # 0.75 < 0.9 → 不切换
    decision = _router_with_stub_selector(
        confidence=0.75, confidence_threshold=0.9
    ).route("u", None, "react")
    assert decision is None


def test_switch_happens_above_threshold():
    decision = _router_with_stub_selector(
        confidence=0.75, confidence_threshold=0.6
    ).route("u", None, "react")

    assert decision is not None
    assert decision.paradigm == "plan-execute"


def test_switch_only_on_improvement_blocks_large_downgrade():
    # reflection(3) → direct(1)：降级超过 1 级
    decision = _router_with_stub_selector(
        confidence=0.95,
        paradigm="direct",
        switch_only_on_improvement=True,
    ).route("u", None, "reflection")
    assert decision is None

    decision = _router_with_stub_selector(
        confidence=0.95,
        paradigm="direct",
        switch_only_on_improvement=False,
    ).route("u", None, "reflection")
    assert decision is not None
    assert decision.paradigm == "direct"
