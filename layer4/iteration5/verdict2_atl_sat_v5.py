"""Layer 4 Iteration 5: Verdict 2 on ATL-SAT.

Verdict 2 never consumes the Wave 1 logit at all (Delta's feed-market share
comes from observed DB1B data, per Layer 2's own design) -- there is nothing
to swap. This module exists only for structural parity with the other
iteration5 modules and passes straight through to Wave 2's implementation.
"""

from layer4.verdict2_atl_sat import run_verdict2_atl_sat as run_verdict2_atl_sat_v5  # noqa: F401
