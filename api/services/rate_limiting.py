from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from api.config import RATE_LIMIT_HOURLY

logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _seconds_until_next_hour() -> int:
    now = datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return int((next_hour - now).total_seconds())


async def rate_limit(request: Request) -> None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return

    ip = _get_client_ip(request)
    now = datetime.now()
    key = f"ratelimit:{ip}:{now.strftime('%Y%m%d%H')}"

    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 3600)

        request.state.rate_limit_remaining = max(0, RATE_LIMIT_HOURLY - count)

        if count > RATE_LIMIT_HOURLY:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again in a few minutes.",
                headers={
                    "Retry-After": str(_seconds_until_next_hour()),
                    "X-RateLimit-Limit": str(RATE_LIMIT_HOURLY),
                    "X-RateLimit-Remaining": "0",
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("Redis rate limiting failed, skipping", exc_info=True)
