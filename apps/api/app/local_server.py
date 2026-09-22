"""Development-only Uvicorn entry point with a Psycopg-compatible Windows loop."""

from __future__ import annotations

import asyncio
import platform
import selectors

import uvicorn

from app.core.config import get_settings


def main() -> None:
    """Serve the local API without changing production event-loop configuration."""
    if get_settings().app_env != "development":
        raise RuntimeError("The local server is restricted to APP_ENV=development.")

    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app",
            host="127.0.0.1",
            port=8010,
            access_log=False,
            log_level="info",
        )
    )
    if platform.system() == "Windows":
        with asyncio.Runner(
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        ) as runner:
            runner.run(server.serve())
        return
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
