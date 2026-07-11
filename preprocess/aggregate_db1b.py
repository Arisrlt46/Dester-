"""One-time preprocessing: aggregate Layer 0's raw ~2GB DB1BMarket CSV into
two small, committable parquet files under data/, so DESTER can be cloned
and explored without downloading BTS data.

This is purely additive -- it does not modify or replace any layerN module.
Layer 1-4 continue to run against the raw CSV exactly as before; this script
only produces a smaller, approximate, portable alternative dataset.

Two aggregates, from a single streaming pass over the raw CSV:

- data/db1b_local_agg.parquet -- one row per (Origin, Dest, RPCarrier,
  OpCarrier, MktCoupons), all itineraries nationally. RPCarrier is Wave 1's
  own carrier-identity dimension (market-share grouping); OpCarrier is kept
  too because Wave 1's hub_dominance feature needs the *operating* carrier's
  airport-touch share, which RPCarrier alone cannot support -- an addition
  to the schema as originally sketched, not a deviation from it.

- data/db1b_feed_agg.parquet -- one row per (hub, spoke, beyond_endpoint,
  direction, OpCarrier, MktCoupons), for 2-coupon itineraries where a
  top-10-hub airport is the connecting (middle) airport of the routing.
  Mirrors Layer 4's screener rule: a single itinerary can contribute to two
  different (hub, spoke) feed entries when both outer endpoints are
  non-hub spokes.

Approximations inherent to aggregating away itinerary-level rows (documented,
not hidden): log_fare and routing_efficiency are recovered downstream as
ratio-of-sums (e.g. log(sum_fare_x_passengers / sum_passengers)), not the raw
pipeline's exact passenger-weighted mean-of-ratios. This is expected to
introduce small numerical differences versus the raw-CSV pipeline, not
correctness bugs.
"""

import glob
import json
import os

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB1B_GLOB_PATTERN = os.path.join(PROJECT_ROOT, "layer0", "data", "*.csv")

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOCAL_AGG_PATH = os.path.join(DATA_DIR, "db1b_local_agg.parquet")
FEED_AGG_PATH = os.path.join(DATA_DIR, "db1b_feed_agg.parquet")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

HUB_AIRPORTS = ["ATL", "DFW", "ORD", "DEN", "LAX", "CLT", "LAS", "PHX", "SEA", "MSP"]
FEED_MKT_COUPONS = 2

SOFT_SIZE_LIMIT_MB = 50
HARD_SIZE_LIMIT_MB = 100

DB1B_USECOLS = [
    "MktID", "Origin", "Dest", "RPCarrier", "OpCarrier", "MktCoupons",
    "BulkFare", "Passengers", "MktFare", "MktDistance", "NonStopMiles", "AirportGroup",
]

LOCAL_KEY_COLS = ["Origin", "Dest", "RPCarrier", "OpCarrier", "MktCoupons"]
LOCAL_SUM_COLS = ["sum_passengers", "sum_fare_x_passengers", "sum_mktdistance_x_passengers", "sum_nonstopmiles_x_passengers"]


def resolve_csv_path(pattern):
    matches = sorted(glob.glob(pattern))
    if len(matches) == 0:
        raise FileNotFoundError(f"No CSV files found matching {pattern}.")
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one CSV matching {pattern}, found {len(matches)}: {matches}. "
            f"Remove extras so the input is unambiguous."
        )
    return matches[0]


def _market_pair(a, b):
    return "-".join(sorted((a, b)))


