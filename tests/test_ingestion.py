from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.ingestion import build_record, normalize_metric, normalize_observations
from backend.models import SourceSnapshot
from backend.sources.databank import discover_markets, parse_detail, parse_market

FIXTURES = Path(__file__).parent / "fixtures" / "databank"
MARKET = "https://www.databank.com/data-centers/chicago/"


def test_discovery_variants_and_label_matching():
    candidates, claims = parse_market((FIXTURES / "market.html").read_bytes(), MARKET)
    assert [c.code for c in candidates] == ["ORD1", "ORD2", "ORD3", None]
    assert candidates[0].url == MARKET + "one/"
    assert candidates[0].metrics["critical_it_mw"] == "1 MW"
    assert candidates[1].record_level == "facility"
    assert candidates[1].campus_name == "Synthetic Campus"
    assert candidates[2].campus_name is None
    assert candidates[3].record_level == "campus"
    assert len([o for o in claims if o["record_level"] == "market"]) == 1


def test_detail_uses_stats_not_campus_prose():
    candidates, _ = parse_market((FIXTURES / "market.html").read_bytes(), MARKET)
    name, metrics, claims = parse_detail(
        (FIXTURES / "detail.html").read_bytes(), candidates[0].url
    )
    snapshot = SourceSnapshot(
        candidates[0].url,
        candidates[0].url,
        datetime(2026, 1, 1, tzinfo=UTC),
        200,
        {},
        0,
        b"",
        "",
    )
    record = build_record(candidates[0], name, metrics, snapshot)
    assert record.critical_it_mw == 40
    assert record.it_area_sqft == 200_000
    assert record.onsite_carriers is None
    assert record.capacity_density_w_per_sqft == 200
    normalize_observations(claims)
    assert [o["value"] for o in claims if o["field"] == "critical_it_mw"] == [40, 40]
    with pytest.raises(ValidationError):
        build_record(candidates[0], name, {**metrics, "it_area_sqft": "0"}, snapshot)
    with pytest.raises(ValidationError):
        build_record(
            candidates[0], name, {**metrics, "critical_it_mw": "TBD"}, snapshot
        )


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("critical_it_mw", "2,000 kW", 2.0),
        ("critical_it_mw", "1 GW", 1000.0),
        ("it_area_sqft", "4.98M", 4_980_000),
        ("it_area_sqft", " 10,130 sq ft ", 10130),
        ("onsite_carriers", "TBD", None),
        ("onsite_carriers", "0", 0),
    ],
)
def test_normalization(field, raw, expected):
    assert normalize_metric(field, raw) == expected


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("critical_it_mw", "2 MWh"),
        ("critical_it_mw", "2"),
        ("it_area_sqft", "10,13"),
        ("onsite_carriers", "1.5"),
    ],
)
def test_ambiguous_units_and_bad_numbers_are_not_silently_coerced(field, raw):
    with pytest.raises(ValueError):
        normalize_metric(field, raw)


def test_directory_only_returns_market_links():
    html = b'<a href="/data-centers/chicago/">Chicago</a><a href="/data-centers/chicago/?x=1">Chicago</a><a href="/data-centers/edge-strategy/">Edge</a><a href="/data-centers/chicago/one/">Facility</a><a href="https://evil.example/data-centers/elsewhere/">Other</a>'
    assert discover_markets(html) == [MARKET]
