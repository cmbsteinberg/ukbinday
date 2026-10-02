from datetime import date, datetime

from pydantic import BaseModel


class CollectionItem(BaseModel):
    date: date
    type: str
    icon: str | None = None


class DeeplinkInfo(BaseModel):
    url: str
    reason: str
    council_name: str


class LookupResponse(BaseModel):
    uprn: str
    council: str
    cached: bool = False
    cached_at: datetime | None = None
    collections: list[CollectionItem] = []
    deeplink: DeeplinkInfo | None = None


class AddressResult(BaseModel):
    uprn: str
    full_address: str
    postcode: str
    address_line_1: str | None = None
    house_number_or_name: str | None = None
    street: str | None = None


class AddressLookupResponse(BaseModel):
    postcode: str
    addresses: list[AddressResult]


class CouncilInfo(BaseModel):
    id: str
    name: str
    url: str
    params: list[str]


class CouncilCandidate(BaseModel):
    slug: str
    name: str
    homepage_url: str


class CouncilLookupResponse(BaseModel):
    postcode: str
    council_id: str | None = None
    council_name: str | None = None
    candidates: list[CouncilCandidate] = []
    deeplink: DeeplinkInfo | None = None


# --- v2: shaped after the LocalGov Drupal waste collection provider contract ---


class CollectionTypeV2(BaseModel):
    label: str  # the council's own bin name
    colour: str | None = None  # read off the label, when it names one
    icon: str | None = None


class CollectionDateV2(BaseModel):
    date: date  # ISO (Drupal uses d-m-Y)
    holiday: str | None = None  # the bank holiday falling on this date, if any
    type: CollectionTypeV2


class ScheduleResponseV2(BaseModel):
    uprn: str
    council: str
    cached: bool = False
    cached_at: datetime | None = None
    dates: list[CollectionDateV2] = []  # ascending
    deeplink: DeeplinkInfo | None = None


class FindResponseV2(BaseModel):
    council: str
    postcode: str
    addresses: list[AddressResult]


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
