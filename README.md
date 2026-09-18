# home

Scraping and analyzing advertised data center capacity and floor area.

## Run locally

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
uv run backend serve
```

Open <http://127.0.0.1:8000>.
Check the running server with `uv run backend ping`.
Optional settings are in `.env.example`.

## Checks

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

`./scripts/demo.sh` checks the app and stops the server afterward.
Set `PORT=18080` to use another port.

## API

- `GET /api/health` — server health.

Interactive documentation: <http://127.0.0.1:8000/docs>.

## The task

1. **Find data center data online** and build **a simple scraping framework** for it. There isn't time to make it polished, but we want to see some thinking about how it would work in production.

2. Analyze the data. Look at data quality first, then derive whatever insights you find interesting.

What data you use, how broad you go, and which language and tools you pick are all up to you. AI tools are allowed without restriction. Cover as much ground as the time permits.

### Approach, decisions and tradeoffs

#### Find data center data online

So yesterday I saw epoch, they extended their compute coverage, I thought maybe I can use that. But at the end of the day it was interesting but... , but personally it felt like a finished product, and I wasn’t sure it gave me enough room to show my own scraping and analysis. Google’s location pages didn’t provide enough comparable numerical data. I chose DataBank because it publishes power capacity and floor area for individual facilities, and its pages are straightforward to download and extract data from. There was other stuff here and there, but I didn't have the time to look at it.

#### A simple scraping framework

A Typer command runs the pipeline. HTTPX2 downloads DataBank’s directory, market and facility pages; BeautifulSoup extracts labelled specifications; Pydantic validates one row per facility. Facility detail values are canonical, with market cards kept for comparison and campus totals excluded.

1. **Bronze:** save HTML, source URLs, retrieval times and content hashes so runs can be replayed offline.
2. **Silver:** normalize power to MW and IT floor area to square feet. Save facility rows, rejected records and quality checks, including missing values, duplicates and conflicting totals.
3. **Gold:** calculate summaries and chart data. Publish through an atomic `latest.json` update only when quality checks pass. FastAPI reads the published files; failed runs leave the last good result available.

##### How it would work in production

A scheduler such as Windmill would run the same command in a container. Immutable object storage would hold snapshots and versioned outputs, with the API reading the last successful run.

Keep requests rate limited with bounded retries and timeouts; add conditional requests using ETag or Last-Modified. Alert on failed pages, changed selectors, unexpected count drops and rising rejection rates. Saved snapshots allow parser fixes and backfills without fetching everything again. Add a database when query or concurrency needs justify it.
