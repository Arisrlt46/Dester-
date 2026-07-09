"""Layer 3 CPA markup refinement: Verdict 3 with CPA-adjusted CASM.

Mirrors layer3/verdict3.py's orchestration exactly -- standalone fares,
Shapley/mileage attribution, and pnl_by_regime are all identical and reused
unchanged -- but sources casm_cents, local pax/revenue, and breakeven load
factor from verdict1_cpa.json instead of verdict1.json.

Runs the whole three-verdict chain end-to-end (verdict1_cpa -> verdict2_cpa
-> verdict3_cpa) and writes all three CPA-adjusted JSONs. Runnable via
`python -m layer3.cpa_markup.verdict3_cpa`.
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
from layer1.cpa_markup import pnl_cpa
from layer1.cpa_markup.verdict1_cpa import VERDICT1_CPA_OUTPUT_PATH, run_verdict1_cpa
from layer2.cpa_markup.verdict2_cpa import FEED_ITINERARIES_CPA_PATH, run_verdict2_cpa
from layer3 import attribution, pnl_by_regime, standalone_fares

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer0", "out")
LAYER0_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")
AUS_SLC_PARQUET_PATH = os.path.join(LAYER0_OUT_DIR, "aus_slc_market.parquet")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer1", "out")
VERDICT1_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")

LAYER3_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
STANDALONE_FARES_CPA_PATH = os.path.join(LAYER3_OUT_DIR, "standalone_fares_cpa.parquet")
ATTRIBUTION_CPA_PATH = os.path.join(LAYER3_OUT_DIR, "attribution_by_itinerary_cpa.parquet")
VERDICT3_CPA_OUTPUT_PATH = os.path.join(LAYER3_OUT_DIR, "verdict3_cpa.json")

MARKET = "AUS-SLC"
CARRIER = "DL"
REGIMES = ["mileage", "shapley"]


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def run_verdict3_cpa(verdict1_data, feed_econ_df):
    os.makedirs(LAYER3_OUT_DIR, exist_ok=True)

    with open(LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)

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

    feed_itineraries_df = pd.read_parquet(FEED_ITINERARIES_CPA_PATH)
    endpoints = sorted(feed_itineraries_df["beyond_endpoint"].unique())

    db1b_csv_path = standalone_fares.resolve_csv_path(standalone_fares.DB1B_GLOB_PATTERN)
    standalone_df = standalone_fares.standalone_fares_slc_beyond(db1b_csv_path, endpoints)
    standalone_df.to_parquet(STANDALONE_FARES_CPA_PATH, engine="pyarrow", index=False)
    print(f"Wrote {STANDALONE_FARES_CPA_PATH}")

    print("Computing mileage and Shapley attribution per feed itinerary...")
    attribution_df = attribution.attribute_all(feed_itineraries_df, standalone_df, v_a)
    attribution_df.to_parquet(ATTRIBUTION_CPA_PATH, engine="pyarrow", index=False)
    print(f"Wrote {ATTRIBUTION_CPA_PATH}")

    negative_phi_a_count = int(attribution_df["phi_A_negative"].sum())
    valid_delta = attribution_df["delta"].dropna()
    mean_delta = float(valid_delta.mean())
    median_delta = float(valid_delta.median())

    joined = feed_econ_df.merge(
        attribution_df[["MktID", "phi_A", "aus_slc_fare_mileage"]], on="MktID", how="left"
    )
    joined["phi_A_filled"] = joined["phi_A"].fillna(joined["aus_slc_fare_mileage"])

    feed_revenue_mileage_sample = float((joined["delta_feed_passengers"] * joined["aus_slc_fare_mileage"]).sum())
    feed_revenue_shapley_sample = float((joined["delta_feed_passengers"] * joined["phi_A_filled"]).sum())

    feed_pax_annual = layer1_sizing.annualize_sample(feed_econ_df["delta_feed_passengers"].sum())
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
        "mean_delta": mean_delta,
        "median_delta": median_delta,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT3_CPA_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT3_CPA_OUTPUT_PATH}")

    return output


def main():
    print("=" * 60)
    print("VERDICT 1 -- AUS-SLC (CPA markup)")
    print("=" * 60)
    v1_cpa = run_verdict1_cpa()

    print()
    print("=" * 60)
    print("VERDICT 2 -- AUS-SLC (CPA markup)")
    print("=" * 60)
    v2_cpa, feed_econ_df = run_verdict2_cpa()

    print()
    print("=" * 60)
    print("VERDICT 3 -- AUS-SLC (CPA markup)")
    print("=" * 60)
    v3_cpa = run_verdict3_cpa(v1_cpa, feed_econ_df)

    with open(VERDICT1_PATH) as f:
        v1_orig = json.load(f)
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "layer2", "out", "verdict2.json")) as f:
        v2_orig = json.load(f)
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "layer3", "out", "verdict3.json")) as f:
        v3_orig = json.load(f)

    orig_mileage = next(r for r in v3_orig["attribution_regimes"] if r["regime"] == "mileage")
    orig_shapley = next(r for r in v3_orig["attribution_regimes"] if r["regime"] == "shapley")
    cpa_mileage = next(r for r in v3_cpa["attribution_regimes"] if r["regime"] == "mileage")
    cpa_shapley = next(r for r in v3_cpa["attribution_regimes"] if r["regime"] == "shapley")

    print()
    print("=" * 72)
    print(f"{'':32s} {'ORIGINAL (v1)':18s} {'CPA-ADJUSTED':18s}")
    print("=" * 72)

    def row(label, orig, cpa):
        print(f"{label:32s} {orig:18s} {cpa:18s}")

    row("SkyWest raw CASM (cents/ASM)", f"{v1_orig['delta_e175_casm_cents']:.3f}", f"{v1_cpa['raw_skywest_casm_cents']:.3f}")
    row("Delta effective CASM", f"{v1_orig['delta_e175_casm_cents']:.3f}", f"{v1_cpa['delta_e175_casm_cents']:.3f}")
    row("V1 revenue", f"${v1_orig['revenue_annual_usd']/1e6:.2f}M", f"${v1_cpa['revenue_annual_usd']/1e6:.2f}M")
    row("V1 cost", f"${v1_orig['cost_annual_usd']/1e6:.2f}M", f"${v1_cpa['cost_annual_usd']/1e6:.2f}M")
    row("V1 contribution", f"${v1_orig['contribution_annual_usd']/1e6:.2f}M", f"${v1_cpa['contribution_annual_usd']/1e6:.2f}M")
    row("V1 verdict", v1_orig["verdict"].upper(), v1_cpa["verdict"].upper())
    row("V2 total contribution", f"${v2_orig['total_contribution_annual_usd']/1e6:.2f}M", f"${v2_cpa['total_contribution_annual_usd']/1e6:.2f}M")
    row("V3 contribution (mileage)", f"${orig_mileage['total_contribution_annual_usd']/1e6:.2f}M", f"${cpa_mileage['total_contribution_annual_usd']/1e6:.2f}M")
    row("V3 contribution (Shapley)", f"${orig_shapley['total_contribution_annual_usd']/1e6:.2f}M", f"${cpa_shapley['total_contribution_annual_usd']/1e6:.2f}M")
    row("V3 leverage", f"{v3_orig['attribution_leverage_pct']:.2%}", f"{v3_cpa['attribution_leverage_pct']:.2%}")
    row("V3 verdict (mileage)", orig_mileage["verdict"].upper(), cpa_mileage["verdict"].upper())
    row("V3 verdict (Shapley)", orig_shapley["verdict"].upper(), cpa_shapley["verdict"].upper())
    row("V3 verdict flipped?", "YES" if v3_orig["verdict_flipped"] else "NO", "YES" if v3_cpa["verdict_flipped"] else "NO")

    flips = []
    if v1_orig["verdict"] != v1_cpa["verdict"]:
        flips.append(f"Verdict 1: {v1_orig['verdict'].upper()} -> {v1_cpa['verdict'].upper()}")
    if orig_mileage["verdict"] != cpa_mileage["verdict"]:
        flips.append(f"Verdict 3 (mileage): {orig_mileage['verdict'].upper()} -> {cpa_mileage['verdict'].upper()}")
    if orig_shapley["verdict"] != cpa_shapley["verdict"]:
        flips.append(f"Verdict 3 (Shapley): {orig_shapley['verdict'].upper()} -> {cpa_shapley['verdict'].upper()}")

    print()
    if flips:
        print("*** VERDICT(S) FLIPPED UNDER CPA MARKUP: ***")
        for f_desc in flips:
            print(f"  {f_desc}")
    else:
        print(f"No verdicts flipped under the {pnl_cpa.CPA_MARKUP}x CPA markup. Contribution shrinks; GO holds throughout.")


if __name__ == "__main__":
    main()
