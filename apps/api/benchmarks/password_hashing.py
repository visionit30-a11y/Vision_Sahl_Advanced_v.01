"""Repeatable local benchmark for the candidate G3 Argon2id profile."""

from __future__ import annotations

import asyncio
import json
import secrets
import statistics
import time

from app.security.passwords import PasswordService

SAMPLES = 7
HASH_P95_LIMIT_SECONDS = 1.5
VERIFY_P95_LIMIT_SECONDS = 1.5
TWO_CONCURRENT_LIMIT_SECONDS = 3.0


async def timed(operation) -> tuple[object, float]:
    started = time.perf_counter()
    result = await operation
    return result, time.perf_counter() - started


async def main() -> None:
    service = PasswordService(max_concurrency=2)
    password = secrets.token_urlsafe(24)
    await service.hash_password(password)  # warm native code and worker thread
    hash_times: list[float] = []
    verify_times: list[float] = []
    for _ in range(SAMPLES):
        password_hash, duration = await timed(service.hash_password(password))
        hash_times.append(duration)
        verified, duration = await timed(service.verify_password(str(password_hash), password))
        assert verified is True
        verify_times.append(duration)
    started = time.perf_counter()
    await asyncio.gather(service.hash_password(password), service.hash_password(password))
    concurrent_seconds = time.perf_counter() - started
    result = {
        "profile": {
            "type": "argon2id",
            "memory_kib": 65536,
            "time_cost": 3,
            "parallelism": 4,
            "salt_bytes": 16,
            "hash_bytes": 32,
        },
        "samples": SAMPLES,
        "hash_median_ms": round(statistics.median(hash_times) * 1000, 2),
        "hash_max_ms": round(max(hash_times) * 1000, 2),
        "verify_median_ms": round(statistics.median(verify_times) * 1000, 2),
        "verify_max_ms": round(max(verify_times) * 1000, 2),
        "two_concurrent_hashes_ms": round(concurrent_seconds * 1000, 2),
        "accepted": max(hash_times) <= HASH_P95_LIMIT_SECONDS
        and max(verify_times) <= VERIFY_P95_LIMIT_SECONDS
        and concurrent_seconds <= TWO_CONCURRENT_LIMIT_SECONDS,
    }
    print(json.dumps(result, sort_keys=True))
    if not result["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
