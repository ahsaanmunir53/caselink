"""Event-loop helpers.

The async Postgres driver (psycopg) cannot run on Windows' default ProactorEventLoop, so
anything we start ourselves on Windows uses a SelectorEventLoop instead.
"""

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


def postgres_loop_problem() -> str | None:
    """Return an explanation if the running loop cannot be used with async psycopg."""
    if sys.platform != "win32":
        return None
    loop = asyncio.get_running_loop()
    if isinstance(loop, getattr(asyncio, "ProactorEventLoop", ())):
        return (
            "On Windows the Postgres driver needs a selector event loop. Start the API with "
            "`python run.py` or `uvicorn app.main:app --reload` (both use one), or leave DATABASE_URL "
            "empty to use SQLite locally."
        )
    return None
