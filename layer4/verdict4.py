"""Layer 4 Wave 2, Module 6: orchestrator and comparative payoff.

Runs Verdicts 1-3 on ATL-SAT (Modules 3-5), then produces the comparative
summary against AUS-SLC's already-computed verdict1/2/3.json outputs --
AUS-SLC is never recomputed here.

Runnable via `python -m layer4.verdict4` from the project root.
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd

from layer1 import pnl as layer1_pnl
from layer4 import config, verdict1_atl_sat, verdict2_atl_sat, verdict3_atl_sat
from layer4.screener import resolve_csv_path, DB1B_GLOB_PATTERN

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "out")
AUS_SLC_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer1", "out")
LAYER2_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer2", "out")
LAYER3_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer3", "out")
AUS_SLC_VERDICT1_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")
AUS_SLC_VERDICT2_PATH = os.path.join(LAYER2_OUT_DIR, "verdict2.json")
AUS_SLC_VERDICT3_PATH = os.path.join(LAYER3_OUT_DIR, "verdict3.json")

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
MARKET_SCREENER_PATH = os.path.join(LAYER4_OUT_DIR, "market_screener.parquet")
VERDICT4_OUTPUT_PATH = os.path.join(LAYER4_OUT_DIR, "verdict4.json")


def _build_comparative_summary(aus_slc_v1, aus_slc_v2, aus_slc_v3, atl_sat_v1, atl_sat_v2, atl_sat_v3, aus_slc_local_sample, atl_sat_local_sample):
    aus_slc_mileage = next(r for r in aus_slc_v3["attribution_regimes"] if r["regime"] == "mileage")
    aus_slc_shapley = next(r for r in aus_slc_v3["attribution_regimes"] if r["regime"] == "shapley")
    atl_sat_mileage = next(r for r in atl_sat_v3["attribution_regimes"] if r["regime"] == "mileage")
    atl_sat_shapley = next(r for r in atl_sat_v3["attribution_regimes"] if r["regime"] == "shapley")

    return {
        "local_sample_passengers": {"aus_slc": aus_slc_local_sample, "atl_sat": atl_sat_local_sample},
        "feed_share_of_revenue": {"aus_slc": aus_slc_v2["feed_share_of_total_revenue"], "atl_sat": atl_sat_v2["feed_share_of_total_revenue"]},
        "predicted_dominant_share": {"aus_slc": aus_slc_v1["predicted_delta_share"], "atl_sat": atl_sat_v1["predicted_delta_share"]},
        "expected_load_factor": {"aus_slc": aus_slc_v1["expected_load_factor"], "atl_sat": atl_sat_v1["expected_load_factor"]},
        "verdict1": {"aus_slc": aus_slc_v1["verdict"], "atl_sat": atl_sat_v1["verdict"]},
        "verdict2_total_contribution_usd": {"aus_slc": aus_slc_v2["total_contribution_annual_usd"], "atl_sat": atl_sat_v2["total_contribution_annual_usd"]},
        "verdict3_contribution_mileage_usd": {"aus_slc": aus_slc_mileage["total_contribution_annual_usd"], "atl_sat": atl_sat_mileage["total_contribution_annual_usd"]},
        "verdict3_contribution_shapley_usd": {"aus_slc": aus_slc_shapley["total_contribution_annual_usd"], "atl_sat": atl_sat_shapley["total_contribution_annual_usd"]},
        "verdict3_attribution_delta_usd": {"aus_slc": aus_slc_v3["attribution_delta_usd"], "atl_sat": atl_sat_v3["attribution_delta_usd"]},
        "verdict3_attribution_leverage_pct": {"aus_slc": aus_slc_v3["attribution_leverage_pct"], "atl_sat": atl_sat_v3["attribution_leverage_pct"]},
        "verdict3_flipped": {"aus_slc": aus_slc_v3["verdict_flipped"], "atl_sat": atl_sat_v3["verdict_flipped"]},
    }


def _research_finding(comparative):
    aus = comparative["verdict3_attribution_leverage_pct"]["aus_slc"]
    atl = comparative["verdict3_attribution_leverage_pct"]["atl_sat"]
    aus_flip = comparative["verdict3_flipped"]["aus_slc"]
    atl_flip = comparative["verdict3_flipped"]["atl_sat"]
    flip_desc = "flipped" if atl_flip else "did not flip"
    return (
        f"Attribution mechanism produces {atl:.2%} leverage on ATL-SAT vs. {aus:.2%} on AUS-SLC; "
        f"ATL-SAT's verdict {flip_desc} (AUS-SLC: {'flipped' if aus_flip else 'did not flip'})."
    )


def main():
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)
    db1b_csv_path = resolve_csv_path(DB1B_GLOB_PATTERN)

    print("=" * 60)
    print("VERDICT 1 -- ATL-SAT")
    print("=" * 60)
    v1_output, v1_context = verdict1_atl_sat.run_verdict1_atl_sat(db1b_csv_path)

    days_per_year = config.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    capacity_seats_annual = v1_context["seats_per_departure"] * config.PROPOSED_FREQ_DAILY * days_per_year
    local_pax_annual = v1_output["expected_load_factor"] * capacity_seats_annual
    local_revenue_annual = v1_output["revenue_annual_usd"]

    print()
    print("=" * 60)
    print("VERDICT 2 -- ATL-SAT")
    print("=" * 60)
    v2_output, v2_context = verdict2_atl_sat.run_verdict2_atl_sat(
        db1b_csv_path, local_pax_annual, local_revenue_annual,
        v1_context["seats_per_departure"], v1_context["casm_cents"], v1_context["distance_miles"],
    )

    print()
    print("=" * 60)
    print("VERDICT 3 -- ATL-SAT")
    print("=" * 60)
    v3_output = verdict3_atl_sat.run_verdict3_atl_sat(
        db1b_csv_path, verdict1_atl_sat.ATL_SAT_LOCAL_PATH, v2_context["feed_econ_df"],
        local_pax_annual, local_revenue_annual, v2_context["feed_pax_annual"],
        v1_context["seats_per_departure"], v1_context["casm_cents"], v1_context["distance_miles"],
        v1_output["breakeven_load_factor"],
    )

    with open(AUS_SLC_VERDICT1_PATH) as f:
        aus_slc_v1 = json.load(f)
    with open(AUS_SLC_VERDICT2_PATH) as f:
        aus_slc_v2 = json.load(f)
    with open(AUS_SLC_VERDICT3_PATH) as f:
        aus_slc_v3 = json.load(f)

    # "Local sample passengers" reference figures are quoted directly from each
    # market's own selection record rather than re-derived: AUS-SLC's row_count
    # from Layer 0's summary.json, ATL-SAT's dominant-carrier local_pax_sample
    # from Wave 1's screener (the two are computed differently -- row count vs.
    # a passenger sum -- matching the pairing already used in the Wave 2 spec's
    # own market-selection narrative, not a new formula invented here).
    with open(AUS_SLC_SUMMARY_PATH) as f:
        aus_slc_summary = json.load(f)
    aus_slc_local_sample = aus_slc_summary["row_count"]

    screener_df = pd.read_parquet(MARKET_SCREENER_PATH)
    atl_sat_local_sample = float(screener_df.loc[screener_df["market_pair"] == config.MARKET_PAIR, "local_pax_sample"].iloc[0])

    comparative = _build_comparative_summary(
        aus_slc_v1, aus_slc_v2, aus_slc_v3, v1_output, v2_output, v3_output,
        aus_slc_local_sample, atl_sat_local_sample,
    )
    finding = _research_finding(comparative)

    output = {
        **v1_output,
        **v2_output,
        **v3_output,
        "comparative_summary": comparative,
        "research_finding": finding,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT4_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {VERDICT4_OUTPUT_PATH}")

    print()
    print("=" * 68)
    print(f"{'':25s} {'AUS-SLC (2025 Q2)':20s} {'ATL-SAT (2025 Q2)':20s}")
    print("=" * 68)

    def row(label, aus_val, atl_val):
        print(f"{label:25s} {aus_val:20s} {atl_val:20s}")

    row("Local sample passengers", f"{comparative['local_sample_passengers']['aus_slc']:,.0f}", f"{comparative['local_sample_passengers']['atl_sat']:,.0f}")
    row("Feed share of revenue", f"{comparative['feed_share_of_revenue']['aus_slc']:.1%}", f"{comparative['feed_share_of_revenue']['atl_sat']:.1%}")
    row("Dominant share (predicted)", f"{comparative['predicted_dominant_share']['aus_slc']:.1%}", f"{comparative['predicted_dominant_share']['atl_sat']:.1%}")
    row("Expected load factor", f"{comparative['expected_load_factor']['aus_slc']:.1%}", f"{comparative['expected_load_factor']['atl_sat']:.1%}")
    row("Verdict 1", comparative["verdict1"]["aus_slc"].upper(), comparative["verdict1"]["atl_sat"].upper())
    row("Contribution (mileage)", f"${comparative['verdict3_contribution_mileage_usd']['aus_slc']/1e6:.2f}M", f"${comparative['verdict3_contribution_mileage_usd']['atl_sat']/1e6:.2f}M")
    row("Contribution (Shapley)", f"${comparative['verdict3_contribution_shapley_usd']['aus_slc']/1e6:.2f}M", f"${comparative['verdict3_contribution_shapley_usd']['atl_sat']/1e6:.2f}M")
    row("Attribution leverage", f"{comparative['verdict3_attribution_leverage_pct']['aus_slc']:.2%}", f"{comparative['verdict3_attribution_leverage_pct']['atl_sat']:.2%}")
    row("Verdict flipped?", "YES" if comparative["verdict3_flipped"]["aus_slc"] else "NO", "YES" if comparative["verdict3_flipped"]["atl_sat"] else "NO")

    print()
    print("=== DESTER research finding ===")
    print(finding)

    if comparative["verdict3_flipped"]["atl_sat"]:
        print()
        print(
            "*** VERDICT FLIPPED on ATL-SAT. This is the positive result that pairs with AUS-SLC's null "
            "result to characterize the attribution mechanism empirically -- warrants careful diagnosis "
            "before publication. ***"
        )
    else:
        print()
        print(
            f"Verdict did not flip on ATL-SAT either. The empirical bracket: the mechanism does not flip "
            f"verdicts at feed shares up to {comparative['feed_share_of_revenue']['atl_sat']:.1%} on this "
            f"comparable healthy market. Still a real finding."
        )


if __name__ == "__main__":
    main()
