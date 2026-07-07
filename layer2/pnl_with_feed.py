"""Layer 2, Module 3: combined local + feed route P&L.

Replays Verdict 1's P&L math with total AUS-SLC passengers = local + feed and
total revenue = local revenue + Delta's feed-allocated revenue. Reuses
layer1.pnl for the cost side -- feed does not change the cost of flying the
aircraft, only the revenue side and passenger mix change.

The 2x-daily E175 provides ~54,000 annual seats; local demand alone already
runs near capacity (per Verdict 1). The meaningful output here is not
whether load factor changes (it can't much) but how the passenger mix splits
between local and feed, and what that means for total contribution.
"""

from layer1 import pnl as layer1_pnl

YEAR_QUARTERS = 4


def combined_pnl(local_pax, local_revenue, feed_pax, feed_revenue, seats_per_departure, freq_per_day, quarter_days, distance_miles, casm_cents):
    """distance_miles must match the mean_distance_miles Verdict 1 used for its
    own ASM/cost calculation (Layer 0's summary.json), not the AUS-SLC
    great-circle constant used for fare proration -- otherwise this would
    silently recompute a different cost than Verdict 1's, contradicting
    'feed does not change the cost of flying the aircraft'."""
    days_per_year = quarter_days * YEAR_QUARTERS
    capacity_seats_annual = seats_per_departure * freq_per_day * days_per_year
    asms = capacity_seats_annual * distance_miles

    # Cost is capacity-driven and unaffected by feed; reuse route_pnl purely for its cost formula.
    cost = layer1_pnl.route_pnl(revenue=0.0, asms=asms, casm=casm_cents)["cost"]

    local_contribution = local_revenue - cost
    feed_contribution = feed_revenue  # cost already fully attributed to local; feed rides the same flights
    total_revenue = local_revenue + feed_revenue
    total_pax = local_pax + feed_pax
    total_contribution = local_contribution + feed_contribution
    total_load_factor = total_pax / capacity_seats_annual if capacity_seats_annual > 0 else 0.0

    return {
        "cost": cost,
        "local_contribution": local_contribution,
        "feed_contribution": feed_contribution,
        "total_contribution": total_contribution,
        "total_revenue": total_revenue,
        "total_pax": total_pax,
        "total_load_factor": total_load_factor,
    }
