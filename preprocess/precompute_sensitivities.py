"""Batch-precomputes the 48-combination x 2-regime sensitivity grid for
every candidate market in layer4/out/market_screener.parquet, using the
on-demand engine (dashboard.engine). Gives every Catalog market the same
sensitivity depth as the two hand-analyzed featured markets (AUS-SLC,
ATL-SAT), and produces a research-grade distribution of attribution
leverage across real US spoke-to-hub markets.

Run via: python -m preprocess.precompute_sensitivities

Performance note: a naive implementation (calling run_dester_engine once
per grid point, 934 markets x 48 points) projected to ~80+ minutes, driven
by two costs that are actually invariant across a market's whole grid --
re-reading the 120MB T-100 CSV and a per-feed-endpoint DataFrame scan
(934 catalog markets average ~85 feed endpoints each). Both were cached /
vectorized in dashboard.engine (see _load_t100_features,
_cached_airport_carrier_share, and the vectorized feed-share/v(B) lookup in
_resolve_market_context) without changing run_dester_engine's output --
verified against reference outputs captured before that change. This script
then resolves each market's context ONCE (engine._resolve_market_context)
and re-scores all 48 grid points against it cheaply
(engine._score_grid_point, pure arithmetic, ~0.04ms/point), bringing the
full 934-market precompute to ~2-3 minutes.

Also discovered along the way: this engine's `alpha` parameter has no effect
on its output -- unlike the real Layer 1 pipeline, it never implements the
S-curve, so the 3 alpha slices recorded per (market, uplift, recapture,
regime) below are numerically identical. Recorded in full per the requested
schema regardless (not silently collapsed), since the schema is meant to
match the featured markets' grid shape.
"""

import os
import sys
import time

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dashboard import engine
from dashboard.catalog import load_catalog

DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
SENSITIVITIES_OUT_PATH = os.path.join(DATA_DIR, "catalog_sensitivities.parquet")
SUMMARY_OUT_PATH = os.path.join(DATA_DIR, "catalog_summary.parquet")

# Matches Layers 1-3's own sensitivity-grid convention.
UPLIFT_GRID = [0.10, 0.15, 0.20, 0.25]
RECAPTURE_GRID = [0.10, 0.15, 0.20, 0.30]
ALPHA_GRID = [1.4, 1.6, 1.8]

DEFAULT_UPLIFT = 0.15
DEFAULT_RECAPTURE = 0.15
DEFAULT_ALPHA = 1.6

CASM_MARKUP = 1.12
PROGRESS_EVERY = 25


