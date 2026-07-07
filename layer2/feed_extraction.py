"""Layer 2, Module 1: extract behind/beyond feed itineraries through SLC.

Streams the raw DB1BMarket CSV chunk-by-chunk (reusing Layer 0's raw file
directly, never loading the whole ~2GB file into memory) and keeps two-coupon
itineraries where the AUS-SLC segment appears as one of the two legs, and the
itinerary's own market pair is not AUS-SLC directly.

Feed extraction is intentionally permissive: all feasible connections through
SLC are kept, even geographic-detour routings. Real observed passenger
behavior is the honest count.
"""

import glob
import os

import numpy as np
import pandas as pd

LAYER0_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "data")
DB1B_GLOB_PATTERN = os.path.join(LAYER0_DATA_DIR, "*.csv")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

AUS = "AUS"
SLC = "SLC"
AUS_SLC_SUBSTR = "AUS:SLC"
SLC_AUS_SUBSTR = "SLC:AUS"

FEED_MKT_COUPONS = 2

DB1B_USECOLS = [
    "ItinID",
    "MktID",
    "Year",
    "Quarter",
    "Origin",
    "Dest",
    "RPCarrier",
    "TkCarrier",
    "OpCarrier",
    "MktCoupons",
    "BulkFare",
    "Passengers",
    "MktFare",
    "MktDistance",
    "NonStopMiles",
    "AirportGroup",
]


def resolve_csv_path(pattern):
    """Find a single CSV matching pattern, raising a clear error otherwise."""
    matches = sorted(glob.glob(pattern))
    if len(matches) == 0:
        raise FileNotFoundError(f"No CSV files found matching {pattern}.")
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one CSV matching {pattern}, found {len(matches)}: {matches}. "
            f"Remove extras so the input is unambiguous."
        )
    return matches[0]


def _clean_chunk(chunk):
    chunk = chunk.dropna(subset=["Passengers", "MktFare", "MktDistance", "NonStopMiles"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def _filter_feed_rows(chunk):
    """Apply the feed rule. AUS must be one of the itinerary's true endpoints
    (Origin or Dest) -- otherwise the AirportGroup substring match can pick up
    unrelated markets that merely connect through AUS or SLC as a waypoint
    (e.g. SLC-PIT routed via AUS has AirportGroup "SLC:AUS:PIT", which
    contains "SLC:AUS" but has nothing to do with AUS-SLC feed)."""
    chunk = chunk[chunk["MktCoupons"] == FEED_MKT_COUPONS]
    airport_group = chunk["AirportGroup"].astype(str)
    touches_aus_slc = airport_group.str.contains(AUS_SLC_SUBSTR, regex=False) | airport_group.str.contains(
        SLC_AUS_SUBSTR, regex=False
    )
    chunk = chunk[touches_aus_slc]
    chunk = chunk[(chunk["Origin"] == AUS) | (chunk["Dest"] == AUS)]
    is_aus_slc_market = chunk["Origin"].isin([AUS, SLC]) & chunk["Dest"].isin([AUS, SLC])
    return chunk[~is_aus_slc_market]


def _add_feed_columns(df):
    df = df.copy()
    is_behind = df["Origin"] == AUS
    df["feed_direction"] = np.where(is_behind, "BEHIND", "BEYOND")
    df["beyond_endpoint"] = np.where(is_behind, df["Dest"], df["Origin"])
    df["aus_slc_leg_direction"] = np.where(is_behind, "A_TO_B", "B_TO_A")
    return df


def extract_feed_itineraries(db1b_csv_path):
    """Stream the raw DB1BMarket CSV and extract feed itineraries through SLC."""
    reader = pd.read_csv(db1b_csv_path, usecols=DB1B_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)

    matched_chunks = []
    for i, chunk in enumerate(reader, start=1):
        cleaned = _clean_chunk(chunk)
        matched = _filter_feed_rows(cleaned)
        if len(matched):
            matched_chunks.append(matched)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks")

    if matched_chunks:
        df = pd.concat(matched_chunks, ignore_index=True)
    else:
        df = pd.DataFrame(columns=DB1B_USECOLS)

    return _add_feed_columns(df)
