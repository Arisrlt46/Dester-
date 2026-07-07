"""Layer 2, Module 2: feed passenger economics on the AUS-SLC segment.

Delta's share of each feed market comes from observed DB1B data (option 2B),
not the Wave 1 logit -- Verdict 2 answers a factual question about the
passenger flow Delta actually captures. The logit stays reserved for Layer
3's counterfactuals. Fare allocation to the AUS-SLC segment is provisional
mileage proration; Layer 3 will replace this with Shapley.
"""

import numpy as np
import pandas as pd

from layer2.feed_extraction import DB1B_CHUNK_SIZE, PROGRESS_EVERY_N_CHUNKS

AUS = "AUS"
AUS_SLC_GREAT_CIRCLE_MILES = 1085

FEED_SHARE_USECOLS = ["Origin", "Dest", "OpCarrier", "Passengers"]

DELTA_CARRIER_CODE = "DL"


def compute_feed_shares(feed_df, raw_db1b_csv_path):
    """Delta's observed share of each feed market's TOTAL passenger flow
    (any routing, not just SLC-connecting), one row per (beyond_endpoint,
    direction) combination present in feed_df."""
    endpoints = sorted(feed_df["beyond_endpoint"].unique())
    target_markets = {"-".join(sorted((AUS, endpoint))) for endpoint in endpoints}

    dl_pax = {market: 0.0 for market in target_markets}
    total_pax = {market: 0.0 for market in target_markets}

    reader = pd.read_csv(raw_db1b_csv_path, usecols=FEED_SHARE_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, start=1):
        chunk = chunk.dropna(subset=["Passengers"])
        market = [
            "-".join(sorted((o, d))) for o, d in zip(chunk["Origin"], chunk["Dest"])
        ]
        chunk = chunk.assign(market=market)
        chunk = chunk[chunk["market"].isin(target_markets)]
        if len(chunk):
            dl_sums = chunk[chunk["OpCarrier"] == DELTA_CARRIER_CODE].groupby("market")["Passengers"].sum()
            total_sums = chunk.groupby("market")["Passengers"].sum()
            for market, val in dl_sums.items():
                dl_pax[market] += float(val)
            for market, val in total_sums.items():
                total_pax[market] += float(val)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (feed share pass)")

    rows = []
    seen = feed_df[["beyond_endpoint", "feed_direction"]].drop_duplicates()
    for endpoint, direction in zip(seen["beyond_endpoint"], seen["feed_direction"]):
        market = "-".join(sorted((AUS, endpoint)))
        total = total_pax.get(market, 0.0)
        share = (dl_pax.get(market, 0.0) / total) if total > 0 else 0.0
        rows.append(
            {
                "beyond_endpoint": endpoint,
                "direction": direction,
                "delta_share": share,
                "market_total_passengers_sample": total,
                "market_dl_passengers_sample": dl_pax.get(market, 0.0),
            }
        )
    return pd.DataFrame(rows)


def allocate_fares(feed_df, aus_slc_miles=AUS_SLC_GREAT_CIRCLE_MILES):
    """Provisional mileage-prorated AUS-SLC segment fare per feed itinerary."""
    df = feed_df.copy()
    df["aus_slc_allocated_fare"] = df["MktFare"] * (aus_slc_miles / df["NonStopMiles"])
    return df


def feed_economics(feed_df, shares_df):
    """Join Delta's market share and the allocated fare onto each feed
    itinerary; returns per-itinerary Delta feed passenger and revenue
    estimates."""
    merged = feed_df.merge(
        shares_df,
        left_on=["beyond_endpoint", "feed_direction"],
        right_on=["beyond_endpoint", "direction"],
        how="left",
    )
    merged["delta_share"] = merged["delta_share"].fillna(0.0)
    merged["delta_feed_passengers"] = merged["Passengers"] * merged["delta_share"]
    merged["delta_feed_revenue"] = merged["delta_feed_passengers"] * merged["aus_slc_allocated_fare"]
    return merged
