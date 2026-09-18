from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, computed_field


class HealthResponse(BaseModel):
    """Public contract returned by the health endpoint."""

    status: Literal["ok"] = "ok"


class FacilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    facility_code: Annotated[str, Field(pattern=r"^[A-Z]{2,5}\d{1,3}$")]
    facility_name: Annotated[str, Field(min_length=1)]
    market: Annotated[str, Field(min_length=1)]
    campus_name: str | None = None
    address_raw: str | None = None
    it_area_sqft: Annotated[int, Field(gt=0, strict=True)]
    critical_it_mw: Annotated[float, Field(gt=0, strict=True)]
    onsite_carriers: Annotated[int, Field(ge=0, strict=True)] | None = None
    detail_url: HttpUrl
    market_url: HttpUrl
    fetched_at: datetime

    @computed_field
    @property
    def capacity_density_w_per_sqft(self) -> float:
        return self.critical_it_mw * 1_000_000 / self.it_area_sqft


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    requested_url: str
    final_url: str
    fetched_at: datetime
    status_code: int
    headers: dict[str, str]
    elapsed_seconds: float
    content: bytes
    sha256: str
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    url: str
    market: str
    market_url: str
    code: str | None
    address: str | None
    metrics: dict[str, str]
    campus_name: str | None = None
    record_level: str = "facility"


class OverviewResponse(BaseModel):
    run_id: str
    as_of: datetime
    summary: dict[str, JsonValue]
    quality: dict[str, JsonValue]
    breakdowns: dict[str, JsonValue]
    methodology: dict[str, JsonValue]
    source: dict[str, JsonValue]


class FacilitiesResponse(BaseModel):
    run_id: str
    count: int
    facilities: list[FacilityRecord]
