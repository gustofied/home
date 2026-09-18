import re
from decimal import Decimal

from .models import Candidate, FacilityRecord, SourceSnapshot

NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"


def normalize_metric(field: str, raw: str | None) -> int | float | None:
    if raw is None or raw.strip().lower() in {"", "tbd", "n/a", "unknown", "—", "-"}:
        return None
    text = " ".join(raw.split())
    if field == "critical_it_mw":
        match = re.fullmatch(rf"({NUMBER})\s*(MW|kW|GW)", text, re.I)
        if not match:
            raise ValueError(f"Unrecognized power value/unit: {raw!r}")
        return float(
            Decimal(match[1].replace(",", ""))
            * {"mw": Decimal(1), "kw": Decimal("0.001"), "gw": Decimal(1000)}[
                match[2].lower()
            ]
        )
    suffix = (
        r"\s*(?:sq\.?\s*ft\.?|square feet|sqft)?" if field == "it_area_sqft" else ""
    )
    match = re.fullmatch(rf"({NUMBER})\s*([MK])?{suffix}", text, re.I)
    if not match:
        raise ValueError(f"Unrecognized {field} value: {raw!r}")
    value = (
        Decimal(match[1].replace(",", ""))
        * {None: 1, "M": 1_000_000, "K": 1000}[(match[2] or "").upper() or None]
    )
    if value != value.to_integral_value():
        raise ValueError(f"Non-integral {field}: {raw!r}")
    return int(value)


def normalize_observations(observations: list[dict]) -> None:
    for observation in observations:
        if not observation["field"]:
            continue
        try:
            observation["value"] = normalize_metric(
                observation["field"], observation["raw_value"]
            )
        except ValueError as exc:
            observation["value"] = None
            observation["error"] = str(exc)


def build_record(
    candidate: Candidate, name: str, metrics: dict[str, str], snapshot: SourceSnapshot
) -> FacilityRecord:
    if candidate.record_level != "facility":
        raise ValueError("Campus aggregate excluded from facility dataset")
    values = {
        field: normalize_metric(field, metrics.get(field))
        for field in ("it_area_sqft", "critical_it_mw", "onsite_carriers")
    }
    return FacilityRecord(
        facility_code=candidate.code,
        facility_name=name or candidate.name,
        market=candidate.market,
        campus_name=candidate.campus_name,
        address_raw=candidate.address,
        detail_url=candidate.url,
        market_url=candidate.market_url,
        fetched_at=snapshot.fetched_at,
        **values,
    )
