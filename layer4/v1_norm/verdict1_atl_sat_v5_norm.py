"""Layer 4 v1_norm: ATL-SAT Verdict 1 (Iteration 5 v5, lambda=15 shrinkage
logit) with the normalized contribution-based verdict rule.

This is the row that should resolve the documented LF-vs-contribution rule
inconsistency: RESEARCH_FINDINGS.md records ATL-SAT's Verdict 1 as NO_GO
under the load-factor rule even though contribution is positive under the
v5 model. Reuses layer4.iteration5.verdict1_atl_sat_v5.run_verdict1_atl_sat_v5
unchanged for the full pipeline, then re-derives the sensitivity grid's
verdicts from the same _run_scenario function using the contribution rule.
Writes to a distinct output path; the Iteration 5 outputs are untouched.
"""

import itertools
import json
import os
from datetime import datetime, timezone

from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer4 import verdict1_atl_sat
from layer4.iteration5 import verdict1_atl_sat_v5
from layer4.screener import DB1B_GLOB_PATTERN, resolve_csv_path

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
VERDICT1_ATL_SAT_V5_NORM_OUTPUT_PATH = os.path.join(LAYER4_OUT_DIR, "verdict1_atl_sat_v5_norm.json")


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def run_verdict1_atl_sat_v5_norm():
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)
    db1b_csv_path = resolve_csv_path(DB1B_GLOB_PATTERN)

    v1_output, context = verdict1_atl_sat_v5.run_verdict1_atl_sat_v5(db1b_csv_path)

    base_pax = context["base_pax"]
    predicted_dominant_share = context["predicted_dominant_share"]
    seats_per_departure = context["seats_per_departure"]
    casm_cents = context["casm_cents"]
    mean_fare = context["mean_fare"]
    distance_miles = context["distance_miles"]

    verdict_lf = v1_output["verdict"]
    verdict_norm = _verdict_from_contribution(v1_output["contribution_annual_usd"])

    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        # verdict1_atl_sat._run_scenario is the same underlying scenario
        # runner used by both the v1 and v5 models -- only predicted_dominant_share
        # (already baked into context from the v5-coefficients run) differs.
        _, _, sens_pnl, sens_verdict_lf = verdict1_atl_sat._run_scenario(
            base_pax, predicted_dominant_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
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
        **v1_output,
        "verdict": verdict_norm,
        "verdict_lf_based": verdict_lf,
        "verdict_rule": "contribution_annual_usd >= 0",
        "robust": robust,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT1_ATL_SAT_V5_NORM_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT1_ATL_SAT_V5_NORM_OUTPUT_PATH}")

    print()
    print("=== Verdict 1 normalization: ATL-SAT (v5 model, lambda=15) ===")
    print(
        f"Original (LF-based):             {verdict_lf.upper():6s}  "
        f"(expected_lf={v1_output['expected_load_factor']:.3f} vs breakeven_lf={v1_output['breakeven_load_factor']:.3f})"
    )
    print(
        f"Normalized (contribution-based): {verdict_norm.upper():6s}  "
        f"(contribution=${v1_output['contribution_annual_usd']:,.0f})"
    )
    if verdict_lf != verdict_norm:
        print("*** VERDICT CHANGES under normalization -- this resolves the documented LF-vs-contribution inconsistency. ***")
    else:
        print("No change: both rules agree for ATL-SAT under the v5 model.")

    return output


if __name__ == "__main__":
    run_verdict1_atl_sat_v5_norm()
