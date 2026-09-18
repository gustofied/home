from datetime import datetime

import pandas as pd

from .models import FacilityRecord, OverviewResponse


def analyze(
    records: list[FacilityRecord],
    quality: dict,
    run_id: str,
    as_of: datetime,
    source: dict,
) -> OverviewResponse:
    frame = pd.DataFrame([r.model_dump(mode="json") for r in records])
    total_mw = sum(r.critical_it_mw for r in records)
    summary = {
        "facility_count": len(records),
        "market_count": len({r.market for r in records}),
        "critical_it_mw": round(total_mw, 6),
        "it_area_sqft": sum(r.it_area_sqft for r in records),
        "density_w_per_sqft": {"median": None, "p10": None, "p90": None},
        "correlation": {
            "n": len(records),
            "pearson": None,
            "spearman": None,
            "reason": "Fewer than five accepted facilities; association estimates withheld.",
        },
    }
    markets = []
    outliers = []
    if records:
        density = frame["capacity_density_w_per_sqft"]
        summary["density_w_per_sqft"] = {
            name: round(float(density.quantile(q)), 3)
            for name, q in [("median", 0.5), ("p10", 0.1), ("p90", 0.9)]
        }
        for market, group in frame.groupby("market", sort=True):
            capacity = float(group["critical_it_mw"].sum())
            markets.append(
                {
                    "market": market,
                    "facility_count": len(group),
                    "critical_it_mw": round(capacity, 6),
                    "it_area_sqft": int(group["it_area_sqft"].sum()),
                    "capacity_share": capacity / total_mw,
                }
            )
        markets.sort(key=lambda m: (-m["critical_it_mw"], m["market"]))
        summary["top_three_market_capacity_share"] = sum(
            m["capacity_share"] for m in markets[:3]
        )
        if len(records) >= 5:
            x, y = frame["it_area_sqft"], frame["critical_it_mw"]
            if x.nunique() > 1 and y.nunique() > 1:
                summary["correlation"] = {
                    "n": len(records),
                    "pearson": float(x.corr(y)),
                    "spearman": float(x.rank().corr(y.rank())),
                    "reason": None,
                }
            else:
                summary["correlation"]["reason"] = (
                    "At least one variable is constant; correlation is undefined."
                )
            q1, q3 = float(density.quantile(0.25)), float(density.quantile(0.75))
            low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            outliers = frame.loc[
                (density < low) | (density > high),
                ["facility_code", "capacity_density_w_per_sqft"],
            ].to_dict("records")
    return OverviewResponse(
        run_id=run_id,
        as_of=as_of,
        summary=summary,
        quality=quality,
        breakdowns={
            "markets": markets,
            "area_power_scatter": [
                {
                    "facility_code": r.facility_code,
                    "market": r.market,
                    "it_area_sqft": r.it_area_sqft,
                    "critical_it_mw": r.critical_it_mw,
                    "capacity_density_w_per_sqft": r.capacity_density_w_per_sqft,
                }
                for r in records
            ],
            "density_outliers": outliers,
        },
        methodology={
            "question": "How does advertised critical IT load scale with IT floor area, and in which DataBank markets is that capacity concentrated?",
            "canonical_values": "Detail main figures take precedence over repeated detail specifications. Market-card values are retained as comparison evidence, never as fallback for missing required detail values.",
            "density_formula": "critical_it_mw * 1000000 / it_area_sqft",
            "density_meaning": "Advertised capacity per IT floor area, not measured consumption, utilization, or energy efficiency.",
            "correlation": "Pearson on values; Spearman as Pearson on average ranks. Descriptive associations only; withheld for n < 5 or constant inputs.",
            "outliers": "Tukey 1.5 IQR fences on capacity density for n >= 5; flagged records remain included.",
            "reconciliation": "All market/portfolio claims compared separately. Rounding tolerance is half the last displayed digit; conflicts remain visible and do not on their own invalidate otherwise complete records.",
            "limitations": [
                "Single operator's advertised inventory, not global market share.",
                "Operating, planned and expansion status is not consistently available; totals are not confirmed operational capacity.",
                "Retrieval time is not source freshness. Last-Modified, when supplied, is stored in the raw snapshot manifest and is not necessarily metric freshness.",
                "Campus/market aggregates are excluded from facility rows. Missing values are never imputed as zero.",
                "Uncertain or incomplete facilities are rejected visibly; failed quality gates never replace the published run.",
                "Publicly accessible source; no open-data license asserted. Raw captures contain HTML and response metadata; images are not downloaded.",
            ],
        },
        source=source,
    )
