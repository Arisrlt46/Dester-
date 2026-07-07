"""Layer 2, Module 4: Verdict 2 orchestrator.

Runs feed extraction -> feed shares -> feed fare allocation -> combined P&L
-> sensitivities -> verdict. There is no go/no-go flip here -- Verdict 1
already established viability. Verdict 2 answers: what fraction of Delta's
AUS-SLC economic case is local vs. feed?

Runnable via `python -m layer2.verdict2` from the project root. Reads Layer
0/Layer 1 artifacts read-only; does not regenerate any of them.
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
from layer2 import feed_economics, feed_extraction, pnl_with_feed

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "out")
LAYER0_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer1", "out")
VERDICT1_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")

LAYER2_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
FEED_ITINERARIES_PATH = os.path.join(LAYER2_OUT_DIR, "feed_itineraries.parquet")
FEED_ECONOMICS_PATH = os.path.join(LAYER2_OUT_DIR, "feed_economics.parquet")
VERDICT2_OUTPUT_PATH = os.path.join(LAYER2_OUT_DIR, "verdict2.json")

MARKET = "AUS-SLC"
CARRIER = "DL"

TOP_N_FEED_MARKETS = 10
FEED_SHARE_LEVERAGE_WARNING_THRESHOLD = 0.20

CONTRIBUTION_SANITY_TOLERANCE_USD = 1.0


def _annual_capacity_seats(seats_per_departure):
    days_per_year = layer1_pnl.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    return seats_per_departure * layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY * days_per_year


def main():
    os.makedirs(LAYER2_OUT_DIR, exist_ok=True)

    with open(LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)
    with open(VERDICT1_PATH) as f:
        verdict1_data = json.load(f)

    mean_fare = summary["mean_fare"]
    distance_miles = summary["mean_distance_miles"]
    base_pax = verdict1_data["sizing"]["base_pax"]
    predicted_delta_share = verdict1_data["predicted_delta_share"]
    casm_cents = verdict1_data["delta_e175_casm_cents"]

    t100_csv_path = layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)
    seats_per_departure = layer1_pnl.e175_seats_per_departure(t100_csv_path)
    days_per_year = layer1_pnl.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    capacity_seats_annual = _annual_capacity_seats(seats_per_departure)

    local_pax_annual = verdict1_data["expected_load_factor"] * capacity_seats_annual
    local_revenue_annual = verdict1_data["revenue_annual_usd"]

    print("Extracting feed itineraries through SLC...")
    db1b_csv_path = feed_extraction.resolve_csv_path(feed_extraction.DB1B_GLOB_PATTERN)
    feed_df = feed_extraction.extract_feed_itineraries(db1b_csv_path)
    feed_df.to_parquet(FEED_ITINERARIES_PATH, engine="pyarrow", index=False)
    print(f"Wrote {FEED_ITINERARIES_PATH} ({len(feed_df)} feed itineraries)")

    print("Computing Delta's observed share of each feed market...")
    shares_df = feed_economics.compute_feed_shares(feed_df, db1b_csv_path)

    feed_df_fares = feed_economics.allocate_fares(feed_df)
    feed_econ_df = feed_economics.feed_economics(feed_df_fares, shares_df)
    feed_econ_df.to_parquet(FEED_ECONOMICS_PATH, engine="pyarrow", index=False)
    print(f"Wrote {FEED_ECONOMICS_PATH}")

    feed_pax_sample = feed_econ_df["delta_feed_passengers"].sum()
    feed_revenue_sample = feed_econ_df["delta_feed_revenue"].sum()
    feed_pax_annual = layer1_sizing.annualize_sample(feed_pax_sample)
    feed_revenue_annual = layer1_sizing.annualize_sample(feed_revenue_sample)

    combined = pnl_with_feed.combined_pnl(
        local_pax_annual, local_revenue_annual, feed_pax_annual, feed_revenue_annual,
        seats_per_departure, layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY, layer1_pnl.QUARTER_DAYS,
        distance_miles, casm_cents,
    )

    contribution_mismatch = abs(combined["local_contribution"] - verdict1_data["contribution_annual_usd"])
    if contribution_mismatch > CONTRIBUTION_SANITY_TOLERANCE_USD:
        print(
            f"  WARNING: recomputed local contribution (${combined['local_contribution']:,.2f}) does not match "
            f"Verdict 1's stored contribution (${verdict1_data['contribution_annual_usd']:,.2f})"
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

    with open(VERDICT2_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT2_OUTPUT_PATH}")

    print()
    print("=== Verdict 2 summary ===")
    print(f"Total feed itineraries extracted: {len(feed_df)}")
    print(f"Top {TOP_N_FEED_MARKETS} feed markets by Delta revenue:")
    for row in top_feed_markets:
        print(f"  {row['endpoint']:5s} {row['direction']:7s} pax={row['passengers']:,.0f}  revenue=${row['revenue']:,.0f}")
    print()
    print(f"Local pax (annual): {local_pax_annual:,.0f}   Feed pax (annual): {feed_pax_annual:,.0f}   "
          f"Feed share of pax: {feed_share_of_total_pax:.1%}")
    print(f"Local revenue: ${local_revenue_annual:,.0f}   Feed revenue: ${feed_revenue_annual:,.0f}   "
          f"Feed share of revenue: {feed_share_of_total_revenue:.1%}")
    print(f"Local contribution: ${combined['local_contribution']:,.0f}   "
          f"Feed contribution: ${combined['feed_contribution']:,.0f}   "
          f"Total contribution: ${combined['total_contribution']:,.0f}")
    print()
    print(
        f"Layer 3's Shapley-vs-mileage attribution question has "
        f"{feed_share_of_total_revenue:.0%} leverage on Delta's AUS-SLC economics."
    )

    if feed_share_of_total_revenue < FEED_SHARE_LEVERAGE_WARNING_THRESHOLD:
        print()
        print(
            f"*** NOTE: feed share of total revenue ({feed_share_of_total_revenue:.1%}) is below the "
            f"{FEED_SHARE_LEVERAGE_WARNING_THRESHOLD:.0%} threshold. Layer 3's attribution flip question "
            f"would be small potatoes on this market. ***"
        )


if __name__ == "__main__":
    main()
