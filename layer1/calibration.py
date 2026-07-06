"""Layer 1 Wave 1, Module 1: select comparable calibration markets from DB1BMarket.

Streams the national DB1BMarket CSV in chunks (never loads the whole ~2GB file
into memory), restricts to a stage-length band, cleans per DB1B conventions,
then selects markets with a dominant carrier and real competition. Joins T-100
schedule features and computes hub dominance across the selected set.

Public API and schemas per docs/TECHNICAL_ARCHITECTURE.md (Layer 1, Wave 1,
Module 1).
"""

import glob
import os

import numpy as np
import pandas as pd

LAYER0_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "layer0", "data")
LAYER1_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

DB1B_GLOB_PATTERN = os.path.join(LAYER0_DATA_DIR, "*.csv")
T100_GLOB_PATTERN = os.path.join(LAYER1_DATA_DIR, "T_T100D*.csv")

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

EXCLUDED_MARKET_AIRPORTS = ("AUS", "SLC")

STAGE_LENGTH_MIN_MILES = 800
STAGE_LENGTH_MAX_MILES = 1500
DOMINANT_SHARE_THRESHOLD = 0.40
COMPETITOR_SHARE_THRESHOLD = 0.10
MIN_MARKET_PASSENGERS = 5000
ALLOWED_MKT_COUPONS = (1, 2)

HUB_DOMINANCE_THRESHOLD = 0.40

T100_YEAR = 2025
T100_MONTHS = (4, 5, 6)
T100_WEEKS_PER_QUARTER = 13

TEST_FRAC = 0.30
RANDOM_STATE = 42

DB1B_USECOLS = [
    "Origin",
    "Dest",
    "RPCarrier",
    "OpCarrier",
    "MktCoupons",
    "BulkFare",
    "Passengers",
    "MktFare",
    "MktDistance",
    "NonStopMiles",
    "AirportGroup",
]

T100_USECOLS = [
    "ORIGIN",
    "DEST",
    "CARRIER",
    "DEPARTURES_PERFORMED",
    "SEATS",
    "YEAR",
    "MONTH",
]


def resolve_csv_path(glob_pattern):
    """Find a single CSV matching glob_pattern, raising a clear error otherwise."""
    matches = sorted(glob.glob(glob_pattern))
    if len(matches) == 0:
        raise FileNotFoundError(f"No CSV files found matching {glob_pattern}.")
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one CSV matching {glob_pattern}, found {len(matches)}: {matches}. "
            f"Remove extras so the input is unambiguous."
        )
    return matches[0]


