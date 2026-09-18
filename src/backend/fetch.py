import hashlib
import logging
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx2

from .models import SourceSnapshot
from .storage import read_snapshot, write_json, write_snapshot

logger = logging.getLogger(__name__)
USER_AGENT = "DataBankResearch/0.1 (+https://github.com/gustofied/home)"


class FetchError(ValueError):
    pass


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(
                    0,
                    (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(),
                )
            except (ValueError, TypeError):
                pass
    return float(2 ** (attempt - 1))


class Fetcher:
    """Sequential requests, persisted before parsing; replay never opens a client."""

    def __init__(
        self,
        bronze: Path,
        manifest: dict,
        *,
        replay: Path | None = None,
        interval: float = 1.0,
        client: httpx2.Client | None = None,
    ):
        self.bronze = bronze
        self.manifest = manifest
        self.replay = replay
        self.interval = interval
        self.client = client
        self.owns_client = False
        self.last_request = 0.0
        self.cache: dict[str, SourceSnapshot] = {}
        self.robots: RobotFileParser | None = None

    def __enter__(self):
        if self.replay is None and self.client is None:
            self.client = httpx2.Client(
                timeout=httpx2.Timeout(20, connect=10),
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            )
            self.owns_client = True
        return self

    def __exit__(self, *_):
        if self.owns_client:
            self.client.close()

    def save_manifest(self):
        write_json(self.bronze / "manifest.json", self.manifest)

    def fetch(self, url: str) -> SourceSnapshot:
        if url in self.cache:
            return self.cache[url]
        if (
            urlsplit(url).hostname != "www.databank.com"
            or urlsplit(url).scheme != "https"
        ):
            raise FetchError(f"URL outside DataBank source: {url}")
        if self.replay is not None:
            snapshot = read_snapshot(self.replay, url)
            self._persist(snapshot)
        else:
            if self.robots is not None and not self.robots.can_fetch(USER_AGENT, url):
                raise FetchError(f"robots.txt disallows {url}")
            snapshot = self._request(url)
        if snapshot.status_code != 200:
            raise FetchError(f"HTTP {snapshot.status_code}: {url}")
        self.cache[url] = snapshot
        return snapshot

    def check_robots(self):
        snapshot = self.fetch("https://www.databank.com/robots.txt")
        self.robots = RobotFileParser()
        self.robots.parse(
            snapshot.content.decode("utf-8", errors="replace").splitlines()
        )
        delay = self.robots.crawl_delay(USER_AGENT)
        if delay:
            self.interval = max(self.interval, float(delay))

    def _persist(self, snapshot):
        entry = write_snapshot(self.bronze, snapshot)
        self.manifest["pages"].append(entry)
        self.save_manifest()

    def _request(self, url):
        for attempt in range(1, 4):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            started = time.monotonic()
            try:
                response = self.client.get(url)
            except httpx2.TransportError as exc:
                self.manifest["request_errors"].append(
                    {"url": url, "attempt": attempt, "error": str(exc)}
                )
                self.save_manifest()
                if attempt == 3:
                    raise FetchError(f"Request failed: {url}: {exc}") from exc
                time.sleep(retry_delay(None, attempt))
                continue
            snapshot = SourceSnapshot(
                requested_url=url,
                final_url=str(response.url),
                fetched_at=datetime.now(UTC),
                status_code=response.status_code,
                headers=dict(response.headers),
                elapsed_seconds=round(time.monotonic() - started, 6),
                content=response.content,
                sha256=hashlib.sha256(response.content).hexdigest(),
                attempt=attempt,
            )
            self._persist(snapshot)
            logger.info(
                "GET %s %s (%s bytes)", response.status_code, url, len(response.content)
            )
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 3:
                return snapshot
            delay = retry_delay(response.headers.get("retry-after"), attempt)
            if delay > 60:
                raise FetchError(f"Retry-After {delay:.0f}s exceeds run budget: {url}")
            time.sleep(delay)
        raise AssertionError("unreachable")
