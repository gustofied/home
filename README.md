# DataBank

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

## Run

```bash
uv sync --locked
uv run backend serve
```

Open <http://127.0.0.1:8000>. API docs: <http://127.0.0.1:8000/docs>.
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
