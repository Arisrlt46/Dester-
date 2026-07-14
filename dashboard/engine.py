"""On-demand DESTER engine: runs the three-verdict pipeline for any US O&D
pair using the committed aggregate parquet files (data/db1b_local_agg.parquet,
data/db1b_feed_agg.parquet) instead of the raw ~2GB DB1B CSV. Makes DESTER
usable immediately after a clone, with no BTS download required.

Returns a dict shaped like the union of verdict1/2/3.json, for drop-in
compatibility with the existing dashboard chart code. Does not compute the
48-combination sensitivity grid -- point estimate only, for performance
(target: under 10 seconds per market).

Feature reconstruction from the aggregate is ratio-of-sums, not the raw
pipeline's exact passenger-weighted mean-of-ratios -- the documented
approximation from preprocess/aggregate_db1b.py. Aircraft identification is
market-specific (T-100 filtered to the requested carrier + O&D pair), not
the carrier's national dominant type Layer 1/4 use -- falls back to the
national type if the route has no T-100 segment data in-band.
"""

import os

import numpy as np
import pandas as pd

from layer1 import calibration as layer1_calibration
from layer1 import logit as layer1_logit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOCAL_AGG_PATH = os.path.join(DATA_DIR, "db1b_local_agg.parquet")
FEED_AGG_PATH = os.path.join(DATA_DIR, "db1b_feed_agg.parquet")
CATALOG_SUMMARY_PATH = os.path.join(DATA_DIR, "catalog_summary.parquet")

LOGIT_COEFFICIENTS_PATH = os.path.join(PROJECT_ROOT, "layer1", "out", "logit_coefficients_v5_lambda15.json")
T100_CSV_PATH = os.path.join(PROJECT_ROOT, "layer1", "data", "T_T100D_SEGMENT_US_CARRIER_ONLY.csv")
P52_CSV_PATH = os.path.join(PROJECT_ROOT, "layer1", "data", "T_F41SCHEDULE_P52.csv")

HUB_AIRPORTS = ["ATL", "DFW", "ORD", "DEN", "LAX", "CLT", "LAS", "PHX", "SEA", "MSP"]

DB1B_SAMPLE_RATE = 0.10
QUARTERS_PER_YEAR = 4
ANNUALIZATION_FACTOR = round((1 / DB1B_SAMPLE_RATE) * QUARTERS_PER_YEAR)  # 40, matches sizing.annualize_sample

QUARTER_DAYS = 91
YEAR_QUARTERS = 4
DAYS_PER_YEAR = QUARTER_DAYS * YEAR_QUARTERS

DEFAULT_FREQ_DAILY = 2  # generic proposed one-directional daily frequency for a custom market
HUB_DOMINANCE_THRESHOLD = 0.40
AIRCRAFT_SEATS_MIN = 70
AIRCRAFT_SEATS_MAX = 230
FORM41_DOLLAR_UNITS = 1000  # Form 41 Schedule P-5.2 reports dollar figures in thousands

NORMAL_APPROX_MEAN_THRESHOLD = 30.0
FARE_OUTLIER_MIN_USD = 50
FARE_OUTLIER_MAX_USD = 2000

_CACHE = {}


def _market_pair(a, b):
    return "-".join(sorted((a, b)))


def _load_local_agg():
    if "local" not in _CACHE:
        _CACHE["local"] = pd.read_parquet(LOCAL_AGG_PATH)
    return _CACHE["local"]


def _load_feed_agg():
    if "feed" not in _CACHE:
        _CACHE["feed"] = pd.read_parquet(FEED_AGG_PATH)
    return _CACHE["feed"]


def _load_t100():
    if "t100" not in _CACHE:
        _CACHE["t100"] = pd.read_csv(T100_CSV_PATH)
    return _CACHE["t100"]


def _load_p52():
    if "p52" not in _CACHE:
        _CACHE["p52"] = pd.read_csv(P52_CSV_PATH)
    return _CACHE["p52"]


def _load_coefficients():
    if "coefficients" not in _CACHE:
        _CACHE["coefficients"] = layer1_logit.load_coefficients(LOGIT_COEFFICIENTS_PATH)
    return _CACHE["coefficients"]


