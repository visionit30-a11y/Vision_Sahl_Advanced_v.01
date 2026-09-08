"""Test-only real-server fixture; never imported by the product router."""

from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.exc import DBAPIError

from app.core.logging import get_logger
from app.main import create_app

app = create_app()


@app.post("/auth/_redaction_probe/{selector}")
async def force_failure(request: Request, selector: str) -> None:
    payload = await request.json()
    try:
        raise ValueError(selector)
    except ValueError:
        get_logger().exception(selector, request_body=payload, nested={selector: payload})
        logging.getLogger("app.probe").error("body=%r", payload, exc_info=True)
    raise DBAPIError("SELECT " + selector, payload, RuntimeError(selector), False)
