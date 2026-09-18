# home

Scraping and analyzing data center capacity and floor area.

## Run locally

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/gustofied/home.git
cd home
uv sync --locked
uv run backend run --from-snapshot data/raw/20260918T081720-ab352538
# Optional: refresh data from the source website
# uv run backend run --all-markets
uv run fastapi dev
```

Open <http://127.0.0.1:8000>. The CLI builds data; FastAPI serves the page and published results.
Optional settings: `.env.example`.

## Checks

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

`./scripts/demo.sh` replays the included raw capture, checks the API and stops the server afterward.
Set `PORT=18080` to use another port.

## API

- `GET /api/health` — server health.
- `GET /api/overview` — summary, quality checks and chart data.
- `GET /api/facilities` — facility rows; optional `market`, `min_capacity_mw` and `run_id` filters.

Interactive documentation: <http://127.0.0.1:8000/docs>.

## The task

1. **Find data center data online** and build **a simple scraping framework** for it. There isn't time to make it polished, but we want to see some thinking about how it would work in production.

2. Analyze the data. Look at data quality first, then derive whatever insights you find interesting.

What data you use, how broad you go, and which language and tools you pick are all up to you. AI tools are allowed without restriction. Cover as much ground as the time permits.

### Approach, decisions and tradeoffs

#### Find data center data online

So yesterday I saw epoch, they extended their compute coverage, I thought maybe I can use that. But at the end of the day it was interesting but... , but personally it felt like a finished product, and I wasn’t sure it gave me enough room to show my own scraping and analysis. Google’s location pages didn’t provide enough comparable numerical data. I chose DataBank because it publishes power capacity and floor area for individual facilities, and its pages are straightforward to download and extract data from. There was other stuff here and there, but I didn't have the time to look at it.

#### A simple scraping framework

A Typer command runs the pipeline: HTTPX2 downloads directory, market and facility pages; BeautifulSoup extracts labelled specifications; Pydantic validates one row per facility. Detail pages supply the values, market cards provide a cross-check, and campus totals stay separate.

1. **Bronze (`data/raw/`):** HTML, URLs, retrieval times and hashes for offline replay.
2. **Silver (`data/silver/`):** validated facility rows in MW and square feet, rejected records and quality checks.
3. **Gold (`data/gold/`):** summaries and chart data. Quality checks gate an atomic `latest.json` update; FastAPI reads the published files. Failed runs preserve the last good result.

##### How it would work in production

My initial suggestion would be to keep the Python pipeline we already have and put something around it to run the job.

- **Running it:** Something like Windmill, Dagster/Airflow, or GitHub Actions. I’d choose based on how much coordination we need and what the team already uses.
- **Storing it:** I’d use S3 for the raw snapshots, cleaned records and analytical results, keeping each run separate so we can trace a result back to its source.
- **Processing it:** The same raw → validated → summary stages. Keeping the original captures means we can fix a parser and replay the data without scraping everything again.
- **Serving it:** S3 could form the storage layer of a small data lake. The API would expose the prepared results to a frontend for analysis and presentation.
- **Keeping it reliable:** Keep rate limits, retries and timeouts, alert on failed runs or unexpected data changes, and only publish results that pass the quality checks. A failed run should leave the previous results available.

#### Analyze the data

I start with data quality, then compare markets and facilities. The frontend makes the findings and their sources easy to inspect.

##### Data quality

76 accepted facilities, no rejected rows. Four market-total conflicts and one campus power claim without a unit remain visible. Carrier counts are missing for 7.9% of facilities representing 39.5% of advertised capacity.

##### Insights of interest

Dallas, Northern Virginia and Atlanta contain 73.5% of advertised capacity across 24 of 76 facilities. Median facility density is 118 W/ft²; total power divided by total IT area is 206 W/ft². The first weights facilities equally; the second weights by area.

##### Why this data

Comparable facility specifications with source pages we can inspect and replay.

###### How broad you go

One operator, 27 markets and 76 facilities. Advertised inventory; operating status is not consistently available.

##### My analysis

Quality first, then concentration and facility differences. Counts alone hide how much capacity sits behind missing information. Advertised MW do not establish operating status, availability, utilisation or GPU performance.

##### Visualising the data

Basic HTML, CSS and JavaScript served by FastAPI. Two data requests load a consistent published run; filtering, sorting, charts and facility evidence then work locally. Each facility exposes original values, source links, retrieval times and page hashes.