def _load_t100_features():
    """Cached wrapper around layer1.calibration.load_t100_features, which
    re-reads and re-aggregates the 120MB T-100 CSV from scratch on every
    call -- fine for a single point estimate (run_dester_engine's original
    10-second budget), but the dominant cost by ~2 orders of magnitude when
    called dozens of times per market across a sensitivity-grid precompute.
    Same data every call (the CSV path and filters are constants), so it's
    cached here rather than in the frozen layer1/ module."""
    if "t100_features" not in _CACHE:
        _CACHE["t100_features"] = layer1_calibration.load_t100_features(T100_CSV_PATH)
    return _CACHE["t100_features"]


def _cached_airport_carrier_share(local_df):
    """Same cache rationale as _load_t100_features: this is a national
    groupby over the whole local aggregate, identical for every call in a
    process regardless of which market is being scored, so it's wasteful to
    redo per call across a batch precompute."""
    if "airport_carrier_share" not in _CACHE:
        _CACHE["airport_carrier_share"] = _airport_carrier_share(local_df)
    return _CACHE["airport_carrier_share"]


def _airport_carrier_share(local_df):
    """National OpCarrier passenger share touching each airport, reconstructed
    from the aggregate's own (Origin, Dest, OpCarrier, sum_passengers) --
    mirrors Wave 1's original calibration.py hub_dominance methodology
    (DB1B passenger touches), not Wave 2's T-100-departures substitute."""
    origin_leg = local_df[["Origin", "OpCarrier", "sum_passengers"]].rename(columns={"Origin": "airport"})
    dest_leg = local_df[["Dest", "OpCarrier", "sum_passengers"]].rename(columns={"Dest": "airport"})
    touches = pd.concat([origin_leg, dest_leg], ignore_index=True)

    airport_totals = touches.groupby("airport")["sum_passengers"].sum()
    airport_carrier_totals = touches.groupby(["airport", "OpCarrier"], observed=True)["sum_passengers"].sum()
    return airport_carrier_totals / airport_totals.reindex(airport_carrier_totals.index.get_level_values("airport")).values


def _hub_dominance_lookup(airport, carrier, airport_carrier_share):
    try:
        share = airport_carrier_share.loc[(airport, carrier)]
    except KeyError:
        share = 0.0
    return 1.0 if share >= HUB_DOMINANCE_THRESHOLD else 0.0


def _identify_dominant_carrier(market_local_df):
    nonstop = market_local_df[market_local_df["MktCoupons"] == 1]
    if nonstop.empty:
        nonstop = market_local_df
    by_carrier = nonstop.groupby("RPCarrier")["sum_passengers"].sum()
    return by_carrier.idxmax()


def _build_choice_set(market_local_df, t100_freq_features, airport_carrier_share):
    """One alternative-row per RPCarrier, nonstop-only (matching Layer 1/4's
    own choice-set convention), reconstructed as ratio-of-sums from the
    aggregate."""
    nonstop = market_local_df[market_local_df["MktCoupons"] == 1].copy()
    if nonstop.empty:
        return pd.DataFrame(columns=["market", "carrier", "log_fare", "n_stops", "routing_efficiency", "frequency_weekly", "hub_dominance"])

    nonstop = nonstop.merge(
        t100_freq_features, left_on=["Origin", "Dest", "OpCarrier"],
        right_on=["ORIGIN", "DEST", "CARRIER"], how="left",
    ).drop(columns=["ORIGIN", "DEST", "CARRIER"])
    nonstop["frequency_weekly"] = nonstop["frequency_weekly"].fillna(0.0)

    nonstop["hub_dominance"] = [
        _hub_dominance_lookup(origin, op_carrier, airport_carrier_share)
        for origin, op_carrier in zip(nonstop["Origin"], nonstop["OpCarrier"])
    ]

    rows = []
    for carrier, group in nonstop.groupby("RPCarrier", observed=True):
        pax = group["sum_passengers"]
        total_pax = pax.sum()
        if total_pax <= 0:
            continue
        total_fare_pax = group["sum_fare_x_passengers"].sum()
        total_dist_pax = group["sum_mktdistance_x_passengers"].sum()
        total_nsm_pax = group["sum_nonstopmiles_x_passengers"].sum()
        rows.append(
            {
                "market": "custom",
                "carrier": str(carrier),
                "log_fare": float(np.log(total_fare_pax / total_pax)),
                "n_stops": 0,
                "routing_efficiency": float(total_dist_pax / total_nsm_pax) if total_nsm_pax > 0 else 1.0,
                "frequency_weekly": float(np.average(group["frequency_weekly"], weights=pax)),
                "hub_dominance": float(np.average(group["hub_dominance"], weights=pax)),
            }
        )
    return pd.DataFrame(rows)


