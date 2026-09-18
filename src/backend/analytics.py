from datetime import datetime

import pandas as pd

from .models import FacilityRecord, OverviewResponse


def rank_correlation(frame: pd.DataFrame, x: str, y: str) -> float | None:
    pairs = frame[[x, y]].dropna()
    if len(pairs) < 5 or pairs[x].nunique() < 2 or pairs[y].nunique() < 2:
        return None
    return float(pairs[x].rank().corr(pairs[y].rank()))


def size_density_analysis(frame: pd.DataFrame) -> dict | None:
    if len(frame) < 4:
        return None
    ordered = frame.sort_values(["it_area_sqft", "facility_code"])
    groups = []
    labels = ["Smallest quarter", "Second quarter", "Third quarter", "Largest quarter"]
    for index, label in enumerate(labels):
        group = ordered.iloc[index * len(frame) // 4 : (index + 1) * len(frame) // 4]
        groups.append(
            {
                "label": label,
                "facility_count": len(group),
                "area_min_sqft": int(group.it_area_sqft.min()),
                "area_max_sqft": int(group.it_area_sqft.max()),
                "median_density_w_per_sqft": float(
                    group.capacity_density_w_per_sqft.median()
                ),
                "missing_carriers": int(group.onsite_carriers.isna().sum()),
            }
        )
    samples = [
        ("All facilities", frame),
        (
            "Without Dallas and Northern Virginia",
            frame[~frame.market.isin(["dallas", "northern-virginia"])],
        ),
        (
            "Without DFW9–DFW12",
            frame[~frame.facility_code.isin(["DFW9", "DFW10", "DFW11", "DFW12"])],
        ),
    ]
    known = frame.dropna(subset=["onsite_carriers"])
    return {
        "groups": groups,
        "largest_to_smallest_median_ratio": groups[-1]["median_density_w_per_sqft"]
        / groups[0]["median_density_w_per_sqft"],
        "checks": [
            {
                "label": label,
                "facility_count": len(sample),
                "area_density_spearman": rank_correlation(
                    sample, "it_area_sqft", "capacity_density_w_per_sqft"
                ),
            }
            for label, sample in samples
            if label == "All facilities" or len(sample) < len(frame)
        ],
        "power_carriers": {
            "facility_count": len(known),
            "missing_count": len(frame) - len(known),
            "spearman": rank_correlation(known, "critical_it_mw", "onsite_carriers"),
        },
    }


def analyze(
    records: list[FacilityRecord],
    quality: dict,
    run_id: str,
    as_of: datetime,
    source: dict,
    observations: list[dict] | None = None,
) -> OverviewResponse:
    frame = pd.DataFrame([r.model_dump(mode="json") for r in records])
    total_mw = sum(r.critical_it_mw for r in records)
    total_area = sum(r.it_area_sqft for r in records)
    summary = {
        "facility_count": len(records),
        "market_count": len({r.market for r in records}),
        "critical_it_mw": round(total_mw, 6),
        "it_area_sqft": total_area,
        "portfolio_density_w_per_sqft": round(total_mw * 1_000_000 / total_area, 3)
        if total_area
        else None,
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
        summary["top_three_market_facility_count"] = sum(
            m["facility_count"] for m in markets[:3]
        )
        summary["top_three_markets"] = [m["market"] for m in markets[:3]]
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
            "size_density": size_density_analysis(frame),
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
            "facility_evidence": {
                r.facility_code: [
                    o
                    for o in observations or []
                    if o.get("record_level") == "facility"
                    and o.get("facility_url", o["source_url"]) == str(r.detail_url)
                    and o.get("field")
                    in {"critical_it_mw", "it_area_sqft", "onsite_carriers"}
                ]
                for r in records
            },
        },
        methodology={
            "question": "Where is advertised capacity concentrated, how do facilities differ, and how much can we trust the published information?",
            "canonical_values": "Detail main figures take precedence over repeated detail specifications. Market-card values are retained as comparison evidence, never as fallback for missing required detail values.",
            "density_formula": "critical_it_mw * 1000000 / it_area_sqft",
            "density_meaning": "Advertised capacity per IT floor area, not measured consumption, utilization, or energy efficiency.",
            "density_comparison": "The median gives every accepted facility equal weight. Portfolio density divides total MW by total IT floor area on the same rows; it is an area-weighted mean of facility densities.",
            "size_density": "Sort facilities by IT floor area, breaking ties by facility code, and split into four groups with counts as equal as possible. Compare each group's median W/ft². Spearman correlations use average ranks, exclude missing pairs, and are withheld for fewer than five pairs or constant inputs. Excluding Dallas and Northern Virginia, and separately DFW9–DFW12, provides exploratory sensitivity checks; these are not causal estimates.",
            "carrier_coverage": "Missing carrier counts are measured both as a share of accepted facilities and as a share of their total advertised MW. Missing counts are not zero; carrier count does not establish latency or connectivity quality.",
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
