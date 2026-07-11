"""DESTER dashboard: plain-English narrative generator.

Builds a 2-4 sentence summary of what the *currently selected* parameter
combination says about a route, read live from the loaded verdict JSONs --
never recomputes the model. Local contribution at a given slider position is
derived as total_contribution - feed_contribution (both already stored per
sensitivity combo / regime); feed revenue is provably constant across the
uplift/recapture/alpha grid (feed is purely observational, per Layer 2/3/4's
own design), so this subtraction is exact, not an approximation.
"""

from dashboard import data_loader

LOW_LEVERAGE_THRESHOLD = 0.20


def _regime_lookup(verdict3):
    return {r["regime"]: r for r in (verdict3.get("attribution_regimes") or [])}


def generate_verdict_narrative(market, verdict1, verdict2, verdict3, regime, uplift, recapture, alpha):
    if not verdict1 or not verdict2 or not verdict3:
        return f"No complete verdict data available for {market} at this parameter combination."

    regimes_headline = _regime_lookup(verdict3)
    if "mileage" not in regimes_headline or "shapley" not in regimes_headline:
        return f"No attribution-regime data available for {market}."

    sensitivities = verdict3.get("sensitivities") or []
    sens_mileage = data_loader.nearest_sensitivity(sensitivities, uplift, recapture, alpha, regime="mileage")
    sens_shapley = data_loader.nearest_sensitivity(sensitivities, uplift, recapture, alpha, regime="shapley")

    if sens_mileage and sens_shapley and "contribution" in sens_mileage:
        contribution_mileage = sens_mileage["contribution"]
        contribution_shapley = sens_shapley["contribution"]
        verdict_mileage = sens_mileage["verdict"]
        verdict_shapley = sens_shapley["verdict"]
    else:
        # No regime-aware sensitivity grid for this market/variant -- fall back
        # to the headline (default-parameter) attribution_regimes figures.
        contribution_mileage = regimes_headline["mileage"]["total_contribution_annual_usd"]
        contribution_shapley = regimes_headline["shapley"]["total_contribution_annual_usd"]
        verdict_mileage = regimes_headline["mileage"]["verdict"]
        verdict_shapley = regimes_headline["shapley"]["verdict"]

    # Feed revenue == feed contribution (no cost is attributed to feed; the
    # aircraft flies regardless) and is constant across the sensitivity grid,
    # so this recovers the exact local-only contribution at this slider
    # position without recomputing anything.
    feed_revenue_mileage = regimes_headline["mileage"]["feed_revenue_annual_usd"]
    local_contribution = contribution_mileage - feed_revenue_mileage

    current_verdict = verdict_mileage if regime == "mileage" else verdict_shapley
    verdict_label = "GO" if current_verdict == "go" else "NO_GO"

    delta = contribution_shapley - contribution_mileage
    leverage = abs(delta) / abs(contribution_mileage) if contribution_mileage != 0 else float("inf")
    feed_share = verdict2.get("feed_share_of_total_revenue", 0.0)

    flipped = verdict_mileage != verdict_shapley

    if flipped:
        return (
            f"At these parameters, the attribution regime flips the verdict on {market} -- "
            f"{'GO' if verdict_mileage == 'go' else 'NO_GO'} under mileage proration, "
            f"{'GO' if verdict_shapley == 'go' else 'NO_GO'} under Shapley value. "
            f"This is the exact mechanism DESTER was built to detect: whether the rule used to split "
            f"connecting-passenger revenue between segments can change a route's go/no-go decision."
        )

    spoke = market.split("-")[-1]

    if local_contribution >= 0:
        driver_sentence = (
            f"Local point-to-point demand alone covers cost (${local_contribution / 1e6:.1f}M contribution), and "
            f"adding {spoke} connecting traffic brings total contribution to ${contribution_mileage / 1e6:.1f}M "
            f"under mileage proration or ${contribution_shapley / 1e6:.1f}M under Shapley value."
        )
    else:
        driver_sentence = (
            f"Local point-to-point demand alone doesn't cover cost (${local_contribution / 1e6:.1f}M), but "
            f"connecting traffic through the hub turns the route "
            f"{'profitable' if contribution_mileage >= 0 else 'less unprofitable'} overall -- "
            f"${contribution_mileage / 1e6:.1f}M under mileage proration, ${contribution_shapley / 1e6:.1f}M under Shapley value."
        )

    if leverage < LOW_LEVERAGE_THRESHOLD:
        attribution_sentence = (
            f"The attribution rule (how connecting revenue is split between segments) swings the answer by "
            f"~${abs(delta) / 1e3:,.0f}K here ({leverage:.1%} of the P&L) -- real dollars, but too small to move the verdict."
        )
    else:
        attribution_sentence = (
            f"The attribution rule matters a lot here: mileage proration credits Delta ${contribution_mileage / 1e6:.1f}M "
            f"on this segment, Shapley value credits ${contribution_shapley / 1e6:.1f}M -- a ${abs(delta) / 1e6:.1f}M swing "
            f"({leverage:.0%} of the answer), driven by {feed_share:.0%} of the route's revenue coming from "
            f"connecting itineraries."
        )

    return f"At these parameters, Delta's {market} route is {verdict_label}. {driver_sentence} {attribution_sentence}"
