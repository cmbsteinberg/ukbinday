from datetime import date, datetime

from pydantic import BaseModel, Field


class DeeplinkInfo(BaseModel):
    url: str
    reason: str
    council_name: str
    blocker: str = Field(
        description="Why there are no bin days: captcha, login, bot_protection, browser_only, "
        "no_lookup, site_down or not_supported."
    )
    blocker_label: str = Field(description="`blocker` in words, e.g. \"Requires a captcha\".")


class AddressResult(BaseModel):
    uprn: str
    full_address: str
    postcode: str
    address_line_1: str | None = None
    house_number_or_name: str | None = None
    street: str | None = None


class CouncilInfo(BaseModel):
    id: str
    name: str
    url: str
    params: list[str]


class CouncilCandidate(BaseModel):
    council: str  # LAD code
    name: str
    homepage_url: str


class FindResponse(BaseModel):
    """A postcode's council and addresses.

    `council` is the LAD code when we serve the council; otherwise `deeplink`
    (unwired, or a scraper that needs a browser) or `candidates` (a postcode
    straddling councils) says what to do instead, and `addresses` is empty.
    `addresses` is None when the request had no Turnstile token.
    """

    postcode: str
    council: str | None = None
    council_name: str | None = None
    candidates: list[CouncilCandidate] = []
    deeplink: DeeplinkInfo | None = None
    addresses: list[AddressResult] | None = []


# Shaped after the LocalGov Drupal waste collection provider contract


class CollectionType(BaseModel):
    label: str  # the council's own bin name
    colour: str | None = None  # read off the label, when it names one
    icon: str | None = None


class CollectionDate(BaseModel):
    date: date  # ISO (Drupal uses d-m-Y)
    holiday: str | None = None  # the bank holiday falling on this date, if any
    type: CollectionType


class ScheduleResponse(BaseModel):
    uprn: str
    council: str
    cached: bool = False
    cached_at: datetime | None = None
    dates: list[CollectionDate] = []  # ascending
    deeplink: DeeplinkInfo | None = None


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
