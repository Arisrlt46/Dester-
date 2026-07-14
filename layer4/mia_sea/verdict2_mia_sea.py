"""Layer 4 MIA-SEA, Module 2: Verdict 2 on MIA-SEA.

Mirrors layer4/verdict2_atl_sat.py exactly, substituting config_mia_sea for
config. Imports layer2.feed_economics.allocate_fares/feed_economics and
layer2.pnl_with_feed.combined_pnl unchanged -- both are already parameterized
generically. layer2.feed_extraction.extract_feed_itineraries and
feed_economics.compute_feed_shares are hardcoded to the AUS/SLC substrings
internally, so this module reimplements their exact (bug-fixed) logic
generalized to config.HUB/config.SPOKE rather than calling them directly.
"""

import os

import numpy as np
import pandas as pd

from layer1 import sizing as layer1_sizing
from layer2 import feed_economics as layer2_feed_economics
from layer2 import pnl_with_feed as layer2_pnl_with_feed
from layer4.mia_sea import config_mia_sea as config

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
MIA_SEA_FEED_PATH = os.path.join(LAYER4_OUT_DIR, "mia_sea_feed.parquet")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

FEED_MKT_COUPONS = 2

DB1B_USECOLS = [
    "ItinID", "MktID", "Year", "Quarter", "Origin", "Dest", "RPCarrier", "TkCarrier", "OpCarrier",
    "MktCoupons", "BulkFare", "Passengers", "MktFare", "MktDistance", "NonStopMiles", "AirportGroup",
]


