"""Layer 1 CPA markup refinement, Module 1: Delta's CPA-effective CASM.

Delta mainline doesn't operate the E175 -- SkyWest does, under a capacity-
purchase agreement. DESTER's core CASM (layer1.pnl.compute_delta_e175_casm)
uses SkyWest's raw operating cost, which is the floor of Delta's true
effective cost. This applies the documented CPA markup on top -- an
additive refinement producing a parallel artifact, not a correction to the
pre-registered figure.
"""

from layer1 import pnl

# Industry CPA markups run 8-15%; 12% is a documented central estimate.
# Applied to SkyWest's raw CASM to estimate Delta's effective cost under
# the Delta Connection capacity-purchase agreement.
CPA_MARKUP = 1.12


def compute_delta_e175_casm_cpa(p52_csv_path, t100_csv_path, quarter=pnl.DEFAULT_QUARTER, year=pnl.DEFAULT_YEAR):
    raw = pnl.compute_delta_e175_casm(p52_csv_path, t100_csv_path, quarter=quarter, year=year)
    marked_up = dict(raw)
    marked_up["raw_casm_cents_per_asm"] = raw["casm_cents_per_asm"]
    marked_up["casm_cents_per_asm"] = raw["casm_cents_per_asm"] * CPA_MARKUP
    marked_up["cpa_markup"] = CPA_MARKUP
    return marked_up
