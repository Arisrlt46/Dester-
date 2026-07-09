"""Layer 4 Iteration 5: Verdict 1 on ATL-SAT using the v5 (lambda=15
shrinkage-regularized) logit.

Imports Wave 2's verdict1_atl_sat.py logic unchanged, swapping only the
logit coefficients path from logit_coefficients.json to the selected
logit_coefficients_v5_lambda15.json.
"""

import os

from layer4 import verdict1_atl_sat

LAYER1_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "layer1", "out")
LOGIT_COEFFICIENTS_V5_PATH = os.path.join(LAYER1_OUT_DIR, "logit_coefficients_v5_lambda15.json")


def run_verdict1_atl_sat_v5(db1b_csv_path):
    original_path = verdict1_atl_sat.LOGIT_COEFFICIENTS_PATH
    verdict1_atl_sat.LOGIT_COEFFICIENTS_PATH = LOGIT_COEFFICIENTS_V5_PATH
    try:
        return verdict1_atl_sat.run_verdict1_atl_sat(db1b_csv_path)
    finally:
        verdict1_atl_sat.LOGIT_COEFFICIENTS_PATH = original_path