def _score_market(row):
    """Returns ((sensitivity_rows, summary_row), None) on success, or
    (None, error_message) if the engine can't resolve this market (e.g. no
    aggregate data, no nonstop choice-set row for the dominant carrier, no
    aircraft/CASM match) -- callers should skip and continue."""
    context = engine._resolve_market_context(row.hub, row.spoke, row.dominant_carrier, CASM_MARKUP)
    if context.get("error"):
        return None, context["error"]

    sensitivity_rows = []
    mileage_verdicts = set()
    shapley_verdicts = set()
    flipped_anywhere = False
    default_regimes = None
    default_result = None

    for u in UPLIFT_GRID:
        for rc in RECAPTURE_GRID:
            for a in ALPHA_GRID:
                result = engine._score_grid_point(context, u, rc, a)
                regimes = {r["regime"]: r for r in result["attribution_regimes"]}

                mileage_verdicts.add(regimes["mileage"]["verdict"])
                shapley_verdicts.add(regimes["shapley"]["verdict"])
                if regimes["mileage"]["verdict"] != regimes["shapley"]["verdict"]:
                    flipped_anywhere = True

                for regime_name, regime_entry in regimes.items():
                    sensitivity_rows.append(
                        {
                            "market_pair": row.market_pair,
                            "uplift": u,
                            "recapture": rc,
                            "alpha": a,
                            "regime": regime_name,
                            "contribution": regime_entry["total_contribution_annual_usd"],
                            "verdict": regime_entry["verdict"],
                        }
                    )

                if u == DEFAULT_UPLIFT and rc == DEFAULT_RECAPTURE and a == DEFAULT_ALPHA:
                    default_regimes = regimes
                    default_result = result

    mileage_contrib_default = default_regimes["mileage"]["total_contribution_annual_usd"]
    shapley_contrib_default = default_regimes["shapley"]["total_contribution_annual_usd"]
    attribution_leverage = abs(mileage_contrib_default - shapley_contrib_default) / max(abs(mileage_contrib_default), 1)

    summary_row = {
        "market_pair": row.market_pair,
        "headline_verdict_mileage": default_regimes["mileage"]["verdict"],
        "headline_verdict_shapley": default_regimes["shapley"]["verdict"],
        "robust_mileage": len(mileage_verdicts) == 1,
        "robust_shapley": len(shapley_verdicts) == 1,
        "verdict_flipped_anywhere": flipped_anywhere,
        "attribution_leverage": attribution_leverage,
        "feed_share": row.feed_share,
        "size_bucket": row.size_bucket,
        # Beyond the literal per-point schema above: the app's Verdict 1/2
        # tab sections need a local-only revenue/cost/contribution headline
        # to render at all, which the compact 48x2-row sensitivity schema
        # deliberately doesn't carry per grid point. Captured once here at
        # the default (uplift=0.15, recapture=0.15, alpha=1.6) point --
        # already computed for free as part of default_result above.
        "carrier": default_result["carrier"],
        "verdict_local": default_result["verdict"],
        "revenue_annual_usd": default_result["revenue_annual_usd"],
        "cost_annual_usd": default_result["cost_annual_usd"],
        "contribution_annual_usd": default_result["contribution_annual_usd"],
        "predicted_delta_share": default_result["predicted_delta_share"],
        "expected_load_factor": default_result["expected_load_factor"],
        "breakeven_load_factor": default_result["breakeven_load_factor"],
        "local_contribution_annual_usd": default_result["local_contribution_annual_usd"],
        "feed_contribution_annual_usd": default_result["feed_contribution_annual_usd"],
        "feed_share_of_total_revenue": default_result["feed_share_of_total_revenue"],
        "is_hub_spoke_pair": default_result["is_hub_spoke_pair"],
    }
    return (sensitivity_rows, summary_row), None


def main():
    screener = load_catalog()
    print(f"Loaded {len(screener)} candidate markets from the Wave 1 screener")

    all_sensitivity_rows = []
    all_summary_rows = []
    skipped = []

    start = time.time()
    for i, row in enumerate(screener.itertuples(index=False), start=1):
        outcome, error = _score_market(row)
        if error:
            skipped.append((row.market_pair, error))
        else:
            sens_rows, summary_row = outcome
            all_sensitivity_rows.extend(sens_rows)
            all_summary_rows.append(summary_row)

        if i % PROGRESS_EVERY == 0 or i == len(screener):
            elapsed = time.time() - start
            print(f"[{i}/{len(screener)}] elapsed={elapsed:.0f}s, ok={len(all_summary_rows)}, skipped={len(skipped)}")

    os.makedirs(DATA_DIR, exist_ok=True)
    sensitivities_df = pd.DataFrame(all_sensitivity_rows)
    summary_df = pd.DataFrame(all_summary_rows)
    sensitivities_df.to_parquet(SENSITIVITIES_OUT_PATH, index=False)
    summary_df.to_parquet(SUMMARY_OUT_PATH, index=False)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed / 60:.1f} min.")
    print(f"  {SENSITIVITIES_OUT_PATH}: {len(sensitivities_df):,} rows")
    print(f"  {SUMMARY_OUT_PATH}: {len(summary_df):,} rows")
    print(f"  skipped: {len(skipped)}")
    for market_pair, err in skipped:
        print(f"    skipped {market_pair}: {err}")

    if len(summary_df):
        flipped_count = int(summary_df["verdict_flipped_anywhere"].sum())
        print(f"  verdict_flipped_anywhere == True: {flipped_count} / {len(summary_df)} markets")


if __name__ == "__main__":
    main()
