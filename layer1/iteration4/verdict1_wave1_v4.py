"""Layer 1 Wave 1 Iteration 4 orchestrator.

Runs fit -> shrink -> Layer 1's original backtest.run_backtest (unchanged,
via a temporary monkey-patch of layer1.logit.fit so every internal refit
gets the same shrinkage treatment) -- on Wave 1's original, unfiltered
calibration set. Runnable via `python -m layer1.iteration4.verdict1_wave1_v4`.

Checks two stop conditions before Layer 4 iteration 4 can proceed:
  A) v4 MAE must be <= 15pp.
  B) F9 and NK intercepts must each be reduced in absolute value by >= 40%
     from the base (unshrunk) fit -- otherwise lambda=10.0 is too weak for
     this failure mode.
"""

import os

from layer1 import backtest, logit
from layer1.iteration4 import logit_v4

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
BACKTEST_REPORT_V4_PATH = os.path.join(LAYER1_OUT_DIR, "backtest_report_v4.json")

WAVE1_HEADLINE_MAE_PP = 13.34
WAVE1_HEADLINE_RMSE_PP = 25.35

ULCC_CARRIERS_OF_INTEREST = ["F9", "NK"]
MIN_PCT_REDUCTION = 0.40


def main():
    train_df, test_df = logit_v4.load_calibration_split()

    print("Fitting base MNLogit and computing post-fit shrinkage...")
    shrunk_coefficients, shrinkage_table = logit_v4.fit_and_save_v4(train_df)

    print()
    print("=== Shrinkage table (sorted by absolute intercept change) ===")
    for row in shrinkage_table:
        print(
            f"  {row['carrier']:3s}  fitted={row['fitted_intercept']:+8.3f}  "
            f"var={row['residual_variance']:.6f}  s={row['shrinkage_factor']:.4f}  "
            f"shrunk={row['shrunk_intercept']:+8.3f}  reduction={row['pct_reduction']:.1%}"
        )

    original_fit = logit.fit
    try:
        logit.fit = logit_v4.fit_with_shrinkage
        report = backtest.run_backtest(train_df, test_df)
    finally:
        logit.fit = original_fit

    backtest.write_backtest_report(report, BACKTEST_REPORT_V4_PATH)

    print()
    print("=== Wave 1 Iteration 4 summary ===")
    print(
        f"Headline MAE (v4): {report['headline_mae_pp']:.2f}pp  RMSE (v4): {report['headline_rmse_pp']:.2f}pp  "
        f"(Wave 1 v1: {WAVE1_HEADLINE_MAE_PP}pp / {WAVE1_HEADLINE_RMSE_PP}pp)"
    )

    shrinkage_by_carrier = {row["carrier"]: row for row in shrinkage_table}
    ulcc_status = {}
    for carrier in ULCC_CARRIERS_OF_INTEREST:
        row = shrinkage_by_carrier.get(carrier)
        if row is None:
            ulcc_status[carrier] = False
            print(f"  {carrier}: not found in shrinkage table")
        else:
            meets = row["pct_reduction"] >= MIN_PCT_REDUCTION
            ulcc_status[carrier] = meets
            print(
                f"  {carrier}: fitted={row['fitted_intercept']:+.3f} -> shrunk={row['shrunk_intercept']:+.3f} "
                f"(reduction={row['pct_reduction']:.1%}, meets >= {MIN_PCT_REDUCTION:.0%}: {meets})"
            )

    stop_a = report["exceeds_danger_threshold"]
    stop_b = not all(ulcc_status.values())

    if stop_a:
        print()
        print(
            f"*** STOP CONDITION A: v4 MAE ({report['headline_mae_pp']:.2f}pp) exceeds the "
            f"{backtest.MAE_DANGER_THRESHOLD_PP}pp danger threshold. Not proceeding to Layer 4 iteration 4. ***"
        )
    elif stop_b:
        print()
        print(
            f"*** STOP CONDITION B: v4 MAE holds ({report['headline_mae_pp']:.2f}pp <= 15pp) but F9/NK reduction "
            f"status is {ulcc_status} -- not both >= {MIN_PCT_REDUCTION:.0%}. lambda={logit_v4.SHRINKAGE_LAMBDA} "
            f"under-shrinks this failure mode. Not proceeding to Layer 4 iteration 4 until confirmed. ***"
        )
    else:
        print()
        print("Both stop conditions pass: MAE holds and F9/NK intercepts were both meaningfully shrunk. Proceeding to Layer 4 iteration 4.")


if __name__ == "__main__":
    main()
