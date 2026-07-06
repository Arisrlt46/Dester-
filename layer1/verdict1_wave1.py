"""Layer 1 Wave 1 orchestrator: calibration -> logit fit -> backtest, end to end.

Runnable via `python -m layer1.verdict1_wave1` from the project root.
"""

import os

import pandas as pd

from layer1 import backtest, calibration, logit

OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
CALIBRATION_MARKETS_PATH = os.path.join(OUT_DIR, "calibration_markets.parquet")
LOGIT_COEFFICIENTS_PATH = os.path.join(OUT_DIR, "logit_coefficients.json")
BACKTEST_REPORT_PATH = os.path.join(OUT_DIR, "backtest_report.json")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    db1b_csv_path = calibration.resolve_csv_path(calibration.DB1B_GLOB_PATTERN)
    t100_csv_path = calibration.resolve_csv_path(calibration.T100_GLOB_PATTERN)

    alternatives = calibration.select_calibration_markets(db1b_csv_path, t100_csv_path)
    train_df, test_df = calibration.train_test_split(alternatives)

    combined = pd.concat([train_df, test_df], ignore_index=True)
    combined.to_parquet(CALIBRATION_MARKETS_PATH, engine="pyarrow", index=False)
    print(f"Wrote {CALIBRATION_MARKETS_PATH} ({len(combined)} rows)")

    coefficients = logit.fit(train_df)
    logit.save_coefficients(coefficients, LOGIT_COEFFICIENTS_PATH)
    print(f"Wrote {LOGIT_COEFFICIENTS_PATH}")

    report = backtest.run_backtest(train_df, test_df)
    backtest.write_backtest_report(report, BACKTEST_REPORT_PATH)

    top_features = sorted(
        report["feature_ablation"].items(), key=lambda kv: kv[1]["mae_impact_pp"], reverse=True
    )[:3]

    print()
    print("=== Wave 1 summary ===")
    print(f"Calibration markets: {alternatives['market'].nunique()}")
    print(f"Train markets: {train_df['market'].nunique()} ({len(train_df)} rows)")
    print(f"Test markets: {test_df['market'].nunique()} ({len(test_df)} rows)")
    print(f"Headline MAE: {report['headline_mae_pp']:.2f}pp")
    print(f"Headline RMSE: {report['headline_rmse_pp']:.2f}pp")
    print("Top 3 most-impactful features (by MAE increase when removed):")
    for feature, stats in top_features:
        print(f"  {feature}: {stats['mae_impact_pp']:+.2f}pp")

    if report["exceeds_danger_threshold"]:
        print()
        print(
            f"*** WARNING: headline MAE exceeds the {backtest.MAE_DANGER_THRESHOLD_PP}pp danger "
            f"threshold. Wave 1 is NOT validated per docs/TECHNICAL_ARCHITECTURE.md success criteria. ***"
        )


if __name__ == "__main__":
    main()
