import json
import shutil
from pathlib import Path

import pytest

from backend.analytics import analyze
from backend.ingestion import normalize_observations
from backend.pipeline import run_pipeline
from backend.quality import assess_quality
from backend.storage import read_facilities

EXAMPLE = Path(__file__).resolve().parents[1] / "data" / "bronze" / "example"


@pytest.fixture
def offline(monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError("Network client opened during offline replay")

    monkeypatch.setattr("backend.fetch.httpx2.Client", forbidden)


def test_replay_is_deterministic_and_reconciles_chicago(tmp_path, offline):
    first = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    second = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    assert first.published and second.published
    assert first.accepted == 4 and first.rejected == 0
    a, b = (
        json.loads(first.report_path.read_text()),
        json.loads(second.report_path.read_text()),
    )
    assert a.pop("run_id") != b.pop("run_id")
    assert a == b
    assert a["summary"]["critical_it_mw"] == 14.45
    assert a["summary"]["it_area_sqft"] == 128060
    assert a["summary"]["correlation"]["pearson"] is None
    assert a["source"]["data_kind"] == "synthetic"
    powers = [
        r for r in a["quality"]["reconciliation"] if r["field"] == "critical_it_mw"
    ]
    assert [(r["raw_value"], r["status"]) for r in powers] == [
        ("14.5MW", "rounding"),
        ("13.8MW", "conflict"),
    ]
    for name in [
        "facilities.csv",
        "facilities.jsonl",
        "quality.json",
        "observations.jsonl",
        "rejected.jsonl",
    ]:
        assert (tmp_path / "silver" / first.run_id / name).read_bytes() == (
            tmp_path / "silver" / second.run_id / name
        ).read_bytes()


def test_incomplete_replay_keeps_known_good_publication(tmp_path, offline):
    good = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    broken = tmp_path / "broken"
    shutil.copytree(EXAMPLE, broken)
    manifest = json.loads((broken / "manifest.json").read_text())
    manifest["pages"] = [
        p for p in manifest["pages"] if "/oak-brook/" not in p["requested_url"]
    ]
    (broken / "manifest.json").write_text(json.dumps(manifest))
    result = run_pipeline(tmp_path, from_snapshot=broken)
    assert not result.published
    assert result.accepted == 3 and result.rejected == 1
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == good.run_id
    quality = json.loads(result.report_path.read_text())["quality"]
    assert quality["accounting"] == {
        "candidates": 4,
        "accepted": 3,
        "rejected": 1,
        "reconciled": True,
    }


def test_duplicate_and_conflict_accounting(tmp_path, offline):
    result = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    records = read_facilities(tmp_path, result.run_id)[:1]
    url = str(records[0].detail_url)
    claims = [
        {
            "record_level": "facility",
            "source_url": url,
            "origin": "card",
            "field": "critical_it_mw",
            "raw_value": "2MW",
        },
        {
            "record_level": "facility",
            "source_url": url,
            "origin": "detail_main",
            "field": "critical_it_mw",
            "raw_value": "1MW",
        },
    ]
    normalize_observations(claims)
    quality = assess_quality(
        records,
        [{"url": url, "code": "ORD1"}] * 2,
        [{"reason": "duplicate_candidate"}],
        claims,
        [],
        [],
    )
    assert quality["accounting"]["reconciled"]
    assert quality["gate"] == "failed"
    assert quality["duplicates"]["codes"] == {"ORD1": 2}
    assert len(quality["card_detail_conflicts"]) == 1


def test_constant_data_correlation_is_explicitly_undefined(tmp_path, offline):
    result = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    record = read_facilities(tmp_path, result.run_id)[0]
    report = analyze([record] * 5, {}, "test", record.fetched_at, {})
    assert report.summary["correlation"]["pearson"] is None
    assert "constant" in report.summary["correlation"]["reason"]
