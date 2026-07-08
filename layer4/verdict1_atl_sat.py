"""Layer 4 Wave 2, Module 3: Verdict 1 on ATL-SAT.

Imports layer1.sizing, layer1.scurve, layer1.spill, layer1.pnl unchanged and
runs them with ATL-SAT config values. Layer 0's own parquet is AUS-SLC
specific, so this module builds its own ATL-SAT local dataframe by reusing
layer0.pipeline.build_market_dataset (already parameterized for any (a, b)
pair) rather than re-streaming the CSV by hand.

Unlike AUS-SLC (a hypothetical entry), Delta already flies ATL-SAT, so the
choice set uses every carrier's real observed nonstop rows -- including
Delta's own -- with no synthetic record.

layer1.pnl.compute_delta_e175_casm and resolve_e175_aircraft_type_code are
hardcoded to SkyWest/E175 and aren't reusable for Delta mainline metal here;
aircraft_id.py generalizes the identification, and CASM itself is computed
locally below using the same opex/ASM formula (including the Form 41
thousands-of-dollars fix already discovered for AUS-SLC).
"""

import itertools
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from layer0 import pipeline as layer0_pipeline
from layer1 import calibration as layer1_calibration
from layer1 import logit as layer1_logit
from layer1 import pnl as layer1_pnl
from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer1 import verdict1 as layer1_verdict1
from layer4 import aircraft_id, config

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "layer1", "out")
LOGIT_COEFFICIENTS_PATH = os.path.join(LAYER1_OUT_DIR, "logit_coefficients.json")

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
ATL_SAT_LOCAL_PATH = os.path.join(LAYER4_OUT_DIR, "atl_sat_local.parquet")

FORM41_DOLLAR_UNITS = 1000  # Form 41 Schedule P-5.2 reports dollar figures in thousands


def build_local_dataframe(db1b_csv_path):
    df = layer0_pipeline.build_market_dataset(db1b_csv_path, a=config.MARKET_ORIGIN, b=config.MARKET_DEST)
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)
    df.to_parquet(ATL_SAT_LOCAL_PATH, engine="pyarrow", index=False)
    print(f"Wrote {ATL_SAT_LOCAL_PATH} ({len(df)} rows)")
    return df


def _build_choice_set(local_df, t100_freq_features, airport_carrier_share):
    """One alternative-row per carrier, from real observed nonstop rows.
    No synthetic record: Delta already flies ATL-SAT, unlike AUS-SLC."""
    nonstop = local_df[local_df["MktCoupons"] == 1].copy()
    nonstop["log_fare"] = np.log(nonstop["MktFare"].astype(float))
    nonstop["routing_efficiency"] = nonstop["MktDistance"] / nonstop["NonStopMiles"]

    nonstop = nonstop.merge(
        t100_freq_features,
        left_on=["Origin", "Dest", "OpCarrier"],
        right_on=["ORIGIN", "DEST", "CARRIER"],
        how="left",
    ).drop(columns=["ORIGIN", "DEST", "CARRIER"])

    nonstop["hub_dominance"] = [
        layer1_verdict1._hub_dominance_lookup(origin, op_carrier, airport_carrier_share)
        for origin, op_carrier in zip(nonstop["Origin"], nonstop["OpCarrier"])
    ]

    before = len(nonstop)
    nonstop = nonstop.dropna(subset=["frequency_weekly"])
    dropped = before - len(nonstop)
    if dropped:
        print(f"  dropped {dropped} ATL-SAT itineraries with no matching T-100 segment for the choice set")

    rows = []
    for carrier, group in nonstop.groupby("RPCarrier", observed=True):
        pax = group["Passengers"].astype(float)
        if pax.sum() == 0:
            continue
        rows.append(
            {
                "market": config.MARKET_PAIR,
                "carrier": str(carrier),
                "log_fare": float(np.average(group["log_fare"], weights=pax)),
                "n_stops": 0,
                "routing_efficiency": float(np.average(group["routing_efficiency"], weights=pax)),
                "frequency_weekly": float(np.average(group["frequency_weekly"], weights=pax)),
                "hub_dominance": float(np.average(group["hub_dominance"], weights=pax)),
            }
        )
    return pd.DataFrame(rows)


def _compute_casm(carrier, aircraft_type_code, p52_csv_path, t100_csv_path):
    p52 = pd.read_csv(p52_csv_path)
    p52_match = p52[
        (p52["CARRIER"] == carrier)
        & (p52["YEAR"] == config.YEAR)
        & (p52["QUARTER"] == config.QUARTER)
        & (p52["AIRCRAFT_TYPE"] == aircraft_type_code)
    ]
    opex_usd = float(p52_match["TOT_AIR_OP_EXPENSES"].sum()) * FORM41_DOLLAR_UNITS

    t100 = pd.read_csv(t100_csv_path, usecols=["CARRIER", "AIRCRAFT_TYPE", "SEATS", "DISTANCE", "YEAR", "MONTH"])
    t100_match = t100[
        (t100["CARRIER"] == carrier)
        & (t100["YEAR"] == config.YEAR)
        & (t100["MONTH"].isin(config.QUARTER_MONTHS))
        & (t100["AIRCRAFT_TYPE"] == aircraft_type_code)
    ]
    asms = float((t100_match["SEATS"] * t100_match["DISTANCE"]).sum())

    return (opex_usd / asms) * 100 if asms > 0 else None


