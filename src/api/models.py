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


class CouncilInfo(BaseModel):
    id: str
    name: str
    url: str
    params: list[str]


class AddressItem(BaseModel):
    uprn: str
    full_address: str
    postcode: str


class AddressLookupResponse(BaseModel):
    postcode: str
    council_id: str | None = None
    council_name: str | None = None
    addresses: list[AddressItem]


class HealthEntry(BaseModel):
    id: str
    name: str
    status: str  # "ok", "error", "unknown"
    last_success: datetime | None = None
    last_error: str | None = None
    error_count: int = 0
