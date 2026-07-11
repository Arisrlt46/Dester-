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

import streamlit as st

from dashboard import charts, data_loader

st.set_page_config(page_title="DESTER", layout="wide")

data = data_loader.load_all_data()
docs = data_loader.load_docs()
pitch = data_loader.load_readme_pitch()

st.title("DESTER")
if pitch:
    st.caption(pitch)

market = st.radio("Market", ["AUS-SLC", "ATL-SAT"], horizontal=True)

variants = data_loader.available_variants(data, market)
default_variant = "original" if market == "AUS-SLC" else "v5 (final)"
default_index = variants.index(default_variant) if default_variant in variants else 0

st.sidebar.header("Parameters")
st.sidebar.caption("Selects the nearest pre-computed sensitivity-grid point -- does not recompute the model.")

variant = st.sidebar.selectbox("Model variant", options=variants, index=default_index)
uplift = st.sidebar.slider("Stimulation uplift", min_value=0.10, max_value=0.25, value=0.15, step=0.01, format="%.2f")
recapture = st.sidebar.slider("Recapture rate", min_value=0.10, max_value=0.30, value=0.15, step=0.01, format="%.2f")
alpha = st.sidebar.slider("S-curve alpha", min_value=1.4, max_value=1.8, value=1.6, step=0.05, format="%.2f")
regime = st.sidebar.radio("Attribution regime", ["mileage", "shapley"])

snapped_uplift = data_loader.nearest(uplift, data_loader.UPLIFT_GRID)
snapped_recapture = data_loader.nearest(recapture, data_loader.RECAPTURE_GRID)
snapped_alpha = data_loader.nearest(alpha, data_loader.ALPHA_GRID)
if (snapped_uplift, snapped_recapture, snapped_alpha) != (uplift, recapture, alpha):
    st.sidebar.caption(f"Snapped to grid point: uplift={snapped_uplift:.0%}, recapture={snapped_recapture:.0%}, alpha={snapped_alpha}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Verdicts", "Comparison", "Feed", "Sensitivity", "Docs"])

# ---------------------------------------------------------------- Verdicts
with tab1:
    v1 = data_loader.get_verdict1(data, market, variant)
    v2 = data_loader.get_verdict2(data, market, variant)
    v3 = data_loader.get_verdict3(data, market, variant)

    if v1 is None:
        st.warning(f"No Verdict 1 data for {market} / {variant}.")
    else:
        sens1 = data_loader.nearest_sensitivity(v1.get("sensitivities", []), snapped_uplift, snapped_recapture, snapped_alpha)
        is_contribution_rule = "verdict_rule" in v1  # only the _norm variants override the default LF rule

        st.subheader("Verdict 1 -- Local viability")
        badge = sens1["verdict"] if sens1 else v1["verdict"]
        st.markdown(f"### {'🟢 GO' if badge == 'go' else '🔴 NO_GO'}")
        st.caption(f"Rule: {'contribution' if is_contribution_rule else 'load-factor'}")
        cols = st.columns(4)
        cols[0].metric("Revenue (annual)", f"${v1['revenue_annual_usd']:,.0f}")
        cols[1].metric("Cost (annual)", f"${v1['cost_annual_usd']:,.0f}")
        cols[2].metric("Contribution (annual)", f"${v1['contribution_annual_usd']:,.0f}")
        cols[3].metric("Predicted dominant share", f"{v1['predicted_delta_share']:.1%}")
        if sens1:
            st.caption(f"At snapped grid point: expected LF={sens1.get('expected_lf', float('nan')):.1%}, breakeven LF={sens1.get('breakeven_lf', float('nan')):.1%}")

    if v2 is not None:
        st.subheader("Verdict 2 -- Feed contribution")
        cols = st.columns(3)
        cols[0].metric("Local contribution", f"${v2['local_contribution_annual_usd']:,.0f}")
        cols[1].metric("Feed contribution", f"${v2['feed_contribution_annual_usd']:,.0f}")
        cols[2].metric("Feed share of revenue", f"{v2['feed_share_of_total_revenue']:.1%}")

    if v3 is not None:
        st.subheader("Verdict 3 -- Attribution sensitivity")
        regime_entry = data_loader.get_regime(v3, regime)
        if regime_entry:
            st.markdown(f"### {'🟢 GO' if regime_entry['verdict'] == 'go' else '🔴 NO_GO'}  ({regime})")
            cols = st.columns(3)
            cols[0].metric("Total contribution", f"${regime_entry['total_contribution_annual_usd']:,.0f}")
            cols[1].metric("Attribution leverage", f"{v3['attribution_leverage_pct']:.1%}")
            cols[2].metric("Verdict flipped?", "YES" if v3["verdict_flipped"] else "NO")

# ---------------------------------------------------------------- Comparison
with tab2:
    st.plotly_chart(charts.two_market_comparison_chart(data, regime), use_container_width=True)
    st.plotly_chart(charts.leverage_chart(data), use_container_width=True)

# ---------------------------------------------------------------- Feed
with tab3:
    v2 = data_loader.get_verdict2(data, market, variant)
    if v2 is None or not v2.get("top_feed_markets"):
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
    v1 = data_loader.get_verdict1(data, market, variant)
    v3 = data_loader.get_verdict3(data, market, variant)

    sensitivities = (v3 or {}).get("sensitivities") or (v1 or {}).get("sensitivities") or []
    if not sensitivities:
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
