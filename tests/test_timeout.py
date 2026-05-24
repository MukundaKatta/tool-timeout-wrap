"""Tests for tool_timeout_wrap."""

from __future__ import annotations

import asyncio
import time

import pytest

from tool_timeout_wrap import ToolTimeoutError, ToolTimeoutWrapper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAST_SLEEP = 0.01   # well within any timeout
SLOW_SLEEP = 2.0    # exceeds all timeouts used in tests
TIGHT_TIMEOUT = 0.15  # budget: slow fn will blow past this


def fast_fn(x: int, y: int = 0) -> int:
    """Returns x + y after a short sleep."""
    time.sleep(FAST_SLEEP)
    return x + y


def slow_fn() -> str:
    time.sleep(SLOW_SLEEP)
    return "done"


async def fast_async_fn(value: str) -> str:
    await asyncio.sleep(FAST_SLEEP)
    return value


async def slow_async_fn() -> str:
    await asyncio.sleep(SLOW_SLEEP)
    return "done"


# ---------------------------------------------------------------------------
# ToolTimeoutError
# ---------------------------------------------------------------------------


def test_error_attributes() -> None:
    err = ToolTimeoutError("my_tool", 5.0)
    assert err.tool_name == "my_tool"
    assert err.timeout_seconds == 5.0


def test_error_message() -> None:
    err = ToolTimeoutError("search", 2.5)
    assert "search" in str(err)
    assert "2.5" in str(err)


# ---------------------------------------------------------------------------
# timeout_for / registered
# ---------------------------------------------------------------------------


def test_timeout_for_default() -> None:
    w = ToolTimeoutWrapper(default_timeout=15.0)
    assert w.timeout_for("unknown_tool") == 15.0


def test_timeout_for_registered() -> None:
    w = ToolTimeoutWrapper(default_timeout=15.0)
    w.register("special", 3.0)
    assert w.timeout_for("special") == 3.0


def test_timeout_for_unregistered_uses_default() -> None:
    w = ToolTimeoutWrapper(default_timeout=7.0)
    w.register("other", 2.0)
    assert w.timeout_for("unrelated") == 7.0


def test_registered_returns_copy() -> None:
    w = ToolTimeoutWrapper()
    w.register("a", 1.0)
    w.register("b", 2.0)
    copy = w.registered()
    assert copy == {"a": 1.0, "b": 2.0}
    # mutating copy does not affect wrapper
    copy["c"] = 9.0
    assert "c" not in w.registered()


def test_multiple_tools_registered_independently() -> None:
    w = ToolTimeoutWrapper(default_timeout=30.0)
    w.register("alpha", 1.0)
    w.register("beta", 5.0)
    assert w.timeout_for("alpha") == 1.0
    assert w.timeout_for("beta") == 5.0
    assert w.timeout_for("gamma") == 30.0


# ---------------------------------------------------------------------------
# wrap() - sync
# ---------------------------------------------------------------------------


def test_wrap_fast_fn_completes() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    wrapped = w.wrap("fast_tool", fast_fn)
    result = wrapped(3, y=4)
    assert result == 7


def test_wrap_return_value_preserved() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    wrapped = w.wrap("fast_tool", fast_fn)
    assert wrapped(10) == 10


def test_wrap_args_kwargs_passed_through() -> None:
    captured: dict = {}

    def recorder(a: int, b: str = "x") -> tuple[int, str]:
        captured["a"] = a
        captured["b"] = b
        return a, b

    w = ToolTimeoutWrapper(default_timeout=1.0)
    wrapped = w.wrap("recorder", recorder)
    result = wrapped(42, b="hello")
    assert result == (42, "hello")
    assert captured == {"a": 42, "b": "hello"}


def test_wrap_slow_fn_raises_timeout_error() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    wrapped = w.wrap("slow_tool", slow_fn)
    with pytest.raises(ToolTimeoutError) as exc_info:
        wrapped()
    assert exc_info.value.tool_name == "slow_tool"
    assert exc_info.value.timeout_seconds == TIGHT_TIMEOUT


def test_wrap_zero_timeout_calls_directly_no_enforcement() -> None:
    w = ToolTimeoutWrapper(default_timeout=0)
    calls: list[int] = []

    def fn() -> int:
        calls.append(1)
        return 99

    wrapped = w.wrap("no_limit", fn)
    result = wrapped()
    assert result == 99
    assert calls == [1]


def test_wrap_per_tool_zero_disables_enforcement() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    w.register("no_limit_tool", 0)
    calls: list[int] = []

    def fn() -> int:
        calls.append(1)
        return 55

    wrapped = w.wrap("no_limit_tool", fn)
    assert wrapped() == 55
    assert len(calls) == 1


