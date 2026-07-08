"""Layer 3, Module 3: replay combined P&L under each attribution regime.

Reuses layer2.pnl_with_feed.combined_pnl unchanged -- the cost side and
combination logic are attribution-regime-neutral by design. Only the feed
revenue figure differs between mileage and Shapley.
"""

from layer2 import pnl_with_feed


def pnl_by_regime(local_pax, local_revenue, feed_pax, feed_revenue_by_regime, seats_per_departure, freq_per_day, quarter_days, casm_cents, distance_miles):
    return {
        regime: pnl_with_feed.combined_pnl(
            local_pax, local_revenue, feed_pax, feed_revenue,
            seats_per_departure, freq_per_day, quarter_days, distance_miles, casm_cents,
        )
        for regime, feed_revenue in feed_revenue_by_regime.items()
    }
