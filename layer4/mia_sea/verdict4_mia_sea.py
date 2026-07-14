"""Layer 4 MIA-SEA, Module 4: orchestrator and comparative payoff.

Mirrors layer4/iteration5/verdict4_v5.py's structure exactly, substituting
MIA-SEA's own verdict1/2/3 modules and building in the regime-aware 96-row
sensitivity grid from the start (ATL-SAT needed a retroactive follow-up
script, layer4/iteration5/verdict3_v5_sensitivities.py, because its Wave 2
verdict3 module predates the regime-aware-grid design; MIA-SEA doesn't
carry that history, so this orchestrator just does both in one run).

AUS-SLC is read from its existing, pre-registered outputs -- never
recomputed. ATL-SAT's own layer4/out/ artifacts are untouched.

Writes:
  layer4/out/verdict1_mia_sea.json (Verdict 1 alone)
  layer4/out/verdict2_mia_sea.json (Verdict 2 alone)
  layer4/out/verdict3_mia_sea.json (Verdict 3 point estimate alone)
  layer4/out/verdict3_mia_sea_sensitivities.json (96-row regime-aware grid)
  layer4/out/verdict4_mia_sea.json (merged {**v1,**v2,**v3} + comparative
    summary vs. AUS-SLC -- "sensitivities" here is the 96-row regime-aware
    grid, not Verdict 1's own 48-row load-factor-only grid, matching how
    the dashboard already treats ATL-SAT/v5 after its own supersession step)

Runnable via `python -m layer4.mia_sea.verdict4_mia_sea`.
"""

import json
import os
from datetime import datetime, timezone

from layer1 import pnl as layer1_pnl
from layer4.mia_sea import config_mia_sea as config
from layer4.mia_sea import verdict1_mia_sea, verdict2_mia_sea, verdict3_mia_sea
from layer4.screener import DB1B_GLOB_PATTERN, resolve_csv_path

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer0", "out")
AUS_SLC_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer1", "out")
LAYER2_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer2", "out")
LAYER3_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer3", "out")
AUS_SLC_VERDICT1_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")
AUS_SLC_VERDICT2_PATH = os.path.join(LAYER2_OUT_DIR, "verdict2.json")
AUS_SLC_VERDICT3_PATH = os.path.join(LAYER3_OUT_DIR, "verdict3.json")

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
VERDICT1_MIA_SEA_PATH = os.path.join(LAYER4_OUT_DIR, "verdict1_mia_sea.json")
VERDICT2_MIA_SEA_PATH = os.path.join(LAYER4_OUT_DIR, "verdict2_mia_sea.json")
VERDICT3_MIA_SEA_PATH = os.path.join(LAYER4_OUT_DIR, "verdict3_mia_sea.json")
VERDICT3_MIA_SEA_SENSITIVITIES_PATH = os.path.join(LAYER4_OUT_DIR, "verdict3_mia_sea_sensitivities.json")
VERDICT4_MIA_SEA_PATH = os.path.join(LAYER4_OUT_DIR, "verdict4_mia_sea.json")


def _build_comparative_summary(aus_slc_v1, aus_slc_v2, aus_slc_v3, mia_sea_v1, mia_sea_v2, mia_sea_v3, aus_slc_local_sample, mia_sea_local_sample):
    aus_slc_mileage = next(r for r in aus_slc_v3["attribution_regimes"] if r["regime"] == "mileage")
    aus_slc_shapley = next(r for r in aus_slc_v3["attribution_regimes"] if r["regime"] == "shapley")
    mia_sea_mileage = next(r for r in mia_sea_v3["attribution_regimes"] if r["regime"] == "mileage")
    mia_sea_shapley = next(r for r in mia_sea_v3["attribution_regimes"] if r["regime"] == "shapley")

    return {
        "local_sample_passengers": {"aus_slc": aus_slc_local_sample, "mia_sea": mia_sea_local_sample},
        "feed_share_of_revenue": {"aus_slc": aus_slc_v2["feed_share_of_total_revenue"], "mia_sea": mia_sea_v2["feed_share_of_total_revenue"]},
        "predicted_dominant_share": {"aus_slc": aus_slc_v1["predicted_delta_share"], "mia_sea": mia_sea_v1["predicted_delta_share"]},
        "expected_load_factor": {"aus_slc": aus_slc_v1["expected_load_factor"], "mia_sea": mia_sea_v1["expected_load_factor"]},
        "verdict1": {"aus_slc": aus_slc_v1["verdict"], "mia_sea": mia_sea_v1["verdict"]},
        "verdict2_total_contribution_usd": {"aus_slc": aus_slc_v2["total_contribution_annual_usd"], "mia_sea": mia_sea_v2["total_contribution_annual_usd"]},
        "verdict3_contribution_mileage_usd": {"aus_slc": aus_slc_mileage["total_contribution_annual_usd"], "mia_sea": mia_sea_mileage["total_contribution_annual_usd"]},
        "verdict3_contribution_shapley_usd": {"aus_slc": aus_slc_shapley["total_contribution_annual_usd"], "mia_sea": mia_sea_shapley["total_contribution_annual_usd"]},
        "verdict3_attribution_delta_usd": {"aus_slc": aus_slc_v3["attribution_delta_usd"], "mia_sea": mia_sea_v3["attribution_delta_usd"]},
        "verdict3_attribution_leverage_pct": {"aus_slc": aus_slc_v3["attribution_leverage_pct"], "mia_sea": mia_sea_v3["attribution_leverage_pct"]},
        "verdict3_flipped": {"aus_slc": aus_slc_v3["verdict_flipped"], "mia_sea": mia_sea_v3["verdict_flipped"]},
    }


