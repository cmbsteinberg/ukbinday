from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

DAILY_LIMIT = 100


def _get_client_ip(request: Request) -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _seconds_until_midnight() -> int:
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight.replace(day=now.day + 1) if now.hour >= 0 else midnight
    from datetime import timedelta

    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    return int((tomorrow - now).total_seconds())


async def rate_limit(request: Request) -> None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return

    ip = _get_client_ip(request)
    key = f"ratelimit:{ip}:{date.today().isoformat()}"

    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 86400)

        request.state.rate_limit_remaining = max(0, DAILY_LIMIT - count)

        if count > DAILY_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again tomorrow.",
                headers={
                    "Retry-After": str(_seconds_until_midnight()),
                    "X-RateLimit-Limit": str(DAILY_LIMIT),
                    "X-RateLimit-Remaining": "0",
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("Redis rate limiting failed, skipping", exc_info=True)
