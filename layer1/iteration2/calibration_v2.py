"""Layer 1 Wave 1 Iteration 2: minimum-support filter on carrier calibration.

Reuses Layer 1's original calibration.select_calibration_markets and
train_test_split unchanged. Wave 1's diagnosis found thin-data carriers
(e.g. MX with 27 rows, F9 with 805) receiving large positive fixed-effect
intercepts that dominate the softmax on markets where they hold real
presence. This applies a minimum training-row threshold per carrier as an
additive iteration -- Wave 1's original fit stays immutable and
reproducible; this writes to a distinct _v2 artifact instead.
"""

import os

import pandas as pd

from layer1 import calibration

MIN_SUPPORT_ROWS = 200

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
CALIBRATION_MARKETS_V2_PATH = os.path.join(LAYER1_OUT_DIR, "calibration_markets_v2.parquet")


def apply_min_support_filter(train_df, test_df, min_rows=MIN_SUPPORT_ROWS):
    """Drops any carrier with fewer than min_rows occurrences in the
    training set, from both train and test -- a carrier's alternative-rows
    must be removed from both so predict_shares' per-market softmax
    denominator doesn't silently include a carrier with no fitted
    coefficients (which would default to a zero-utility base-category
    alternative and distort every other carrier's predicted share in that
    market)."""
    counts = train_df["carrier"].value_counts()
    dropped_carriers = sorted(counts[counts < min_rows].index.tolist())
    kept_carriers = set(counts[counts >= min_rows].index)

    train_filtered = train_df[train_df["carrier"].isin(kept_carriers)].copy()
    test_filtered = test_df[test_df["carrier"].isin(kept_carriers)].copy()
    return train_filtered, test_filtered, dropped_carriers


def build_calibration_v2(db1b_csv_path, t100_csv_path):
    alternatives = calibration.select_calibration_markets(db1b_csv_path, t100_csv_path)
    train_df, test_df = calibration.train_test_split(alternatives)
    train_v2, test_v2, dropped_carriers = apply_min_support_filter(train_df, test_df)

    print(f"  dropped {len(dropped_carriers)} carrier(s) below {MIN_SUPPORT_ROWS} training rows: {dropped_carriers}")

    combined = pd.concat([train_v2, test_v2], ignore_index=True)
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)
    combined.to_parquet(CALIBRATION_MARKETS_V2_PATH, engine="pyarrow", index=False)
    print(f"Wrote {CALIBRATION_MARKETS_V2_PATH} ({len(combined)} rows)")

    return train_v2, test_v2, dropped_carriers
