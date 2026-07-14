"""DESTER dashboard: Plotly chart builders. Pure functions -- take already-
loaded data, return a go.Figure. No I/O, no recomputation."""

import plotly.graph_objects as go

from dashboard import data_loader
from dashboard.styles import COLORS, PLOTLY_TEMPLATE, teal_gradient

MARKETS = ["AUS-SLC", "ATL-SAT", "MIA-SEA"]
PRIMARY_VARIANT = {"AUS-SLC": "original", "ATL-SAT": "v5 (final)", "MIA-SEA": "v5 (final)"}
MARKET_COLOR = {"AUS-SLC": COLORS["teal"], "ATL-SAT": COLORS["amber"], "MIA-SEA": COLORS["violet"]}


def two_market_comparison_chart(data, regime):
    """Grouped bars: local revenue, feed revenue, cost, contribution -- side
    by side for every featured market (AUS-SLC/ATL-SAT/MIA-SEA), each
    market's primary (headline) variant. Name kept for compatibility with
    existing callers; the loop below already handles any MARKETS length."""
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
            go.Bar(
                name=market,
                x=metrics,
                y=[local_revenue, feed_revenue, cost, contribution],
                marker_color=MARKET_COLOR[market],
            )
        )

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        barmode="group",
        title=f"Local vs. feed economics ({regime} attribution)",
        yaxis_title="USD / year",
        legend_title_text="Market",
    )
    return fig


def leverage_chart(data):
    """Horizontal bar of attribution leverage % per market's primary
    variant (one bar per featured market), with a vertical line at 100%
    marking the theoretical verdict-flip threshold (leverage exceeding the
    mileage-regime contribution's own magnitude). Bars use each market's own
    MARKET_COLOR so the identity link to the comparison chart above holds."""
    labels, values, colors = [], [], []
    for market in MARKETS:
        variant = PRIMARY_VARIANT[market]
        v3 = data_loader.get_verdict3(data, market, variant)
        if v3 is None:
            continue
        labels.append(market)
        values.append(v3["attribution_leverage_pct"] * 100)
        colors.append(MARKET_COLOR[market])

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            text=[f"{v:.1f}%" for v in values],
            textposition="auto",
            marker_color=colors,
        )
    )
    fig.add_vline(
        x=100,
        line_dash="dash",
        line_color=COLORS["text_secondary"],
        annotation_text="verdict flip threshold (100%)",
        annotation_font_color=COLORS["text_secondary"],
    )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Attribution leverage (Shapley vs. mileage)",
        xaxis_title="Leverage (%)",
    )
    return fig


def feed_waterfall_chart(verdict2_dict, top_n=10):
    """Waterfall of the top-N feed endpoints by revenue for one market,
    building up to the total feed revenue."""
    if not verdict2_dict or not verdict2_dict.get("top_feed_markets"):
        return go.Figure()

    rows = sorted(verdict2_dict["top_feed_markets"], key=lambda r: r["revenue"], reverse=True)[:top_n]
    labels = [f"{r['endpoint']} ({r['direction']})" for r in rows]
    values = [r["revenue"] for r in rows]
    total = sum(values)

    # go.Waterfall's marker only accepts single increasing/decreasing/totals
    # colors, not a per-point array, so a true gradient is built by hand:
    # stacked Bar traces with an explicit running `base`, giving the same
    # step-up waterfall shape with independent per-bar fill. Darkest shade =
    # largest endpoint, lightest = smallest; the total bar is one shade
    # darker than the darkest step.
    bar_shades = list(reversed(teal_gradient(len(values))))
    bases = []
    running = 0
    for v in values:
        bases.append(running)
        running += v

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=values,
            base=bases,
            marker_color=bar_shades,
            text=[f"${v:,.0f}" for v in values],
            textposition="outside",
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Bar(
            x=[f"Total (top {top_n})"],
            y=[total],
            base=[0],
            marker_color=[COLORS["teal_dark"]],
            text=[f"${total:,.0f}"],
            textposition="outside",
            showlegend=False,
        )
    )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Top {top_n} feed endpoints by revenue",
        yaxis_title="USD / year",
        showlegend=False,
    )
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
            textfont=dict(color=COLORS["text_primary"]),
            colorscale=[[0, COLORS["amber"]], [1, COLORS["teal"]]],
            showscale=False,
            zmin=0,
            zmax=1,
            xgap=2,
            ygap=2,
        )
    )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=f"Verdict grid at alpha={snapped_alpha}{' (' + regime + ')' if has_regime else ''}",
        xaxis_title="Stimulation uplift",
        yaxis_title="Recapture rate",
    )
    return fig, has_regime
