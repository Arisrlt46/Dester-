"""Layer 1 Wave 1 Iteration 3: refit using the market-diversity-filtered
calibration set.

Imports Layer 1's original logit.fit/save_coefficients unchanged. The only
difference from Wave 1 is the input dataframe (calibration_v3's filtered
train set) -- same standardize -> lbfgs -> unstandardize approach.
"""

import os

from layer1 import logit

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
LOGIT_COEFFICIENTS_V3_PATH = os.path.join(LAYER1_OUT_DIR, "logit_coefficients_v3.json")


def fit_and_save_v3(train_df_v3):
    coefficients = logit.fit(train_df_v3)
    os.makedirs(LAYER1_OUT_DIR, exist_ok=True)
    logit.save_coefficients(coefficients, LOGIT_COEFFICIENTS_V3_PATH)
    print(f"Wrote {LOGIT_COEFFICIENTS_V3_PATH}")
    return coefficients
