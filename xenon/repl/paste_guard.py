"""Windows prompt_toolkit 括号粘贴（bracketed-paste）看门狗。

背景
----
在 Windows 上，prompt_toolkit 的 ``Win32Input`` 在支持
``ENABLE_VIRTUAL_TERMINAL_INPUT`` 时使用 ``Vt100ConsoleInputReader``：
粘贴时控制台发送 ``ESC[200~``（开始）与 ``ESC[201~``（结束）。
``Vt100Parser`` 一旦收到开始标记就进入 ``_in_bracketed_paste=True``，
把之后的**所有**字节（含空格、字母，甚至 Ctrl+C）都累积进粘贴缓冲区，
直到看见结束标记——并且该状态机**没有超时**，解析器又随 ``Win32Input``
长期缓存、``reset()`` 除构造外从不被调用。

因此，一旦结束标记因控制台/注入时序被切碎或丢失（经典 conhost 下粘贴后
尤其容易出现），输入会被永久“吞掉”，表现为：本轮或下一轮怎么打字屏幕
都没有反应，连 Ctrl+C 也无法中断。这与本项目在 Unix 自建输入处理器中
修复过的“paste end 丢失 → paste_mode 死锁”是同一类问题，只是 Windows
的 prompt_toolkit 路径此前没有任何防护。

本模块提供两层、且全部为防御式（任何异常都静默降级，绝不影响正常输入）：

1. :func:`reset_stuck_paste`：每次进入输入前调用，若解析器卡在粘贴状态
   则立即复位——保证“上一轮粘贴后，下一轮一定能输入”。
2. :func:`arm_paste_watchdog`：在应用自身的事件循环线程上跑一个空闲超时
   看门狗，粘贴期间若连续 ``idle_timeout`` 没有任何新字节，自动结束粘贴，
   从而在同一轮也能自愈，并让 Ctrl+C 重新生效。
"""

from __future__ import annotations

import functools
import logging
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

# 粘贴期间连续多久没有新字节即判定结束标记丢失。
# 本地剪贴板注入是连续且极快的，正常粘贴不会出现 0.5s 的空档。
PASTE_IDLE_TIMEOUT_S = 0.5
# 看门狗轮询间隔。
WATCHDOG_POLL_S = 0.1

_LAST_ATTR = "_xenon_last_feed_at"
_WRAPPED_ATTR = "_xenon_feed_wrapped"


def _session_app(session: Any) -> Any:
    return getattr(session, "app", None)


def find_vt_parser(session: Any) -> Any:
    """返回会话长期持有的 Win32 VT 解析器；不可用时返回 ``None``。"""
    try:
        app = _session_app(session)
        inp = getattr(app, "input", None)
        reader = getattr(inp, "console_input_reader", None)
        return getattr(reader, "_vt100_parser", None)
    except Exception:
        return None


def _console_reader(session: Any) -> Any:
    """Return the Win32 reader that owns the parser and pending key buffer."""
    try:
        app = _session_app(session)
        inp = getattr(app, "input", None)
        return getattr(inp, "console_input_reader", None)
    except Exception:
        return None


def _install_feed_timestamp(parser: Any) -> bool:
    """在解析器的 ``feed`` 上记录“最近一次收到字节”的时间（幂等）。"""
    try:
        if getattr(parser, _WRAPPED_ATTR, False):
            return True

        original_feed = parser.feed

        @functools.wraps(original_feed)
        def _wrapped(data: str, *args: Any, **kwargs: Any) -> Any:
            setattr(parser, _LAST_ATTR, monotonic())
            return original_feed(data, *args, **kwargs)

        parser.feed = _wrapped
        setattr(parser, _LAST_ATTR, monotonic())
        setattr(parser, _WRAPPED_ATTR, True)
        return True
    except Exception:
        logger.debug("粘贴 feed 时间戳安装失败", exc_info=True)
        return False


def reset_stuck_paste(session: Any) -> bool:
    """若解析器卡在括号粘贴状态则复位；返回是否执行了复位。"""
    try:
        parser = find_vt_parser(session)
        if parser is None:
            return False
        if getattr(parser, "_in_bracketed_paste", False):
            parser.reset()
            reader = _console_reader(session)
            pending = getattr(reader, "_buffer", None)
            if isinstance(pending, list):
                pending.clear()
            logger.warning("检测到粘贴状态卡死（结束标记丢失），已自动恢复输入。")
            return True
        return False
    except Exception:
        logger.debug("reset_stuck_paste 失败", exc_info=True)
        return False


def arm_paste_watchdog(
    session: Any,
    *,
    idle_timeout: float = PASTE_IDLE_TIMEOUT_S,
    poll: float = WATCHDOG_POLL_S,
) -> bool:
    """注册一个 ``pre_run`` 回调，在输入期间启动粘贴空闲看门狗。

    prompt_toolkit 在每次运行开始时处理并清空 ``pre_run_callables``，因此需要
    在每轮输入前重新调用本函数。看门狗通过 ``create_background_task`` 运行在
    应用自己的事件循环线程上，与 ``read_keys``/``feed`` 同线程、协作式调度，
    故调用 ``parser.reset()`` 不存在跨线程竞争；应用退出时该任务也会被取消。
    """
    try:
        app = _session_app(session)
        parser = find_vt_parser(session)
        if app is None or parser is None:
            return False
        if not _install_feed_timestamp(parser):
            return False

        def _pre_run() -> None:
            try:
                application = _session_app(session)

                async def _watchdog() -> None:
                    from asyncio import sleep

                    while not getattr(application, "is_done", True):
                        await sleep(poll)
                        try:
                            if getattr(parser, "_in_bracketed_paste", False):
                                last = getattr(parser, _LAST_ATTR, None)
                                if (
                                    last is not None
                                    and monotonic() - last > idle_timeout
                                ):
                                    parser.reset()
                                    reader = _console_reader(session)
                                    pending = getattr(reader, "_buffer", None)
                                    if isinstance(pending, list):
                                        pending.clear()
                                    logger.warning(
                                        "粘贴已空闲 %.2fs 仍未收到结束标记，"
                                        "已自动结束粘贴并恢复输入。",
                                        idle_timeout,
                                    )
                        except Exception:
                            return

                application.create_background_task(_watchdog())
            except Exception:
                logger.debug("粘贴看门狗启动失败", exc_info=True)

        app.pre_run_callables.append(_pre_run)
        return True
    except Exception:
        logger.debug("arm_paste_watchdog 失败", exc_info=True)
        return False
