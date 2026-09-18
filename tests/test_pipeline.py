import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.analytics import analyze
from backend.fetch import Fetcher
from backend.ingestion import normalize_observations
from backend.models import SourceSnapshot
from backend.pipeline import run_pipeline
from backend.quality import assess_quality
from backend.storage import read_facilities, write_json, write_snapshot

EXAMPLE = Path(__file__).resolve().parents[1] / "data" / "raw" / "example"


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


@pytest.mark.parametrize(
    ("title", "expected_reason", "published"),
    [
        ("(ORD1) Duplicate facility", "duplicate_candidate", False),
        ("Aggregate Campus", "campus_aggregate", True),
    ],
)
def test_duplicate_candidates_and_aggregate_cards_are_accounted_for(
    tmp_path, offline, title, expected_reason, published
):
    snapshot = tmp_path / "input"
    shutil.copytree(EXAMPLE, snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    market_url = manifest["scope"][0]
    entry = next(p for p in manifest["pages"] if p["requested_url"] == market_url)
    path = snapshot / entry["path"]
    extra = f'<div class="c-data-center-card"><h4 class="c-data-center-card__title"><a href="{market_url}600-south-federal-street/">{title}</a></h4></div>'.encode()
    path.write_bytes(path.read_bytes() + extra)
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    result = run_pipeline(tmp_path, from_snapshot=snapshot)
    assert result.published is published
    assert result.accepted == 4 and result.rejected == 1
    quality = json.loads(result.report_path.read_text())["quality"]
    assert quality["accounting"]["reconciled"]
    assert quality["rejections"][0]["reason"] == expected_reason


def test_count_collapse_blocks_publication(tmp_path, offline):
    result = run_pipeline(tmp_path, from_snapshot=EXAMPLE)
    records = read_facilities(tmp_path, result.run_id)
    candidates = [{"url": str(r.detail_url), "code": r.facility_code} for r in records]
    quality = assess_quality(records, candidates, [], [], [], [], previous_count=10)
    assert "candidate_count_drop_over_20_percent" in quality["blockers"]


def test_full_portfolio_count_drop_is_checked_when_market_discovery_changes(
    tmp_path, offline, monkeypatch
):
    snapshot = tmp_path / "input"
    shutil.copytree(EXAMPLE, snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    url = "https://www.databank.com/data-centers/"
    content = b'<a href="/data-centers/chicago/">Chicago</a>'
    manifest["pages"].append(
        write_snapshot(
            snapshot,
            SourceSnapshot(
                url,
                url,
                datetime(2026, 1, 1, tzinfo=UTC),
                200,
                {},
                0,
                content,
                hashlib.sha256(content).hexdigest(),
            ),
        )
    )
    write_json(snapshot / "manifest.json", manifest)
    write_json(tmp_path / "latest.json", {"run_id": "previous"})
    write_json(
        tmp_path / "gold" / "previous" / "report.json",
        {
            "source": {"all_markets": True},
            "quality": {
                "scope": [url + "chicago/", url + "boston/"],
                "accounting": {"candidates": 10},
            },
        },
    )

    def saved_fetcher(raw, run_manifest, **kwargs):
        return Fetcher(raw, run_manifest, replay=snapshot)

    monkeypatch.setattr("backend.pipeline.Fetcher", saved_fetcher)
    result = run_pipeline(tmp_path, all_markets=True)
    assert result.accepted == 4
    assert not result.published
    assert json.loads((tmp_path / "latest.json").read_text())["run_id"] == "previous"
    quality = json.loads(result.report_path.read_text())["quality"]
    assert "candidate_count_drop_over_20_percent" in quality["blockers"]
