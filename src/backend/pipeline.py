import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .analytics import analyze
from .fetch import Fetcher
from .ingestion import build_record, normalize_observations
from .models import FacilityRecord
from .quality import assess_quality
from .sources.databank import (
    DIRECTORY_URL,
    PARSER_VERSION,
    discover_markets,
    parse_detail,
    parse_directory,
    parse_market,
)
from .storage import latest_run, write_csv, write_json, write_jsonl

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    published: bool
    accepted: int
    rejected: int
    report_path: Path
    bronze_path: Path


def run_pipeline(
    data_dir: Path,
    *,
    market: str | None = None,
    all_markets: bool = False,
    from_snapshot: Path | None = None,
    interval: float = 1.0,
) -> RunResult:
    if sum([market is not None, all_markets, from_snapshot is not None]) != 1:
        raise ValueError(
            "Choose exactly one of --market, --all-markets, or --from-snapshot"
        )
    if market is not None and not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", market):
        raise ValueError("Market must be a DataBank URL slug, for example chicago")
    original = (
        json.loads((from_snapshot / "manifest.json").read_text())
        if from_snapshot
        else None
    )
    scope = (
        original["scope"]
        if original
        else [DIRECTORY_URL + market + "/"]
        if market
        else []
    )
    all_markets = original["all_markets"] if original else all_markets
    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    bronze = data_dir / "bronze" / run_id
    silver = data_dir / "silver" / run_id
    gold = data_dir / "gold" / run_id
    manifest = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "scope": scope,
        "all_markets": all_markets,
        "parser_version": PARSER_VERSION,
        "replay_of": str(from_snapshot) if from_snapshot else None,
        "data_kind": original.get("data_kind", "live") if original else "live",
        "pages": [],
        "request_errors": [],
        "status": "running",
    }
    candidates, observations, rejected, records, failures = [], [], [], [], []
    seen_urls, seen_codes = set(), set()
    with Fetcher(bronze, manifest, replay=from_snapshot, interval=interval) as fetcher:
        fetcher.save_manifest()
        try:
            fetcher.check_robots()
            if all_markets:
                directory = fetcher.fetch(DIRECTORY_URL)
                scope = discover_markets(directory.content)
                manifest["scope"] = scope
                observations.extend(parse_directory(directory.content))
                if not scope:
                    raise ValueError("Directory discovery returned no markets")
        except ValueError as exc:
            failures.append(
                {
                    "url": DIRECTORY_URL,
                    "stage": "discovery_or_robots",
                    "error": str(exc),
                }
            )
        if not failures:
            for url in scope:
                try:
                    snapshot = fetcher.fetch(url)
                    discovered, claims = parse_market(snapshot.content, url)
                    observations.extend(claims)
                    if not discovered:
                        raise ValueError(
                            "No facility cards found; possible selector drift"
                        )
                    candidates.extend(discovered)
                except ValueError as exc:
                    failures.append({"url": url, "stage": "market", "error": str(exc)})
            for index, candidate in enumerate(candidates, start=1):
                reason = None
                if candidate.record_level != "facility":
                    reason = "campus_aggregate"
                elif not candidate.url or not candidate.code:
                    reason = "missing_identity"
                elif candidate.url in seen_urls or candidate.code in seen_codes:
                    reason = "duplicate_candidate"
                seen_urls.add(candidate.url)
                seen_codes.add(candidate.code)
                if reason:
                    rejected.append(
                        {
                            "candidate_index": index,
                            "reason": reason,
                            "candidate": asdict(candidate),
                        }
                    )
                    continue
                try:
                    snapshot = fetcher.fetch(candidate.url)
                    name, metrics, claims = parse_detail(
                        snapshot.content, candidate.url
                    )
                    observations.extend(claims)
                    record = build_record(candidate, name, metrics, snapshot)
                    records.append(record)
                    logger.info(
                        "Accepted %s: %s MW, %s sqft",
                        record.facility_code,
                        record.critical_it_mw,
                        record.it_area_sqft,
                    )
                except ValueError as exc:
                    rejected.append(
                        {
                            "candidate_index": index,
                            "reason": "retrieval_or_validation",
                            "error": str(exc),
                            "candidate": asdict(candidate),
                        }
                    )
        fetcher.save_manifest()
    records.sort(key=lambda record: record.facility_code)
    normalize_observations(observations)
    previous_count = None
    # Replay is independent of mutable publication history.
    if from_snapshot is None:
        try:
            previous = json.loads(
                (
                    data_dir / "silver" / latest_run(data_dir) / "quality.json"
                ).read_text()
            )
            if previous["scope"] == scope:
                previous_count = previous["accounting"]["candidates"]
        except (FileNotFoundError, ValueError, KeyError):
            pass
    candidate_dicts = [asdict(candidate) for candidate in candidates]
    quality = assess_quality(
        records,
        candidate_dicts,
        rejected,
        observations,
        failures,
        scope,
        previous_count,
    )
    as_of = max(
        [datetime.fromisoformat(page["fetched_at"]) for page in manifest["pages"]],
        default=started,
    )
    source = {
        "name": "DataBank",
        "directory_url": DIRECTORY_URL,
        "terms_url": "https://www.databank.com/terms-of-use/",
        "scope": scope,
        "all_markets": all_markets,
        "parser_version": PARSER_VERSION,
        "data_kind": manifest["data_kind"],
        "page_count": len({page["requested_url"] for page in manifest["pages"]}),
        "retrieval_started_at": min(
            [page["fetched_at"] for page in manifest["pages"]],
            default=started.isoformat(),
        ),
        "retrieval_finished_at": as_of.isoformat(),
        "source_freshness": "Unknown; retrieval timestamps are not publication dates.",
    }
    report = analyze(records, quality, run_id, as_of, source)
    write_jsonl(
        silver / "facilities.jsonl",
        [r.model_dump(mode="json", exclude_computed_fields=True) for r in records],
    )
    write_csv(
        silver / "facilities.csv",
        [r.model_dump(mode="json") for r in records],
        list(FacilityRecord.model_fields) + ["capacity_density_w_per_sqft"],
    )
    write_jsonl(silver / "candidates.jsonl", candidate_dicts)
    write_jsonl(silver / "observations.jsonl", observations)
    write_jsonl(silver / "rejected.jsonl", rejected)
    write_csv(
        silver / "market_totals.csv",
        [o for o in observations if o["record_level"] != "facility"],
        [
            "source_url",
            "record_level",
            "origin",
            "field",
            "raw_value",
            "raw_label",
            "value",
            "error",
        ],
    )
    write_json(silver / "quality.json", quality)
    write_json(gold / "report.json", report.model_dump(mode="json"))
    published = quality["gate"] == "passed"
    manifest["status"] = "complete" if published else "failed_quality"
    manifest["completed_at"] = datetime.now(UTC).isoformat()
    write_json(bronze / "manifest.json", manifest)
    if published:
        write_json(data_dir / "latest.json", {"run_id": run_id})
    return RunResult(
        run_id, published, len(records), len(rejected), gold / "report.json", bronze
    )
