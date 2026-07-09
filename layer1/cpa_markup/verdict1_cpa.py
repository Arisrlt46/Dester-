"""Layer 1 CPA markup refinement, Module 2: Verdict 1 with CPA-adjusted CASM.

Mirrors layer1/verdict1.py's orchestration exactly -- logit, sizing,
S-curve, spill are all identical and reused unchanged (imported directly,
including verdict1.py's own private helpers) -- swapping only the CASM
source: pnl_cpa.compute_delta_e175_casm_cpa instead of
pnl.compute_delta_e175_casm. Writes to a distinct output path so the
pre-registered verdict1.json stays untouched.
"""

import itertools
import json
import os
from datetime import datetime, timezone

import pandas as pd

from layer1 import calibration, logit, pnl, scurve, sizing, spill
from layer1 import verdict1 as verdict1_v1
from layer1.cpa_markup import pnl_cpa

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
VERDICT1_CPA_OUTPUT_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1_cpa.json")


def run_verdict1_cpa():
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)

    with open(verdict1_v1.LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)
    aus_slc_df = pd.read_parquet(verdict1_v1.AUS_SLC_PARQUET_PATH)
    mean_fare = summary["mean_fare"]
    distance_miles = summary["mean_distance_miles"]

    t100_csv_path = calibration.resolve_csv_path(calibration.T100_GLOB_PATTERN)
    p52_csv_path = calibration.resolve_csv_path(verdict1_v1.P52_GLOB_PATTERN)

    print("Building AUS-SLC choice set...")
    t100_freq_features = calibration.load_t100_features(t100_csv_path)
    airport_carrier_share = verdict1_v1._t100_airport_carrier_share(t100_csv_path)

    real_choice_set = verdict1_v1._build_real_choice_set(aus_slc_df, t100_freq_features, airport_carrier_share)
    delta_row = verdict1_v1._synthetic_delta_row(mean_fare, airport_carrier_share)
    choice_set = pd.concat([real_choice_set, pd.DataFrame([delta_row])], ignore_index=True)
    print(f"  choice set: {list(choice_set['carrier'])}")

    coefficients = logit.load_coefficients(verdict1_v1.LOGIT_COEFFICIENTS_PATH)
    predicted = logit.predict_shares(choice_set, coefficients)
    predicted_delta_share = float(predicted[choice_set["carrier"] == verdict1_v1.CARRIER].iloc[0])

    delta_freq = float(verdict1_v1.DELTA_PROPOSED_FREQUENCY_PER_DAY)
    incumbent_freqs = verdict1_v1._aus_slc_segment_daily_frequencies(t100_csv_path)
    all_freqs = [delta_freq] + list(incumbent_freqs.values())
    scurve_share_value = scurve.scurve_share(delta_freq, all_freqs, alpha=scurve.DEFAULT_ALPHA)

    sizing_result = sizing.market_size(verdict1_v1.LAYER0_SUMMARY_PATH, uplift=sizing.DEFAULT_STIMULATION_UPLIFT)
    base_pax = sizing_result["base_pax"]

    print("Resolving Delta E175 CPA-effective CASM...")
    casm_result = pnl_cpa.compute_delta_e175_casm_cpa(p52_csv_path, t100_csv_path)
    seats_per_departure = pnl.e175_seats_per_departure(t100_csv_path)
    casm_cents = casm_result["casm_cents_per_asm"]
    print(f"  SkyWest raw CASM: {casm_result['raw_casm_cents_per_asm']:.3f} cents/ASM")
    print(f"  Delta CPA-effective CASM ({pnl_cpa.CPA_MARKUP}x): {casm_cents:.3f} cents/ASM")

    sized_pax, boardings, pnl_result, verdict = verdict1_v1._run_scenario(
        base_pax, predicted_delta_share, sizing.DEFAULT_STIMULATION_UPLIFT, spill.DEFAULT_RECAPTURE_RATE,
        seats_per_departure, casm_cents, mean_fare, distance_miles,
    )

    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        sizing.UPLIFT_SENSITIVITY_VALUES, spill.RECAPTURE_SENSITIVITY_VALUES, scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, _, sens_pnl, sens_verdict = verdict1_v1._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        sensitivities.append(
            {
                "uplift": uplift,
                "recapture": recapture,
                "alpha": alpha,
                "verdict": sens_verdict,
                "expected_lf": sens_pnl["expected_load_factor"],
                "breakeven_lf": sens_pnl["breakeven_lf"],
            }
        )

    robust = len({s["verdict"] for s in sensitivities}) == 1

    output = {
        "market": verdict1_v1.MARKET,
        "carrier": verdict1_v1.CARRIER,
        "verdict": verdict,
        "robust": robust,
        "expected_load_factor": pnl_result["expected_load_factor"],
        "breakeven_load_factor": pnl_result["breakeven_lf"],
        "revenue_annual_usd": pnl_result["revenue"],
        "cost_annual_usd": pnl_result["cost"],
        "contribution_annual_usd": pnl_result["contribution"],
        "delta_e175_casm_cents": casm_cents,
        "raw_skywest_casm_cents": casm_result["raw_casm_cents_per_asm"],
        "cpa_markup": pnl_cpa.CPA_MARKUP,
        "sizing": {"base_pax": sizing_result["base_pax"], "uplift": sizing_result["uplift"], "sized_pax": sized_pax},
        "predicted_delta_share": predicted_delta_share,
        "scurve_share_cross_check": scurve_share_value,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT1_CPA_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT1_CPA_OUTPUT_PATH}")

    return output


if __name__ == "__main__":
    run_verdict1_cpa()
