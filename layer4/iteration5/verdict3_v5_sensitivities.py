"""Layer 4 Iteration 5 follow-up: regime-aware sensitivity grid for ATL-SAT
under the v5 (lambda=15 shrinkage) model.

layer4/verdict3_atl_sat.py (reused unchanged by verdict4_v5.py) never
computes a regime-aware sensitivity sweep the way layer3/verdict3.py does
for AUS-SLC -- verdict4_v5.json's only sensitivities are Verdict 1's
load-factor-based 48-entry grid (it survives the {**v1,**v2,**v3} merge
because v2/v3's own dicts never define a competing "sensitivities" key).

This retroactively computes the same 48-combination x 2-regime (96-row)
sweep for ATL-SAT, reusing already-written Iteration 5 artifacts on disk
(verdict4_v5.json, atl_sat_local/feed/attribution parquets) -- no
re-streaming of the raw DB1B CSV needed.

Writes a standalone artifact: layer4/out/verdict3_v5_sensitivities.json.
Does not modify verdict4_v5.json or any other existing file.
"""

import itertools
import json
import os

import pandas as pd

from layer1 import calibration as layer1_calibration
from layer1 import pnl as layer1_pnl
from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer3 import pnl_by_regime
from layer4 import aircraft_id, config, verdict1_atl_sat

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer4", "out")
VERDICT4_V5_PATH = os.path.join(LAYER4_OUT_DIR, "verdict4_v5.json")
ATL_SAT_LOCAL_PATH = os.path.join(LAYER4_OUT_DIR, "atl_sat_local.parquet")
ATL_SAT_FEED_PATH = os.path.join(LAYER4_OUT_DIR, "atl_sat_feed.parquet")
ATL_SAT_ATTRIBUTION_PATH = os.path.join(LAYER4_OUT_DIR, "atl_sat_attribution.parquet")
OUTPUT_PATH = os.path.join(LAYER4_OUT_DIR, "verdict3_v5_sensitivities.json")

REGIMES = ["mileage", "shapley"]


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def main():
    with open(VERDICT4_V5_PATH) as f:
        v5_data = json.load(f)

    base_pax = v5_data["sizing"]["base_pax"]
    predicted_delta_share = v5_data["predicted_delta_share"]
    casm_cents = v5_data["delta_e175_casm_cents"]

    local_df = pd.read_parquet(ATL_SAT_LOCAL_PATH)
    mean_fare = float(local_df["MktFare"].mean())
    distance_miles = float(local_df["MktDistance"].mean())

    t100_csv_path = layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)
    p52_csv_path = os.path.join(os.path.dirname(__file__), "..", "..", "layer1", "data", "T_F41SCHEDULE_P52.csv")
    _, seats_per_departure, _ = aircraft_id.resolve_dominant_aircraft_type_code(
        config.DOMINANT_CARRIER, config.AIRCRAFT_SEATS_MIN, config.AIRCRAFT_SEATS_MAX,
        t100_csv_path, p52_csv_path, year=config.YEAR, quarter=config.QUARTER,
    )

    feed_econ_df = pd.read_parquet(ATL_SAT_FEED_PATH)
    attribution_df = pd.read_parquet(ATL_SAT_ATTRIBUTION_PATH)

    assert attribution_df["MktID"].is_unique, "MktID must be the unique per-row key before joining"
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

    days_per_year = config.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS

    print("Running regime-aware sensitivity grid (48 combinations x 2 regimes) for ATL-SAT (v5)...")
    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, boardings, pnl_result, _ = verdict1_atl_sat._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        sens_local_pax = boardings["expected_boarded"] * days_per_year
        sens_local_revenue = pnl_result["revenue"]

        for regime in REGIMES:
            sens_pnl = pnl_by_regime.pnl_by_regime(
                sens_local_pax, sens_local_revenue, feed_pax_annual, {regime: feed_revenue_by_regime_annual[regime]},
                seats_per_departure, config.PROPOSED_FREQ_DAILY, config.QUARTER_DAYS,
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

    output = {"market": config.MARKET_PAIR, "carrier": config.DOMINANT_CARRIER, "sensitivities": sensitivities}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {OUTPUT_PATH} ({len(sensitivities)} rows)")

    print()
    print("Sample rows (identical params, both regimes):")
    sample_uplift, sample_recapture, sample_alpha = layer1_sizing.UPLIFT_SENSITIVITY_VALUES[0], layer1_spill.RECAPTURE_SENSITIVITY_VALUES[0], layer1_scurve.ALPHA_SENSITIVITY_VALUES[0]
    sample_rows = [
        s for s in sensitivities
        if s["uplift"] == sample_uplift and s["recapture"] == sample_recapture and s["alpha"] == sample_alpha
    ]
    for row in sample_rows:
        print(f"  {row}")

    verdict_counts = {}
    for regime in REGIMES:
        regime_rows = [s for s in sensitivities if s["regime"] == regime]
        verdict_counts[regime] = {v: sum(1 for r in regime_rows if r["verdict"] == v) for v in {"go", "no_go"}}
    print()
    print(f"Verdict counts by regime (of 48 each): {verdict_counts}")


if __name__ == "__main__":
    main()
