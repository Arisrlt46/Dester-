"""Layer 2 CPA markup refinement: Verdict 2 with CPA-adjusted CASM.

Mirrors layer2/verdict2.py's orchestration exactly -- feed extraction, feed
economics, and combined P&L are all identical and reused unchanged -- but
sources casm_cents and local pax/revenue from verdict1_cpa.json instead of
verdict1.json. Writes to distinct output paths (including intermediate
parquets) so none of the pre-registered Layer 2 artifacts are touched.
"""

import itertools
import json
import os
from datetime import datetime, timezone

from layer1 import calibration as layer1_calibration
from layer1 import pnl as layer1_pnl
from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer1 import verdict1 as layer1_verdict1
from layer1.cpa_markup.verdict1_cpa import VERDICT1_CPA_OUTPUT_PATH
from layer2 import feed_economics, feed_extraction, pnl_with_feed

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer0", "out")
LAYER0_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")

LAYER2_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
FEED_ITINERARIES_CPA_PATH = os.path.join(LAYER2_OUT_DIR, "feed_itineraries_cpa.parquet")
FEED_ECONOMICS_CPA_PATH = os.path.join(LAYER2_OUT_DIR, "feed_economics_cpa.parquet")
VERDICT2_CPA_OUTPUT_PATH = os.path.join(LAYER2_OUT_DIR, "verdict2_cpa.json")

MARKET = "AUS-SLC"
CARRIER = "DL"
TOP_N_FEED_MARKETS = 10
FEED_SHARE_LEVERAGE_WARNING_THRESHOLD = 0.20


def run_verdict2_cpa():
    os.makedirs(LAYER2_OUT_DIR, exist_ok=True)

    with open(LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)
    with open(VERDICT1_CPA_OUTPUT_PATH) as f:
        verdict1_data = json.load(f)

    mean_fare = summary["mean_fare"]
    distance_miles = summary["mean_distance_miles"]
    base_pax = verdict1_data["sizing"]["base_pax"]
    predicted_delta_share = verdict1_data["predicted_delta_share"]
    casm_cents = verdict1_data["delta_e175_casm_cents"]

    t100_csv_path = layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)
    seats_per_departure = layer1_pnl.e175_seats_per_departure(t100_csv_path)
    days_per_year = layer1_pnl.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    capacity_seats_annual = seats_per_departure * layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY * days_per_year

    local_pax_annual = verdict1_data["expected_load_factor"] * capacity_seats_annual
    local_revenue_annual = verdict1_data["revenue_annual_usd"]

    print("Extracting feed itineraries through SLC (CPA run)...")
    db1b_csv_path = feed_extraction.resolve_csv_path(feed_extraction.DB1B_GLOB_PATTERN)
    feed_df = feed_extraction.extract_feed_itineraries(db1b_csv_path)
    feed_df.to_parquet(FEED_ITINERARIES_CPA_PATH, engine="pyarrow", index=False)
    print(f"Wrote {FEED_ITINERARIES_CPA_PATH} ({len(feed_df)} feed itineraries)")

    print("Computing Delta's observed share of each feed market...")
    shares_df = feed_economics.compute_feed_shares(feed_df, db1b_csv_path)

    feed_df_fares = feed_economics.allocate_fares(feed_df)
    feed_econ_df = feed_economics.feed_economics(feed_df_fares, shares_df)
    feed_econ_df.to_parquet(FEED_ECONOMICS_CPA_PATH, engine="pyarrow", index=False)
    print(f"Wrote {FEED_ECONOMICS_CPA_PATH}")

    feed_pax_sample = feed_econ_df["delta_feed_passengers"].sum()
    feed_revenue_sample = feed_econ_df["delta_feed_revenue"].sum()
    feed_pax_annual = layer1_sizing.annualize_sample(feed_pax_sample)
    feed_revenue_annual = layer1_sizing.annualize_sample(feed_revenue_sample)

    combined = pnl_with_feed.combined_pnl(
        local_pax_annual, local_revenue_annual, feed_pax_annual, feed_revenue_annual,
        seats_per_departure, layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY, layer1_pnl.QUARTER_DAYS,
        distance_miles, casm_cents,
    )

    feed_share_of_total_revenue = (
        feed_revenue_annual / (local_revenue_annual + feed_revenue_annual)
        if (local_revenue_annual + feed_revenue_annual) > 0 else 0.0
    )
    feed_share_of_total_pax = (
        feed_pax_annual / (local_pax_annual + feed_pax_annual)
        if (local_pax_annual + feed_pax_annual) > 0 else 0.0
    )

    market_agg = (
        feed_econ_df.groupby(["beyond_endpoint", "feed_direction"])
        .agg(passengers=("delta_feed_passengers", "sum"), revenue=("delta_feed_revenue", "sum"))
        .reset_index()
    )
    market_agg["passengers"] = market_agg["passengers"].apply(layer1_sizing.annualize_sample)
    market_agg["revenue"] = market_agg["revenue"].apply(layer1_sizing.annualize_sample)
    market_agg = market_agg.sort_values("revenue", ascending=False).head(TOP_N_FEED_MARKETS)
    top_feed_markets = [
        {
            "endpoint": row["beyond_endpoint"],
            "direction": row["feed_direction"],
            "passengers": float(row["passengers"]),
            "revenue": float(row["revenue"]),
        }
        for _, row in market_agg.iterrows()
    ]

    print("Running sensitivity grid...")
    local_vs_feed_by_sensitivity = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, boardings, pnl_result, _ = layer1_verdict1._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        local_vs_feed_by_sensitivity.append(
            {
                "uplift": uplift,
                "recapture": recapture,
                "alpha": alpha,
                "local_pax": boardings["expected_boarded"] * days_per_year,
                "feed_pax": feed_pax_annual,
                "local_rev": pnl_result["revenue"],
                "feed_rev": feed_revenue_annual,
            }
        )

    output = {
        "market": MARKET,
        "carrier": CARRIER,
        "local_contribution_annual_usd": combined["local_contribution"],
        "feed_contribution_annual_usd": combined["feed_contribution"],
        "total_contribution_annual_usd": combined["total_contribution"],
        "feed_share_of_total_revenue": feed_share_of_total_revenue,
        "feed_share_of_total_pax": feed_share_of_total_pax,
        "top_feed_markets": top_feed_markets,
        "local_vs_feed_by_sensitivity": local_vs_feed_by_sensitivity,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT2_CPA_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT2_CPA_OUTPUT_PATH}")

    return output, feed_econ_df


if __name__ == "__main__":
    run_verdict2_cpa()
