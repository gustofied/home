## A home for data center facility insights

Includes the scraper to get the data, a pipeline to process it, a frontend to look at it, some analysis to understand it, and a suggested production setup.

## Run locally

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/gustofied/home.git
cd home
uv sync --locked
uv run --locked fastapi dev
```

Open <http://127.0.0.1:8000>. The included results are ready to view. FastAPI serves the HTML, CSS, JavaScript and saved data. It stays running and does not scrape.

To serve without development reload:

```bash
uv run --locked fastapi run --host 127.0.0.1 --port 8000
```

## Data pipeline

Rebuild from the included HTML without contacting DataBank:

```bash
uv run --locked backend run --from-snapshot data/raw/20260918T081720-ab352538
```

Refresh the complete portfolio from the website:

```bash
./scripts/refresh.sh
```

The script runs `uv run --locked backend run --all-markets`. It discovers markets and facilities, saves HTML, parses and validates records, calculates the analysis, and publishes results when quality checks pass. It runs once and exits. Failures return a nonzero exit code and leave the previous published results available.

The pipeline and server use the same `data/` directory. Set `BACKEND_DATA_DIR` for both to use another location; see `.env.example`. Reload the page after a refresh to see the new results. Use the saved HTML command for a reproducible walkthrough.

## Checks

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

## API

- `GET /api/health`: server health.
- `GET /api/overview`: summary, quality checks and chart data.
- `GET /api/facilities`: facility rows; optional `market`, `min_capacity_mw` and `run_id` filters.

Interactive documentation: <http://127.0.0.1:8000/docs>.

## The task

1. **Find data center data online** and build **a simple scraping framework** for it. There isn't time to make it polished, but we want to see some thinking about how it would work in production.

2. Analyze the data. Look at data quality first, then derive whatever insights you find interesting.

What data you use, how broad you go, and which language and tools you pick are all up to you. AI tools are allowed without restriction. Cover as much ground as the time permits.

### Approach, decisions and tradeoffs

#### Find data center data online

Google’s location pages didn’t provide enough comparable numerical data. I chose DataBank because it publishes power capacity and floor area for individual facilities, and its pages are straightforward to download and extract data from. There was other stuff here and there, but I didn't have the time to look at it.

#### A simple scraping framework

A Typer command runs the pipeline. HTTPX2 downloads pages, BeautifulSoup extracts labelled specifications, and Pydantic validates one row per facility. Detail pages supply the values; market cards provide a cross-check. Campus totals stay separate.

1. **Raw pages (`data/raw/`):** HTML, source URLs, collection times and file hashes.
2. **Facility rows (`data/silver/`):** values in MW and square feet, rejected records and quality checks.
3. **Analysis (`data/gold/`):** summaries and chart data. After checks pass, `latest.json` points the website to the new results.

##### How it would work in production

I’d have a scheduler such as Windmill run `./scripts/refresh.sh` from a checkout with Python and uv installed. The script is the job; the scheduler decides when it runs.

- Keep `data/` between runs and make it available to the separately running FastAPI server.
- Prevent overlapping refreshes in the scheduler, capture logs and alert on failures or unexpected data changes.
- Keep request limits, retries, timeouts and quality checks. A failed refresh leaves the website on the previous results.
- For cloud storage, adapt the file storage to S3 while keeping each run and its source pages together. Saved HTML lets us fix parsing and rebuild results without fetching again.

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

Basic HTML, CSS and JavaScript served by FastAPI. Two requests load the report and facility rows from the same run. Filtering, sorting and source details then work in the browser. Each facility shows original values, source links, collection times and file hashes.
