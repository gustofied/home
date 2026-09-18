import re
from collections import Counter, defaultdict

from .models import FacilityRecord


def rounding_tolerance(raw: str, field: str) -> float:
    if field == "facility_count":
        return 0.0
    match = re.match(r"([\d,.]+)\s*([a-zA-Z]*)", raw)
    if not match:
        return 0.0
    places = len(match[1].split(".")[1]) if "." in match[1] else 0
    multiplier = {"kw": 0.001, "mw": 1, "gw": 1000, "m": 1_000_000, "k": 1000}.get(
        match[2].lower(), 1
    )
    return 0.5 * (10**-places) * multiplier


def assess_quality(
    records: list[FacilityRecord],
    candidates: list[dict],
    rejected: list[dict],
    observations: list[dict],
    failures: list[dict],
    scope: list[str],
    previous_count: int | None = None,
) -> dict:
    issues = []
    facilities = [
        c for c in candidates if c.get("record_level", "facility") == "facility"
    ]
    urls = Counter(c["url"] for c in facilities if c["url"])
    codes = Counter(c["code"] for c in facilities if c["code"])
    duplicates = {
        "urls": {key: n for key, n in urls.items() if n > 1},
        "codes": {key: n for key, n in codes.items() if n > 1},
    }
    grouped = defaultdict(list)
    for observation in observations:
        if observation.get("record_level") == "facility" and observation.get("field"):
            url = observation.get("facility_url", observation["source_url"])
            grouped[(url, observation["field"])].append(observation)
        if observation.get("error"):
            issues.append({"type": "unrecognized_value", **observation})
        if not observation.get("field") and observation.get("origin") in {
            "card",
            "detail_main",
        }:
            issues.append({"type": "unknown_label", **observation})
    conflicts = []
    for (url, field), claims in grouped.items():
        values = {claim.get("value") for claim in claims}
        if len(values) > 1:
            conflicts.append(
                {
                    "facility_url": url,
                    "field": field,
                    "claims": claims,
                    "selection_rule": "Detail main figures, then detail specification table; never fall back to market cards.",
                }
            )
    reconciliations = []
    for claim in observations:
        if claim.get("record_level") not in {"market", "portfolio"} or not claim.get(
            "field"
        ):
            continue
        included = (
            records
            if claim["record_level"] == "portfolio"
            else [r for r in records if str(r.market_url) == claim["source_url"]]
        )
        field = claim["field"]
        total = (
            len(included)
            if field == "facility_count"
            else sum(getattr(r, field) or 0 for r in included)
        )
        value = claim.get("value")
        difference = round(total - value, 6) if value is not None else None
        tolerance = rounding_tolerance(claim["raw_value"], field)
        status = (
            "unparseable"
            if value is None
            else "exact"
            if abs(difference) < 1e-8
            else "rounding"
            if abs(difference) <= tolerance + 1e-8
            else "conflict"
        )
        reconciliations.append(
            {
                **claim,
                "facility_sum": round(total, 6),
                "difference": difference,
                "rounding_tolerance": tolerance,
                "status": status,
            }
        )
    blockers = []
    if failures:
        blockers.append("failed_pages_or_discovery")
    if not records:
        blockers.append("no_accepted_facilities")
    if any(item["reason"] != "campus_aggregate" for item in rejected):
        blockers.append("rejected_facility_candidates")
    if duplicates["urls"] or duplicates["codes"]:
        blockers.append("duplicate_candidates")
    if len(candidates) != len(records) + len(rejected):
        blockers.append("candidate_accounting_mismatch")
    change = None
    if previous_count is not None:
        change = {
            "previous": previous_count,
            "current": len(candidates),
            "delta": len(candidates) - previous_count,
        }
        if previous_count and len(candidates) < previous_count * 0.8:
            blockers.append("candidate_count_drop_over_20_percent")
    missing_carriers = [r for r in records if r.onsite_carriers is None]
    total_mw = sum(r.critical_it_mw for r in records)
    missing_mw = sum(r.critical_it_mw for r in missing_carriers)
    return {
        "gate": "failed" if blockers else "passed",
        "blockers": blockers,
        "scope": scope,
        "accounting": {
            "candidates": len(candidates),
            "accepted": len(records),
            "rejected": len(rejected),
            "reconciled": len(candidates) == len(records) + len(rejected),
        },
        "missingness": {
            field: sum(getattr(r, field) is None for r in records)
            for field in ("onsite_carriers", "address_raw", "campus_name")
        },
        "missingness_denominator": len(records),
        "carrier_coverage": {
            "missing_count": len(missing_carriers),
            "facility_count": len(records),
            "missing_facility_share": len(missing_carriers) / len(records)
            if records
            else None,
            "missing_capacity_mw": round(missing_mw, 6),
            "total_capacity_mw": round(total_mw, 6),
            "missing_capacity_share": missing_mw / total_mw if total_mw else None,
            "facility_codes": [r.facility_code for r in missing_carriers],
        },
        "missingness_notes": {
            "campus_name": "Null means no explicit campus grouping in the market listing; it does not invalidate a facility."
        },
        "warning_counts": {
            "card_detail_conflicts": len(conflicts),
            "aggregate_conflicts": sum(
                r["status"] == "conflict" for r in reconciliations
            ),
            "parse_issues": len(issues),
        },
        "duplicates": duplicates,
        "card_detail_conflicts": conflicts,
        "reconciliation": reconciliations,
        "parse_issues": issues,
        "failures": failures,
        "rejections": rejected,
        "candidate_count_change": change,
    }
