"""Layer 4 MIA-SEA: market and aircraft constants.

Mirrors layer4/config.py's structure exactly for the third featured market
(MIA-SEA, Delta). Single source of truth for every MIA-SEA-specific value --
downstream modules (verdict1_mia_sea.py, verdict2_mia_sea.py,
verdict3_mia_sea.py, verdict4_mia_sea.py) import from here rather than
re-declaring, and never from layer4/config.py (that module is ATL-SAT-only).

SEA is Delta's hub on this pair (MIA is dominantly American's territory,
per the research brief) -- so HUB/SPOKE are the reverse of MARKET_ORIGIN/
MARKET_DEST's own AUS-SLC-style "market_origin, market_dest" ordering used
for feed detection: HUB=SEA, SPOKE=MIA.
"""

import pandas as pd

from layer1 import calibration as layer1_calibration
from layer1 import pnl as layer1_pnl

MARKET_ORIGIN = "MIA"
MARKET_DEST = "SEA"
HUB = "SEA"
SPOKE = "MIA"
DOMINANT_CARRIER = "DL"
MARKET_PAIR = "-".join(sorted((MARKET_ORIGIN, MARKET_DEST)))

YEAR = 2025
QUARTER = 2
QUARTER_MONTHS = (4, 5, 6)
QUARTER_DAYS = layer1_pnl.QUARTER_DAYS

# Mainline narrowbody equipment (A220/737/A319-A321 family), matching
# ATL-SAT's own band -- not a regional jet.
AIRCRAFT_SEATS_MIN = 100
AIRCRAFT_SEATS_MAX = 230


def _resolve_t100_path():
    return layer1_calibration.resolve_csv_path(layer1_calibration.T100_GLOB_PATTERN)


def _compute_proposed_freq_daily_and_miles():
    """Delta's observed one-directional (MIA->SEA) daily frequency and the
    market's stage length, both from T-100 2025 Q2. One-directional to match
    ATL-SAT's own PROPOSED_FREQ_DAILY convention."""
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
