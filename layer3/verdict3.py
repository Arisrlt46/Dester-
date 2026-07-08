"""Layer 3, Module 4: Verdict 3 orchestrator.

Runs standalone fares -> attribution -> both P&Ls -> sensitivity grid ->
verdict comparison. Answers DESTER's central research question: does
Delta's AUS-SLC verdict change depending on the connecting-revenue
attribution regime (mileage proration vs. Shapley value)?

Runnable via `python -m layer3.verdict3` from the project root. Reads Layer
0/1/2 artifacts read-only; does not regenerate any of them.
"""

import itertools
import json
import os
from datetime import datetime, timezone

import pandas as pd

from layer1 import calibration as layer1_calibration
from layer1 import pnl as layer1_pnl
from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer1 import verdict1 as layer1_verdict1
from layer3 import attribution, pnl_by_regime, standalone_fares

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "out")
LAYER0_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")
AUS_SLC_PARQUET_PATH = os.path.join(LAYER0_OUT_DIR, "aus_slc_market.parquet")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer1", "out")
VERDICT1_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")

LAYER2_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer2", "out")
FEED_ITINERARIES_PATH = os.path.join(LAYER2_OUT_DIR, "feed_itineraries.parquet")
FEED_ECONOMICS_PATH = os.path.join(LAYER2_OUT_DIR, "feed_economics.parquet")

LAYER3_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
STANDALONE_FARES_PATH = os.path.join(LAYER3_OUT_DIR, "standalone_fares.parquet")
ATTRIBUTION_PATH = os.path.join(LAYER3_OUT_DIR, "attribution_by_itinerary.parquet")
VERDICT3_OUTPUT_PATH = os.path.join(LAYER3_OUT_DIR, "verdict3.json")

