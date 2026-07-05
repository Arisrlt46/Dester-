"""Layer 0: raw DB1BMarket CSV -> clean, typed O&D market Parquet + summary.

Public API and schemas per docs/TECHNICAL_ARCHITECTURE.md.
"""

import glob
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

DEFAULT_ORIGIN = "AUS"
DEFAULT_DEST = "SLC"
DEFAULT_CHUNK_SIZE = 200_000
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
CSV_GLOB_PATTERN = os.path.join(DATA_DIR, "*.csv")
PROGRESS_EVERY_N_CHUNKS = 10

OUTPUT_PARQUET_NAME = "aus_slc_market.parquet"
OUTPUT_SUMMARY_NAME = "summary.json"

REQUIRED_ECONOMIC_FIELDS = ["Passengers", "MktFare", "MktDistance", "NonStopMiles"]

RAW_USECOLS = [
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
]


def resolve_csv_path():
    """Find the single raw DB1BMarket CSV under layer0/data/ via glob."""
    matches = sorted(glob.glob(CSV_GLOB_PATTERN))
    if len(matches) == 0:
        raise FileNotFoundError(
            f"No CSV files found matching {CSV_GLOB_PATTERN}. "
            f"Place the raw DB1BMarket CSV under {DATA_DIR}/."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Expected exactly one CSV under {DATA_DIR}/, found {len(matches)}: "
            f"{matches}. Remove extras so the input is unambiguous."
        )
    return matches[0]


def load_raw_chunks(csv_path, chunk_size=DEFAULT_CHUNK_SIZE):
    """Stream the raw CSV chunk by chunk. Never loads the whole file into memory.

    Yields raw chunks; no filtering yet.
    """
    reader = pd.read_csv(
        csv_path,
        usecols=RAW_USECOLS,
        chunksize=chunk_size,
        low_memory=False,
    )
    for chunk in reader:
        yield chunk


def filter_to_market(chunk, a, b):
    """Keep rows where the directional market is (a to b) or (b to a).

    Preserves both directions; adds a `Direction` column with values
    `A_TO_B` (Origin==a and Dest==b) or `B_TO_A` (Origin==b and Dest==a).
    """
    a_to_b = (chunk["Origin"] == a) & (chunk["Dest"] == b)
    b_to_a = (chunk["Origin"] == b) & (chunk["Dest"] == a)
    matched = chunk[a_to_b | b_to_a].copy()
    matched["Direction"] = np.where(
        (matched["Origin"] == a) & (matched["Dest"] == b), "A_TO_B", "B_TO_A"
    )
    return matched


def clean_and_type(df):
    """Enforce column dtypes; drop invalid rows per DB1B conventions."""
    df = df.dropna(subset=REQUIRED_ECONOMIC_FIELDS).copy()
    df = df[df["MktFare"] > 0]
    if "BulkFare" in df.columns:
        df = df[df["BulkFare"] != 1]

    df["ItinID"] = df["ItinID"].astype("int64")
    df["MktID"] = df["MktID"].astype("int64")
    df["Year"] = df["Year"].astype("int16")
    df["Quarter"] = df["Quarter"].astype("int8")
    df["Origin"] = df["Origin"].astype("category")
    df["Dest"] = df["Dest"].astype("category")
    df["Direction"] = df["Direction"].astype("category")
    df["RPCarrier"] = df["RPCarrier"].astype("category")
    df["TkCarrier"] = df["TkCarrier"].astype("category")
    df["OpCarrier"] = df["OpCarrier"].astype("category")
    df["MktCoupons"] = df["MktCoupons"].astype("int8")
    df["Passengers"] = df["Passengers"].astype("float32")
    df["MktFare"] = df["MktFare"].astype("float32")
    df["MktDistance"] = df["MktDistance"].astype("float32")
    df["NonStopMiles"] = df["NonStopMiles"].astype("float32")

    columns = [
        "ItinID",
        "MktID",
        "Year",
        "Quarter",
        "Origin",
        "Dest",
        "Direction",
        "RPCarrier",
        "TkCarrier",
        "OpCarrier",
        "MktCoupons",
        "Passengers",
        "MktFare",
        "MktDistance",
        "NonStopMiles",
    ]
    return df[columns].reset_index(drop=True)


