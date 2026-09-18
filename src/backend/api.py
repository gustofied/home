from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .config import settings
from .models import FacilitiesResponse, HealthResponse, OverviewResponse
from .storage import latest_run, read_facilities

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse()


def published_run() -> str:
    try:
        return latest_run(settings.data_dir)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503, detail="No published data. Run backend run first."
        ) from None
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=503, detail="Published run pointer is invalid."
        ) from None


@router.get("/overview", tags=["data"])
def overview() -> OverviewResponse:
    run_id = published_run()
    try:
        return OverviewResponse.model_validate_json(
            (settings.data_dir / "gold" / run_id / "report.json").read_text()
        )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=503, detail="Published report is unavailable."
        ) from None


@router.get("/facilities", tags=["data"])
def facilities(
    market: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    min_capacity_mw: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
) -> FacilitiesResponse:
    run_id = published_run()
    try:
        records = read_facilities(settings.data_dir, run_id)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=503, detail="Published facilities are unavailable."
        ) from None
    selected = [
        r
        for r in records
        if (market is None or r.market == market.lower())
        and (min_capacity_mw is None or r.critical_it_mw >= min_capacity_mw)
    ]
    return FacilitiesResponse(run_id=run_id, count=len(selected), facilities=selected)
