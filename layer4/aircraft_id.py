"""Layer 4 Wave 2, Module 2: market-agnostic aircraft identifier.

Generalizes layer1.pnl.resolve_e175_aircraft_type_code (hardcoded to
SkyWest/E175) to any carrier and seat-count band. Adds a "fleet-mixed"
diagnostic: if more than one aircraft type each represents a substantial
share of the carrier's departures within the band, the top type is still
returned, but downstream P&L should be understood as an average across a
mix rather than a single aircraft type's pure economics.
"""

import pandas as pd

QUARTER_MONTHS = {1: (1, 2, 3), 2: (4, 5, 6), 3: (7, 8, 9), 4: (10, 11, 12)}

FLEET_MIXED_SHARE_THRESHOLD = 0.30

T100_USECOLS = ["CARRIER", "AIRCRAFT_TYPE", "DEPARTURES_PERFORMED", "SEATS", "DISTANCE", "YEAR", "MONTH"]
P52_USECOLS = ["CARRIER", "AIRCRAFT_TYPE", "YEAR", "QUARTER"]


def _candidates(carrier, seats_min, seats_max, t100_csv_path, year, quarter):
    months = QUARTER_MONTHS[quarter]
    t100 = pd.read_csv(t100_csv_path, usecols=T100_USECOLS)
    sub = t100[(t100["CARRIER"] == carrier) & (t100["YEAR"] == year) & (t100["MONTH"].isin(months))]

    agg = sub.groupby("AIRCRAFT_TYPE").agg(departures=("DEPARTURES_PERFORMED", "sum"), seats=("SEATS", "sum"))
    agg = agg[agg["departures"] > 0]
    agg["seats_per_departure"] = agg["seats"] / agg["departures"]
    band = agg[(agg["seats_per_departure"] >= seats_min) & (agg["seats_per_departure"] <= seats_max)].copy()

    weighted_distance = sub.groupby("AIRCRAFT_TYPE").apply(
        lambda g: (g["DISTANCE"] * g["DEPARTURES_PERFORMED"]).sum() / g["DEPARTURES_PERFORMED"].sum(),
        include_groups=False,
    )
    band["mean_distance"] = weighted_distance.reindex(band.index)
    return band


def resolve_dominant_aircraft_type_code(carrier, seats_min, seats_max, t100_csv_path, p52_csv_path, year=2025, quarter=2):
    """Returns (aircraft_type_code, mean_seats_per_departure, mean_departure_distance)."""
    band = _candidates(carrier, seats_min, seats_max, t100_csv_path, year, quarter)
    if band.empty:
        raise RuntimeError(
            f"No {carrier} aircraft type found with seats-per-departure in [{seats_min}, {seats_max}] "
            f"for {year} Q{quarter}"
        )

    total_departures = band["departures"].sum()
    shares = band["departures"] / total_departures
    heavy = shares[shares > FLEET_MIXED_SHARE_THRESHOLD]
    if len(heavy) > 1:
        mix_desc = ", ".join(f"{code}={s:.0%}" for code, s in heavy.sort_values(ascending=False).items())
        print(
            f"  WARNING: fleet-mixed -- multiple {carrier} aircraft types each exceed "
            f"{FLEET_MIXED_SHARE_THRESHOLD:.0%} of departures in this seat band ({mix_desc}). "
            f"Downstream P&L reflects the top type only, understood as an average across the mix."
        )

    chosen = band.sort_values("departures", ascending=False).iloc[0]
    code = int(chosen.name)
    mean_seats_per_departure = float(chosen["seats_per_departure"])
    mean_departure_distance = float(chosen["mean_distance"])

    print(
        f"Identified {carrier} aircraft type code: {code} (seats/departure={mean_seats_per_departure:.1f}, "
        f"mean distance={mean_departure_distance:.1f}mi, departures={int(chosen['departures'])})"
    )

    p52 = pd.read_csv(p52_csv_path, usecols=P52_USECOLS)
    in_p52 = (
        (p52["CARRIER"] == carrier) & (p52["YEAR"] == year) & (p52["QUARTER"] == quarter) & (p52["AIRCRAFT_TYPE"] == code)
    ).any()
    if not in_p52:
        print(f"  WARNING: aircraft type {code} not found in Form 41 P-5.2 for {carrier} {year} Q{quarter}")

    return code, mean_seats_per_departure, mean_departure_distance