MARKET = "AUS-SLC"
CARRIER = "DL"
REGIMES = ["mileage", "shapley"]


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def main():
    os.makedirs(LAYER3_OUT_DIR, exist_ok=True)

    with open(LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)
    with open(VERDICT1_PATH) as f:
        verdict1_data = json.load(f)

    mean_fare = summary["mean_fare"]
    distance_miles = summary["mean_distance_miles"]
    base_pax = verdict1_data["sizing"]["base_pax"]
    predicted_delta_share = verdict1_data["predicted_delta_share"]
    casm_cents = verdict1_data["delta_e175_casm_cents"]
    breakeven_load_factor = verdict1_data["breakeven_load_factor"]

    t100_csv_path = layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)
    seats_per_departure = layer1_pnl.e175_seats_per_departure(t100_csv_path)
    days_per_year = layer1_pnl.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    capacity_seats_annual = seats_per_departure * layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY * days_per_year
    local_pax_annual = verdict1_data["expected_load_factor"] * capacity_seats_annual
    local_revenue_annual = verdict1_data["revenue_annual_usd"]

    print("Computing standalone coalition values...")
    v_a = standalone_fares.standalone_fare_aus_slc(AUS_SLC_PARQUET_PATH)
    print(f"  v(A) AUS-SLC standalone nonstop fare: ${v_a:.2f}")

    feed_itineraries_df = pd.read_parquet(FEED_ITINERARIES_PATH)
    feed_economics_df = pd.read_parquet(FEED_ECONOMICS_PATH)
    endpoints = sorted(feed_itineraries_df["beyond_endpoint"].unique())

    db1b_csv_path = standalone_fares.resolve_csv_path(standalone_fares.DB1B_GLOB_PATTERN)
    standalone_df = standalone_fares.standalone_fares_slc_beyond(db1b_csv_path, endpoints)
    standalone_df.to_parquet(STANDALONE_FARES_PATH, engine="pyarrow", index=False)
    print(f"Wrote {STANDALONE_FARES_PATH}")

    flagged = standalone_df[standalone_df["flagged"]]
    if len(flagged):
        print(f"  {len(flagged)} endpoint(s) flagged (zero observations or fare outlier):")
        for _, row in flagged.iterrows():
            print(f"    {row['beyond_endpoint']}: n={row['n_observations']}, mean_fare={row['mean_standalone_fare']}")

    print("Computing mileage and Shapley attribution per feed itinerary...")
    attribution_df = attribution.attribute_all(feed_itineraries_df, standalone_df, v_a)
    attribution_df.to_parquet(ATTRIBUTION_PATH, engine="pyarrow", index=False)
    print(f"Wrote {ATTRIBUTION_PATH}")

    negative_phi_a_count = int(attribution_df["phi_A_negative"].sum())
    valid_delta = attribution_df["delta"].dropna()
    mean_delta = float(valid_delta.mean())
    median_delta = float(valid_delta.median())
    missing_v_b_count = int(attribution_df["phi_A"].isna().sum())

    joined = feed_economics_df.merge(
        attribution_df[["MktID", "phi_A", "aus_slc_fare_mileage"]], on="MktID", how="left"
    )
    # A single itinerary (endpoint with zero standalone observations) has no phi_A;
    # fall back to its mileage fare so it doesn't propagate NaN into the regime total.
    joined["phi_A_filled"] = joined["phi_A"].fillna(joined["aus_slc_fare_mileage"])

    feed_revenue_mileage_sample = float((joined["delta_feed_passengers"] * joined["aus_slc_fare_mileage"]).sum())
    feed_revenue_shapley_sample = float((joined["delta_feed_passengers"] * joined["phi_A_filled"]).sum())

    feed_pax_annual = layer1_sizing.annualize_sample(feed_economics_df["delta_feed_passengers"].sum())
    feed_revenue_by_regime_annual = {
        "mileage": layer1_sizing.annualize_sample(feed_revenue_mileage_sample),
        "shapley": layer1_sizing.annualize_sample(feed_revenue_shapley_sample),
    }

    regime_pnls = pnl_by_regime.pnl_by_regime(
        local_pax_annual, local_revenue_annual, feed_pax_annual, feed_revenue_by_regime_annual,
        seats_per_departure, layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY, layer1_pnl.QUARTER_DAYS,
        casm_cents, distance_miles,
    )

    attribution_regimes = []
    for regime in REGIMES:
        pnl_result = regime_pnls[regime]
        attribution_regimes.append(
            {
                "regime": regime,
                "feed_revenue_annual_usd": feed_revenue_by_regime_annual[regime],
                "total_revenue_annual_usd": pnl_result["total_revenue"],
                "total_contribution_annual_usd": pnl_result["total_contribution"],
                "expected_load_factor": pnl_result["total_load_factor"],
                "breakeven_load_factor": breakeven_load_factor,
                "verdict": _verdict_from_contribution(pnl_result["total_contribution"]),
            }
        )

    contribution_mileage = regime_pnls["mileage"]["total_contribution"]
    contribution_shapley = regime_pnls["shapley"]["total_contribution"]
    attribution_delta_usd = contribution_shapley - contribution_mileage
    attribution_leverage_pct = (
        abs(attribution_delta_usd) / contribution_mileage if contribution_mileage != 0 else float("inf")
    )
    verdict_flipped = attribution_regimes[0]["verdict"] != attribution_regimes[1]["verdict"]

    print("Running sensitivity grid (48 combinations x 2 regimes)...")
    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, boardings, pnl_result, _ = layer1_verdict1._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        sens_local_pax = boardings["expected_boarded"] * days_per_year
        sens_local_revenue = pnl_result["revenue"]

        for regime in REGIMES:
            sens_pnl = pnl_by_regime.pnl_by_regime(
                sens_local_pax, sens_local_revenue, feed_pax_annual, {regime: feed_revenue_by_regime_annual[regime]},
                seats_per_departure, layer1_verdict1.DELTA_PROPOSED_FREQUENCY_PER_DAY, layer1_pnl.QUARTER_DAYS,
                casm_cents, distance_miles,
            )[regime]
            sensitivities.append(
                {
                    "uplift": uplift,
                    "recapture": recapture,
                    "alpha": alpha,
                    "regime": regime,
                    "verdict": _verdict_from_contribution(sens_pnl["total_contribution"]),
                    "contribution": sens_pnl["total_contribution"],
                }
            )

    output = {
        "market": MARKET,
        "carrier": CARRIER,
        "attribution_regimes": attribution_regimes,
        "attribution_delta_usd": attribution_delta_usd,
        "attribution_leverage_pct": attribution_leverage_pct,
        "verdict_flipped": verdict_flipped,
        "negative_phi_a_count": negative_phi_a_count,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT3_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT3_OUTPUT_PATH}")

    print()
    print("=== Verdict 3 summary ===")
    print(f"Total feed itineraries attributed: {len(attribution_df)}")
    if missing_v_b_count:
        print(f"  ({missing_v_b_count} itinerary excluded from delta stats / fell back to mileage fare for revenue totals: no standalone fare data)")
    print(f"Mean Shapley-vs-mileage delta on AUS-SLC fare: ${mean_delta:+.2f}   Median: ${median_delta:+.2f}")
    print(f"Negative phi_A count: {negative_phi_a_count} of {len(attribution_df)}")
    print()
    for regime_data in attribution_regimes:
        print(
            f"[{regime_data['regime'].upper()}] feed revenue: ${regime_data['feed_revenue_annual_usd']:,.0f}  "
            f"total revenue: ${regime_data['total_revenue_annual_usd']:,.0f}  "
            f"total contribution: ${regime_data['total_contribution_annual_usd']:,.0f}  "
            f"verdict: {regime_data['verdict'].upper()}"
        )
    print()
    print(f"Attribution delta (Shapley - mileage) on total contribution: ${attribution_delta_usd:+,.0f}")
    print(f"Attribution leverage: {attribution_leverage_pct:.2%}")

    if verdict_flipped:
        print()
        print(
            "*** VERDICT FLIPPED between attribution regimes. Given Layer 2's 13% feed leverage, this is a "
            "genuinely surprising result and warrants careful diagnosis before publication. ***"
        )
    else:
        print()
        print(
            f"Verdict did NOT flip ({attribution_regimes[0]['verdict'].upper()} under both regimes). This is the "
            f"expected honest null result on the pre-registered AUS-SLC market: feed leverage (13%) is too small "
            f"for the attribution mechanism to change the go/no-go decision here. Layer 4 will apply the same "
            f"three-verdict engine to a hub-heavy market with more leverage."
        )


if __name__ == "__main__":
    main()