def _resolve_aircraft_and_casm(carrier, origin, dest, casm_markup):
    """Market-specific aircraft identification: T-100 filtered to this
    carrier + O&D pair (either direction), seats in [70, 230], most
    departures. Falls back to the carrier's national dominant type in that
    band if the route has no in-band T-100 segment data."""
    t100 = _load_t100()
    t100 = t100[(t100["YEAR"] == layer1_calibration.T100_YEAR) & (t100["MONTH"].isin(layer1_calibration.T100_MONTHS))]

    route_mask = (t100["CARRIER"] == carrier) & (
        ((t100["ORIGIN"] == origin) & (t100["DEST"] == dest)) | ((t100["ORIGIN"] == dest) & (t100["DEST"] == origin))
    )
    route_t100 = t100[route_mask]
    fallback_used = False

    agg = route_t100.groupby("AIRCRAFT_TYPE").agg(departures=("DEPARTURES_PERFORMED", "sum"), seats=("SEATS", "sum"))
    agg = agg[agg["departures"] > 0]
    agg["seats_per_departure"] = agg["seats"] / agg["departures"]
    band = agg[(agg["seats_per_departure"] >= AIRCRAFT_SEATS_MIN) & (agg["seats_per_departure"] <= AIRCRAFT_SEATS_MAX)]

    if band.empty:
        fallback_used = True
        national = t100[t100["CARRIER"] == carrier]
        agg = national.groupby("AIRCRAFT_TYPE").agg(departures=("DEPARTURES_PERFORMED", "sum"), seats=("SEATS", "sum"))
        agg = agg[agg["departures"] > 0]
        agg["seats_per_departure"] = agg["seats"] / agg["departures"]
        band = agg[(agg["seats_per_departure"] >= AIRCRAFT_SEATS_MIN) & (agg["seats_per_departure"] <= AIRCRAFT_SEATS_MAX)]
        if band.empty:
            return None, None, None, fallback_used

    chosen = band.sort_values("departures", ascending=False).iloc[0]
    aircraft_type = int(chosen.name)
    seats_per_departure = float(chosen["seats_per_departure"])

    p52 = _load_p52()
    p52_match = p52[
        (p52["CARRIER"] == carrier) & (p52["YEAR"] == layer1_calibration.T100_YEAR)
        & (p52["QUARTER"] == 2) & (p52["AIRCRAFT_TYPE"] == aircraft_type)
    ]
    opex_usd = float(p52_match["TOT_AIR_OP_EXPENSES"].sum()) * FORM41_DOLLAR_UNITS

    t100_match = t100[(t100["CARRIER"] == carrier) & (t100["AIRCRAFT_TYPE"] == aircraft_type)]
    asms = float((t100_match["SEATS"] * t100_match["DISTANCE"]).sum())
    raw_casm_cents = (opex_usd / asms) * 100 if asms > 0 else None
    casm_cents = raw_casm_cents * casm_markup if raw_casm_cents is not None else None

    return aircraft_type, seats_per_departure, casm_cents, fallback_used


def _expected_boarded_poisson(mean_daily_pax, capacity):
    from scipy.stats import poisson
    cap_int = int(np.floor(capacity))
    if cap_int <= 0:
        return 0.0
    k = np.arange(0, cap_int)
    pmf = poisson.pmf(k, mean_daily_pax)
    partial_sum = float(np.sum(k * pmf))
    tail_prob = float(poisson.sf(cap_int - 1, mean_daily_pax))
    return partial_sum + cap_int * tail_prob


