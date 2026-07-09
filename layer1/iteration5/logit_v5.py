"""Layer 1 Wave 1 Iteration 5: shrinkage strength sweep.

Reuses Iteration 4's shrinkage procedure (layer1.iteration4.logit_v4)
unchanged, parameterizing the shrinkage strength lambda instead of using
its fixed default (10.0) -- Iteration 4 left NK's shrinkage (39.1%) just
under the 40% threshold at lambda=10.0 while F9 passed (51.1%).
"""

import json
import os

from layer1 import backtest, logit
from layer1.iteration4 import logit_v4

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")


def _paths_for_lambda(lambda_val):
    suffix = f"lambda{int(lambda_val)}"
    return {
        "coefficients": os.path.join(LAYER1_OUT_DIR, f"logit_coefficients_v5_{suffix}.json"),
        "shrinkage_report": os.path.join(LAYER1_OUT_DIR, f"shrinkage_report_v5_{suffix}.json"),
        "backtest_report": os.path.join(LAYER1_OUT_DIR, f"backtest_report_v5_{suffix}.json"),
    }


def _fit_and_shrink_at_lambda(train_df, lambda_val, features=None):
    # logit_v4._ORIGINAL_FIT is the captured, never-patched base fit function
    # -- using it (rather than a live logit.fit lookup) avoids recursion when
    # this module later monkey-patches logit.fit for the backtest call.
    base_coefficients = logit_v4._ORIGINAL_FIT(train_df, features=features)
    variance_per_carrier = logit_v4.compute_residual_variance_per_carrier(train_df, base_coefficients)
    shrunk_coefficients, shrinkage_table = logit_v4.shrink_intercepts(
        base_coefficients, variance_per_carrier, lam=lambda_val
    )
    return shrunk_coefficients, shrinkage_table


def fit_and_shrink(lambda_val):
    """Fits, shrinks at lambda_val, backtests, and saves all three artifacts
    under distinct lambda-suffixed filenames. Returns a dict with the
    shrunk coefficients, the shrinkage table, and the backtest MAE/RMSE."""
    train_df, test_df = logit_v4.load_calibration_split()
    paths = _paths_for_lambda(lambda_val)
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)

    shrunk_coefficients, shrinkage_table = _fit_and_shrink_at_lambda(train_df, lambda_val)
    logit.save_coefficients(shrunk_coefficients, paths["coefficients"])
    print(f"Wrote {paths['coefficients']}")

    shrinkage_table_sorted = sorted(
        shrinkage_table, key=lambda r: abs(r["fitted_intercept"] - r["shrunk_intercept"]), reverse=True
    )
    with open(paths["shrinkage_report"], "w") as f:
        json.dump({"lambda": lambda_val, "shrinkage_table": shrinkage_table_sorted}, f, indent=2)
    print(f"Wrote {paths['shrinkage_report']}")

    def _fit_with_shrinkage_at_lambda(train_df_inner, features=None):
        shrunk, _ = _fit_and_shrink_at_lambda(train_df_inner, lambda_val, features=features)
        return shrunk

    original_fit = logit.fit
    try:
        logit.fit = _fit_with_shrinkage_at_lambda
        report = backtest.run_backtest(train_df, test_df)
    finally:
        logit.fit = original_fit

    backtest.write_backtest_report(report, paths["backtest_report"])

    return {
        "lambda": lambda_val,
        "coefficients": shrunk_coefficients,
        "shrinkage_table": shrinkage_table_sorted,
        "mae_pp": report["headline_mae_pp"],
        "rmse_pp": report["headline_rmse_pp"],
        "exceeds_danger_threshold": report["exceeds_danger_threshold"],
        "paths": paths,
    }
