"""Layer 3, Module 1: standalone coalition values v(A) and v(B) for Shapley.

v(A) is AUS-SLC's own nonstop-only mean fare (from Layer 0's parquet). v(B)
is, for each beyond_endpoint observed in Layer 2's feed itineraries, the mean
nonstop fare on the SLC-endpoint market, found by streaming the raw DB1B CSV
a third time (Layer 3's own distinct filter over the same source).
"""

import glob
import os

import pandas as pd

LAYER0_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "data")
DB1B_GLOB_PATTERN = os.path.join(LAYER0_DATA_DIR, "*.csv")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

SLC = "SLC"
NONSTOP_MKT_COUPONS = 1

FARE_OUTLIER_MIN_USD = 50
FARE_OUTLIER_MAX_USD = 2000

DB1B_USECOLS = ["Origin", "Dest", "MktCoupons", "BulkFare", "MktFare"]


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


def standalone_fare_aus_slc(aus_slc_parquet_path):
    """Mean standalone (nonstop-only) fare for AUS-SLC."""
    df = pd.read_parquet(aus_slc_parquet_path)
    nonstop = df[df["MktCoupons"] == NONSTOP_MKT_COUPONS]
    return float(nonstop["MktFare"].mean())


def _clean_chunk(chunk):
    chunk = chunk.dropna(subset=["MktFare"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def standalone_fares_slc_beyond(db1b_csv_path, endpoints):
    """Mean standalone nonstop fare on the SLC-endpoint market, one row per endpoint."""
    target_market_to_endpoint = {"-".join(sorted((SLC, e))): e for e in endpoints}

    fare_sums = {e: 0.0 for e in endpoints}
    counts = {e: 0 for e in endpoints}

    reader = pd.read_csv(db1b_csv_path, usecols=DB1B_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, start=1):
        chunk = _clean_chunk(chunk)
        chunk = chunk[chunk["MktCoupons"] == NONSTOP_MKT_COUPONS]
        market = ["-".join(sorted((o, d))) for o, d in zip(chunk["Origin"], chunk["Dest"])]
        chunk = chunk.assign(market=market)
        chunk = chunk[chunk["market"].isin(target_market_to_endpoint)]

        for market_key, group in chunk.groupby("market"):
            endpoint = target_market_to_endpoint[market_key]
            fare_sums[endpoint] += float(group["MktFare"].sum())
            counts[endpoint] += len(group)

        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (standalone fare pass)")

    rows = []
    for endpoint in endpoints:
        n = counts[endpoint]
        mean_fare = (fare_sums[endpoint] / n) if n > 0 else float("nan")
        flagged = n == 0 or (n > 0 and (mean_fare < FARE_OUTLIER_MIN_USD or mean_fare > FARE_OUTLIER_MAX_USD))
        rows.append(
            {
                "beyond_endpoint": endpoint,
                "mean_standalone_fare": mean_fare,
                "n_observations": n,
                "flagged": flagged,
            }
        )
    return pd.DataFrame(rows)
