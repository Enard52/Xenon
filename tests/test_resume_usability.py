"""会话恢复可用性修复：CLI 位置参数 + 扁平 credentials 派生模型。"""

from __future__ import annotations

import sys

import yaml


def _run_cli(argv: list[str], monkeypatch) -> dict:
    """跑一次 main.cli() 并拦截结果。"""
    import xenon.main as main_mod

    captured: dict = {}
    monkeypatch.setattr(main_mod, "_cmd_chat", lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(main_mod, "_print_session_list", lambda: captured.setdefault("list", True))
    monkeypatch.setattr(main_mod, "_validate_resume_target", lambda t: t)
    monkeypatch.setattr(sys, "argv", ["xenon", *argv])
    main_mod.cli()
    return captured


def test_cli_resume_positional_defaults_to_latest(monkeypatch):
    """"xenon resume"（无参）→ 恢复最近会话（列表第 1 个）。"""
    captured = _run_cli(["resume"], monkeypatch)
    assert captured["args"].resume == "1"


def test_cli_resume_positional_number(monkeypatch):
    captured = _run_cli(["resume", "3"], monkeypatch)
    assert captured["args"].resume == "3"


def test_cli_resume_positional_list_prints_and_exits(monkeypatch):
    captured = _run_cli(["resume", "list"], monkeypatch)
    assert captured == {"list": True}


def test_flat_credentials_derive_builtin_models(tmp_path, monkeypatch):
    """credentials.yaml 只写 ``deepseek: sk-...``（无 providers 段）→ 仍派生模型。"""

    from xenon.repl.model_registry import ModelRegistry

    creds = tmp_path / "credentials.yaml"
    creds.write_text("deepseek: sk-test-token\n", encoding="utf-8")

    registry = ModelRegistry()
    registry.load_from_credentials(credentials_path=creds)
    ids = [m.model_id for m in registry.models.values()]
    assert "deepseek/deepseek-v4-pro" in ids
    assert "deepseek/deepseek-v4-flash" in ids


def test_flat_credentials_ignore_unknown_provider(tmp_path):
    """非内置厂商 key（中转站）无离线目录 → 不猜、不注册。"""

    from xenon.repl.model_registry import ModelRegistry

    creds = tmp_path / "credentials.yaml"
    creds.write_text("my-proxy: sk-xxx\n", encoding="utf-8")
    registry = ModelRegistry()
    registry.load_from_credentials(credentials_path=creds)
    assert len(registry.models) == 0


def test_providers_section_still_wins_over_flat(tmp_path):
    """providers 段存在时走原路径，扁平段不重复注册。"""

    from xenon.repl.model_registry import ModelRegistry

    creds = tmp_path / "credentials.yaml"
    creds.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "deepseek": {
                        "api_key": "sk-a",
                        "base_url": "https://api.deepseek.com/v1",
                        "models": ["deepseek-v4-flash"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    registry = ModelRegistry()
    registry.load_from_credentials(credentials_path=creds)
    ids = [m.model_id for m in registry.models.values()]
    assert ids == ["deepseek/deepseek-v4-flash"]


def test_startup_picker_returns_chosen_index(monkeypatch, capsys):
    """门前进会话选择器：选 1 → 返回 '1'；选 0 → None（新对话）。"""

    import xenon.main as main_mod
    import xenon.repl.session as session_mod
    import rich.prompt as rich_prompt

    fake_sessions = [
        {
            "name": "_auto",
            "messages": 3,
            "paradigm": "direct",
            "saved_at": "2026-10-12T12:00:00",
        }
    ]
    monkeypatch.setattr(session_mod, "list_sessions", lambda: fake_sessions)
    monkeypatch.setattr(session_mod, "get_session_age", lambda s: "刚刚")

    class _Stdin:
        def isatty(self):
            return True

    monkeypatch.setattr(main_mod.sys, "stdin", _Stdin())

    class _FakeIntPrompt:
        @staticmethod
        def ask(prompt, choices=None, default=None, show_default=True):
            return default

    monkeypatch.setattr(rich_prompt, "IntPrompt", _FakeIntPrompt)
    assert main_mod._interactive_session_picker() == "1"


def test_startup_picker_new_conversation(monkeypatch):
    import xenon.main as main_mod
    import xenon.repl.session as session_mod
    import rich.prompt as rich_prompt

    monkeypatch.setattr(session_mod, "list_sessions", lambda: [{"name": "_auto", "messages": 1}])
    monkeypatch.setattr(session_mod, "get_session_age", lambda s: "刚刚")

    class _Stdin:
        def isatty(self):
            return True

    monkeypatch.setattr(main_mod.sys, "stdin", _Stdin())

    class _FakeIntPrompt:
        @staticmethod
        def ask(prompt, choices=None, default=None, show_default=True):
            return 0

    monkeypatch.setattr(rich_prompt, "IntPrompt", _FakeIntPrompt)
    assert main_mod._interactive_session_picker() is None


def test_startup_picker_skipped_when_not_tty(monkeypatch):
    import xenon.main as main_mod
    import xenon.repl.session as session_mod

    called = []
    monkeypatch.setattr(session_mod, "list_sessions", lambda: called.append(1) or [])

    class _Stdin:
        def isatty(self):
            return False

    monkeypatch.setattr(main_mod.sys, "stdin", _Stdin())
    assert main_mod._interactive_session_picker() is None
    assert called == []  # 非 TTY 连会话列表都不读


def test_startup_picker_env_kill_switch(monkeypatch):
    import xenon.main as main_mod

    monkeypatch.setenv("XENON_NO_SESSION_PICKER", "1")

    class _Stdin:
        def isatty(self):
            return True

    monkeypatch.setattr(main_mod.sys, "stdin", _Stdin())
    assert main_mod._interactive_session_picker() is None
