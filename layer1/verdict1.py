"""Layer 1 Wave 2, Module 8: Verdict 1 orchestrator.

Runs: market sizing -> logit predict on Delta's proposed AUS-SLC itinerary ->
S-curve cross-check -> spill model -> P&L -> verdict, then re-runs the full
chain across the documented sensitivity grid.

Runnable via `python -m layer1.verdict1` from the project root. Reads Wave 1's
logit_coefficients.json and Layer 0's aus_slc_market.parquet/summary.json
read-only; does not regenerate any Wave 0/Wave 1 artifact.
"""

import itertools
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from layer1 import calibration, logit, pnl, scurve, sizing, spill

LAYER0_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "out")
AUS_SLC_PARQUET_PATH = os.path.join(LAYER0_OUT_DIR, "aus_slc_market.parquet")
LAYER0_SUMMARY_PATH = os.path.join(LAYER0_OUT_DIR, "summary.json")

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
LOGIT_COEFFICIENTS_PATH = os.path.join(LAYER1_OUT_DIR, "logit_coefficients.json")
P52_GLOB_PATTERN = os.path.join(os.path.dirname(__file__), "data", "T_F41SCHEDULE*.csv")
VERDICT1_OUTPUT_PATH = os.path.join(LAYER1_OUT_DIR, "verdict1.json")

MARKET = "AUS-SLC"
CARRIER = "DL"

DELTA_PROPOSED_FREQUENCY_PER_DAY = 2

HUB_DOMINANCE_THRESHOLD = 0.40


def _t100_airport_carrier_share(t100_csv_path):
    """Each carrier's share of T-100 departures touching an airport (2025 Q2),
    used as the hub-dominance basis for this market's choice set (per the
    build prompt: synthetic-record features come from T-100, not a fresh
    national DB1B re-parse)."""
    t100 = pd.read_csv(t100_csv_path, usecols=["ORIGIN", "DEST", "CARRIER", "DEPARTURES_PERFORMED", "YEAR", "MONTH"])
    t100 = t100[(t100["YEAR"] == calibration.T100_YEAR) & (t100["MONTH"].isin(calibration.T100_MONTHS))]

    origin_leg = t100[["ORIGIN", "CARRIER", "DEPARTURES_PERFORMED"]].rename(columns={"ORIGIN": "airport"})
    dest_leg = t100[["DEST", "CARRIER", "DEPARTURES_PERFORMED"]].rename(columns={"DEST": "airport"})
    touches = pd.concat([origin_leg, dest_leg], ignore_index=True)

    airport_totals = touches.groupby("airport")["DEPARTURES_PERFORMED"].sum()
    airport_carrier_totals = touches.groupby(["airport", "CARRIER"])["DEPARTURES_PERFORMED"].sum()
    return airport_carrier_totals / airport_totals.reindex(
        airport_carrier_totals.index.get_level_values("airport")
    ).values


def _hub_dominance_lookup(airport, carrier, airport_carrier_share):
    try:
        share = airport_carrier_share.loc[(airport, carrier)]
    except KeyError:
        share = 0.0
    return 1.0 if share >= HUB_DOMINANCE_THRESHOLD else 0.0


def _aus_slc_segment_daily_frequencies(t100_csv_path):
    """Current nonstop AUS-SLC daily frequency by carrier, excluding Delta
    (Delta's real current service is replaced by the synthetic proposed
    itinerary rather than double-counted)."""
    t100 = pd.read_csv(t100_csv_path, usecols=["ORIGIN", "DEST", "CARRIER", "DEPARTURES_PERFORMED", "YEAR", "MONTH"])
    t100 = t100[(t100["YEAR"] == calibration.T100_YEAR) & (t100["MONTH"].isin(calibration.T100_MONTHS))]
    mask = ((t100["ORIGIN"] == "AUS") & (t100["DEST"] == "SLC")) | ((t100["ORIGIN"] == "SLC") & (t100["DEST"] == "AUS"))
    sub = t100[mask & (t100["CARRIER"] != CARRIER)]
    quarterly = sub.groupby("CARRIER")["DEPARTURES_PERFORMED"].sum()
    return (quarterly / pnl.QUARTER_DAYS).to_dict()


