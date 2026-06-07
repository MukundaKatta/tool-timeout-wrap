# tool-timeout-wrap

[![PyPI](https://img.shields.io/pypi/v/tool-timeout-wrap.svg)](https://pypi.org/project/tool-timeout-wrap/)
[![Python](https://img.shields.io/pypi/pyversions/tool-timeout-wrap.svg)](https://pypi.org/project/tool-timeout-wrap/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Wrap sync and async tool functions with per-tool timeouts.**

Agent and LLM tool calls can hang: a flaky HTTP request, a runaway loop, a
slow subprocess. This library puts a wall-clock deadline on every tool call
and raises `ToolTimeoutError` when a tool exceeds its budget — without
requiring cooperative `check()` calls inside the function body.

Zero runtime dependencies (stdlib only: `threading`, `asyncio`,
`concurrent.futures`).

## Install

```bash
pip install tool-timeout-wrap
```

## Use

```python
from tool_timeout_wrap import ToolTimeoutWrapper, ToolTimeoutError

wrapper = ToolTimeoutWrapper(default_timeout=10.0)
wrapper.register("slow_search", timeout_seconds=3.0)


@wrapper.timed("slow_search")
def slow_search(query: str) -> list[str]:
    ...  # raises ToolTimeoutError if it takes more than 3s


@wrapper.timed_async("fetch_url")
async def fetch_url(url: str) -> str:
    ...  # raises ToolTimeoutError if it takes more than 10s (the default)
```

Catch the timeout where you dispatch tools:

```python
try:
    results = slow_search("python timeouts")
except ToolTimeoutError as e:
    print(f"{e.tool_name} exceeded {e.timeout_seconds}s")
```

You can also wrap an existing function without a decorator:

```python
def search(query: str) -> list[str]:
    ...

wrapped_search = wrapper.wrap("slow_search", search)
wrapped_fetch = wrapper.wrap_async("fetch_url", fetch_url)
```

## Timeout resolution

Each tool's budget is the registered per-tool override when present,
otherwise `default_timeout`:

```python
wrapper = ToolTimeoutWrapper(default_timeout=30.0)
wrapper.register("alpha", 1.0)

wrapper.timeout_for("alpha")    # 1.0  (override)
wrapper.timeout_for("beta")     # 30.0 (default)
wrapper.registered()            # {"alpha": 1.0}
```

Overrides are resolved at call time, so calling `register()` after a function
is wrapped still takes effect.

Setting a timeout to `0` disables enforcement for that tool — the function is
called directly with no overhead:

```python
wrapper.register("trusted_tool", 0)         # no timeout for this tool
no_limit = ToolTimeoutWrapper(default_timeout=0)  # no timeout anywhere
```

## How it works

- **Sync** (`wrap`, `timed`): runs the function in a
  `concurrent.futures.ThreadPoolExecutor` worker and blocks the calling thread
  for at most `timeout_seconds`. The calling thread is freed on expiry even if
  the function body never yields.
- **Async** (`wrap_async`, `timed_async`): uses `asyncio.wait_for`, which
  cancels the coroutine when the budget is exceeded.

In both cases an exception raised inside the wrapped function (other than the
timeout) propagates unchanged.

## What it does NOT do

- **It cannot kill a runaway sync function.** A timed-out sync call frees the
  *calling* thread, but the worker thread keeps running until the function
  returns — Python has no safe way to forcibly terminate a thread. Use this to
  bound how long a caller waits, not to reclaim CPU from a hot loop.
- **No retries, no backoff.** It raises `ToolTimeoutError`; retry policy is
  yours.
- **No HTTP / provider logic.** It wraps any callable; it does not talk to any
  LLM provider.

## License

MIT
