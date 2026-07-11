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


def run_dester_engine(origin, dest, carrier=None, uplift=0.15, recapture=0.15, alpha=1.6, casm_markup=1.12, shrinkage_lambda=15.0):
    origin, dest = origin.upper(), dest.upper()
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

    t100_freq_features = layer1_calibration.load_t100_features(T100_CSV_PATH)
    airport_carrier_share = _airport_carrier_share(local_df)
    choice_set = _build_choice_set(market_local_df, t100_freq_features, airport_carrier_share)

    if choice_set.empty or carrier not in set(choice_set["carrier"]):
        return {"error": f"No nonstop choice-set data for {carrier} on {origin}-{dest}"}

    coefficients = _load_coefficients()
    predicted = layer1_logit.predict_shares(choice_set, coefficients)
    predicted_share = float(predicted[choice_set["carrier"] == carrier].iloc[0])

    base_pax = float(market_local_df["sum_passengers"].sum()) * ANNUALIZATION_FACTOR
    sized_pax = base_pax * (1 + uplift)

    aircraft_type, seats_per_departure, casm_cents, aircraft_fallback_used = _resolve_aircraft_and_casm(carrier, origin, dest, casm_markup)
    if casm_cents is None:
        return {"error": f"No aircraft/CASM data available for {carrier} in the {AIRCRAFT_SEATS_MIN}-{AIRCRAFT_SEATS_MAX} seat band"}

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

        for beyond in endpoints:
            submarket = _market_pair(spoke, beyond)
            sub_mask = ((local_df["Origin"] == spoke) & (local_df["Dest"] == beyond)) | (
                (local_df["Origin"] == beyond) & (local_df["Dest"] == spoke)
            )
            sub_df = local_df[sub_mask]
            total_sub_pax = float(sub_df["sum_passengers"].sum())
            dominant_sub_pax = float(sub_df.loc[sub_df["OpCarrier"] == carrier, "sum_passengers"].sum())
            share = (dominant_sub_pax / total_sub_pax) if total_sub_pax > 0 else 0.0

            # v(B): standalone nonstop mean fare on (hub, beyond) -- if unavailable, fall back to mileage.
            vb_mask = ((local_df["Origin"] == hub) & (local_df["Dest"] == beyond) & (local_df["MktCoupons"] == 1)) | (
                (local_df["Origin"] == beyond) & (local_df["Dest"] == hub) & (local_df["MktCoupons"] == 1)
            )
            vb_df = local_df[vb_mask]
            vb_pax = float(vb_df["sum_passengers"].sum())
            v_b = float(vb_df["sum_fare_x_passengers"].sum() / vb_pax) if vb_pax > 0 else None
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

    local_contribution = contribution
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

    market_label = _market_pair(origin, dest)

    return {
        "market": market_label,
        "carrier": carrier,
        "verdict": verdict1_result,
        "robust": None,
        "expected_load_factor": boardings["expected_load_factor"],
        "breakeven_load_factor": breakeven_lf,
        "revenue_annual_usd": revenue,
        "cost_annual_usd": cost,
        "contribution_annual_usd": contribution,
        "delta_e175_casm_cents": casm_cents,
        "aircraft_type": aircraft_type,
        "aircraft_fallback_used": aircraft_fallback_used,
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
        "negative_phi_a_count": negative_phi_a_count,
        "feed_v_b_fallback_count": fallback_v_b_count,
        "total_feed_itineraries_sampled": total_feed_rows,
        "is_hub_spoke_pair": hub is not None,
    }