def _research_finding(comparative):
    aus = comparative["verdict3_attribution_leverage_pct"]["aus_slc"]
    mia = comparative["verdict3_attribution_leverage_pct"]["mia_sea"]
    aus_flip = comparative["verdict3_flipped"]["aus_slc"]
    mia_flip = comparative["verdict3_flipped"]["mia_sea"]
    flip_desc = "flipped" if mia_flip else "did not flip"
    return (
        f"Attribution mechanism produces {mia:.2%} leverage on MIA-SEA (v5, lambda=15 shrinkage) vs. "
        f"{aus:.2%} on AUS-SLC (v1); MIA-SEA's verdict {flip_desc} "
        f"(AUS-SLC: {'flipped' if aus_flip else 'did not flip'})."
    )


def main():
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)
    db1b_csv_path = resolve_csv_path(DB1B_GLOB_PATTERN)

    print("=" * 60)
    print("VERDICT 1 -- MIA-SEA")
    print("=" * 60)
    v1_output, v1_context = verdict1_mia_sea.run_verdict1_mia_sea(db1b_csv_path)
    with open(VERDICT1_MIA_SEA_PATH, "w") as f:
        json.dump(v1_output, f, indent=2)
    print(f"Wrote {VERDICT1_MIA_SEA_PATH}")

    days_per_year = config.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    capacity_seats_annual = v1_context["seats_per_departure"] * config.PROPOSED_FREQ_DAILY * days_per_year
    local_pax_annual = v1_output["expected_load_factor"] * capacity_seats_annual
    local_revenue_annual = v1_output["revenue_annual_usd"]

    print()
    print("=" * 60)
    print("VERDICT 2 -- MIA-SEA")
    print("=" * 60)
    v2_output, v2_context = verdict2_mia_sea.run_verdict2_mia_sea(
        db1b_csv_path, local_pax_annual, local_revenue_annual,
        v1_context["seats_per_departure"], v1_context["casm_cents"], v1_context["distance_miles"],
    )
    with open(VERDICT2_MIA_SEA_PATH, "w") as f:
        json.dump(v2_output, f, indent=2)
    print(f"Wrote {VERDICT2_MIA_SEA_PATH}")

    print()
    print("=" * 60)
    print("VERDICT 3 -- MIA-SEA")
    print("=" * 60)
    v3_output, v3_sens_context = verdict3_mia_sea.run_verdict3_mia_sea(
        db1b_csv_path, verdict1_mia_sea.MIA_SEA_LOCAL_PATH, v2_context["feed_econ_df"],
        local_pax_annual, local_revenue_annual, v2_context["feed_pax_annual"],
        v1_context["seats_per_departure"], v1_context["casm_cents"], v1_context["distance_miles"],
        v1_output["breakeven_load_factor"],
    )
    with open(VERDICT3_MIA_SEA_PATH, "w") as f:
        json.dump(v3_output, f, indent=2)
    print(f"Wrote {VERDICT3_MIA_SEA_PATH}")

    print()
    print("Running regime-aware sensitivity grid (48 combinations x 2 regimes) for MIA-SEA...")
    sensitivities = verdict3_mia_sea.run_verdict3_sensitivities_mia_sea(
        v1_context["base_pax"], v1_context["predicted_dominant_share"], v1_context["seats_per_departure"],
        v1_context["casm_cents"], v1_context["mean_fare"], v1_context["distance_miles"],
        v3_sens_context["feed_pax_annual"], v3_sens_context["feed_revenue_by_regime_annual"],
    )
    with open(VERDICT3_MIA_SEA_SENSITIVITIES_PATH, "w") as f:
        json.dump({"market": config.MARKET_PAIR, "carrier": config.DOMINANT_CARRIER, "sensitivities": sensitivities}, f, indent=2)
    print(f"Wrote {VERDICT3_MIA_SEA_SENSITIVITIES_PATH} ({len(sensitivities)} rows)")

    with open(AUS_SLC_VERDICT1_PATH) as f:
        aus_slc_v1 = json.load(f)
    with open(AUS_SLC_VERDICT2_PATH) as f:
        aus_slc_v2 = json.load(f)
    with open(AUS_SLC_VERDICT3_PATH) as f:
        aus_slc_v3 = json.load(f)
    with open(AUS_SLC_SUMMARY_PATH) as f:
        aus_slc_summary = json.load(f)
    aus_slc_local_sample = aus_slc_summary["row_count"]

    # MIA-SEA's own local sample: the local dataframe's Passengers sum (same
    # basis as ATL-SAT's screener-derived figure -- a DB1B passenger count,
    # not annualized).
    mia_sea_local_sample = float(v1_context["local_df"]["Passengers"].sum())

    comparative = _build_comparative_summary(
        aus_slc_v1, aus_slc_v2, aus_slc_v3, v1_output, v2_output, v3_output,
        aus_slc_local_sample, mia_sea_local_sample,
    )
    finding = _research_finding(comparative)

    output = {
        **v1_output,
        **v2_output,
        **v3_output,
        "sensitivities": sensitivities,
        "comparative_summary": comparative,
        "research_finding": finding,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT4_MIA_SEA_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {VERDICT4_MIA_SEA_PATH}")

    print()
    print("=" * 68)
    print(f"{'':25s} {'AUS-SLC (v1)':20s} {'MIA-SEA (v5, lambda=15)':24s}")
    print("=" * 68)

    def row(label, aus_val, mia_val):
        print(f"{label:25s} {aus_val:20s} {mia_val:24s}")

    row("Local sample passengers", f"{comparative['local_sample_passengers']['aus_slc']:,.0f}", f"{comparative['local_sample_passengers']['mia_sea']:,.0f}")
    row("Feed share of revenue", f"{comparative['feed_share_of_revenue']['aus_slc']:.1%}", f"{comparative['feed_share_of_revenue']['mia_sea']:.1%}")
    row("Dominant share (predicted)", f"{comparative['predicted_dominant_share']['aus_slc']:.1%}", f"{comparative['predicted_dominant_share']['mia_sea']:.1%}")
    row("Expected load factor", f"{comparative['expected_load_factor']['aus_slc']:.1%}", f"{comparative['expected_load_factor']['mia_sea']:.1%}")
    row("Verdict 1", comparative["verdict1"]["aus_slc"].upper(), comparative["verdict1"]["mia_sea"].upper())
    row("Contribution (mileage)", f"${comparative['verdict3_contribution_mileage_usd']['aus_slc']/1e6:.2f}M", f"${comparative['verdict3_contribution_mileage_usd']['mia_sea']/1e6:.2f}M")
    row("Contribution (Shapley)", f"${comparative['verdict3_contribution_shapley_usd']['aus_slc']/1e6:.2f}M", f"${comparative['verdict3_contribution_shapley_usd']['mia_sea']/1e6:.2f}M")
    row("Attribution leverage", f"{comparative['verdict3_attribution_leverage_pct']['aus_slc']:.2%}", f"{comparative['verdict3_attribution_leverage_pct']['mia_sea']:.2%}")
    row("Verdict flipped?", "YES" if comparative["verdict3_flipped"]["aus_slc"] else "NO", "YES" if comparative["verdict3_flipped"]["mia_sea"] else "NO")

    print()
    print("=== DESTER research finding ===")
    print(finding)

    mileage_by_combo = {(s["uplift"], s["recapture"], s["alpha"]): s["verdict"] for s in sensitivities if s["regime"] == "mileage"}
    shapley_by_combo = {(s["uplift"], s["recapture"], s["alpha"]): s["verdict"] for s in sensitivities if s["regime"] == "shapley"}
    flip_count = sum(1 for combo, v in mileage_by_combo.items() if shapley_by_combo[combo] != v)
    print(f"\nGrid flip count: {flip_count} of {len(mileage_by_combo)} (uplift, recapture, alpha) combinations flip between mileage and Shapley.")

    if comparative["verdict3_flipped"]["mia_sea"]:
        print()
        print(
            "*** VERDICT FLIPPED on MIA-SEA at default parameters. This is the market DESTER's own catalog "
            "scan identified as the strongest verdict-flip candidate among 934 real US spoke-to-hub markets. ***"
        )
    else:
        print()
        print(
            f"Verdict did not flip on MIA-SEA at default parameters, though the catalog scan flagged it as a "
            f"flip candidate -- check the sensitivity grid for where in the grid it flips, if anywhere."
        )


if __name__ == "__main__":
    main()