def _expected_boarded_normal(mean_daily_pax, capacity):
    from scipy.stats import norm
    sigma = np.sqrt(mean_daily_pax)
    if sigma == 0:
        return min(mean_daily_pax, capacity)
    z = (mean_daily_pax - capacity) / sigma
    expected_spill = sigma * (z * norm.cdf(z) + norm.pdf(z))
    return mean_daily_pax - expected_spill


def _expected_boardings(mean_daily_pax, seats_per_departure, freq_per_day, recapture):
    capacity = seats_per_departure * freq_per_day
    if mean_daily_pax >= NORMAL_APPROX_MEAN_THRESHOLD:
        expected_boarded_direct = _expected_boarded_normal(mean_daily_pax, capacity)
    else:
        expected_boarded_direct = _expected_boarded_poisson(mean_daily_pax, capacity)
    expected_spill = mean_daily_pax - expected_boarded_direct
    expected_recapture = expected_spill * recapture
    expected_boarded = expected_boarded_direct + expected_recapture
    expected_load_factor = expected_boarded / capacity if capacity > 0 else 0.0
    return {
        "expected_demand": float(mean_daily_pax), "expected_spill": float(expected_spill),
        "expected_recapture": float(expected_recapture), "expected_boarded": float(expected_boarded),
        "expected_load_factor": float(expected_load_factor),
    }


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def _resolve_market_context(origin, dest, carrier, casm_markup):
    """Everything about a market that does NOT depend on (uplift, recapture,
    alpha): choice-set/logit prediction, aircraft/CASM resolution, and the
    full feed-attribution loop (share, phi_a, mileage_fare are all pure
    functions of the aggregate, independent of the sizing-grid params).

    Split out from run_dester_engine so a sensitivity-grid precompute can
    resolve this once per market and cheaply re-score 48 (uplift, recapture,
    alpha) combinations against it, instead of redoing this -- by far the
    most expensive part of a call, dominated by the feed loop's per-endpoint
    DataFrame scans -- on every grid point. run_dester_engine itself still
    returns byte-for-byte the same output as before this split; only the
    internal call path changed."""
    local_df = _load_local_agg()

    market_mask = ((local_df["Origin"] == origin) & (local_df["Dest"] == dest)) | (
        (local_df["Origin"] == dest) & (local_df["Dest"] == origin)
    )
    market_local_df = local_df[market_mask]
    if market_local_df.empty:
        return {"error": f"No data for market {origin}-{dest}"}

    if carrier is None:
        carrier = _identify_dominant_carrier(market_local_df)
    carrier = carrier.upper()

    # Matches the committed pipeline's *scope* (all MktCoupons, not nonstop-only) --
    # but not its exact statistic. verdict1_atl_sat.py computes a simple,
    # unweighted mean of raw per-row MktFare/MktDistance; the aggregate only
    # retains passenger-weighted sums (sum_fare_x_passengers etc.), not a plain
    # unweighted fare sum, so an exact match isn't reconstructable from this
    # schema without modifying the (frozen) preprocessing script. This is a
    # real, documented source of divergence from the committed figures, not
    # an approximation I can tighten further here.
    mean_fare = float(market_local_df["sum_fare_x_passengers"].sum() / max(market_local_df["sum_passengers"].sum(), 1e-9))
    distance_miles = float(market_local_df["sum_mktdistance_x_passengers"].sum() / max(market_local_df["sum_passengers"].sum(), 1e-9))

    t100_freq_features = _load_t100_features()
    airport_carrier_share = _cached_airport_carrier_share(local_df)
    choice_set = _build_choice_set(market_local_df, t100_freq_features, airport_carrier_share)

    if choice_set.empty or carrier not in set(choice_set["carrier"]):
        return {"error": f"No nonstop choice-set data for {carrier} on {origin}-{dest}"}

    coefficients = _load_coefficients()
    predicted = layer1_logit.predict_shares(choice_set, coefficients)
    predicted_share = float(predicted[choice_set["carrier"] == carrier].iloc[0])

    base_pax = float(market_local_df["sum_passengers"].sum()) * ANNUALIZATION_FACTOR

    aircraft_type, seats_per_departure, casm_cents, aircraft_fallback_used = _resolve_aircraft_and_casm(carrier, origin, dest, casm_markup)
    if casm_cents is None:
        return {"error": f"No aircraft/CASM data available for {carrier} in the {AIRCRAFT_SEATS_MIN}-{AIRCRAFT_SEATS_MAX} seat band"}

    # ---------------- Verdict 2: feed ----------------
    feed_df = _load_feed_agg()
    hub, spoke = None, None
    if dest in HUB_AIRPORTS:
        hub, spoke = dest, origin
    elif origin in HUB_AIRPORTS:
        hub, spoke = origin, dest

    feed_market_df = pd.DataFrame()
    if hub is not None:
        feed_market_df = feed_df[(feed_df["hub"] == hub) & (feed_df["spoke"] == spoke)]

    feed_pax_annual = 0.0
    feed_revenue_mileage_annual = 0.0
    feed_revenue_shapley_annual = 0.0
    negative_phi_a_count = 0
    fallback_v_b_count = 0
    total_feed_rows = 0

    if not feed_market_df.empty:
        # Dominant carrier's observed share of each (spoke, beyond_endpoint) submarket,
        # pooled from the local aggregate (any routing), matching Layer 2's convention.
        endpoints = sorted(feed_market_df["beyond_endpoint"].unique())
        v_a = mean_fare  # market's own nonstop mean fare, standalone coalition value

        # Both of these were originally one boolean mask over the full
        # 416K-row local_df PER endpoint (~85 endpoints/market on average,
        # ~90ms each) -- the dominant cost of a call by ~2 orders of
        # magnitude. Vectorized here into one filter + groupby each,
        # indexed by "other" endpoint, then looked up per beyond below.
        # Numerically identical to the original per-endpoint masks --
        # verified against reference outputs captured before this change.
        spoke_mask = (local_df["Origin"] == spoke) | (local_df["Dest"] == spoke)
        spoke_df = local_df[spoke_mask]
        spoke_other = np.where(spoke_df["Origin"] == spoke, spoke_df["Dest"], spoke_df["Origin"])
        total_sub_pax_by_beyond = spoke_df.groupby(spoke_other)["sum_passengers"].sum()
        dominant_sub_pax_by_beyond = spoke_df[spoke_df["OpCarrier"] == carrier].groupby(
            spoke_other[spoke_df["OpCarrier"].values == carrier]
        )["sum_passengers"].sum()
        share_by_beyond = (dominant_sub_pax_by_beyond / total_sub_pax_by_beyond).reindex(total_sub_pax_by_beyond.index).fillna(0.0)

        hub_nonstop_mask = (local_df["MktCoupons"] == 1) & ((local_df["Origin"] == hub) | (local_df["Dest"] == hub))
        hub_df = local_df[hub_nonstop_mask]
        hub_other = np.where(hub_df["Origin"] == hub, hub_df["Dest"], hub_df["Origin"])
        vb_pax_by_beyond = hub_df.groupby(hub_other)["sum_passengers"].sum()
        vb_farepax_by_beyond = hub_df.groupby(hub_other)["sum_fare_x_passengers"].sum()
        v_b_by_beyond = (vb_farepax_by_beyond / vb_pax_by_beyond)[vb_pax_by_beyond > 0]

        for beyond in endpoints:
            total_sub_pax = float(total_sub_pax_by_beyond.get(beyond, 0.0))
            share = float(share_by_beyond.get(beyond, 0.0)) if total_sub_pax > 0 else 0.0

            # v(B): standalone nonstop mean fare on (hub, beyond) -- if unavailable, fall back to mileage.
            v_b = v_b_by_beyond.get(beyond)
            v_b = float(v_b) if v_b is not None and not pd.isna(v_b) else None
            has_v_b = v_b is not None and FARE_OUTLIER_MIN_USD <= v_b <= FARE_OUTLIER_MAX_USD

            for direction in feed_market_df.loc[feed_market_df["beyond_endpoint"] == beyond, "direction"].unique():
                rows = feed_market_df[(feed_market_df["beyond_endpoint"] == beyond) & (feed_market_df["direction"] == direction)]
                total_feed_rows += int(rows["sample_MktID_count"].sum())

                itin_pax = float(rows["sum_passengers"].sum())
                itin_fare_pax = float(rows["sum_fare_x_passengers"].sum())
                itin_dist_pax = float(rows["sum_mktdistance_x_passengers"].sum())
                itin_nsm_pax = float(rows["sum_nonstopmiles_x_passengers"].sum())
                if itin_pax <= 0 or itin_nsm_pax <= 0:
                    continue

                mkt_fare = itin_fare_pax / itin_pax
                total_miles = itin_nsm_pax / itin_pax
                mileage_fare = mkt_fare * (distance_miles / total_miles) if total_miles > 0 else 0.0

                if has_v_b:
                    v_ab = mkt_fare
                    phi_a = 0.5 * (v_a + (v_ab - v_b))
                    if phi_a < 0:
                        negative_phi_a_count += 1
                else:
                    phi_a = mileage_fare
                    fallback_v_b_count += 1

                delta_feed_pax = itin_pax * share
                feed_pax_annual += delta_feed_pax * ANNUALIZATION_FACTOR
                feed_revenue_mileage_annual += delta_feed_pax * mileage_fare * ANNUALIZATION_FACTOR
                feed_revenue_shapley_annual += delta_feed_pax * phi_a * ANNUALIZATION_FACTOR

    market_label = _market_pair(origin, dest)

    return {
        "market": market_label,
        "origin": origin,
        "dest": dest,
        "carrier": carrier,
        "mean_fare": mean_fare,
        "distance_miles": distance_miles,
        "base_pax": base_pax,
        "predicted_share": predicted_share,
        "aircraft_type": aircraft_type,
        "seats_per_departure": seats_per_departure,
        "casm_cents": casm_cents,
        "aircraft_fallback_used": aircraft_fallback_used,
        "hub": hub,
        "spoke": spoke,
        "feed_pax_annual": feed_pax_annual,
        "feed_revenue_mileage_annual": feed_revenue_mileage_annual,
        "feed_revenue_shapley_annual": feed_revenue_shapley_annual,
        "negative_phi_a_count": negative_phi_a_count,
        "fallback_v_b_count": fallback_v_b_count,
        "total_feed_rows": total_feed_rows,
    }


