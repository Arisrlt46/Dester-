"""Layer 1 Wave 2, Module 7: route P&L and breakeven load factor.

Delta mainline doesn't operate E175 regional jets under its own carrier code
in T-100 or Form 41 P-5.2 -- that flying is filed under the regional partner
that actually operates it. SkyWest (OO) is Delta Connection's dominant E175
operator, so E175 identification and CASM are computed from OO's own filings
(the true cost structure for this equipment type), applied as a unit-cost
rate to Delta's proposed AUS-SLC route economics.
"""

import pandas as pd

E175_CARRIER_CODE = "OO"
E175_SEATS_MIN = 70
E175_SEATS_MAX = 82

DEFAULT_QUARTER = 2
DEFAULT_YEAR = 2025
QUARTER_MONTHS = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}

FORM41_DOLLAR_UNITS = 1000  # Form 41 Schedule P-5.2 reports dollar figures in thousands

QUARTER_DAYS = 91
YEAR_QUARTERS = 4


def _e175_candidates(t100_csv_path, quarter=DEFAULT_QUARTER, year=DEFAULT_YEAR):
    months = QUARTER_MONTHS[quarter]
    t100 = pd.read_csv(
        t100_csv_path,
        usecols=["CARRIER", "AIRCRAFT_TYPE", "DEPARTURES_PERFORMED", "SEATS", "YEAR", "MONTH"],
    )
    sub = t100[(t100["CARRIER"] == E175_CARRIER_CODE) & (t100["YEAR"] == year) & (t100["MONTH"].isin(months))]

    agg = sub.groupby("AIRCRAFT_TYPE").agg(
        departures=("DEPARTURES_PERFORMED", "sum"), seats=("SEATS", "sum")
    )
    agg = agg[agg["departures"] > 0]
    agg["seats_per_departure"] = agg["seats"] / agg["departures"]
    return agg[(agg["seats_per_departure"] >= E175_SEATS_MIN) & (agg["seats_per_departure"] <= E175_SEATS_MAX)]


def resolve_e175_aircraft_type_code(p52_csv_path, t100_csv_path, quarter=DEFAULT_QUARTER, year=DEFAULT_YEAR):
    """Identify the E175 AIRCRAFT_TYPE code: most-heavily-operated by the E175
    carrier with fleet-average seats-per-departure in [70, 82]."""
    band = _e175_candidates(t100_csv_path, quarter=quarter, year=year)
    if band.empty:
        raise RuntimeError(
            f"No {E175_CARRIER_CODE} aircraft type found with seats-per-departure in "
            f"[{E175_SEATS_MIN}, {E175_SEATS_MAX}] for {year} Q{quarter}"
        )

    chosen = band.sort_values("departures", ascending=False).iloc[0]
    code = int(chosen.name)
    print(
        f"Identified E175 aircraft type code: {code} (carrier={E175_CARRIER_CODE}, "
        f"seats/departure={chosen['seats_per_departure']:.1f}, departures={int(chosen['departures'])})"
    )

    p52 = pd.read_csv(p52_csv_path, usecols=["CARRIER", "AIRCRAFT_TYPE", "YEAR", "QUARTER"])
    in_p52 = (
        (p52["CARRIER"] == E175_CARRIER_CODE)
        & (p52["YEAR"] == year)
        & (p52["QUARTER"] == quarter)
        & (p52["AIRCRAFT_TYPE"] == code)
    ).any()
    if not in_p52:
        print(f"  WARNING: aircraft type {code} not found in Form 41 P-5.2 for {E175_CARRIER_CODE} {year} Q{quarter}")

    return code


def e175_seats_per_departure(t100_csv_path, quarter=DEFAULT_QUARTER, year=DEFAULT_YEAR):
    """Fleet-average seats-per-departure for the identified E175 aircraft type."""
    band = _e175_candidates(t100_csv_path, quarter=quarter, year=year)
    chosen = band.sort_values("departures", ascending=False).iloc[0]
    return float(chosen["seats_per_departure"])


def compute_delta_e175_casm(p52_csv_path, t100_csv_path, quarter=DEFAULT_QUARTER, year=DEFAULT_YEAR):
    """Delta E175 CASM: opex from Form 41 P-5.2, ASMs from T-100, both for the
    E175 carrier (SkyWest/OO) and aircraft type identified above."""
    aircraft_type = resolve_e175_aircraft_type_code(p52_csv_path, t100_csv_path, quarter=quarter, year=year)

    p52 = pd.read_csv(p52_csv_path)
    p52_match = p52[
        (p52["CARRIER"] == E175_CARRIER_CODE)
        & (p52["YEAR"] == year)
        & (p52["QUARTER"] == quarter)
        & (p52["AIRCRAFT_TYPE"] == aircraft_type)
    ]
    opex_usd = float(p52_match["TOT_AIR_OP_EXPENSES"].sum()) * FORM41_DOLLAR_UNITS

    months = QUARTER_MONTHS[quarter]
    t100 = pd.read_csv(t100_csv_path, usecols=["CARRIER", "AIRCRAFT_TYPE", "SEATS", "DISTANCE", "YEAR", "MONTH"])
    t100_match = t100[
        (t100["CARRIER"] == E175_CARRIER_CODE)
        & (t100["YEAR"] == year)
        & (t100["MONTH"].isin(months))
        & (t100["AIRCRAFT_TYPE"] == aircraft_type)
    ]
    asms = float((t100_match["SEATS"] * t100_match["DISTANCE"]).sum())

    casm_cents_per_asm = (opex_usd / asms) * 100 if asms > 0 else None
    return {"opex_usd": opex_usd, "asms": asms, "casm_cents_per_asm": casm_cents_per_asm}


def route_pnl(revenue, asms, casm):
    """revenue here is the full-capacity (100% load factor) revenue potential,
    which is what makes cost/revenue a genuine breakeven load factor."""
    cost = asms * (casm / 100.0)
    contribution = revenue - cost
    breakeven_lf = cost / revenue if revenue > 0 else float("inf")
    return {"revenue": revenue, "cost": cost, "contribution": contribution, "breakeven_lf": breakeven_lf}


def main_pnl(expected_boardings, mean_fare, seats_per_departure, freq_per_day, quarter_days, distance_miles, casm_cents):
    """Route P&L for Delta's proposed AUS-SLC service.

    route_pnl needs full-capacity revenue to produce a genuine breakeven load
    factor (cost is capacity-driven via CASM, so revenue must be on the same
    100%-LF basis for cost/revenue to be a load-factor ratio). The realistic
    expected revenue/cost/contribution reported here use expected_boardings'
    actual boarded passengers instead.
    """
    days_per_year = quarter_days * YEAR_QUARTERS
    departures_per_year = freq_per_day * days_per_year
    capacity_seats_annual = seats_per_departure * departures_per_year

    asms = capacity_seats_annual * distance_miles
    full_capacity_revenue = capacity_seats_annual * mean_fare
    capacity_pnl = route_pnl(full_capacity_revenue, asms, casm_cents)

    expected_annual_boarded = expected_boardings["expected_boarded"] * days_per_year
    expected_revenue = expected_annual_boarded * mean_fare
    expected_cost = capacity_pnl["cost"]
    expected_contribution = expected_revenue - expected_cost

    return {
        "revenue": expected_revenue,
        "cost": expected_cost,
        "contribution": expected_contribution,
        "breakeven_lf": capacity_pnl["breakeven_lf"],
        "expected_load_factor": expected_boardings["expected_load_factor"],
        "asms": asms,
    }