def _clean_chunk(chunk):
    chunk = chunk.dropna(subset=["Passengers", "MktFare", "MktDistance", "NonStopMiles"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def _filter_feed_rows(chunk):
    """Generalization of Layer 2's (bug-fixed) AUS-SLC feed rule: the hub
    must be the connecting middle airport, and the spoke must be a true
    endpoint (Origin or Dest) -- not merely present somewhere in AirportGroup."""
    chunk = chunk[chunk["MktCoupons"] == FEED_MKT_COUPONS]
    hub_spoke_substr = f"{config.HUB}:{config.SPOKE}"
    spoke_hub_substr = f"{config.SPOKE}:{config.HUB}"
    airport_group = chunk["AirportGroup"].astype(str)
    touches = airport_group.str.contains(hub_spoke_substr, regex=False) | airport_group.str.contains(
        spoke_hub_substr, regex=False
    )
    chunk = chunk[touches]
    chunk = chunk[(chunk["Origin"] == config.SPOKE) | (chunk["Dest"] == config.SPOKE)]
    is_market_itself = chunk["Origin"].isin([config.HUB, config.SPOKE]) & chunk["Dest"].isin([config.HUB, config.SPOKE])
    return chunk[~is_market_itself]


def _add_feed_columns(df):
    df = df.copy()
    is_behind = df["Origin"] == config.SPOKE
    df["feed_direction"] = np.where(is_behind, "BEHIND", "BEYOND")
    df["beyond_endpoint"] = np.where(is_behind, df["Dest"], df["Origin"])
    df["aus_slc_leg_direction"] = np.where(is_behind, "A_TO_B", "B_TO_A")
    return df


def extract_feed_itineraries(db1b_csv_path):
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


def compute_feed_shares(feed_df, raw_db1b_csv_path):
    """Generalization of Layer 2's compute_feed_shares: pooled observed
    dominant-carrier share on each feed market's full O&D (any routing),
    keyed on config.SPOKE instead of the hardcoded AUS."""
    endpoints = sorted(feed_df["beyond_endpoint"].unique())
    target_markets = {"-".join(sorted((config.SPOKE, endpoint))) for endpoint in endpoints}

    dominant_pax = {market: 0.0 for market in target_markets}
    total_pax = {market: 0.0 for market in target_markets}

    reader = pd.read_csv(
        raw_db1b_csv_path, usecols=["Origin", "Dest", "OpCarrier", "Passengers"],
        chunksize=DB1B_CHUNK_SIZE, low_memory=False,
    )
    for i, chunk in enumerate(reader, start=1):
        chunk = chunk.dropna(subset=["Passengers"])
        market = ["-".join(sorted((o, d))) for o, d in zip(chunk["Origin"], chunk["Dest"])]
        chunk = chunk.assign(market=market)
        chunk = chunk[chunk["market"].isin(target_markets)]
        if len(chunk):
            dom_sums = chunk[chunk["OpCarrier"] == config.DOMINANT_CARRIER].groupby("market")["Passengers"].sum()
            total_sums = chunk.groupby("market")["Passengers"].sum()
            for market, val in dom_sums.items():
                dominant_pax[market] += float(val)
            for market, val in total_sums.items():
                total_pax[market] += float(val)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (feed share pass)")

    rows = []
    seen = feed_df[["beyond_endpoint", "feed_direction"]].drop_duplicates()
    for endpoint, direction in zip(seen["beyond_endpoint"], seen["feed_direction"]):
        market = "-".join(sorted((config.SPOKE, endpoint)))
        total = total_pax.get(market, 0.0)
        share = (dominant_pax.get(market, 0.0) / total) if total > 0 else 0.0
        rows.append(
            {
                "beyond_endpoint": endpoint,
                "direction": direction,
                "delta_share": share,
                "market_total_passengers_sample": total,
                "market_dl_passengers_sample": dominant_pax.get(market, 0.0),
            }
        )
    return pd.DataFrame(rows)


def run_verdict2_mia_sea(db1b_csv_path, local_pax_annual, local_revenue_annual, seats_per_departure, casm_cents, distance_miles):
    print("Extracting feed itineraries through SEA...")
    feed_df = extract_feed_itineraries(db1b_csv_path)
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)

    print("Computing dominant carrier's observed share of each feed market...")
    shares_df = compute_feed_shares(feed_df, db1b_csv_path)

    feed_df_fares = layer2_feed_economics.allocate_fares(feed_df, aus_slc_miles=config.MARKET_MILES)
    feed_econ_df = layer2_feed_economics.feed_economics(feed_df_fares, shares_df)
    feed_econ_df.to_parquet(MIA_SEA_FEED_PATH, engine="pyarrow", index=False)
    print(f"Wrote {MIA_SEA_FEED_PATH} ({len(feed_econ_df)} feed itineraries)")

    feed_pax_sample = feed_econ_df["delta_feed_passengers"].sum()
    feed_revenue_sample = feed_econ_df["delta_feed_revenue"].sum()
    feed_pax_annual = layer1_sizing.annualize_sample(feed_pax_sample)
    feed_revenue_annual = layer1_sizing.annualize_sample(feed_revenue_sample)

    combined = layer2_pnl_with_feed.combined_pnl(
        local_pax_annual, local_revenue_annual, feed_pax_annual, feed_revenue_annual,
        seats_per_departure, config.PROPOSED_FREQ_DAILY, config.QUARTER_DAYS, distance_miles, casm_cents,
    )

    feed_share_of_total_revenue = (
        feed_revenue_annual / (local_revenue_annual + feed_revenue_annual)
        if (local_revenue_annual + feed_revenue_annual) > 0 else 0.0
    )
    feed_share_of_total_pax = (
        feed_pax_annual / (local_pax_annual + feed_pax_annual)
        if (local_pax_annual + feed_pax_annual) > 0 else 0.0
    )

    market_agg = (
        feed_econ_df.groupby(["beyond_endpoint", "feed_direction"])
        .agg(passengers=("delta_feed_passengers", "sum"), revenue=("delta_feed_revenue", "sum"))
        .reset_index()
    )
    market_agg["passengers"] = market_agg["passengers"].apply(layer1_sizing.annualize_sample)
    market_agg["revenue"] = market_agg["revenue"].apply(layer1_sizing.annualize_sample)
    market_agg = market_agg.sort_values("revenue", ascending=False).head(10)
    top_feed_markets = [
        {
            "endpoint": row["beyond_endpoint"],
            "direction": row["feed_direction"],
            "passengers": float(row["passengers"]),
            "revenue": float(row["revenue"]),
        }
        for _, row in market_agg.iterrows()
    ]

    verdict2_output = {
        "market": config.MARKET_PAIR,
        "carrier": config.DOMINANT_CARRIER,
        "local_contribution_annual_usd": combined["local_contribution"],
        "feed_contribution_annual_usd": combined["feed_contribution"],
        "total_contribution_annual_usd": combined["total_contribution"],
        "feed_share_of_total_revenue": feed_share_of_total_revenue,
        "feed_share_of_total_pax": feed_share_of_total_pax,
        "top_feed_markets": top_feed_markets,
    }

    context = {
        "feed_econ_df": feed_econ_df,
        "feed_pax_annual": feed_pax_annual,
        "feed_revenue_annual": feed_revenue_annual,
    }
    return verdict2_output, context