def _clean_chunk(chunk):
    chunk = chunk.dropna(subset=["Passengers", "MktFare", "MktDistance", "NonStopMiles"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def _accumulate_local(chunk, local_agg):
    chunk = chunk.copy()
    chunk["_fare_x_pax"] = chunk["MktFare"] * chunk["Passengers"]
    chunk["_dist_x_pax"] = chunk["MktDistance"] * chunk["Passengers"]
    chunk["_nsm_x_pax"] = chunk["NonStopMiles"] * chunk["Passengers"]

    grouped = chunk.groupby(LOCAL_KEY_COLS, observed=True).agg(
        sum_passengers=("Passengers", "sum"),
        sum_fare_x_passengers=("_fare_x_pax", "sum"),
        sum_mktdistance_x_passengers=("_dist_x_pax", "sum"),
        sum_nonstopmiles_x_passengers=("_nsm_x_pax", "sum"),
        row_count=("Passengers", "size"),
    )

    for key, row in grouped.iterrows():
        acc = local_agg.setdefault(
            key, {"sum_passengers": 0.0, "sum_fare_x_passengers": 0.0, "sum_mktdistance_x_passengers": 0.0, "sum_nonstopmiles_x_passengers": 0.0, "row_count": 0}
        )
        acc["sum_passengers"] += row["sum_passengers"]
        acc["sum_fare_x_passengers"] += row["sum_fare_x_passengers"]
        acc["sum_mktdistance_x_passengers"] += row["sum_mktdistance_x_passengers"]
        acc["sum_nonstopmiles_x_passengers"] += row["sum_nonstopmiles_x_passengers"]
        acc["row_count"] += int(row["row_count"])


def _add_feed_row(feed_agg, hub, spoke, beyond, direction, op_carrier, mktid, pax, fare, mkt_dist, nsm, airport_group):
    key = (hub, spoke, beyond, direction, op_carrier, FEED_MKT_COUPONS)
    acc = feed_agg.setdefault(
        key,
        {
            "sum_passengers": 0.0, "sum_fare_x_passengers": 0.0,
            "sum_mktdistance_x_passengers": 0.0, "sum_nonstopmiles_x_passengers": 0.0,
            "mktid_set": set(), "sample_airportgroup": airport_group,
        },
    )
    acc["sum_passengers"] += pax
    acc["sum_fare_x_passengers"] += fare * pax
    acc["sum_mktdistance_x_passengers"] += mkt_dist * pax
    acc["sum_nonstopmiles_x_passengers"] += nsm * pax
    acc["mktid_set"].add(mktid)


def _accumulate_feed(chunk, hub_set, feed_agg):
    two_coupon = chunk[chunk["MktCoupons"] == FEED_MKT_COUPONS]
    if not len(two_coupon):
        return
    parts = two_coupon["AirportGroup"].astype(str).str.split(":")
    three_leg = parts.str.len() == 3
    two_coupon = two_coupon[three_leg]
    parts = parts[three_leg]
    if not len(two_coupon):
        return

    middle = parts.str[1]
    middle_is_hub = middle.isin(hub_set)
    candidates = two_coupon[middle_is_hub]
    mids = middle[middle_is_hub]
    if not len(candidates):
        return

    for origin, dest, hub, op_carrier, mktid, pax, fare, mkt_dist, nsm, airport_group in zip(
        candidates["Origin"], candidates["Dest"], mids, candidates["OpCarrier"], candidates["MktID"],
        candidates["Passengers"], candidates["MktFare"], candidates["MktDistance"],
        candidates["NonStopMiles"], candidates["AirportGroup"],
    ):
        if origin not in hub_set and _market_pair(hub, origin) != _market_pair(origin, dest):
            _add_feed_row(feed_agg, hub, origin, dest, "BEHIND", op_carrier, mktid, pax, fare, mkt_dist, nsm, airport_group)
        if dest not in hub_set and _market_pair(hub, dest) != _market_pair(origin, dest):
            _add_feed_row(feed_agg, hub, dest, origin, "BEYOND", op_carrier, mktid, pax, fare, mkt_dist, nsm, airport_group)


def _local_agg_to_df(local_agg):
    rows = []
    for (origin, dest, rp_carrier, op_carrier, mkt_coupons), acc in local_agg.items():
        rows.append(
            {
                "Origin": origin, "Dest": dest, "RPCarrier": rp_carrier, "OpCarrier": op_carrier,
                "MktCoupons": int(mkt_coupons), **{k: acc[k] for k in LOCAL_SUM_COLS}, "row_count": acc["row_count"],
            }
        )
    return pd.DataFrame(rows)


def _feed_agg_to_df(feed_agg):
    rows = []
    for (hub, spoke, beyond, direction, op_carrier, mkt_coupons), acc in feed_agg.items():
        rows.append(
            {
                "hub": hub, "spoke": spoke, "beyond_endpoint": beyond, "direction": direction,
                "OpCarrier": op_carrier, "MktCoupons": int(mkt_coupons),
                "sum_passengers": acc["sum_passengers"],
                "sum_fare_x_passengers": acc["sum_fare_x_passengers"],
                "sum_mktdistance_x_passengers": acc["sum_mktdistance_x_passengers"],
                "sum_nonstopmiles_x_passengers": acc["sum_nonstopmiles_x_passengers"],
                "sample_MktID_count": len(acc["mktid_set"]),
                "sample_AirportGroup": acc["sample_airportgroup"],
            }
        )
    return pd.DataFrame(rows)


def build_aggregates(db1b_csv_path):
    hub_set = set(HUB_AIRPORTS)
    local_agg = {}
    feed_agg = {}

    print(f"Reading raw DB1BMarket CSV: {db1b_csv_path}")
    reader = pd.read_csv(db1b_csv_path, usecols=DB1B_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    total_rows = 0
    for i, chunk in enumerate(reader, start=1):
        total_rows += len(chunk)
        cleaned = _clean_chunk(chunk)
        _accumulate_local(cleaned, local_agg)
        _accumulate_feed(cleaned, hub_set, feed_agg)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks ({total_rows:,} raw rows read so far)")

    print(f"Total raw rows read: {total_rows:,}")
    local_df = _local_agg_to_df(local_agg)
    feed_df = _feed_agg_to_df(feed_agg)
    return local_df, feed_df, total_rows


def _mb(path):
    return os.path.getsize(path) / (1024 * 1024)


def write_outputs(local_df, feed_df):
    os.makedirs(DATA_DIR, exist_ok=True)
    local_df.to_parquet(LOCAL_AGG_PATH, engine="pyarrow", index=False)
    feed_df.to_parquet(FEED_AGG_PATH, engine="pyarrow", index=False)

    local_mb = _mb(LOCAL_AGG_PATH)
    feed_mb = _mb(FEED_AGG_PATH)

    print(f"Wrote {LOCAL_AGG_PATH} ({len(local_df):,} rows, {local_mb:.1f} MB)")
    print(f"Wrote {FEED_AGG_PATH} ({len(feed_df):,} rows, {feed_mb:.1f} MB)")

    for path, mb in [(LOCAL_AGG_PATH, local_mb), (FEED_AGG_PATH, feed_mb)]:
        if mb > HARD_SIZE_LIMIT_MB:
            print(f"*** STOP: {path} is {mb:.1f} MB, exceeding GitHub's {HARD_SIZE_LIMIT_MB} MB hard block. ***")
            raise SystemExit(1)
        if mb > SOFT_SIZE_LIMIT_MB:
            print(f"*** WARNING: {path} is {mb:.1f} MB, exceeding the {SOFT_SIZE_LIMIT_MB} MB soft target (GitHub's soft-block threshold). ***")

    return local_mb, feed_mb


def validate_against_layer0_summary(local_df):
    summary_path = os.path.join(PROJECT_ROOT, "layer0", "out", "summary.json")
    if not os.path.exists(summary_path):
        print("No layer0/out/summary.json found -- skipping validation.")
        return None

    with open(summary_path) as f:
        summary = json.load(f)

    mask = (
        ((local_df["Origin"] == "AUS") & (local_df["Dest"] == "SLC"))
        | ((local_df["Origin"] == "SLC") & (local_df["Dest"] == "AUS"))
    ) & (local_df["RPCarrier"] == "DL")
    aggregate_pax = float(local_df.loc[mask, "sum_passengers"].sum())
    reference_pax = summary["passenger_total_sample"] * summary["carrier_share_by_pax"].get("DL", 0.0)

    # Layer 0's own passenger_total_sample is all-carrier; scale by DL's own
    # reported share for an apples-to-apples DL-only comparison, since the
    # aggregate is filtered to RPCarrier == DL specifically.
    if reference_pax == 0:
        print("Could not derive a DL-only reference figure from summary.json -- skipping validation.")
        return None

    pct_diff = abs(aggregate_pax - reference_pax) / reference_pax * 100
    print(f"AUS-SLC + Delta local passengers: aggregate={aggregate_pax:.1f} vs. Layer 0-derived reference={reference_pax:.1f} ({pct_diff:.2f}% diff)")
    if pct_diff > 1.0:
        print("*** WARNING: aggregate diverges from Layer 0's reference by more than 1% -- possible bug. ***")
    else:
        print("Within 1% tolerance.")
    return pct_diff


def main():
    db1b_csv_path = resolve_csv_path(DB1B_GLOB_PATTERN)
    local_df, feed_df, total_rows = build_aggregates(db1b_csv_path)
    local_mb, feed_mb = write_outputs(local_df, feed_df)
    validate_against_layer0_summary(local_df)

    print()
    print("=== Aggregate preprocessing summary ===")
    print(f"Total raw rows read: {total_rows:,}")
    print(f"Local aggregate: {len(local_df):,} rows, {local_mb:.1f} MB")
    print(f"Feed aggregate: {len(feed_df):,} rows, {feed_mb:.1f} MB")


if __name__ == "__main__":
    main()
