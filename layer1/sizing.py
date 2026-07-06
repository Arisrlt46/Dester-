"""Layer 1 Wave 2, Module 4: market sizing with stimulation uplift.

Turns Layer 0's 10% quarterly DB1B sample into an annualized total market
size, then applies a stimulation uplift for the demand a new nonstop creates
that didn't previously exist (upgraded connecting pax, diverted drivers, and
previously-unmade trips).
"""

import json

DB1B_SAMPLE_RATE = 0.10
QUARTERS_PER_YEAR = 4

DEFAULT_STIMULATION_UPLIFT = 0.15
UPLIFT_SENSITIVITY_VALUES = [0.10, 0.15, 0.20, 0.25]


def annualize_sample(quarter_passenger_sample):
    return quarter_passenger_sample * (1 / DB1B_SAMPLE_RATE) * QUARTERS_PER_YEAR


def apply_stimulation(base_pax, uplift=DEFAULT_STIMULATION_UPLIFT):
    return base_pax * (1 + uplift)


def market_size(layer0_summary_path, uplift=DEFAULT_STIMULATION_UPLIFT):
    with open(layer0_summary_path) as f:
        summary = json.load(f)

    base_pax = annualize_sample(summary["passenger_total_sample"])
    sized_pax = apply_stimulation(base_pax, uplift)

    return {"base_pax": base_pax, "uplift": uplift, "sized_pax": sized_pax}
