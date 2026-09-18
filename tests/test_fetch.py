import hashlib
from pathlib import Path

import httpx2
import pytest

from backend.fetch import Fetcher, FetchError
from backend.storage import read_snapshot

URL = "https://www.databank.com/data-centers/chicago/"


def test_retry_persists_responses_and_fetches_canonical_url_once(tmp_path, monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr("backend.fetch.time.sleep", sleeps.append)

    def handle(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx2.Response(503, content=b"busy", headers={"Retry-After": "2"})
        return httpx2.Response(200, content=b"<html>ok</html>")

    manifest = {"pages": [], "request_errors": []}
    with httpx2.Client(transport=httpx2.MockTransport(handle)) as client:
        with Fetcher(tmp_path, manifest, interval=0, client=client) as fetcher:
            snapshot = fetcher.fetch(URL)
            assert fetcher.fetch(URL) is snapshot
    assert len(calls) == 2
    assert 2 in sleeps
    assert [p["status_code"] for p in manifest["pages"]] == [503, 200]
    assert read_snapshot(tmp_path, URL).content == b"<html>ok</html>"
    assert snapshot.sha256 == hashlib.sha256(snapshot.content).hexdigest()
    Path(tmp_path / manifest["pages"][-1]["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_snapshot(tmp_path, URL)


def test_long_retry_after_stops_without_early_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.fetch.time.sleep", lambda _: None)
    with httpx2.Client(
        transport=httpx2.MockTransport(
            lambda _: httpx2.Response(429, headers={"Retry-After": "120"})
        )
    ) as client:
        with Fetcher(
            tmp_path, {"pages": [], "request_errors": []}, client=client
        ) as fetcher:
            with pytest.raises(FetchError, match="Retry-After"):
                fetcher.fetch(URL)


def test_robots_disallow_prevents_request(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx2.Response(
            200, content=b"User-agent: *\nDisallow: /data-centers/\n"
        )

    with httpx2.Client(transport=httpx2.MockTransport(handle)) as client:
        with Fetcher(
            tmp_path, {"pages": [], "request_errors": []}, client=client
        ) as fetcher:
            fetcher.check_robots()
            with pytest.raises(FetchError, match="disallows"):
                fetcher.fetch(URL)
    assert calls == ["https://www.databank.com/robots.txt"]