def _run_scenario(base_pax, predicted_dominant_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles):
    sized_pax = layer1_sizing.apply_stimulation(base_pax, uplift)
    days_per_year = config.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
    mean_daily_pax = sized_pax * predicted_dominant_share / days_per_year

    boardings = layer1_spill.expected_boardings(
        mean_daily_pax, seats_per_departure, config.PROPOSED_FREQ_DAILY, recapture=recapture
    )
    pnl_result = layer1_pnl.main_pnl(
        boardings, mean_fare, seats_per_departure, config.PROPOSED_FREQ_DAILY,
        config.QUARTER_DAYS, distance_miles, casm_cents,
    )
    verdict = "go" if pnl_result["expected_load_factor"] >= pnl_result["breakeven_lf"] else "no_go"
    return sized_pax, boardings, pnl_result, verdict


def _atl_sat_segment_daily_frequencies(t100_csv_path):
    """Every carrier's real observed daily frequency on the ATL-SAT segment
    (one direction, matching config.PROPOSED_FREQ_DAILY's convention)."""
    t100 = pd.read_csv(t100_csv_path, usecols=["ORIGIN", "DEST", "CARRIER", "DEPARTURES_PERFORMED", "YEAR", "MONTH"])
    t100 = t100[(t100["YEAR"] == config.YEAR) & (t100["MONTH"].isin(config.QUARTER_MONTHS))]
    outbound = t100[(t100["ORIGIN"] == config.MARKET_ORIGIN) & (t100["DEST"] == config.MARKET_DEST)]
    quarterly = outbound.groupby("CARRIER")["DEPARTURES_PERFORMED"].sum()
    return (quarterly / config.QUARTER_DAYS).to_dict()


def run_verdict1_atl_sat(db1b_csv_path):
    """Builds ATL-SAT's local dataframe, predicts Delta's share via the
    unrefit Wave 1 logit, resolves Delta's mainline aircraft/CASM, and runs
    the 48-combination sensitivity grid. Returns (verdict1_output_dict,
    context_dict) -- context is what Verdict 2/3 need downstream."""
    local_df = build_local_dataframe(db1b_csv_path)
    mean_fare = float(local_df["MktFare"].mean())
    distance_miles = float(local_df["MktDistance"].mean())
    passenger_total_sample = float(local_df["Passengers"].sum())
    base_pax = layer1_sizing.annualize_sample(passenger_total_sample)

    t100_csv_path = layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)
    p52_csv_path = os.path.join(os.path.dirname(__file__), "..", "layer1", "data", "T_F41SCHEDULE_P52.csv")

    print("Building ATL-SAT choice set...")
    t100_freq_features = layer1_calibration.load_t100_features(t100_csv_path)
    airport_carrier_share = layer1_verdict1._t100_airport_carrier_share(t100_csv_path)
    choice_set = _build_choice_set(local_df, t100_freq_features, airport_carrier_share)
    print(f"  choice set: {list(choice_set['carrier'])}")

    coefficients = layer1_logit.load_coefficients(LOGIT_COEFFICIENTS_PATH)
    predicted = layer1_logit.predict_shares(choice_set, coefficients)
    predicted_dominant_share = float(predicted[choice_set["carrier"] == config.DOMINANT_CARRIER].iloc[0])

    incumbent_freqs = _atl_sat_segment_daily_frequencies(t100_csv_path)
    all_freqs = list(incumbent_freqs.values())
    scurve_share_value = layer1_scurve.scurve_share(
        float(config.PROPOSED_FREQ_DAILY), all_freqs, alpha=layer1_scurve.DEFAULT_ALPHA
    )

    print("Resolving Delta's ATL-SAT aircraft type and CASM...")
    aircraft_code, seats_per_departure, mean_aircraft_distance = aircraft_id.resolve_dominant_aircraft_type_code(
        config.DOMINANT_CARRIER, config.AIRCRAFT_SEATS_MIN, config.AIRCRAFT_SEATS_MAX,
        t100_csv_path, p52_csv_path, year=config.YEAR, quarter=config.QUARTER,
    )
    casm_cents = _compute_casm(config.DOMINANT_CARRIER, aircraft_code, p52_csv_path, t100_csv_path)

    sized_pax, boardings, pnl_result, verdict = _run_scenario(
        base_pax, predicted_dominant_share, layer1_sizing.DEFAULT_STIMULATION_UPLIFT, layer1_spill.DEFAULT_RECAPTURE_RATE,
        seats_per_departure, casm_cents, mean_fare, distance_miles,
    )

    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, _, sens_pnl, sens_verdict = _run_scenario(
            base_pax, predicted_dominant_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
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

    verdict1_output = {
        "market": config.MARKET_PAIR,
        "carrier": config.DOMINANT_CARRIER,
        "verdict": verdict,
        "robust": robust,
        "expected_load_factor": pnl_result["expected_load_factor"],
        "breakeven_load_factor": pnl_result["breakeven_lf"],
        "revenue_annual_usd": pnl_result["revenue"],
        "cost_annual_usd": pnl_result["cost"],
        "contribution_annual_usd": pnl_result["contribution"],
        "delta_e175_casm_cents": casm_cents,
        "sizing": {"base_pax": base_pax, "uplift": layer1_sizing.DEFAULT_STIMULATION_UPLIFT, "sized_pax": sized_pax},
        "predicted_delta_share": predicted_dominant_share,
        "scurve_share_cross_check": scurve_share_value,
        "sensitivities": sensitivities,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    context = {
        "local_df": local_df,
        "mean_fare": mean_fare,
        "distance_miles": distance_miles,
        "base_pax": base_pax,
        "predicted_dominant_share": predicted_dominant_share,
        "seats_per_departure": seats_per_departure,
        "casm_cents": casm_cents,
        "aircraft_code": aircraft_code,
        "t100_csv_path": t100_csv_path,
        "p52_csv_path": p52_csv_path,
    }
    return verdict1_output, context