def build_market_dataset(csv_path, a=DEFAULT_ORIGIN, b=DEFAULT_DEST):
    """Stream the raw CSV, filter to the market, clean, and return the final frame."""
    matched_chunks = []
    for i, chunk in enumerate(load_raw_chunks(csv_path), start=1):
        matched_chunks.append(filter_to_market(chunk, a, b))
        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks")

    if matched_chunks:
        combined = pd.concat(matched_chunks, ignore_index=True)
    else:
        combined = pd.DataFrame(columns=RAW_USECOLS + ["Direction"])

    return clean_and_type(combined)


def write_outputs(df, out_dir=OUT_DIR):
    """Write aus_slc_market.parquet and summary.json. Print a short report."""
    os.makedirs(out_dir, exist_ok=True)

    parquet_path = os.path.join(out_dir, OUTPUT_PARQUET_NAME)
    df.to_parquet(parquet_path, engine="pyarrow", index=False)

    if len(df) > 0:
        year = int(df["Year"].iloc[0])
        quarter = int(df["Quarter"].iloc[0])
    else:
        year = None
        quarter = None

    market = f"{DEFAULT_ORIGIN}-{DEFAULT_DEST}"

    passenger_total_sample = float(df["Passengers"].sum())
    nonstop_pax = float(df.loc[df["MktCoupons"] == 1, "Passengers"].sum())
    nonstop_share_by_pax = (nonstop_pax / passenger_total_sample) if passenger_total_sample > 0 else None

    carrier_pax = df.groupby("RPCarrier", observed=True)["Passengers"].sum().sort_values(ascending=False)
    carrier_share_by_pax = (
        (carrier_pax / passenger_total_sample).head(5).to_dict() if passenger_total_sample > 0 else {}
    )
    carrier_share_by_pax = {str(k): float(v) for k, v in carrier_share_by_pax.items()}

    summary = {
        "market": market,
        "year": year,
        "quarter": quarter,
        "row_count": int(len(df)),
        "passenger_total_sample": passenger_total_sample,
        "passenger_total_annualized_estimate": passenger_total_sample * 10 * 4,
        "mean_fare": float(df["MktFare"].mean()) if len(df) > 0 else None,
        "median_fare": float(df["MktFare"].median()) if len(df) > 0 else None,
        "mean_distance_miles": float(df["MktDistance"].mean()) if len(df) > 0 else None,
        "nonstop_share_by_pax": nonstop_share_by_pax,
        "carrier_share_by_pax": carrier_share_by_pax,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    summary_path = os.path.join(out_dir, OUTPUT_SUMMARY_NAME)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote {parquet_path} ({len(df)} rows)")
    print(f"Wrote {summary_path}")
    print(f"  market={summary['market']} year={summary['year']} quarter={summary['quarter']}")
    print(f"  row_count={summary['row_count']}")
    print(f"  passenger_total_sample={summary['passenger_total_sample']:.1f}")
    print(f"  mean_fare=${summary['mean_fare']:.2f}" if summary["mean_fare"] is not None else "  mean_fare=N/A")
    print(f"  mean_distance_miles={summary['mean_distance_miles']:.1f}" if summary["mean_distance_miles"] is not None else "  mean_distance_miles=N/A")
    print(f"  carrier_share_by_pax={summary['carrier_share_by_pax']}")


def main():
    csv_path = resolve_csv_path()
    print(f"Reading raw CSV: {csv_path}")
    df = build_market_dataset(csv_path, a=DEFAULT_ORIGIN, b=DEFAULT_DEST)
    write_outputs(df, OUT_DIR)


if __name__ == "__main__":
    main()