def test_wrap_per_tool_override_used_not_default() -> None:
    w = ToolTimeoutWrapper(default_timeout=30.0)
    w.register("tight_tool", TIGHT_TIMEOUT)
    wrapped = w.wrap("tight_tool", slow_fn)
    with pytest.raises(ToolTimeoutError) as exc_info:
        wrapped()
    assert exc_info.value.timeout_seconds == TIGHT_TIMEOUT


# ---------------------------------------------------------------------------
# timed() decorator
# ---------------------------------------------------------------------------


def test_timed_decorator_wraps_sync_fn() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)

    @w.timed("add_tool")
    def add(x: int, y: int) -> int:
        return x + y

    assert add(2, 3) == 5


def test_timed_decorator_raises_on_slow() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)

    @w.timed("slow_deco")
    def slow() -> str:
        time.sleep(SLOW_SLEEP)
        return "never"

    with pytest.raises(ToolTimeoutError) as exc_info:
        slow()
    assert exc_info.value.tool_name == "slow_deco"


# ---------------------------------------------------------------------------
# wrap_async() - async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_async_fast_completes() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    wrapped = w.wrap_async("fast_async", fast_async_fn)
    result = await wrapped("hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_wrap_async_slow_raises_timeout() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    wrapped = w.wrap_async("slow_async", slow_async_fn)
    with pytest.raises(ToolTimeoutError) as exc_info:
        await wrapped()
    assert exc_info.value.tool_name == "slow_async"
    assert exc_info.value.timeout_seconds == TIGHT_TIMEOUT


@pytest.mark.asyncio
async def test_wrap_async_zero_timeout_calls_directly() -> None:
    w = ToolTimeoutWrapper(default_timeout=0)
    calls: list[int] = []

    async def fn() -> int:
        calls.append(1)
        return 77

    wrapped = w.wrap_async("no_limit_async", fn)
    assert await wrapped() == 77
    assert calls == [1]


# ---------------------------------------------------------------------------
# timed_async() decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timed_async_decorator_wraps_async_fn() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)

    @w.timed_async("echo_tool")
    async def echo(msg: str) -> str:
        await asyncio.sleep(FAST_SLEEP)
        return msg

    assert await echo("world") == "world"


@pytest.mark.asyncio
async def test_timed_async_decorator_raises_on_slow() -> None:
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)

    @w.timed_async("slow_async_deco")
    async def slow() -> str:
        await asyncio.sleep(SLOW_SLEEP)
        return "never"

    with pytest.raises(ToolTimeoutError) as exc_info:
        await slow()
    assert exc_info.value.tool_name == "slow_async_deco"


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------


def test_wrap_default_timeout_applies_to_unregistered_tool() -> None:
    """default_timeout is the fallback when the tool has no registered override."""
    w = ToolTimeoutWrapper(default_timeout=TIGHT_TIMEOUT)
    # "unregistered_tool" has no entry in overrides
    wrapped = w.wrap("unregistered_tool", slow_fn)
    with pytest.raises(ToolTimeoutError) as exc_info:
        wrapped()
    # timeout reported equals the default
    assert exc_info.value.timeout_seconds == TIGHT_TIMEOUT


def test_register_overwrite_updates_timeout() -> None:
    """Calling register() twice on the same tool name uses the latest value."""
    w = ToolTimeoutWrapper(default_timeout=30.0)
    w.register("tool_a", 5.0)
    w.register("tool_a", 1.0)
    assert w.timeout_for("tool_a") == 1.0


def test_wrap_exception_from_fn_propagates() -> None:
    """Exceptions raised inside fn (not timeout) propagate unchanged."""
    w = ToolTimeoutWrapper(default_timeout=5.0)

    def boom() -> None:
        raise ValueError("inner error")

    wrapped = w.wrap("boom_tool", boom)
    with pytest.raises(ValueError, match="inner error"):
        wrapped()


def test_wrap_timeout_error_is_exception_subclass() -> None:
    err = ToolTimeoutError("t", 1.0)
    assert isinstance(err, Exception)


@pytest.mark.asyncio
async def test_wrap_async_exception_from_fn_propagates() -> None:
    """Exceptions from async fn (not timeout) propagate unchanged."""
    w = ToolTimeoutWrapper(default_timeout=5.0)

    async def async_boom() -> None:
        raise RuntimeError("async inner error")

    wrapped = w.wrap_async("async_boom_tool", async_boom)
    with pytest.raises(RuntimeError, match="async inner error"):
        await wrapped()


def test_wrapper_default_timeout_zero_no_enforcement() -> None:
    """With default_timeout=0, sync wrap calls fn directly for unregistered tools."""
    w = ToolTimeoutWrapper(default_timeout=0)
    calls: list[int] = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    wrapped = w.wrap("any_tool", fn)
    assert wrapped(5) == 10
    assert calls == [5]