def _clean_chunk(chunk):
    """Apply DB1B cleaning conventions and the stage-length / coupon filters."""
    chunk = chunk.dropna(subset=["Passengers", "MktFare", "MktDistance", "NonStopMiles"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    chunk = chunk[chunk["MktCoupons"].isin(ALLOWED_MKT_COUPONS)]
    chunk = chunk[
        (chunk["NonStopMiles"] >= STAGE_LENGTH_MIN_MILES)
        & (chunk["NonStopMiles"] <= STAGE_LENGTH_MAX_MILES)
    ]
    is_excluded = chunk["Origin"].isin(EXCLUDED_MARKET_AIRPORTS) & chunk["Dest"].isin(
        EXCLUDED_MARKET_AIRPORTS
    )
    chunk = chunk[~is_excluded]
    return chunk


def _derive_connecting_hub(chunk):
    """Middle airport of a 2-coupon itinerary's AirportGroup path, else NaN."""
    parts = chunk["AirportGroup"].astype(str).str.split(":")
    hub = pd.Series(np.nan, index=chunk.index, dtype=object)
    two_coupon = chunk["MktCoupons"] == 2
    three_leg_mask = two_coupon & (parts.str.len() == 3)
    hub.loc[three_leg_mask] = parts[three_leg_mask].str[1]
    return hub


def load_and_filter_db1b(csv_path, chunk_size=DB1B_CHUNK_SIZE):
    """Stream the national DB1BMarket CSV, applying the calibration row filter chunk-by-chunk."""
    reader = pd.read_csv(csv_path, usecols=DB1B_USECOLS, chunksize=chunk_size, low_memory=False)

    filtered_chunks = []
    for i, chunk in enumerate(reader, start=1):
        cleaned = _clean_chunk(chunk)
        cleaned = cleaned.copy()
        cleaned["connecting_hub"] = _derive_connecting_hub(cleaned)
        filtered_chunks.append(cleaned)
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks")

    if filtered_chunks:
        df = pd.concat(filtered_chunks, ignore_index=True)
    else:
        df = pd.DataFrame(columns=DB1B_USECOLS + ["connecting_hub"])

    df["market"] = [
        "-".join(sorted((o, d))) for o, d in zip(df["Origin"], df["Dest"])
    ]
    df["itinerary_type"] = np.where(df["MktCoupons"] == 1, "nonstop", "connect")
    df["log_fare"] = np.log(df["MktFare"])
    df["n_stops"] = np.where(df["MktCoupons"] == 1, 0, 1)
    df["routing_efficiency"] = df["MktDistance"] / df["NonStopMiles"]
    return df


def select_markets(df):
    """Apply the market-level selection rule; return the set of qualifying market keys."""
    market_totals = df.groupby("market")["Passengers"].sum()
    carrier_totals = df.groupby(["market", "RPCarrier"], observed=True)["Passengers"].sum()
    carrier_shares = carrier_totals / market_totals.reindex(carrier_totals.index.get_level_values("market")).values

    selected = []
    for market, total_pax in market_totals.items():
        if total_pax < MIN_MARKET_PASSENGERS:
            continue
        shares = carrier_shares.loc[market].sort_values(ascending=False)
        if len(shares) < 2:
            continue
        if shares.iloc[0] >= DOMINANT_SHARE_THRESHOLD and shares.iloc[1] >= COMPETITOR_SHARE_THRESHOLD:
            selected.append(market)
    return set(selected)


def load_t100_features(t100_csv_path):
    """Load T-100 segment data, filter to the 2025 Q2 subset, aggregate to weekly figures."""
    t100 = pd.read_csv(t100_csv_path, usecols=T100_USECOLS)
    t100 = t100[(t100["YEAR"] == T100_YEAR) & (t100["MONTH"].isin(T100_MONTHS))]

    agg = t100.groupby(["ORIGIN", "DEST", "CARRIER"], as_index=False).agg(
        total_departures=("DEPARTURES_PERFORMED", "sum"),
        total_seats=("SEATS", "sum"),
    )
    agg["frequency_weekly"] = agg["total_departures"] / T100_WEEKS_PER_QUARTER
    agg["seats_per_departure"] = agg["total_seats"] / agg["total_departures"].replace(0, np.nan)
    return agg[["ORIGIN", "DEST", "CARRIER", "frequency_weekly", "seats_per_departure"]]


def _join_t100_features(df, t100_features):
    """Join T-100 frequency/seats onto each itinerary's operating segment.

    Nonstop itineraries join on (Origin, Dest, OpCarrier). Connecting itineraries
    join on (Origin, connecting_hub, OpCarrier) — the outbound leg to the hub,
    used as a proxy for the itinerary's schedule quality since DB1BMarket has no
    coupon-level segment detail.
    """
    df = df.copy()
    df["t100_dest"] = np.where(df["itinerary_type"] == "nonstop", df["Dest"], df["connecting_hub"])

    merged = df.merge(
        t100_features,
        left_on=["Origin", "t100_dest", "OpCarrier"],
        right_on=["ORIGIN", "DEST", "CARRIER"],
        how="left",
    )
    return merged.drop(columns=["ORIGIN", "DEST", "CARRIER", "t100_dest"])


def _compute_hub_dominance(df):
    """Each carrier's overall passenger share at each airport across the calibration set.

    Uses OpCarrier (the operating carrier) and counts an airport's traffic from
    both endpoints of every itinerary in the set. Joined back onto each
    connecting itinerary at its connecting airport; nonstop itineraries get 0.
    """
    origin_leg = df[["Origin", "OpCarrier", "Passengers"]].rename(columns={"Origin": "airport"})
    dest_leg = df[["Dest", "OpCarrier", "Passengers"]].rename(columns={"Dest": "airport"})
    touches = pd.concat([origin_leg, dest_leg], ignore_index=True)

    airport_totals = touches.groupby("airport")["Passengers"].sum()
    airport_carrier_totals = touches.groupby(["airport", "OpCarrier"], observed=True)["Passengers"].sum()
    airport_carrier_share = (
        airport_carrier_totals / airport_totals.reindex(airport_carrier_totals.index.get_level_values("airport")).values
    )

    share_lookup = airport_carrier_share.reset_index(name="op_carrier_airport_share")

    merged = df.merge(
        share_lookup,
        left_on=["connecting_hub", "OpCarrier"],
        right_on=["airport", "OpCarrier"],
        how="left",
    )
    hub_dominance = np.where(
        merged["itinerary_type"] == "connect",
        (merged["op_carrier_airport_share"].fillna(0) >= HUB_DOMINANCE_THRESHOLD).astype(float),
        0.0,
    )
    return hub_dominance


def _aggregate_to_alternatives(df, market_totals):
    """Group to one row per (market, carrier, itinerary_type, connecting_hub)."""
    group_cols = ["market", "RPCarrier", "itinerary_type", "connecting_hub"]

    def _weighted_mean(values, weights):
        weights = weights.astype(float)
        if weights.sum() == 0:
            return np.nan
        return np.average(values, weights=weights)

    rows = []
    for keys, group in df.groupby(group_cols, observed=True, dropna=False):
        market, carrier, itinerary_type, connecting_hub = keys
        pax = group["Passengers"]
        rows.append(
            {
                "market": market,
                "carrier": carrier,
                "itinerary_type": itinerary_type,
                "connecting_hub": connecting_hub,
                "observed_share": pax.sum() / market_totals.loc[market],
                "log_fare": _weighted_mean(group["log_fare"], pax),
                "n_stops": group["n_stops"].iloc[0],
                "routing_efficiency": _weighted_mean(group["routing_efficiency"], pax),
                "frequency_weekly": _weighted_mean(group["frequency_weekly"], pax),
                "seats_per_departure": _weighted_mean(group["seats_per_departure"], pax),
                "hub_dominance": _weighted_mean(group["hub_dominance"], pax),
                "passengers": pax.sum(),
            }
        )
    return pd.DataFrame(rows)


def select_calibration_markets(db1b_csv_path, t100_csv_path):
    """Build the full calibration alternatives dataset.

    Returns one row per (market, carrier, itinerary_type, connecting_hub) with
    observed_share as the outcome variable and all model features as columns.
    """
    print(f"Reading raw DB1BMarket CSV: {db1b_csv_path}")
    df = load_and_filter_db1b(db1b_csv_path)

    qualifying_markets = select_markets(df)
    print(f"  {len(qualifying_markets)} markets pass the calibration selection rule")
    df = df[df["market"].isin(qualifying_markets)].copy()

    print(f"Reading T-100 segment CSV: {t100_csv_path}")
    t100_features = load_t100_features(t100_csv_path)
    df = _join_t100_features(df, t100_features)

    df["hub_dominance"] = _compute_hub_dominance(df)

    before_t100_drop = len(df)
    df = df.dropna(subset=["frequency_weekly", "seats_per_departure"])
    dropped = before_t100_drop - len(df)
    if dropped:
        print(f"  dropped {dropped} itineraries with no matching T-100 segment (e.g. interline OpCarrier=99)")

    market_totals = df.groupby("market")["Passengers"].sum()
    alternatives = _aggregate_to_alternatives(df, market_totals)
    return alternatives


def train_test_split(df, test_frac=TEST_FRAC, random_state=RANDOM_STATE):
    """Split stratified by market so that no market appears in both sets."""
    markets = sorted(df["market"].unique())
    rng = np.random.RandomState(random_state)
    shuffled = rng.permutation(markets)
    n_test = max(1, round(len(shuffled) * test_frac))
    test_markets = set(shuffled[:n_test])
    train_markets = set(shuffled[n_test:])

    train_df = df[df["market"].isin(train_markets)].copy()
    test_df = df[df["market"].isin(test_markets)].copy()
    train_df["split"] = "train"
    test_df["split"] = "test"
    return train_df, test_df
