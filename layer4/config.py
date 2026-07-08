"""Layer 4 Wave 2, Module 1: ATL-SAT market and aircraft constants.

Single source of truth for every ATL-SAT-specific value. Downstream Wave 2
modules (verdict1_atl_sat.py, verdict2_atl_sat.py, verdict3_atl_sat.py,
verdict4.py) import from here rather than re-declaring.
"""

import pandas as pd

from layer1 import calibration as layer1_calibration
from layer1 import pnl as layer1_pnl

MARKET_ORIGIN = "ATL"
MARKET_DEST = "SAT"
HUB = "ATL"
SPOKE = "SAT"
DOMINANT_CARRIER = "DL"
MARKET_PAIR = "-".join(sorted((MARKET_ORIGIN, MARKET_DEST)))

YEAR = 2025
QUARTER = 2
QUARTER_MONTHS = (4, 5, 6)
QUARTER_DAYS = layer1_pnl.QUARTER_DAYS

# Wider than the E175's 70-82 seat band: ATL-SAT is flown with Delta mainline
# narrowbody equipment (A220/737/A319-A321 family), not a regional jet.
AIRCRAFT_SEATS_MIN = 100
AIRCRAFT_SEATS_MAX = 230


def _resolve_t100_path():
    return layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)


def _compute_proposed_freq_daily_and_miles():
    """Delta's observed one-directional daily frequency and the market's
    great-circle-equivalent stage length, both from T-100 2025 Q2.

    One-directional (not both directions summed) to match how AUS-SLC's
    freq_per_day fed directly into capacity = seats_per_departure *
    freq_per_day throughout Layer 1 Wave 2 and Layer 2 -- ATL-SAT and SAT-ATL
    are almost perfectly symmetric (666 vs. 662 departures/quarter), so this
    is a one-line direction choice, not an approximation.
    """
    t100_csv_path = _resolve_t100_path()
    t100 = pd.read_csv(
        t100_csv_path,
        usecols=["ORIGIN", "DEST", "CARRIER", "DEPARTURES_PERFORMED", "DISTANCE", "YEAR", "MONTH"],
    )
    t100 = t100[(t100["YEAR"] == YEAR) & (t100["MONTH"].isin(QUARTER_MONTHS))]

    outbound = t100[
        (t100["CARRIER"] == DOMINANT_CARRIER) & (t100["ORIGIN"] == MARKET_ORIGIN) & (t100["DEST"] == MARKET_DEST)
    ]
    departures = float(outbound["DEPARTURES_PERFORMED"].sum())
    freq_daily = int(round(departures / QUARTER_DAYS))
    market_miles = float(outbound["DISTANCE"].mean()) if len(outbound) else float("nan")
    return freq_daily, market_miles


PROPOSED_FREQ_DAILY, MARKET_MILES = _compute_proposed_freq_daily_and_miles()
