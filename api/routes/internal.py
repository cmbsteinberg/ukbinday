from __future__ import annotations

import hmac
import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api import config
from api.services.refresh_job import RefreshJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")


async def require_cron_secret(request: Request) -> None:
    """Bearer CRON_SECRET, which Vercel sends on cron invocations. Refuses outright
    when no secret is configured, so the route is never open."""
    if not config.CRON_SECRET:
        raise HTTPException(status_code=403, detail="Refresh endpoint is not enabled")
    expected = f"Bearer {config.CRON_SECRET}"
    given = request.headers.get("Authorization", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get(
    "/refresh",
    include_in_schema=False,
    dependencies=[Depends(require_cron_secret)],
)
async def refresh(
    request: Request,
    shard: int = Query(0, ge=0),
    of: int = Query(1, ge=1),
):
    """One cron-triggered refresh pass over shard `shard` of `of`."""
    if shard >= of:
        raise HTTPException(status_code=422, detail="shard must be less than of")
    state = request.app.state
    job = RefreshJob(
        state.ics_cache,
        state.registry,
        state.redis,
        concurrency=config.ICS_REFRESH_CONCURRENCY,
        failure_threshold=config.ICS_FAILURE_THRESHOLD,
    )
    stats = await job.run_once(
        shard=shard, of=of, deadline=time.monotonic() + config.REFRESH_DEADLINE_S
    )
    return asdict(stats)
