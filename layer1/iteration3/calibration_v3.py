"""Layer 1 Wave 1 Iteration 3: market-diversity filter on carrier calibration.

Iteration 2's row-count minimum support was the wrong lever: F9 (~805 rows)
and NK (~699 rows) survived it comfortably, since their problem isn't row
volume -- it's that their fixed-effect intercepts get fit to a small number
of niche markets where they hold unusually high share. This filter targets
that mechanism directly: a carrier must appear in at least a minimum number
of *distinct* markets, not just accumulate rows.

Imports Layer 1's original calibration.select_calibration_markets and
train_test_split unchanged. Iteration 2's artifacts stay untouched as the
honest record of the previous attempt; this writes to distinct _v3 files.
"""

import os

import pandas as pd

from layer1 import calibration

MIN_DISTINCT_MARKETS = 15

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
CALIBRATION_MARKETS_V3_PATH = os.path.join(LAYER1_OUT_DIR, "calibration_markets_v3.parquet")


def apply_market_diversity_filter(train_df, test_df, min_markets=MIN_DISTINCT_MARKETS):
    """Drops any carrier appearing in fewer than min_markets distinct
    markets in the training set, from both train and test -- a carrier's
    alternative-rows must be removed from both so predict_shares' per-market
    softmax denominator doesn't silently include a carrier with no fitted
    coefficients."""
    distinct_market_counts = train_df.groupby("carrier")["market"].nunique()
    dropped_carriers = sorted(distinct_market_counts[distinct_market_counts < min_markets].index.tolist())
    kept_carriers = set(distinct_market_counts[distinct_market_counts >= min_markets].index)

    train_filtered = train_df[train_df["carrier"].isin(kept_carriers)].copy()
    test_filtered = test_df[test_df["carrier"].isin(kept_carriers)].copy()
    return train_filtered, test_filtered, dropped_carriers, distinct_market_counts


def build_calibration_v3(db1b_csv_path, t100_csv_path):
    alternatives = calibration.select_calibration_markets(db1b_csv_path, t100_csv_path)
    train_df, test_df = calibration.train_test_split(alternatives)
    train_v3, test_v3, dropped_carriers, distinct_market_counts = apply_market_diversity_filter(train_df, test_df)

    print(f"  distinct training markets per carrier:")
    for carrier, count in distinct_market_counts.sort_values().items():
        flag = " (DROPPED)" if carrier in dropped_carriers else ""
        print(f"    {carrier}: {count}{flag}")
    print(f"  dropped {len(dropped_carriers)} carrier(s) below {MIN_DISTINCT_MARKETS} distinct markets: {dropped_carriers}")

    combined = pd.concat([train_v3, test_v3], ignore_index=True)
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)
    combined.to_parquet(CALIBRATION_MARKETS_V3_PATH, engine="pyarrow", index=False)
    print(f"Wrote {CALIBRATION_MARKETS_V3_PATH} ({len(combined)} rows)")

    return train_v3, test_v3, dropped_carriers, distinct_market_counts
