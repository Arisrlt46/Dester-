"""Layer 4 Iteration 5: Verdict 3 on ATL-SAT.

Verdict 3 never consumes the Wave 1 logit either (mileage/Shapley
attribution is about feed-fare splitting, independent of the demand-share
model) -- there is nothing to swap. This module exists only for structural
parity with the other iteration5 modules and passes straight through to
Wave 2's implementation.
"""

from layer4.verdict3_atl_sat import run_verdict3_atl_sat as run_verdict3_atl_sat_v5  # noqa: F401
