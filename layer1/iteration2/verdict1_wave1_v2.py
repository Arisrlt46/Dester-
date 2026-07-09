"""Layer 1 Wave 1 Iteration 2 orchestrator.

Runs calibration_v2 -> logit_v2 -> Layer 1's original backtest.run_backtest
(unchanged) on the minimum-support-filtered calibration set. Runnable via
`python -m layer1.iteration2.verdict1_wave1_v2`.
"""

import os

from layer1 import backtest, calibration
from layer1.iteration2 import calibration_v2, logit_v2

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
BACKTEST_REPORT_V2_PATH = os.path.join(LAYER1_OUT_DIR, "backtest_report_v2.json")

WAVE1_HEADLINE_MAE_PP = 13.34


def main():
    db1b_csv_path = calibration.resolve_csv_path(calibration.DB1B_GLOB_PATTERN)
    t100_csv_path = calibration.resolve_csv_path(calibration.T100_GLOB_PATTERN)

    train_v2, test_v2, dropped_carriers = calibration_v2.build_calibration_v2(db1b_csv_path, t100_csv_path)
    logit_v2.fit_and_save_v2(train_v2)

    report = backtest.run_backtest(train_v2, test_v2)
    backtest.write_backtest_report(report, BACKTEST_REPORT_V2_PATH)

    print()
    print("=== Wave 1 Iteration 2 summary ===")
    print(f"Dropped carriers (min-support < {calibration_v2.MIN_SUPPORT_ROWS} training rows): {dropped_carriers}")
    print(f"Headline MAE (v2): {report['headline_mae_pp']:.2f}pp  (Wave 1 v1: {WAVE1_HEADLINE_MAE_PP}pp)")

    if report["exceeds_danger_threshold"]:
        print()
        print(
            f"*** WARNING: v2 MAE ({report['headline_mae_pp']:.2f}pp) exceeds the "
            f"{backtest.MAE_DANGER_THRESHOLD_PP}pp danger threshold. Do not proceed to the Layer 4 "
            f"iteration with this model. ***"
        )


if __name__ == "__main__":
    main()
