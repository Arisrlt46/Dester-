"""DESTER dashboard entry point.

Run via: streamlit run dashboard/app.py (from the project root, with the
venv activated). Pure viewer over pre-existing JSON outputs -- no
recomputation happens here.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from dashboard import catalog, charts, data_loader, engine, narrative
from dashboard.styles import COLORS, CSS_INJECTION

st.set_page_config(page_title="DESTER", layout="wide")
st.markdown(CSS_INJECTION, unsafe_allow_html=True)


def _verdict_badge(is_go, suffix=""):
    """### heading text with a colored dot (teal=GO, amber=NO_GO) in place
    of the old 🟢/🔴 emoji, which clashed with the teal/amber palette."""
    color = COLORS["teal"] if is_go else COLORS["amber"]
    label = "GO" if is_go else "NO_GO"
    dot = (
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{color};margin-right:8px;vertical-align:middle;"></span>'
    )
    return f'<h3 style="margin:0;">{dot}{label}{suffix}</h3>'


def _build_catalog_result(market_pair, summary_row, market_sens_df):
    """Builds a verdict1/2/3-union-shaped dict from the precomputed
    catalog_summary.parquet row + this market's slice of
    catalog_sensitivities.parquet -- same shape run_dester_engine returns,
    so the existing tab-rendering code below needs no branching to use it.
    Feed revenue is grid-invariant in this engine (verified when the
    precompute was built), so the default-grid-point feed split is valid at
    every (uplift, recapture, alpha) combo, matching how narrative.py
    already treats feed revenue for the featured markets."""
    sensitivities = market_sens_df.to_dict("records")
    default_pt = market_sens_df[
        (market_sens_df["uplift"] == 0.15) & (market_sens_df["recapture"] == 0.15) & (market_sens_df["alpha"] == 1.6)
    ]
    mileage_default = default_pt[default_pt["regime"] == "mileage"].iloc[0]
    shapley_default = default_pt[default_pt["regime"] == "shapley"].iloc[0]

    local_contribution = summary_row["local_contribution_annual_usd"]
    feed_revenue_mileage = summary_row["feed_contribution_annual_usd"]
    feed_revenue_shapley = shapley_default["contribution"] - local_contribution

    return {
        "market": market_pair,
        "carrier": summary_row["carrier"],
        "verdict": summary_row["verdict_local"],
        "revenue_annual_usd": summary_row["revenue_annual_usd"],
        "cost_annual_usd": summary_row["cost_annual_usd"],
        "contribution_annual_usd": summary_row["contribution_annual_usd"],
        "predicted_delta_share": summary_row["predicted_delta_share"],
        "sensitivities": sensitivities,
        "local_contribution_annual_usd": local_contribution,
        "feed_contribution_annual_usd": feed_revenue_mileage,
        "total_contribution_annual_usd": mileage_default["contribution"],
        "feed_share_of_total_revenue": summary_row["feed_share_of_total_revenue"],
        "is_hub_spoke_pair": bool(summary_row["is_hub_spoke_pair"]),
        "top_feed_markets": [],
        "attribution_regimes": [
            {
                "regime": "mileage", "feed_revenue_annual_usd": feed_revenue_mileage,
                "total_contribution_annual_usd": mileage_default["contribution"],
                "verdict": mileage_default["verdict"],
            },
            {
                "regime": "shapley", "feed_revenue_annual_usd": feed_revenue_shapley,
                "total_contribution_annual_usd": shapley_default["contribution"],
                "verdict": shapley_default["verdict"],
            },
        ],
        "attribution_leverage_pct": summary_row["attribution_leverage"],
        "verdict_flipped": mileage_default["verdict"] != shapley_default["verdict"],
    }

# Plain-English explanations shown as st.metric help= tooltips throughout Tab 1.
HELP = {
    "verdict": "GO means the route is expected to be profitable under these parameters and this rule; NO_GO means it isn't.",
    "revenue": "Annual dollars collected from ticket sales on this route, before subtracting the cost of flying it.",
    "cost": "Annual dollars it costs to operate the scheduled flights, based on the aircraft's actual per-seat-mile operating cost.",
    "contribution": "Annual dollars of profit contribution after paying for the aircraft cost. Positive contribution means the route earns more than it costs to fly.",
    "predicted_share": "The fraction of this market's passengers the discrete-choice model predicts will choose Delta, based on fare, routing, frequency, and hub dominance.",
    "expected_lf": "The fraction of seats sold across all flights. Higher LF means the aircraft is fuller, which is generally more profitable per seat.",
    "breakeven_lf": "The load factor at which revenue exactly covers cost. If actual load factor is above this, the route is profitable.",
    "feed_share": "The fraction of total revenue that comes from passengers connecting through the hub to/from other cities, rather than flying point-to-point.",
    "attribution_leverage": "How much the total contribution figure changes when connecting-passenger revenue is split under Shapley (game-theoretic fair split) vs. mileage proration (distance-weighted). Larger leverage means the attribution rule matters more to the route's answer.",
    "verdict_flipped": "Whether the go/no-go decision itself changes depending on which attribution rule (mileage vs. Shapley) is used -- the central question this project investigates.",
}

data = data_loader.load_all_data()
docs = data_loader.load_docs()
pitch = data_loader.load_readme_pitch()

# Reserved at the top of the page; filled in below once market/variant are
# resolved, so the "Currently analyzing" line can reflect this run's actual
# selection despite Streamlit's top-to-bottom widget execution order.
hero = st.container()

mode = st.radio("Mode", ["Featured Market", "Custom Market", "Catalog"], horizontal=True)

is_custom = mode == "Custom Market"
is_catalog = mode == "Catalog"
uses_engine = is_custom or is_catalog  # both run engine.run_dester_engine and share its caveats
custom_result = None
catalog_result = None

if uses_engine:
    st.info(
        "Custom Market runs a general-purpose estimator against a national aggregate. Results may differ "
        "from featured markets (AUS-SLC, ATL-SAT, MIA-SEA), which were hand-analyzed in the research phase. "
        "Real airline operations have carrier-partner structure -- like Delta's regional-jet flying being "
        "filed under SkyWest's carrier code -- that a fast, generic estimator cannot fully recover from raw "
        "ticket data alone. Featured markets show the rigorous case-study result. Custom Market shows a "
        "defensible fast approximation across any US O&D pair."
    )

FEATURED_DEFAULT_VARIANT = {"AUS-SLC": "original", "ATL-SAT": "v5 (final)", "MIA-SEA": "v5 (final)"}

if mode == "Featured Market":
    market = st.radio("Market", ["AUS-SLC", "ATL-SAT", "MIA-SEA"], horizontal=True)
    variants = data_loader.available_variants(data, market)
    default_variant = FEATURED_DEFAULT_VARIANT.get(market, "v5 (final)")
    default_index = variants.index(default_variant) if default_variant in variants else 0
else:
    market, variant = None, None

st.sidebar.markdown("### Market")

if is_custom:
    st.sidebar.caption("On-demand engine: runs a point-estimate pipeline against the committed data/*.parquet aggregates (no BTS download needed). Not the featured markets' pre-registered, sensitivity-swept pipeline.")
    origin_input = st.sidebar.text_input("Origin airport", value="ATL", max_chars=3).strip().upper()
    dest_input = st.sidebar.text_input("Destination airport", value="SAT", max_chars=3).strip().upper()
    carrier_input = st.sidebar.text_input("Carrier (optional -- blank = dominant carrier)", value="", max_chars=2).strip().upper()
    st.sidebar.caption(
        "Note: For hub-fed markets not in the top-10 US hub list (ATL, DFW, ORD, DEN, LAX, CLT, LAS, PHX, "
        "SEA, MSP), feed calculations return zero. Verdict 1 (local-only) remains meaningful across all pairs."
    )
    run_clicked = st.sidebar.button("Run on-demand analysis")
elif is_catalog:
    st.sidebar.caption("Pick a market from the catalog table below, then click \"Analyze selected market.\"")
else:
    st.sidebar.caption("Selects the nearest pre-computed sensitivity-grid point -- does not recompute the model.")
    variant = st.sidebar.selectbox("Model variant", options=variants, index=default_index)

st.sidebar.markdown("### Parameters")
uplift = st.sidebar.slider("Stimulation uplift", min_value=0.10, max_value=0.25, value=0.15, step=0.01, format="%.2f")
recapture = st.sidebar.slider("Recapture rate", min_value=0.10, max_value=0.30, value=0.15, step=0.01, format="%.2f")
alpha = st.sidebar.slider("S-curve alpha", min_value=1.4, max_value=1.8, value=1.6, step=0.05, format="%.2f")

st.sidebar.markdown("### Attribution regime")
regime = st.sidebar.radio("Attribution regime", ["mileage", "shapley"], label_visibility="collapsed")

snapped_uplift = data_loader.nearest(uplift, data_loader.UPLIFT_GRID)
snapped_recapture = data_loader.nearest(recapture, data_loader.RECAPTURE_GRID)
snapped_alpha = data_loader.nearest(alpha, data_loader.ALPHA_GRID)
if mode == "Featured Market" and (snapped_uplift, snapped_recapture, snapped_alpha) != (uplift, recapture, alpha):
    st.sidebar.caption(f"Snapped to grid point: uplift={snapped_uplift:.0%}, recapture={snapped_recapture:.0%}, alpha={snapped_alpha}")

if is_custom:
    if run_clicked:
        with st.spinner(f"Running on-demand analysis for {origin_input}-{dest_input}..."):
            st.session_state["custom_result"] = engine.run_dester_engine(
                origin_input, dest_input, carrier=carrier_input or None,
                uplift=uplift, recapture=recapture, alpha=alpha,
            )
            st.session_state["custom_market_label"] = f"{origin_input}-{dest_input}"

    custom_result = st.session_state.get("custom_result")
    market = st.session_state.get("custom_market_label", f"{origin_input}-{dest_input}")

    if custom_result is None:
        st.info("Enter an origin/destination and click \"Run on-demand analysis\" in the sidebar.")
    elif custom_result.get("error"):
        st.error(custom_result["error"])

# ------------------------------------------------------------------ Catalog
if is_catalog:
    st.subheader("Market catalog")

    catalog_df = catalog.load_catalog()
    catalog_summary_df = engine.load_catalog_summary()
    has_summary = catalog_summary_df is not None
    if has_summary:
        # feed_share/size_bucket are duplicated from the screener into the
        # summary (per the precompute's own schema) -- drop them here so
        # the merge below doesn't suffix catalog_df's copies into
        # feed_share_x/feed_share_y.
        catalog_summary_df = catalog_summary_df.drop(columns=["feed_share", "size_bucket"])

    if has_summary:
        st.caption(
            "The 934 spoke-to-hub candidates from the Wave 1 screener, each with a precomputed 48-combination x "
            "2-regime sensitivity grid. Pick one to see its verdict tabs instantly -- no live computation."
        )
        merged_df = catalog_df.merge(catalog_summary_df, on="market_pair", how="left")
    else:
        st.caption(
            "The 934 spoke-to-hub candidates from the Wave 1 screener. Run `python -m "
            "preprocess.precompute_sensitivities` to unlock instant per-market verdicts, leverage sort, and the "
            "verdict-flip filter -- showing screener columns only until then."
        )
        merged_df = catalog_df

    all_carriers = sorted(catalog_df["dominant_carrier"].dropna().unique().tolist())

    filt_cols = st.columns([2, 3, 2])
    size_selected = filt_cols[0].multiselect("Size bucket", options=catalog.SIZE_BUCKETS, default=catalog.SIZE_BUCKETS)
    feed_range = filt_cols[1].slider("Feed share", min_value=0.0, max_value=1.0, value=(0.0, 1.0), step=0.01, format="%.2f")
    carrier_selected = filt_cols[2].selectbox("Dominant carrier", options=["All"] + all_carriers, index=0)

    sort_options = ["feed_share", "attribution_leverage", "local_pax_sample"] if has_summary else ["feed_share", "local_pax_sample"]
    sort_cols = st.columns([2, 3])
    sort_by = sort_cols[0].selectbox("Sort by", options=sort_options)

    if has_summary:
        sort_cols[1].caption("Markets where Shapley vs mileage attribution changes the go/no-go answer.")
        flip_only = sort_cols[1].checkbox("Show only verdict-flipping markets")
    else:
        flip_only = False

    filtered_catalog_df = catalog.filter_catalog(
        catalog_df,
        size_buckets=size_selected or catalog.SIZE_BUCKETS,
        min_feed_share=feed_range[0],
        max_feed_share=feed_range[1],
        dominant_carrier=None if carrier_selected == "All" else carrier_selected,
    )
    filtered_df = merged_df[merged_df["market_pair"].isin(filtered_catalog_df["market_pair"])]
    if flip_only and has_summary:
        filtered_df = filtered_df[filtered_df["verdict_flipped_anywhere"] == True]  # noqa: E712
    filtered_df = filtered_df.sort_values(sort_by, ascending=False)

    st.caption(f"{len(filtered_df):,} of {len(catalog_df):,} markets match the current filters.")

    market_options = filtered_df["market_pair"].tolist()
    if market_options:
        select_cols = st.columns([3, 1])
        selected_catalog_market = select_cols[0].selectbox("Select a market to analyze", options=market_options)
        analyze_clicked = select_cols[1].button("Analyze selected market")
    else:
        st.warning("No markets match the current filters.")
        selected_catalog_market, analyze_clicked = None, False

    display_df = filtered_df.copy()
    display_df["dominant_carrier_share"] = display_df["dominant_carrier_share"].map(lambda v: f"{v:.1%}")
    display_df["feed_share"] = display_df["feed_share"].map(lambda v: f"{v:.1%}")
    display_df["local_pax_sample"] = display_df["local_pax_sample"].map(lambda v: f"{v:,.0f}")
    display_cols = ["market_pair", "hub", "spoke", "dominant_carrier", "dominant_carrier_share", "local_pax_sample", "feed_share", "size_bucket"]
    column_config = {}
    if has_summary:
        display_df["attribution_leverage"] = display_df["attribution_leverage"].map(lambda v: f"{v:.1%}" if pd.notna(v) else "n/a")
        display_cols += ["headline_verdict_mileage", "attribution_leverage", "verdict_flipped_anywhere"]
        column_config["verdict_flipped_anywhere"] = st.column_config.CheckboxColumn("verdict_flipped_anywhere", disabled=True)
    st.dataframe(display_df[display_cols], hide_index=True, use_container_width=True, column_config=column_config)

    if analyze_clicked and selected_catalog_market:
        if has_summary and selected_catalog_market in catalog_summary_df["market_pair"].values:
            summary_row = catalog_summary_df[catalog_summary_df["market_pair"] == selected_catalog_market].iloc[0]
            catalog_sens_df = pd.read_parquet(os.path.join(_PROJECT_ROOT, "data", "catalog_sensitivities.parquet"))
            market_sens_df = catalog_sens_df[catalog_sens_df["market_pair"] == selected_catalog_market]
            st.session_state["catalog_result"] = _build_catalog_result(selected_catalog_market, summary_row, market_sens_df)
            st.session_state["catalog_market_label"] = selected_catalog_market
        else:
            row = filtered_catalog_df[filtered_catalog_df["market_pair"] == selected_catalog_market].iloc[0]
            with st.spinner(f"No precomputed data for {selected_catalog_market} (skipped during the batch precompute) -- running the on-demand engine live instead..."):
                st.session_state["catalog_result"] = engine.run_dester_engine(
                    row["hub"], row["spoke"], carrier=row["dominant_carrier"],
                    uplift=uplift, recapture=recapture, alpha=alpha,
                )
                st.session_state["catalog_market_label"] = selected_catalog_market

    catalog_result = st.session_state.get("catalog_result")
    market = st.session_state.get("catalog_market_label")

    if catalog_result is None:
        st.info("Select a market above and click \"Analyze selected market\" to see its verdict tabs below.")
    elif catalog_result.get("error"):
        st.error(catalog_result["error"])

usable_custom = is_custom and custom_result is not None and not custom_result.get("error")
usable_catalog = is_catalog and catalog_result is not None and not catalog_result.get("error")
if uses_engine and not (usable_custom or usable_catalog):
    v1 = v2 = v3 = None
elif is_custom:
    # The engine returns one merged dict with all Verdict 1/2/3 fields, same
    # shape as ATL-SAT's precomputed "merged" variant.
    v1 = v2 = v3 = custom_result
elif is_catalog:
    v1 = v2 = v3 = catalog_result
else:
    v1 = data_loader.get_verdict1(data, market, variant)
    v2 = data_loader.get_verdict2(data, market, variant)
    v3 = data_loader.get_verdict3(data, market, variant)

with hero:
    st.markdown('<div class="dester-hero-title">DESTER</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dester-hero-subtitle">Feed-dependent airline route analysis with '
        'game-theoretic revenue attribution</div>',
        unsafe_allow_html=True,
    )
    if is_custom:
        context_line = f"Currently analyzing: {market} under model on-demand engine" if usable_custom else "Currently analyzing: (enter a market and run the on-demand engine)"
    elif is_catalog:
        context_line = f"Currently analyzing: {market} under model on-demand engine" if usable_catalog else "Currently analyzing: (select a market from the catalog below)"
    else:
        context_line = f"Currently analyzing: {market} under model {variant}"
    st.markdown(f'<div class="dester-hero-context">{context_line}</div>', unsafe_allow_html=True)
    if pitch:
        st.caption(pitch)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Verdicts", "Comparison", "Feed", "Sensitivity", "Docs"])

# ---------------------------------------------------------------- Verdicts
with tab1:
    if v1 is None:
        if mode == "Featured Market":
            st.warning(f"No Verdict 1 data for {market} / {variant}.")
        # (Custom Market's / Catalog's own "select a market" / error message is already shown above.)
    else:
        comparison_context = None
        if mode == "Featured Market":
            comparison_context = {}
            for other_market in charts.MARKETS:
                if other_market == market:
                    continue
                other_v3 = data_loader.get_verdict3(data, other_market, charts.PRIMARY_VARIANT[other_market])
                if other_v3 is not None:
                    comparison_context[other_market] = {
                        "attribution_leverage_pct": other_v3["attribution_leverage_pct"],
                        "verdict_flipped": other_v3["verdict_flipped"],
                    }
        st.info(narrative.generate_verdict_narrative(market, v1, v2, v3, regime, uplift, recapture, alpha, comparison_context=comparison_context))

        sens1 = data_loader.nearest_sensitivity(v1.get("sensitivities", []), snapped_uplift, snapped_recapture, snapped_alpha)
        is_contribution_rule = "verdict_rule" in v1  # only the _norm variants override the default LF rule

        st.subheader("Verdict 1 -- Local viability")
        badge = sens1["verdict"] if sens1 else v1["verdict"]
        st.markdown(_verdict_badge(badge == "go"), unsafe_allow_html=True)
        st.caption(f"Rule: {'contribution' if is_contribution_rule else 'load-factor'}", help=HELP["verdict"])
        cols = st.columns(4)
        cols[0].metric("Revenue (annual)", f"${v1['revenue_annual_usd']:,.0f}", help=HELP["revenue"])
        cols[1].metric("Cost (annual)", f"${v1['cost_annual_usd']:,.0f}", help=HELP["cost"])
        cols[2].metric("Contribution (annual)", f"${v1['contribution_annual_usd']:,.0f}", help=HELP["contribution"])
        cols[3].metric("Predicted dominant share", f"{v1['predicted_delta_share']:.1%}", help=HELP["predicted_share"])
        if sens1:
            lf_cols = st.columns(2)
            lf_cols[0].metric("Expected load factor (at grid point)", f"{sens1.get('expected_lf', float('nan')):.1%}", help=HELP["expected_lf"])
            lf_cols[1].metric("Breakeven load factor", f"{sens1.get('breakeven_lf', float('nan')):.1%}", help=HELP["breakeven_lf"])

    if v2 is not None:
        st.subheader("Verdict 2 -- Feed contribution")
        cols = st.columns(3)
        cols[0].metric("Local contribution", f"${v2['local_contribution_annual_usd']:,.0f}", help=HELP["contribution"])
        cols[1].metric("Feed contribution", f"${v2['feed_contribution_annual_usd']:,.0f}", help=HELP["contribution"])
        cols[2].metric("Feed share of revenue", f"{v2['feed_share_of_total_revenue']:.1%}", help=HELP["feed_share"])

    if v3 is not None:
        st.subheader("Verdict 3 -- Attribution sensitivity")
        regime_entry = data_loader.get_regime(v3, regime)
        if regime_entry:
            st.markdown(_verdict_badge(regime_entry["verdict"] == "go", suffix=f"  ({regime})"), unsafe_allow_html=True)
            st.caption("GO/NO_GO here uses the contribution rule (total local + feed profit >= 0).", help=HELP["verdict"])
            cols = st.columns(3)
            cols[0].metric("Total contribution", f"${regime_entry['total_contribution_annual_usd']:,.0f}", help=HELP["contribution"])
            cols[1].metric("Attribution leverage", f"{v3['attribution_leverage_pct']:.1%}", help=HELP["attribution_leverage"])
            cols[2].metric("Verdict flipped?", "YES" if v3["verdict_flipped"] else "NO", help=HELP["verdict_flipped"])

# ---------------------------------------------------------------- Comparison
with tab2:
    st.plotly_chart(charts.two_market_comparison_chart(data, regime), use_container_width=True)
    st.plotly_chart(charts.leverage_chart(data), use_container_width=True)

# ---------------------------------------------------------------- Feed
with tab3:
    if v2 is None:
        st.info("Run an on-demand analysis to see feed data." if uses_engine else "No feed data.")
    elif uses_engine:
        st.metric("Feed contribution (annual, mileage basis)", f"${v2['feed_contribution_annual_usd']:,.0f}", help=HELP["contribution"])
        st.metric("Feed share of revenue", f"{v2['feed_share_of_total_revenue']:.1%}", help=HELP["feed_share"])
        if not v2.get("is_hub_spoke_pair", True):
            st.caption("Neither endpoint is on the top-10 US hub list used for feed detection, so this market has no feed to attribute.")
        else:
            st.caption("On-demand markets show aggregate feed totals only -- the per-endpoint breakdown (waterfall chart, top-20 table) is computed only for the featured markets.")
    elif not v2.get("top_feed_markets"):
        st.warning(f"No feed data for {market} / {variant}.")
    else:
        st.plotly_chart(charts.feed_waterfall_chart(v2, top_n=10), use_container_width=True)
        st.subheader("Top 20 feed endpoints")
        rows = sorted(v2["top_feed_markets"], key=lambda r: r["revenue"], reverse=True)[:20]
        st.dataframe(
            [{"Endpoint": r["endpoint"], "Direction": r["direction"], "Passengers": round(r["passengers"]), "Revenue": round(r["revenue"])} for r in rows],
            use_container_width=True,
        )

# ---------------------------------------------------------------- Sensitivity
with tab4:
    st.caption(
        "Each cell shows whether the route is GO or NO_GO for a specific combination of stimulation "
        "uplift (rows) and recapture rate (columns). Robustness across the whole grid is a stronger "
        "result than a single-point GO."
    )
    if is_custom:
        st.caption(
            "Sensitivity grid available only for featured markets and the Catalog (precomputed) -- Custom "
            "Market's on-demand engine shows a point estimate only. To see sensitivity, pick a featured "
            "market or a Catalog market."
        )
    else:
        sensitivities = (v3 or {}).get("sensitivities") or (v1 or {}).get("sensitivities") or []
        if not sensitivities:
            if is_catalog:
                st.info("Select a market above and click \"Analyze selected market\" to see its sensitivity grid.")
            else:
                st.warning(f"No sensitivity grid for {market} / {variant}.")
        else:
            fig, has_regime = charts.sensitivity_heatmap(sensitivities, alpha, regime)
            st.plotly_chart(fig, use_container_width=True)
            if not has_regime:
                st.caption(
                    "This market's sensitivity grid predates the regime-aware sweep and reflects the "
                    "load-factor-based verdict rule only (the attribution-regime toggle doesn't apply here)."
                )

# ---------------------------------------------------------------- Docs
with tab5:
    st.subheader("Research Findings")
    st.markdown(docs["research_findings"])
    st.subheader("Problems & Solutions Log")
    st.markdown(docs["problems_and_solutions"])
