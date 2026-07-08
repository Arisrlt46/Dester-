"""Layer 4 Wave 1, Module 1: market screener.

Streams the raw DB1B in chunks (fourth distinct filter over the same source
file used by Layers 0-3), builds per-(hub, spoke, carrier) local accumulators
and per-(hub, spoke) feed-itinerary accumulators, and returns a ranked
candidate table of spoke-to-major-hub markets by feed revenue share.

A single connecting itinerary A-hub-B is feed for *two* candidate markets
simultaneously (hub, A) and (hub, B) -- one as the behind leg of one market,
one as the beyond leg of the other -- whenever both A and B are themselves
non-hub spokes. This generalizes Layer 2's single-market (AUS-SLC) feed rule
to all ten hubs screened at once.

Two streaming passes over the raw CSV:
  Pass 1 -- local nonstop stats per (hub, spoke, carrier) to determine each
            candidate market's dominant carrier, plus every 2-coupon feed
            itinerary touching any of the ten hubs (spoke, beyond_endpoint,
            fare, passengers, miles), deferred until candidates are known.
  Pass 2 -- for the (spoke, beyond_endpoint) sub-markets that survive
            candidate filtering, each carrier's observed passenger share
            pooled across all DB1B routings for that sub-market (Layer 2's
            observed-share convention, generalized).
"""

import glob
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

LAYER0_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "data")
DB1B_GLOB_PATTERN = os.path.join(LAYER0_DATA_DIR, "*.csv")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

HUB_AIRPORTS = ["ATL", "DFW", "ORD", "DEN", "LAX", "CLT", "LAS", "PHX", "SEA", "MSP"]

MIN_LOCAL_PASSENGERS = 500
DOMINANT_SHARE_THRESHOLD = 0.40

BORDERLINE_MIN = 0.25
BORDERLINE_MAX = 0.45

TOP_N_OVERALL = 10
TOP_N_BORDERLINE = 5
N_DECILE_BUCKETS = 10

OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
OUTPUT_PARQUET_NAME = "market_screener.parquet"
OUTPUT_SUMMARY_NAME = "screener_summary.json"

LOCAL_MKT_COUPONS = 1
FEED_MKT_COUPONS = 2

DB1B_USECOLS = [
    "Origin",
    "Dest",
    "RPCarrier",
    "OpCarrier",
    "MktCoupons",
    "BulkFare",
    "Passengers",
    "MktFare",
    "NonStopMiles",
    "AirportGroup",
]