def _score_grid_point(context, uplift, recapture, alpha):
    """Cheap arithmetic-only scoring of one (uplift, recapture, alpha) grid
    point against an already-resolved market context. No DataFrame scans --
    safe to call dozens of times per market. Note: alpha has no effect on
    this engine's output (it never implements the real pipeline's S-curve;
    accepted only for signature parity with run_dester_engine) -- a
    pre-existing property of the simplified on-demand engine, not something
    this split changed."""
    base_pax = context["base_pax"]
    predicted_share = context["predicted_share"]
    seats_per_departure = context["seats_per_departure"]
    mean_fare = context["mean_fare"]
    distance_miles = context["distance_miles"]
    casm_cents = context["casm_cents"]

    sized_pax = base_pax * (1 + uplift)
    mean_daily_pax = sized_pax * predicted_share / DAYS_PER_YEAR
    boardings = _expected_boardings(mean_daily_pax, seats_per_departure, DEFAULT_FREQ_DAILY, recapture)

    capacity_seats_annual = seats_per_departure * DEFAULT_FREQ_DAILY * DAYS_PER_YEAR
    asms = capacity_seats_annual * distance_miles
    full_capacity_revenue = capacity_seats_annual * mean_fare
    cost = asms * (casm_cents / 100.0)
    breakeven_lf = cost / full_capacity_revenue if full_capacity_revenue > 0 else float("inf")

    expected_annual_boarded = boardings["expected_boarded"] * DAYS_PER_YEAR
    revenue = expected_annual_boarded * mean_fare
    contribution = revenue - cost
    verdict1_result = _verdict_from_contribution(contribution)

    local_contribution = contribution
    feed_revenue_mileage_annual = context["feed_revenue_mileage_annual"]
    feed_revenue_shapley_annual = context["feed_revenue_shapley_annual"]
    feed_pax_annual = context["feed_pax_annual"]

    total_contribution_mileage = local_contribution + feed_revenue_mileage_annual
    total_contribution_shapley = local_contribution + feed_revenue_shapley_annual
    verdict_mileage = _verdict_from_contribution(total_contribution_mileage)
    verdict_shapley = _verdict_from_contribution(total_contribution_shapley)

    total_revenue_local = revenue
    feed_share_of_total_revenue = (
        feed_revenue_mileage_annual / (total_revenue_local + feed_revenue_mileage_annual)
        if (total_revenue_local + feed_revenue_mileage_annual) > 0 else 0.0
    )
    feed_share_of_total_pax = (
        feed_pax_annual / (expected_annual_boarded + feed_pax_annual) if (expected_annual_boarded + feed_pax_annual) > 0 else 0.0
    )

    attribution_delta_usd = total_contribution_shapley - total_contribution_mileage
    attribution_leverage_pct = (
        abs(attribution_delta_usd) / abs(total_contribution_mileage) if total_contribution_mileage != 0 else float("inf")
    )
    verdict_flipped = verdict_mileage != verdict_shapley

    return {
        "market": context["market"],
        "carrier": context["carrier"],
        "verdict": verdict1_result,
        "robust": None,
        "expected_load_factor": boardings["expected_load_factor"],
        "breakeven_load_factor": breakeven_lf,
        "revenue_annual_usd": revenue,
        "cost_annual_usd": cost,
        "contribution_annual_usd": contribution,
        "delta_e175_casm_cents": casm_cents,
        "aircraft_type": context["aircraft_type"],
        "aircraft_fallback_used": context["aircraft_fallback_used"],
        "sizing": {"base_pax": base_pax, "uplift": uplift, "sized_pax": sized_pax},
        "predicted_delta_share": predicted_share,
        "sensitivities": [],
        "local_contribution_annual_usd": local_contribution,
        "feed_contribution_annual_usd": feed_revenue_mileage_annual,
        "total_contribution_annual_usd": total_contribution_mileage,
        "feed_share_of_total_revenue": feed_share_of_total_revenue,
        "feed_share_of_total_pax": feed_share_of_total_pax,
        "top_feed_markets": [],
        "attribution_regimes": [
            {
                "regime": "mileage", "feed_revenue_annual_usd": feed_revenue_mileage_annual,
                "total_revenue_annual_usd": total_revenue_local + feed_revenue_mileage_annual,
                "total_contribution_annual_usd": total_contribution_mileage,
                "expected_load_factor": boardings["expected_load_factor"], "breakeven_load_factor": breakeven_lf,
                "verdict": verdict_mileage,
            },
            {
                "regime": "shapley", "feed_revenue_annual_usd": feed_revenue_shapley_annual,
                "total_revenue_annual_usd": total_revenue_local + feed_revenue_shapley_annual,
                "total_contribution_annual_usd": total_contribution_shapley,
                "expected_load_factor": boardings["expected_load_factor"], "breakeven_load_factor": breakeven_lf,
                "verdict": verdict_shapley,
            },
        ],
        "attribution_delta_usd": attribution_delta_usd,
        "attribution_leverage_pct": attribution_leverage_pct,
        "verdict_flipped": verdict_flipped,
        "negative_phi_a_count": context["negative_phi_a_count"],
        "feed_v_b_fallback_count": context["fallback_v_b_count"],
        "total_feed_itineraries_sampled": context["total_feed_rows"],
        "is_hub_spoke_pair": context["hub"] is not None,
    }


def run_dester_engine(origin, dest, carrier=None, uplift=0.15, recapture=0.15, alpha=1.6, casm_markup=1.12, shrinkage_lambda=15.0):
    origin, dest = origin.upper(), dest.upper()
    context = _resolve_market_context(origin, dest, carrier, casm_markup)
    if context.get("error"):
        return context
    return _score_grid_point(context, uplift, recapture, alpha)


def load_catalog_summary():
    """Reads the batch-precomputed per-market sensitivity summary (one row
    per Catalog market: headline verdicts, robustness, attribution leverage)
    written by preprocess/precompute_sensitivities.py. Returns None if the
    precompute hasn't been run yet -- callers should fall back to the plain
    screener columns in that case."""
    if not os.path.exists(CATALOG_SUMMARY_PATH):
        return None
    return pd.read_parquet(CATALOG_SUMMARY_PATH)
