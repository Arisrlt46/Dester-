"""Layer 1 Wave 1 Iteration 3 orchestrator.

Runs calibration_v3 -> logit_v3 -> Layer 1's original backtest.run_backtest
(unchanged) on the market-diversity-filtered calibration set. Runnable via
`python -m layer1.iteration3.verdict1_wave1_v3`.

Checks two stop conditions before Layer 4 iteration 3 can proceed:
  A) v3 MAE must be <= 15pp.
  B) F9 and NK must actually be among the dropped carriers -- otherwise
     this filter is the wrong lever for the same reason Iteration 2 was.
"""

import os

from layer1 import backtest, calibration
from layer1.iteration3 import calibration_v3, logit_v3

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
BACKTEST_REPORT_V3_PATH = os.path.join(LAYER1_OUT_DIR, "backtest_report_v3.json")

WAVE1_HEADLINE_MAE_PP = 13.34
WAVE1_HEADLINE_RMSE_PP = 25.35

ULCC_CARRIERS_OF_INTEREST = ["F9", "NK"]


def main():
    db1b_csv_path = calibration.resolve_csv_path(calibration.DB1B_GLOB_PATTERN)
    t100_csv_path = calibration.resolve_csv_path(calibration.T100_GLOB_PATTERN)

    train_v3, test_v3, dropped_carriers, distinct_market_counts = calibration_v3.build_calibration_v3(
        db1b_csv_path, t100_csv_path
    )
    logit_v3.fit_and_save_v3(train_v3)

    report = backtest.run_backtest(train_v3, test_v3)
    backtest.write_backtest_report(report, BACKTEST_REPORT_V3_PATH)

    print()
    print("=== Wave 1 Iteration 3 summary ===")
    print(f"Dropped carriers (< {calibration_v3.MIN_DISTINCT_MARKETS} distinct training markets): {dropped_carriers}")
    print(
        f"Headline MAE (v3): {report['headline_mae_pp']:.2f}pp  RMSE (v3): {report['headline_rmse_pp']:.2f}pp  "
        f"(Wave 1 v1: {WAVE1_HEADLINE_MAE_PP}pp / {WAVE1_HEADLINE_RMSE_PP}pp)"
    )

    stop_a = report["exceeds_danger_threshold"]
    ulcc_dropped = {c: (c in dropped_carriers) for c in ULCC_CARRIERS_OF_INTEREST}
    stop_b = not all(ulcc_dropped.values())

    for carrier in ULCC_CARRIERS_OF_INTEREST:
        count = int(distinct_market_counts.get(carrier, 0))
        print(f"  {carrier}: appeared in {count} distinct training markets, dropped={ulcc_dropped[carrier]}")

    if stop_a:
        print()
        print(
            f"*** STOP CONDITION A: v3 MAE ({report['headline_mae_pp']:.2f}pp) exceeds the "
            f"{backtest.MAE_DANGER_THRESHOLD_PP}pp danger threshold. Not proceeding to Layer 4 iteration 3. ***"
        )
    elif stop_b:
        print()
        print(
            f"*** STOP CONDITION B: v3 MAE holds ({report['headline_mae_pp']:.2f}pp <= 15pp) but F9/NK status is "
            f"{ulcc_dropped} -- not both dropped. This filter would be the wrong lever for the same reason as "
            f"Iteration 2. Not proceeding to Layer 4 iteration 3 until confirmed. ***"
        )
    else:
        print()
        print("Both stop conditions pass: MAE holds and F9/NK were both dropped. Proceeding to Layer 4 iteration 3.")


if __name__ == "__main__":
    main()
