"""DESTER dashboard: Plotly chart builders. Pure functions -- take already-
loaded data, return a go.Figure. No I/O, no recomputation."""

import plotly.graph_objects as go

from dashboard import data_loader

MARKETS = ["AUS-SLC", "ATL-SAT"]
PRIMARY_VARIANT = {"AUS-SLC": "original", "ATL-SAT": "v5 (final)"}


def two_market_comparison_chart(data, regime):
    """Grouped bars: local revenue, feed revenue, cost, contribution -- side
    by side for AUS-SLC and ATL-SAT, each market's primary (headline)
    variant."""
    metrics = ["Local revenue", "Feed revenue", "Cost", "Contribution"]
    fig = go.Figure()

    for market in MARKETS:
        variant = PRIMARY_VARIANT[market]
        v1 = data_loader.get_verdict1(data, market, variant)
        v3 = data_loader.get_verdict3(data, market, variant)
        regime_entry = data_loader.get_regime(v3, regime)

        if v1 is None or regime_entry is None:
            continue

        local_revenue = v1["revenue_annual_usd"]
        cost = v1["cost_annual_usd"]
        feed_revenue = regime_entry["feed_revenue_annual_usd"]
        contribution = regime_entry["total_contribution_annual_usd"]

        fig.add_trace(
            go.Bar(name=market, x=metrics, y=[local_revenue, feed_revenue, cost, contribution])
        )

    fig.update_layout(
        barmode="group",
        title=f"Local vs. feed economics ({regime} attribution)",
        yaxis_title="USD / year",
    )
    return fig


def leverage_chart(data):
    """Horizontal bar of attribution leverage % per market's primary
    variant, with a vertical line at 100% marking the theoretical
    verdict-flip threshold (leverage exceeding the mileage-regime
    contribution's own magnitude)."""
    labels, values = [], []
    for market in MARKETS:
        variant = PRIMARY_VARIANT[market]
        v3 = data_loader.get_verdict3(data, market, variant)
        if v3 is None:
            continue
        labels.append(market)
        values.append(v3["attribution_leverage_pct"] * 100)

    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", text=[f"{v:.1f}%" for v in values], textposition="auto"))
    fig.add_vline(x=100, line_dash="dash", line_color="red", annotation_text="verdict flip threshold (100%)")
    fig.update_layout(title="Attribution leverage (Shapley vs. mileage)", xaxis_title="Leverage (%)")
    return fig


def feed_waterfall_chart(verdict2_dict, top_n=10):
    """Waterfall of the top-N feed endpoints by revenue for one market,
    building up to the total feed revenue."""
    if not verdict2_dict or not verdict2_dict.get("top_feed_markets"):
        return go.Figure()

    rows = sorted(verdict2_dict["top_feed_markets"], key=lambda r: r["revenue"], reverse=True)[:top_n]
    labels = [f"{r['endpoint']} ({r['direction']})" for r in rows]
    values = [r["revenue"] for r in rows]

    fig = go.Figure(
        go.Waterfall(
            x=labels + ["Total (top {})".format(top_n)],
            y=values + [None],
            measure=["relative"] * len(values) + ["total"],
            text=[f"${v:,.0f}" for v in values] + [f"${sum(values):,.0f}"],
            textposition="outside",
        )
    )
    fig.update_layout(title=f"Top {top_n} feed endpoints by revenue", yaxis_title="USD / year")
    return fig


def sensitivity_heatmap(sensitivities, alpha, regime, uplift_grid=None, recapture_grid=None):
    """Uplift x recapture grid of go/no-go verdicts at the nearest
    precomputed alpha. If the sensitivities list has no "regime" field
    (ATL-SAT's Verdict-1-only, load-factor-based grid), regime is ignored
    and the caption should say so -- handled by the caller."""
    uplift_grid = uplift_grid or data_loader.UPLIFT_GRID
    recapture_grid = recapture_grid or data_loader.RECAPTURE_GRID

    if not sensitivities:
        return go.Figure(), None

    has_regime = "regime" in sensitivities[0]
    snapped_alpha = data_loader.nearest(alpha, data_loader.ALPHA_GRID)

    filtered = [s for s in sensitivities if s["alpha"] == snapped_alpha]
    if has_regime:
        filtered = [s for s in filtered if s["regime"] == regime]

    lookup = {(s["uplift"], s["recapture"]): s["verdict"] for s in filtered}

    z = []
    text = []
    for recapture in recapture_grid:
        row_z = []
        row_text = []
        for uplift in uplift_grid:
            verdict = lookup.get((uplift, recapture))
            row_z.append(1 if verdict == "go" else 0 if verdict == "no_go" else None)
            row_text.append(verdict.upper() if verdict else "N/A")
        z.append(row_z)
        text.append(row_text)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[f"{u:.0%}" for u in uplift_grid],
            y=[f"{r:.0%}" for r in recapture_grid],
            text=text,
            texttemplate="%{text}",
            colorscale=[[0, "#d9534f"], [1, "#5cb85c"]],
            showscale=False,
            zmin=0,
            zmax=1,
        )
    )
    fig.update_layout(
        title=f"Verdict grid at alpha={snapped_alpha}{' (' + regime + ')' if has_regime else ''}",
        xaxis_title="Stimulation uplift",
        yaxis_title="Recapture rate",
    )
    return fig, has_regime
