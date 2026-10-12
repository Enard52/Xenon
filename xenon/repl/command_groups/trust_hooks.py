"""/trust-hooks — 显式信任项目 .xenon/hooks.yaml（H-5）。

克隆仓库自带的 hooks 默认不加载（防无审批执行任意命令）；用户看过内容后
用本命令信任：记录文件指纹到 ~/.xenon/trusted_hooks.json 并立即加载。
文件内容变化后指纹不匹配，需要重新信任。
"""

from __future__ import annotations

from typing import Any

from xenon.repl.command_registry import command_handler, register_command

register_command(
    "/trust-hooks",
    "信任并启用项目 .xenon/hooks.yaml（指纹记录，防克隆仓库无审批执行）",
    "/trust-hooks",
)


@command_handler("/trust-hooks")
def _cmd_trust_hooks(*, session_state: dict, **kwargs: Any) -> str:
    repl = session_state.get("_repl")
    if repl is None:
        return "❌ /trust-hooks 需要交互会话"
    runner = getattr(repl, "_hook_runner", None)
    if runner is None:
        return "hooks 未启用（XENON_HOOKS=0）"
    if runner.trust_project_hooks():
        return (
            "✅ 已信任项目 hooks 并立即加载；"
            "指纹记录在 ~/.xenon/trusted_hooks.json。"
            "文件内容变化后需重新信任。"
        )
    return "当前工作区没有 .xenon/hooks.yaml"