def _build_real_choice_set(aus_slc_df, t100_freq_features, airport_carrier_share):
    """Nonstop, non-Delta itineraries from Layer 0's AUS-SLC parquet,
    aggregated to one alternative per carrier. Restricted to nonstop because
    Layer 0's schema has no AirportGroup column, so connecting-itinerary hubs
    aren't derivable here -- consistent with Verdict 1 being the local,
    point-to-point business case."""
    nonstop = aus_slc_df[(aus_slc_df["MktCoupons"] == 1) & (aus_slc_df["RPCarrier"] != CARRIER)].copy()
    nonstop["log_fare"] = np.log(nonstop["MktFare"].astype(float))
    nonstop["routing_efficiency"] = nonstop["MktDistance"] / nonstop["NonStopMiles"]

    nonstop = nonstop.merge(
        t100_freq_features,
        left_on=["Origin", "Dest", "OpCarrier"],
        right_on=["ORIGIN", "DEST", "CARRIER"],
        how="left",
    ).drop(columns=["ORIGIN", "DEST", "CARRIER"])

    nonstop["hub_dominance"] = [
        _hub_dominance_lookup(origin, op_carrier, airport_carrier_share)
        for origin, op_carrier in zip(nonstop["Origin"], nonstop["OpCarrier"])
    ]

    before = len(nonstop)
    nonstop = nonstop.dropna(subset=["frequency_weekly"])
    dropped = before - len(nonstop)
    if dropped:
        print(f"  dropped {dropped} AUS-SLC itineraries with no matching T-100 segment for the choice set")

    rows = []
    for carrier, group in nonstop.groupby("RPCarrier", observed=True):
        pax = group["Passengers"].astype(float)
        if pax.sum() == 0:
            continue
        rows.append(
            {
                "market": MARKET,
                "carrier": str(carrier),
                "itinerary_type": "nonstop",
                "connecting_hub": None,
                "log_fare": float(np.average(group["log_fare"], weights=pax)),
                "n_stops": 0,
                "routing_efficiency": float(np.average(group["routing_efficiency"], weights=pax)),
                "frequency_weekly": float(np.average(group["frequency_weekly"], weights=pax)),
                "hub_dominance": float(np.average(group["hub_dominance"], weights=pax)),
            }
        )
    return pd.DataFrame(rows)


def _synthetic_delta_row(mean_fare, airport_carrier_share):
    hub_dominance_aus = _hub_dominance_lookup("AUS", CARRIER, airport_carrier_share)
    hub_dominance_slc = _hub_dominance_lookup("SLC", CARRIER, airport_carrier_share)
    return {
        "market": MARKET,
        "carrier": CARRIER,
        "itinerary_type": "nonstop",
        "connecting_hub": None,
        "log_fare": float(np.log(mean_fare)),
        "n_stops": 0,
        "routing_efficiency": 1.0,
        "frequency_weekly": float(DELTA_PROPOSED_FREQUENCY_PER_DAY * 7),
        "hub_dominance": (hub_dominance_aus + hub_dominance_slc) / 2.0,
    }


def _run_scenario(base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles):
    sized_pax = sizing.apply_stimulation(base_pax, uplift)
    days_per_year = pnl.QUARTER_DAYS * pnl.YEAR_QUARTERS
    mean_daily_pax = sized_pax * predicted_delta_share / days_per_year

    boardings = spill.expected_boardings(
        mean_daily_pax, seats_per_departure, DELTA_PROPOSED_FREQUENCY_PER_DAY, recapture=recapture
    )
    pnl_result = pnl.main_pnl(
        boardings, mean_fare, seats_per_departure, DELTA_PROPOSED_FREQUENCY_PER_DAY,
        pnl.QUARTER_DAYS, distance_miles, casm_cents,
    )
    verdict = "go" if pnl_result["expected_load_factor"] >= pnl_result["breakeven_lf"] else "no_go"
    return sized_pax, boardings, pnl_result, verdict


