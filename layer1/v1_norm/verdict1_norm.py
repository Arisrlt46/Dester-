"""Layer 1 v1_norm: Verdict 1 with the normalized contribution-based
verdict rule (go iff total_contribution_annual_usd >= 0), matching the rule
Layer 3 established for Verdicts 2/3. Verdict 1 originally used a
load-factor-based rule (go iff expected_lf >= breakeven_lf) inherited from
AUS-SLC's small-aircraft setup; the two rules can disagree on markets with
different aircraft/share profiles (documented in RESEARCH_FINDINGS.md).

Reruns the exact same AUS-SLC Verdict 1 pipeline -- same logit (v1), same
sizing/S-curve/spill/PnL machinery, reused unchanged via import from
layer1.verdict1 -- only adding the normalized verdict alongside the
original. Writes to a distinct output path; verdict1.json is untouched.
"""

import itertools
import json
import os
from datetime import datetime, timezone

import pandas as pd

from layer1 import calibration, logit, pnl, scurve, sizing, spill
from layer1 import verdict1 as verdict1_v1

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
VERDICT1_NORM_OUTPUT_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1_norm.json")


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def run_verdict1_norm():
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

    coefficients = logit.load_coefficients(verdict1_v1.LOGIT_COEFFICIENTS_PATH)
    predicted = logit.predict_shares(choice_set, coefficients)
    predicted_delta_share = float(predicted[choice_set["carrier"] == verdict1_v1.CARRIER].iloc[0])

    sizing_result = sizing.market_size(verdict1_v1.LAYER0_SUMMARY_PATH, uplift=sizing.DEFAULT_STIMULATION_UPLIFT)
    base_pax = sizing_result["base_pax"]

    print("Resolving Delta E175 CASM...")
    casm_result = pnl.compute_delta_e175_casm(p52_csv_path, t100_csv_path)
    seats_per_departure = pnl.e175_seats_per_departure(t100_csv_path)
    casm_cents = casm_result["casm_cents_per_asm"]

    sized_pax, boardings, pnl_result, verdict_lf = verdict1_v1._run_scenario(
        base_pax, predicted_delta_share, sizing.DEFAULT_STIMULATION_UPLIFT, spill.DEFAULT_RECAPTURE_RATE,
        seats_per_departure, casm_cents, mean_fare, distance_miles,
    )
    verdict_norm = _verdict_from_contribution(pnl_result["contribution"])

    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        sizing.UPLIFT_SENSITIVITY_VALUES, spill.RECAPTURE_SENSITIVITY_VALUES, scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, _, sens_pnl, sens_verdict_lf = verdict1_v1._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        sensitivities.append(
            {
                "uplift": uplift,
                "recapture": recapture,
                "alpha": alpha,
                "verdict": _verdict_from_contribution(sens_pnl["contribution"]),
                "verdict_lf_based": sens_verdict_lf,
                "expected_lf": sens_pnl["expected_load_factor"],
                "breakeven_lf": sens_pnl["breakeven_lf"],
                "contribution": sens_pnl["contribution"],
            }
        )

    robust = len({s["verdict"] for s in sensitivities}) == 1

    output = {
        "market": verdict1_v1.MARKET,
        "carrier": verdict1_v1.CARRIER,
        "verdict": verdict_norm,
        "verdict_lf_based": verdict_lf,
        "verdict_rule": "contribution_annual_usd >= 0",
        "robust": robust,
        "expected_load_factor": pnl_result["expected_load_factor"],
        "breakeven_load_factor": pnl_result["breakeven_lf"],
        "revenue_annual_usd": pnl_result["revenue"],
        "cost_annual_usd": pnl_result["cost"],
        "contribution_annual_usd": pnl_result["contribution"],
        "delta_e175_casm_cents": casm_cents,
        "sizing": {"base_pax": sizing_result["base_pax"], "uplift": sizing_result["uplift"], "sized_pax": sized_pax},
        "predicted_delta_share": predicted_delta_share,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT1_NORM_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT1_NORM_OUTPUT_PATH}")

    print()
    print("=== Verdict 1 normalization: AUS-SLC ===")
    print(
        f"Original (LF-based):          {verdict_lf.upper():6s}  "
        f"(expected_lf={pnl_result['expected_load_factor']:.3f} vs breakeven_lf={pnl_result['breakeven_lf']:.3f})"
    )
    print(
        f"Normalized (contribution-based): {verdict_norm.upper():6s}  "
        f"(contribution=${pnl_result['contribution']:,.0f})"
    )
    if verdict_lf != verdict_norm:
        print("*** VERDICT CHANGES under normalization -- genuine finding. ***")
    else:
        print("No change: both rules agree for AUS-SLC.")

    return output


if __name__ == "__main__":
    run_verdict1_norm()
