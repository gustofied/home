import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from backend.analytics import analyze, size_density_analysis
from backend.models import FacilityRecord
from backend.pipeline import run_pipeline
from backend.quality import assess_quality


def test_weighted_missingness_and_density_use_different_denominators():
    records = [
        FacilityRecord(
            facility_code=code,
            facility_name=code,
            market="example",
            it_area_sqft=area,
            critical_it_mw=power,
            onsite_carriers=carriers,
            detail_url=f"https://www.databank.com/data-centers/example/{code.lower()}/",
            market_url="https://www.databank.com/data-centers/example/",
            fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for code, area, power, carriers in [
            ("AA1", 100_000, 10.0, 0),
            ("AA2", 300_000, 90.0, None),
        ]
    ]
    candidates = [{"url": str(r.detail_url), "code": r.facility_code} for r in records]
    quality = assess_quality(records, candidates, [], [], [], [])
    coverage = quality["carrier_coverage"]
    assert coverage["missing_facility_share"] == 0.5
    assert coverage["missing_capacity_share"] == 0.9
    assert coverage["facility_codes"] == ["AA2"]  # A reported zero is known.
    report = analyze(records, quality, "test", records[0].fetched_at, {})
    assert report.summary["density_w_per_sqft"]["median"] == 200
    assert report.summary["portfolio_density_w_per_sqft"] == 250


def test_empty_population_has_no_invented_percentages():
    quality = assess_quality([], [], [], [], [], [])
    assert quality["carrier_coverage"]["missing_facility_share"] is None
    assert quality["carrier_coverage"]["missing_capacity_share"] is None
    report = analyze([], quality, "test", datetime.now(UTC), {})
    assert report.summary["portfolio_density_w_per_sqft"] is None


def test_saved_portfolio_findings(tmp_path, monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("Offline portfolio check opened a network client")

    monkeypatch.setattr("backend.fetch.httpx2.Client", forbidden)
    data = Path(__file__).resolve().parents[1] / "data"
    result = run_pipeline(tmp_path, from_snapshot=data / "raw/20260918T081720-ab352538")
    assert result.published
    report = json.loads(result.report_path.read_text())
    quality = report["quality"]
    summary = report["summary"]
    assert summary["facility_count"] == 76
    assert quality["carrier_coverage"]["missing_count"] == 6
    assert quality["carrier_coverage"]["missing_capacity_share"] == pytest.approx(
        0.395, abs=0.0005
    )
    assert summary["top_three_market_facility_count"] == 24
    assert summary["top_three_market_capacity_share"] == pytest.approx(0.73517439)
    assert summary["portfolio_density_w_per_sqft"] == 205.622
    size = report["breakdowns"]["size_density"]
    assert [g["facility_count"] for g in size["groups"]] == [19, 19, 19, 19]
    assert [g["missing_carriers"] for g in size["groups"]] == [0, 0, 0, 6]
    assert size["largest_to_smallest_median_ratio"] == pytest.approx(3.92773, abs=0.001)
    assert size["checks"][1]["facility_count"] == 58
    assert size["checks"][1]["area_density_spearman"] == pytest.approx(0.569214)
    assert size["power_carriers"]["facility_count"] == 70
    assert size["power_carriers"]["spearman"] == pytest.approx(-0.0347861)


def test_size_groups_use_medians_and_carrier_pairs_exclude_unknowns():
    frame = pd.DataFrame(
        [
            {
                "facility_code": f"AA{i}",
                "market": "example",
                "it_area_sqft": ((i + 1) // 2) * 100,
                "capacity_density_w_per_sqft": i * 10,
                "critical_it_mw": ((i + 1) // 2) * 100 * i * 10 / 1_000_000,
                "onsite_carriers": 9 - i if i < 8 else None,
            }
            for i in range(1, 9)
        ]
    ).sample(frac=1, random_state=0)
    result = size_density_analysis(frame)
    assert [g["median_density_w_per_sqft"] for g in result["groups"]] == [
        15,
        35,
        55,
        75,
    ]
    assert [g["missing_carriers"] for g in result["groups"]] == [0, 0, 0, 1]
    assert result["largest_to_smallest_median_ratio"] == 5
    assert result["power_carriers"] == {
        "facility_count": 7,
        "missing_count": 1,
        "spearman": -1,
    }
