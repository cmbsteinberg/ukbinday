from datetime import date, datetime

from pydantic import BaseModel


class CollectionItem(BaseModel):
    date: date
    type: str
    icon: str | None = None


class LookupResponse(BaseModel):
    uprn: str
    council: str
    cached: bool = False
    cached_at: datetime | None = None
    collections: list[CollectionItem]


class AddressResult(BaseModel):
    uprn: str
    full_address: str
    postcode: str


class AddressLookupResponse(BaseModel):
    postcode: str
    addresses: list[AddressResult]


class CouncilInfo(BaseModel):
    id: str
    name: str
    url: str
    params: list[str]


class CouncilLookupResponse(BaseModel):
    postcode: str
    council_id: str | None = None
    council_name: str | None = None


class HealthEntry(BaseModel):
    id: str
    name: str
    status: str  # "ok", "error", "unknown"
    last_success: datetime | None = None
    last_error: str | None = None
    error_count: int = 0


class SystemHealth(BaseModel):
    status: str  # "healthy", "degraded", "unhealthy"
    scraper_count: int
    postcode_lookup: bool
    lad_lookup: bool
    redis_connected: bool
    rate_limiting_active: bool
