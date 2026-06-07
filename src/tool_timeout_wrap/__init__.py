"""tool-timeout-wrap - wrap sync and async tool functions with per-tool timeouts.

Automatically enforces a wall-clock deadline on every tool call without
requiring cooperative check() calls inside the function body. Different tools
can have different budgets; a default_timeout covers any unregistered tool.

    from tool_timeout_wrap import ToolTimeoutWrapper, ToolTimeoutError

    wrapper = ToolTimeoutWrapper(default_timeout=10.0)
    wrapper.register("slow_search", timeout_seconds=3.0)

    @wrapper.timed("slow_search")
    def slow_search(query: str) -> list[str]:
        ...  # raises ToolTimeoutError if it takes more than 3s

    @wrapper.timed_async("fetch_url")
    async def fetch_url(url: str) -> str:
        ...  # raises ToolTimeoutError if it takes more than 10s (default)

Sync enforcement uses concurrent.futures.ThreadPoolExecutor so the calling
thread is blocked for at most `timeout_seconds` regardless of what the wrapped
function does.

Async enforcement uses asyncio.wait_for, which cancels the coroutine on
expiry.

Setting timeout_seconds=0 (or default_timeout=0) disables enforcement for
that tool - the function is called directly with no overhead.

Zero runtime dependencies (stdlib only: threading, asyncio, concurrent.futures).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
from collections.abc import Callable
from typing import Any


class ToolTimeoutError(Exception):
    """Raised when a tool call exceeds its configured timeout budget."""

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds}s")


class ToolTimeoutWrapper:
    """Registry that wraps tool functions with automatic timeout enforcement.

    Args:
        default_timeout: Fallback timeout in seconds for tools that have not
            been explicitly registered. 0 means no enforcement.
    """

    def __init__(self, default_timeout: float = 30.0) -> None:
        self._default_timeout = default_timeout
        # tool_name -> override timeout (0 = disabled for that tool)
        self._overrides: dict[str, float] = {}

    def register(self, tool_name: str, timeout_seconds: float) -> None:
        """Set a per-tool timeout override.

        Args:
            tool_name: Logical name of the tool.
            timeout_seconds: Wall-clock budget in seconds. 0 disables
                enforcement for this tool regardless of default_timeout.
        """
        self._overrides[tool_name] = timeout_seconds

    def timeout_for(self, tool_name: str) -> float:
        """Return the effective timeout for *tool_name*.

        Returns the registered per-tool override when present, otherwise
        returns default_timeout.
        """
        return self._overrides.get(tool_name, self._default_timeout)

    def registered(self) -> dict[str, float]:
        """Return a copy of the per-tool override mapping."""
        return dict(self._overrides)

    # ------------------------------------------------------------------
    # Sync wrapping
    # ------------------------------------------------------------------

    def wrap(self, tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Return a new sync callable that enforces the timeout for *tool_name*.

        Uses concurrent.futures.ThreadPoolExecutor to run *fn* in a worker
        thread and blocks the calling thread for at most *timeout_seconds*.

        The timeout is resolved at call time, so registering or updating a
        per-tool override after wrapping still takes effect.

        If timeout_seconds is 0, *fn* is called directly with no enforcement.

        Raises:
            ToolTimeoutError: when *fn* does not return within the budget.
        """

        @functools.wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            timeout = self.timeout_for(tool_name)
            if not timeout:
                return fn(*args, **kwargs)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(fn, *args, **kwargs)
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError as exc:
                    raise ToolTimeoutError(tool_name, timeout) from exc

        return _wrapped

    def timed(self, tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that wraps a sync function with timeout enforcement.

        Usage::

            @wrapper.timed("search_web")
            def search_web(query: str) -> list[str]:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            return self.wrap(tool_name, fn)

        return decorator

    # ------------------------------------------------------------------
    # Async wrapping
    # ------------------------------------------------------------------

    def wrap_async(self, tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Return a new async callable that enforces the timeout for *tool_name*.

        Uses asyncio.wait_for to cancel the coroutine on expiry.

        The timeout is resolved at call time, so registering or updating a
        per-tool override after wrapping still takes effect.

        If timeout_seconds is 0, *fn* is awaited directly with no enforcement.

        Raises:
            ToolTimeoutError: when *fn* does not complete within the budget.
        """

        @functools.wraps(fn)
        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            timeout = self.timeout_for(tool_name)
            if not timeout:
                return await fn(*args, **kwargs)
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise ToolTimeoutError(tool_name, timeout) from exc

        return _wrapped

    def timed_async(self, tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that wraps an async function with timeout enforcement.

        Usage::

            @wrapper.timed_async("fetch_url")
            async def fetch_url(url: str) -> str:
                ...
        """

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            return self.wrap_async(tool_name, fn)

        return decorator


__version__ = "0.1.0"

__all__ = [
    "ToolTimeoutError",
    "ToolTimeoutWrapper",
    "__version__",
]