SUBMARKET_USECOLS = ["Origin", "Dest", "OpCarrier", "Passengers"]


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
    chunk = chunk.dropna(subset=["Passengers", "MktFare", "NonStopMiles"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def _market_pair(a, b):
    return "-".join(sorted((a, b)))


def _accumulate_local(chunk, hub_set, local_pax, local_rev, local_miles):
    nonstop = chunk[chunk["MktCoupons"] == LOCAL_MKT_COUPONS]
    if not len(nonstop):
        return
    origin_is_hub = nonstop["Origin"].isin(hub_set)
    dest_is_hub = nonstop["Dest"].isin(hub_set)
    spoke_mask = origin_is_hub ^ dest_is_hub
    spoke_rows = nonstop[spoke_mask]
    origin_is_hub = origin_is_hub[spoke_mask]

    for origin, dest, carrier, pax, fare, miles, o_is_hub in zip(
        spoke_rows["Origin"], spoke_rows["Dest"], spoke_rows["RPCarrier"],
        spoke_rows["Passengers"], spoke_rows["MktFare"], spoke_rows["NonStopMiles"], origin_is_hub,
    ):
        hub, spoke = (origin, dest) if o_is_hub else (dest, origin)
        key = (hub, spoke, carrier)
        local_pax[key] = local_pax.get(key, 0.0) + pax
        local_rev[key] = local_rev.get(key, 0.0) + fare * pax
        local_miles.setdefault((hub, spoke), []).append(miles)


def _accumulate_feed(chunk, hub_set, feed_rows):
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

    for origin, dest, mid, pax, fare, miles in zip(
        candidates["Origin"], candidates["Dest"], mids,
        candidates["Passengers"], candidates["MktFare"], candidates["NonStopMiles"],
    ):
        if origin not in hub_set and _market_pair(mid, origin) != _market_pair(origin, dest):
            feed_rows.append((mid, origin, dest, pax, fare, miles))
        if dest not in hub_set and _market_pair(mid, dest) != _market_pair(origin, dest):
            feed_rows.append((mid, dest, origin, pax, fare, miles))


def _resolve_candidates(local_pax, local_rev, local_miles, min_pax):
    rows = []
    keys_by_market = {}
    for (hub, spoke, carrier), pax in local_pax.items():
        keys_by_market.setdefault((hub, spoke), []).append((carrier, pax))

    for (hub, spoke), carrier_pax in keys_by_market.items():
        total = sum(p for _, p in carrier_pax)
        if total < min_pax:
            continue
        dominant_carrier, dominant_pax = max(carrier_pax, key=lambda cp: cp[1])
        share = dominant_pax / total
        if share < DOMINANT_SHARE_THRESHOLD:
            continue
        segment_miles = float(np.median(local_miles[(hub, spoke)]))
        rows.append(
            {
                "hub": hub,
                "spoke": spoke,
                "market_pair": _market_pair(hub, spoke),
                "dominant_carrier": dominant_carrier,
                "dominant_carrier_share": share,
                "local_pax_sample": float(dominant_pax),
                "local_revenue_sample": float(local_rev[(hub, spoke, dominant_carrier)]),
                "segment_miles": segment_miles,
            }
        )
    return pd.DataFrame(rows)


def _stream_submarket_shares(db1b_csv_path, target_submarkets):
    submarket_totals = {}
    submarket_carrier_pax = {}

    reader = pd.read_csv(db1b_csv_path, usecols=SUBMARKET_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, start=1):
        chunk = chunk.dropna(subset=["Passengers"])
        market = ["-".join(sorted((o, d))) for o, d in zip(chunk["Origin"], chunk["Dest"])]
        chunk = chunk.assign(market=market)
        chunk = chunk[chunk["market"].isin(target_submarkets)]
        if len(chunk):
            totals = chunk.groupby("market")["Passengers"].sum()
            for market, val in totals.items():
                submarket_totals[market] = submarket_totals.get(market, 0.0) + float(val)
            carrier_totals = chunk.groupby(["market", "OpCarrier"], observed=True)["Passengers"].sum()
            for (market, carrier), val in carrier_totals.items():
                key = (market, carrier)
                submarket_carrier_pax[key] = submarket_carrier_pax.get(key, 0.0) + float(val)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (pass 2: feed sub-market shares)")

    return submarket_totals, submarket_carrier_pax


def stream_candidate_stats(db1b_csv_path, hub_airports=HUB_AIRPORTS, min_pax=MIN_LOCAL_PASSENGERS):
    """Streams the raw CSV (twice) and returns per-(market, dominant_carrier)
    accumulators, including feed_pax_sample and feed_revenue_allocated."""
    hub_set = set(hub_airports)

    local_pax, local_rev, local_miles = {}, {}, {}
    feed_rows = []

    print(f"Reading raw DB1BMarket CSV: {db1b_csv_path}")
    reader = pd.read_csv(db1b_csv_path, usecols=DB1B_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, start=1):
        chunk = _clean_chunk(chunk)
        _accumulate_local(chunk, hub_set, local_pax, local_rev, local_miles)
        _accumulate_feed(chunk, hub_set, feed_rows)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (pass 1: local stats + feed collection)")

    candidates_df = _resolve_candidates(local_pax, local_rev, local_miles, min_pax)
    print(f"  {len(candidates_df)} candidate markets pass the local screening rule")

    feed_df = pd.DataFrame(feed_rows, columns=["hub", "spoke", "beyond_endpoint", "Passengers", "MktFare", "NonStopMiles"])
    candidate_keys = set(zip(candidates_df["hub"], candidates_df["spoke"]))
    if len(feed_df):
        feed_market_keys = pd.Series(list(zip(feed_df["hub"], feed_df["spoke"])), index=feed_df.index)
        feed_df = feed_df[feed_market_keys.isin(candidate_keys)]
    print(f"  {len(feed_df)} feed itineraries touch a candidate market")

    target_submarkets = {_market_pair(s, b) for s, b in zip(feed_df["spoke"], feed_df["beyond_endpoint"])}
    print(f"Resolving observed carrier shares for {len(target_submarkets)} feed sub-markets...")
    submarket_totals, submarket_carrier_pax = _stream_submarket_shares(db1b_csv_path, target_submarkets)

    dominant_carrier_by_market = {
        (row["hub"], row["spoke"]): row["dominant_carrier"] for _, row in candidates_df.iterrows()
    }
    segment_miles_by_market = {(row["hub"], row["spoke"]): row["segment_miles"] for _, row in candidates_df.iterrows()}

    feed_pax_sample = {k: 0.0 for k in candidate_keys}
    feed_revenue_allocated = {k: 0.0 for k in candidate_keys}

    for hub, spoke, beyond, pax, fare, miles in zip(
        feed_df["hub"], feed_df["spoke"], feed_df["beyond_endpoint"],
        feed_df["Passengers"], feed_df["MktFare"], feed_df["NonStopMiles"],
    ):
        key = (hub, spoke)
        dominant_carrier = dominant_carrier_by_market[key]
        submarket = _market_pair(spoke, beyond)
        total = submarket_totals.get(submarket, 0.0)
        carrier_pax = submarket_carrier_pax.get((submarket, dominant_carrier), 0.0)
        share = (carrier_pax / total) if total > 0 else 0.0

        segment_miles = segment_miles_by_market[key]
        feed_revenue_allocated[key] += fare * (segment_miles / miles) * pax * share
        feed_pax_sample[key] += pax

    candidates_df["feed_pax_sample"] = candidates_df.apply(
        lambda r: feed_pax_sample.get((r["hub"], r["spoke"]), 0.0), axis=1
    )
    candidates_df["feed_revenue_allocated"] = candidates_df.apply(
        lambda r: feed_revenue_allocated.get((r["hub"], r["spoke"]), 0.0), axis=1
    )
    return candidates_df


def compute_feed_shares(candidate_stats_df):
    df = candidate_stats_df.copy()
    denom = df["local_revenue_sample"] + df["feed_revenue_allocated"]
    df["feed_share"] = np.where(denom > 0, df["feed_revenue_allocated"] / denom, 0.0)
    df["flag_borderline"] = (df["feed_share"] >= BORDERLINE_MIN) & (df["feed_share"] <= BORDERLINE_MAX)
    return df.sort_values("feed_share", ascending=True).reset_index(drop=True)


def _decile_distribution(feed_shares):
    if len(feed_shares) == 0:
        return []
    edges = np.linspace(0, 1, N_DECILE_BUCKETS + 1)
    counts, _ = np.histogram(feed_shares, bins=edges)
    return [
        {"bucket": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "count": int(counts[i])}
        for i in range(N_DECILE_BUCKETS)
    ]


def write_outputs(df, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)

    output_columns = [
        "market_pair", "hub", "spoke", "dominant_carrier", "dominant_carrier_share",
        "local_pax_sample", "local_revenue_sample", "feed_pax_sample", "feed_revenue_allocated",
        "feed_share", "flag_borderline",
    ]
    parquet_path = os.path.join(out_dir, OUTPUT_PARQUET_NAME)
    df[output_columns].to_parquet(parquet_path, engine="pyarrow", index=False)

    borderline = df[df["flag_borderline"]]
    top_overall = df.sort_values("feed_share", ascending=False).head(TOP_N_OVERALL)
    top_borderline = borderline.sort_values("feed_share", ascending=False).head(TOP_N_BORDERLINE)

    def _row_summary(row):
        return {
            "market_pair": row["market_pair"],
            "dominant_carrier": row["dominant_carrier"],
            "feed_share": float(row["feed_share"]),
        }

    summary = {
        "total_candidates_screened": int(len(df)),
        "borderline_band": {"min": BORDERLINE_MIN, "max": BORDERLINE_MAX},
        "borderline_count": int(len(borderline)),
        "feed_share_decile_distribution": _decile_distribution(df["feed_share"].to_numpy()),
        "top_candidates_overall": [_row_summary(r) for _, r in top_overall.iterrows()],
        "top_candidates_borderline": [_row_summary(r) for _, r in top_borderline.iterrows()],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_path = os.path.join(out_dir, OUTPUT_SUMMARY_NAME)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {parquet_path} ({len(df)} candidate markets)")
    print(f"Wrote {summary_path}")
    return summary


def main():
    db1b_csv_path = resolve_csv_path(DB1B_GLOB_PATTERN)
    candidate_stats_df = stream_candidate_stats(db1b_csv_path)
    ranked_df = compute_feed_shares(candidate_stats_df)
    summary = write_outputs(ranked_df)

    print()
    print("=== Layer 4 Wave 1 screener summary ===")
    print(f"Total candidate markets screened: {summary['total_candidates_screened']}")
    print(f"Borderline band [{BORDERLINE_MIN}, {BORDERLINE_MAX}]: {summary['borderline_count']} candidates")
    print("Feed-share decile distribution:")
    for bucket in summary["feed_share_decile_distribution"]:
        print(f"  {bucket['bucket']}: {bucket['count']}")
    print("Top 10 candidates by feed share overall:")
    for row in summary["top_candidates_overall"]:
        print(f"  {row['market_pair']:10s} {row['dominant_carrier']:3s} feed_share={row['feed_share']:.3f}")

    if summary["borderline_count"] == 0:
        print()
        print(
            "*** No candidates fall in the borderline band. Feed shares are bimodal across the screened "
            "markets -- worth noting as a genuine finding before Wave 2 is designed. ***"
        )
    else:
        print("Top 5 candidates within the borderline band:")
        for row in summary["top_candidates_borderline"]:
            print(f"  {row['market_pair']:10s} {row['dominant_carrier']:3s} feed_share={row['feed_share']:.3f}")


if __name__ == "__main__":
    main()
