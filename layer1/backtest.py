"""Layer 1 Wave 1, Module 3: backtest the fitted logit against held-out markets.

Fits on the training markets, predicts itinerary-level shares on the held-out
test markets, aggregates to carrier-level share, and reports pooled MAE/RMSE,
a per-market breakdown, and a feature-ablation table (refit dropping one
feature at a time).
"""

import json
from datetime import datetime, timezone

import numpy as np

from layer1 import logit

MAE_TARGET_PP = 10.0
MAE_DANGER_THRESHOLD_PP = 15.0


def _aggregate_to_carrier_share(df, share_col):
    return df.groupby(["market", "carrier"])[share_col].sum()


def _score(train_df, test_df, features):
    coefficients = logit.fit(train_df, features=features)
    predicted = logit.predict_shares(test_df, coefficients)

    scored = test_df.copy()
    scored["predicted_share"] = predicted

    predicted_carrier = _aggregate_to_carrier_share(scored, "predicted_share")
    observed_carrier = _aggregate_to_carrier_share(scored, "observed_share")

    joined = predicted_carrier.to_frame("predicted_share").join(
        observed_carrier.to_frame("observed_share"), how="outer"
    ).fillna(0.0)

    errors = joined["predicted_share"] - joined["observed_share"]
    mae_pp = float(errors.abs().mean() * 100)
    rmse_pp = float(np.sqrt((errors ** 2).mean()) * 100)
    return mae_pp, rmse_pp, joined, coefficients


def run_backtest(train_df, test_df, features=None):
    """Fit on train_df, evaluate on test_df. Returns the full backtest report dict."""
    if features is None:
        features = logit.DEFAULT_FEATURES

    headline_mae_pp, headline_rmse_pp, joined, coefficients = _score(train_df, test_df, features)

    per_market_breakdown = [
        {
            "market": market,
            "carrier": carrier,
            "predicted_share": float(row["predicted_share"]),
            "observed_share": float(row["observed_share"]),
            "abs_error_pp": float(abs(row["predicted_share"] - row["observed_share"]) * 100),
        }
        for (market, carrier), row in joined.iterrows()
    ]
    per_market_breakdown.sort(key=lambda r: (r["market"], r["carrier"]))

    ablation = {}
    for dropped_feature in features:
        remaining = [f for f in features if f != dropped_feature]
        ablated_mae_pp, ablated_rmse_pp, _, _ = _score(train_df, test_df, remaining)
        ablation[dropped_feature] = {
            "mae_pp_with_feature_removed": ablated_mae_pp,
            "rmse_pp_with_feature_removed": ablated_rmse_pp,
            "mae_impact_pp": ablated_mae_pp - headline_mae_pp,
        }

    report = {
        "features": list(features),
        "n_train_markets": int(train_df["market"].nunique()),
        "n_test_markets": int(test_df["market"].nunique()),
        "n_train_rows": int(len(train_df)),
        "n_test_rows": int(len(test_df)),
        "headline_mae_pp": headline_mae_pp,
        "headline_rmse_pp": headline_rmse_pp,
        "mae_target_pp": MAE_TARGET_PP,
        "mae_danger_threshold_pp": MAE_DANGER_THRESHOLD_PP,
        "validated": headline_mae_pp <= MAE_TARGET_PP,
        "exceeds_danger_threshold": headline_mae_pp > MAE_DANGER_THRESHOLD_PP,
        "per_market_breakdown": per_market_breakdown,
        "feature_ablation": ablation,
        "coefficients": coefficients,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


def write_backtest_report(report, path):
    with open(path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Wrote {path}")
    print(f"  headline MAE = {report['headline_mae_pp']:.2f}pp, RMSE = {report['headline_rmse_pp']:.2f}pp")
    print(f"  train markets={report['n_train_markets']} test markets={report['n_test_markets']}")

    if report["exceeds_danger_threshold"]:
        print(
            f"  *** WARNING: headline MAE ({report['headline_mae_pp']:.2f}pp) exceeds the "
            f"{MAE_DANGER_THRESHOLD_PP}pp danger threshold. Wave 1 is NOT validated. ***"
        )
    elif not report["validated"]:
        print(
            f"  note: headline MAE ({report['headline_mae_pp']:.2f}pp) is above the "
            f"{MAE_TARGET_PP}pp target but below the {MAE_DANGER_THRESHOLD_PP}pp danger threshold."
        )
    else:
        print(f"  headline MAE meets the {MAE_TARGET_PP}pp validation target.")

    ranked = sorted(
        report["feature_ablation"].items(), key=lambda kv: kv[1]["mae_impact_pp"], reverse=True
    )
    print("  feature ablation (MAE impact when removed, most impactful first):")
    for feature, stats in ranked:
        print(f"    {feature}: {stats['mae_impact_pp']:+.2f}pp")
