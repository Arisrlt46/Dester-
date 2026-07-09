"""Layer 1 Wave 1 Iteration 4: post-fit shrinkage on carrier intercepts.

Iterations 2 (row-count) and 3 (market-diversity) established that F9/NK's
problem isn't thinness by any support-count measure -- they appear broadly,
but hold unusually high share within a subset of the markets they appear in,
so their fitted intercepts absorb that "occasional dominance" pattern and
inflate. This shrinks each carrier's intercept toward zero in proportion to
how unstable (high-variance) its own per-market fit residual is -- an
empirical-Bayes-style correction applied as a post-fit step, since
statsmodels' MNLogit has no native per-coefficient penalty.

Only intercepts (carrier_fe) are shrunk. Slope coefficients are untouched.
"""

import json
import os

import pandas as pd

from layer1 import logit

# Captured at import time, before verdict1_wave1_v4.py monkey-patches
# layer1.logit.fit for the backtest call -- _fit_and_shrink must always fit
# against the *original* estimator, never the patched (shrinking) one, or
# every call recurses into itself.
_ORIGINAL_FIT = logit.fit

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
CALIBRATION_MARKETS_PATH = os.path.join(LAYER1_OUT_DIR, "calibration_markets.parquet")
LOGIT_COEFFICIENTS_V4_PATH = os.path.join(LAYER1_OUT_DIR, "logit_coefficients_v4.json")
SHRINKAGE_REPORT_V4_PATH = os.path.join(LAYER1_OUT_DIR, "shrinkage_report_v4.json")

SHRINKAGE_LAMBDA = 10.0
RESIDUAL_VARIANCE_DDOF = 0  # population variance -- keeps single-market carriers well-defined (var=0) rather than NaN


def compute_residual_variance_per_carrier(train_df, base_coefficients):
    """Per-market predicted-minus-observed carrier share residual, then the
    variance of that residual across all training markets a carrier appears
    in. High variance -> the carrier's per-market fit is unstable (its
    intercept is fitting noise); low variance -> the intercept reflects a
    consistent effect."""
    predicted = logit.predict_shares(train_df, base_coefficients)
    scored = train_df.copy()
    scored["predicted_share"] = predicted

    predicted_carrier = scored.groupby(["market", "carrier"])["predicted_share"].sum()
    observed_carrier = scored.groupby(["market", "carrier"])["observed_share"].sum()
    residual = predicted_carrier - observed_carrier

    return residual.groupby(level="carrier").var(ddof=RESIDUAL_VARIANCE_DDOF)


def shrink_intercepts(base_coefficients, variance_per_carrier, lam=SHRINKAGE_LAMBDA):
    """intercept_new = intercept_old * s, s = 1 / (1 + lambda * var_residual).
    High-variance intercepts get multiplied by a small s (pulled toward
    zero); low-variance intercepts pass through nearly unchanged."""
    base_carrier = base_coefficients["_base_carrier"]
    carriers = base_coefficients["_carriers"]

    shrunk = dict(base_coefficients)
    shrinkage_table = []

    for carrier in carriers:
        if carrier == base_carrier:
            continue
        key = f"{logit.INTERCEPT_KEY}::{carrier}"
        fitted_intercept = base_coefficients[key]
        var_residual = float(variance_per_carrier.get(carrier, 0.0))
        s = 1.0 / (1.0 + lam * var_residual)
        shrunk_intercept = fitted_intercept * s
        shrunk[key] = shrunk_intercept

        pct_reduction = (1.0 - abs(shrunk_intercept) / abs(fitted_intercept)) if fitted_intercept != 0 else 0.0
        shrinkage_table.append(
            {
                "carrier": carrier,
                "fitted_intercept": fitted_intercept,
                "residual_variance": var_residual,
                "shrinkage_factor": s,
                "shrunk_intercept": shrunk_intercept,
                "pct_reduction": pct_reduction,
            }
        )

    return shrunk, shrinkage_table


def _fit_and_shrink(train_df, features=None):
    base_coefficients = _ORIGINAL_FIT(train_df, features=features)
    variance_per_carrier = compute_residual_variance_per_carrier(train_df, base_coefficients)
    shrunk_coefficients, shrinkage_table = shrink_intercepts(base_coefficients, variance_per_carrier)
    return shrunk_coefficients, shrinkage_table


def fit_with_shrinkage(train_df, features=None):
    """Drop-in replacement for logit.fit's signature -- used to monkey-patch
    layer1.logit.fit for the duration of the backtest call, so every
    internal refit (headline + each ablation feature-drop) gets the same
    shrinkage treatment applied consistently."""
    shrunk_coefficients, _ = _fit_and_shrink(train_df, features=features)
    return shrunk_coefficients


def fit_and_save_v4(train_df):
    shrunk_coefficients, shrinkage_table = _fit_and_shrink(train_df)

    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)
    logit.save_coefficients(shrunk_coefficients, LOGIT_COEFFICIENTS_V4_PATH)
    print(f"Wrote {LOGIT_COEFFICIENTS_V4_PATH}")

    shrinkage_table_sorted = sorted(
        shrinkage_table, key=lambda r: abs(r["fitted_intercept"] - r["shrunk_intercept"]), reverse=True
    )
    with open(SHRINKAGE_REPORT_V4_PATH, "w") as f:
        json.dump({"lambda": SHRINKAGE_LAMBDA, "shrinkage_table": shrinkage_table_sorted}, f, indent=2)
    print(f"Wrote {SHRINKAGE_REPORT_V4_PATH}")

    return shrunk_coefficients, shrinkage_table_sorted


def load_calibration_split():
    df = pd.read_parquet(CALIBRATION_MARKETS_PATH)
    train_df = df[df["split"] == "train"].copy()
    test_df = df[df["split"] == "test"].copy()
    return train_df, test_df