def main():
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)

    with open(LAYER0_SUMMARY_PATH) as f:
        summary = json.load(f)
    aus_slc_df = pd.read_parquet(AUS_SLC_PARQUET_PATH)
    mean_fare = summary["mean_fare"]
    distance_miles = summary["mean_distance_miles"]

    t100_csv_path = calibration.resolve_csv_path(calibration.T100_GLOB_PATTERN)
    p52_csv_path = calibration.resolve_csv_path(P52_GLOB_PATTERN)

    print("Building AUS-SLC choice set...")
    t100_freq_features = calibration.load_t100_features(t100_csv_path)
    airport_carrier_share = _t100_airport_carrier_share(t100_csv_path)

    real_choice_set = _build_real_choice_set(aus_slc_df, t100_freq_features, airport_carrier_share)
    delta_row = _synthetic_delta_row(mean_fare, airport_carrier_share)
    choice_set = pd.concat([real_choice_set, pd.DataFrame([delta_row])], ignore_index=True)
    print(f"  choice set: {list(choice_set['carrier'])}")

    coefficients = logit.load_coefficients(LOGIT_COEFFICIENTS_PATH)
    predicted = logit.predict_shares(choice_set, coefficients)
    predicted_delta_share = float(predicted[choice_set["carrier"] == CARRIER].iloc[0])

    delta_freq = float(DELTA_PROPOSED_FREQUENCY_PER_DAY)
    incumbent_freqs = _aus_slc_segment_daily_frequencies(t100_csv_path)
    all_freqs = [delta_freq] + list(incumbent_freqs.values())
    scurve_share_value = scurve.scurve_share(delta_freq, all_freqs, alpha=scurve.DEFAULT_ALPHA)

    sizing_result = sizing.market_size(LAYER0_SUMMARY_PATH, uplift=sizing.DEFAULT_STIMULATION_UPLIFT)
    base_pax = sizing_result["base_pax"]

    print("Resolving Delta E175 aircraft type and CASM...")
    casm_result = pnl.compute_delta_e175_casm(p52_csv_path, t100_csv_path)
    seats_per_departure = pnl.e175_seats_per_departure(t100_csv_path)
    casm_cents = casm_result["casm_cents_per_asm"]

    sized_pax, boardings, pnl_result, verdict = _run_scenario(
        base_pax, predicted_delta_share, sizing.DEFAULT_STIMULATION_UPLIFT, spill.DEFAULT_RECAPTURE_RATE,
        seats_per_departure, casm_cents, mean_fare, distance_miles,
    )

    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        sizing.UPLIFT_SENSITIVITY_VALUES, spill.RECAPTURE_SENSITIVITY_VALUES, scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, _, sens_pnl, sens_verdict = _run_scenario(
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
        "market": MARKET,
        "carrier": CARRIER,
        "verdict": verdict,
        "robust": robust,
        "expected_load_factor": pnl_result["expected_load_factor"],
        "breakeven_load_factor": pnl_result["breakeven_lf"],
        "revenue_annual_usd": pnl_result["revenue"],
        "cost_annual_usd": pnl_result["cost"],
        "contribution_annual_usd": pnl_result["contribution"],
        "delta_e175_casm_cents": casm_cents,
        "sizing": {"base_pax": sizing_result["base_pax"], "uplift": sizing_result["uplift"], "sized_pax": sized_pax},
        "predicted_delta_share": predicted_delta_share,
        "scurve_share_cross_check": scurve_share_value,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(VERDICT1_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {VERDICT1_OUTPUT_PATH}")

    print()
    print("=== Verdict 1 summary ===")
    print(f"Sized market pax (annual): {sized_pax:,.0f} (base={base_pax:,.0f}, uplift={sizing.DEFAULT_STIMULATION_UPLIFT:.0%})")
    print(f"Predicted Delta share (logit): {predicted_delta_share:.4f}")
    print(f"S-curve share (cross-check only, alpha={scurve.DEFAULT_ALPHA}): {scurve_share_value:.4f}")
    print(f"Expected daily demand: {boardings['expected_demand']:.2f}, spill: {boardings['expected_spill']:.2f}, "
          f"recapture: {boardings['expected_recapture']:.2f}, boarded: {boardings['expected_boarded']:.2f}")
    print(f"Delta E175 (SkyWest/OO) CASM: {casm_cents:.3f} cents/ASM")
    print(f"Revenue: ${pnl_result['revenue']:,.0f}  Cost: ${pnl_result['cost']:,.0f}  "
          f"Contribution: ${pnl_result['contribution']:,.0f}")
    print(f"Expected LF: {pnl_result['expected_load_factor']:.3f}  Breakeven LF: {pnl_result['breakeven_lf']:.3f}")
    print(f"Headline verdict: {verdict.upper()}")
    print(f"Robust across all {len(sensitivities)} sensitivity combinations: {robust}")
    if not robust:
        verdict_counts = {v: sum(1 for s in sensitivities if s["verdict"] == v) for v in {s["verdict"] for s in sensitivities}}
        print(f"  verdict split: {verdict_counts}")

    if verdict == "go":
        print()
        print(
            "*** NOTE: headline verdict is GO under default parameters. DESTER's research design "
            "pre-registered a NO-GO expectation for local-only AUS-SLC demand (thin O&D, entrenched "
            "Southwest, non-trivial 2x-daily fixed costs). A GO result here contradicts that expectation "
            "and is worth diagnosing before proceeding to Layer 2. ***"
        )


if __name__ == "__main__":
    main()
