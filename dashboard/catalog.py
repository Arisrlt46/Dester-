"""DESTER dashboard: Wave 1 market screener as a browsable catalog.

Pure data functions -- load and filter the screener parquet. No Streamlit
calls happen here; app.py owns all rendering.
"""

import os

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENER_PATH = os.path.join(_PROJECT_ROOT, "layer4", "out", "market_screener.parquet")

CATALOG_COLUMNS = [
    "market_pair",
    "hub",
    "spoke",
    "dominant_carrier",
    "dominant_carrier_share",
    "local_pax_sample",
    "feed_share",
    "flag_borderline",
]

SIZE_BUCKETS = ["Small", "Mid", "Large"]


def _size_bucket(pax):
    if pax < 1000:
        return "Small"
    if pax < 5000:
        return "Mid"
    return "Large"


def load_catalog():
    """Reads the Wave 1 screener output and adds a derived size_bucket
    column (< 1000 pax = Small, 1000-5000 = Mid, 5000+ = Large)."""
    df = pd.read_parquet(SCREENER_PATH)[CATALOG_COLUMNS].copy()
    df["size_bucket"] = df["local_pax_sample"].apply(_size_bucket)
    return df


def filter_catalog(df, size_buckets, min_feed_share, max_feed_share, dominant_carrier=None):
    out = df[df["size_bucket"].isin(size_buckets)]
    out = out[(out["feed_share"] >= min_feed_share) & (out["feed_share"] <= max_feed_share)]
    if dominant_carrier:
        out = out[out["dominant_carrier"] == dominant_carrier]
    return out
