import csv
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import FacilityRecord, SourceSnapshot


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        name = file.name
        try:
            json.dump(
                value, file, indent=2, sort_keys=True, allow_nan=False, default=str
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            os.unlink(name)
            raise
    os.replace(name, path)


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(v, sort_keys=True, allow_nan=False, default=str) + "\n"
            for v in values
        )
    )


def write_csv(path: Path, values: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(values)


def write_snapshot(raw: Path, snapshot: SourceSnapshot) -> dict:
    filename = f"pages/{hashlib.sha256(snapshot.requested_url.encode()).hexdigest()[:20]}-{snapshot.attempt}.html"
    path = raw / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(snapshot.content)
    entry = asdict(snapshot)
    entry.pop("content")
    entry["fetched_at"] = snapshot.fetched_at.isoformat()
    entry["path"] = filename
    return entry


def read_snapshot(raw: Path, url: str) -> SourceSnapshot:
    manifest = json.loads((raw / "manifest.json").read_text())
    entries = [entry for entry in manifest["pages"] if entry["requested_url"] == url]
    if not entries:
        raise ValueError(f"Snapshot has no response for {url}; network is disabled")
    entry = entries[-1].copy()
    path = (raw / entry.pop("path")).resolve()
    if not path.is_relative_to(raw.resolve()):
        raise ValueError("Snapshot body path escapes its directory")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ValueError(f"Snapshot hash mismatch: {url}")
    entry["fetched_at"] = datetime.fromisoformat(entry["fetched_at"])
    return SourceSnapshot(**entry, content=content)


def latest_run(data_dir: Path) -> str:
    run_id = json.loads((data_dir / "latest.json").read_text())["run_id"]
    if (
        not isinstance(run_id, str)
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("Invalid published run ID")
    return run_id


def read_facilities(data_dir: Path, run_id: str) -> list[FacilityRecord]:
    return [
        FacilityRecord.model_validate_json(line)
        for line in (data_dir / "silver" / run_id / "facilities.jsonl")
        .read_text()
        .splitlines()
        if line
    ]
