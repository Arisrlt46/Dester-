"""Layer 4 MIA-SEA, Module 3: Verdict 3 on MIA-SEA.

Mirrors layer4/verdict3_atl_sat.py's point-estimate logic exactly,
substituting config_mia_sea for config. Imports layer3.standalone_fares,
attribution, and pnl_by_regime unchanged -- all are already generic despite
their AUS-SLC names. standalone_fares.standalone_fares_slc_beyond is
hardcoded to the SLC substring internally, so this module reimplements its
exact logic generalized to config.SPOKE.

Also includes run_verdict3_sensitivities_mia_sea, the regime-aware
48-combination x 2-regime (96-row) sensitivity sweep -- mirroring
layer4/iteration5/verdict3_v5_sensitivities.py, but built in from the start
here (as its own function) rather than retrofitted after the fact, since
MIA-SEA never has a "point-estimate-only" verdict3 stage the way ATL-SAT's
Wave 2 originally did.

Uses the contribution-based verdict rule (go iff total_contribution_annual_usd
>= 0), not the load-factor rule Verdict 1 uses -- load factor is identical
across attribution regimes by construction, so an LF-based rule could never
flip.

MktID is the true per-directional-row key in DB1BMarket. The join between
attribution output and feed economics below uses MktID, never ItinID.
"""

import itertools
import os

import pandas as pd

from layer1 import pnl as layer1_pnl
from layer1 import scurve as layer1_scurve
from layer1 import sizing as layer1_sizing
from layer1 import spill as layer1_spill
from layer3 import attribution as layer3_attribution
from layer3 import pnl_by_regime as layer3_pnl_by_regime
from layer3 import standalone_fares as layer3_standalone_fares
from layer4.mia_sea import config_mia_sea as config
from layer4.mia_sea import verdict1_mia_sea

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "out")
MIA_SEA_ATTRIBUTION_PATH = os.path.join(LAYER4_OUT_DIR, "mia_sea_attribution.parquet")

REGIMES = ["mileage", "shapley"]

DB1B_CHUNK_SIZE = 200_000
PROGRESS_EVERY_N_CHUNKS = 10

FARE_OUTLIER_MIN_USD = 50
FARE_OUTLIER_MAX_USD = 2000

NONSTOP_MKT_COUPONS = 1
DB1B_USECOLS = ["Origin", "Dest", "MktCoupons", "BulkFare", "MktFare"]


def _clean_chunk(chunk):
    chunk = chunk.dropna(subset=["MktFare"])
    chunk = chunk[chunk["MktFare"] > 0]
    if "BulkFare" in chunk.columns:
        chunk = chunk[chunk["BulkFare"] != 1]
    return chunk


def standalone_fares_spoke_beyond(db1b_csv_path, endpoints):
    """Generalization of Layer 3's standalone_fares_slc_beyond, keyed on
    config.SPOKE instead of the hardcoded SLC."""
    target_market_to_endpoint = {"-".join(sorted((config.SPOKE, e))): e for e in endpoints}

    fare_sums = {e: 0.0 for e in endpoints}
    counts = {e: 0 for e in endpoints}

    reader = pd.read_csv(db1b_csv_path, usecols=DB1B_USECOLS, chunksize=DB1B_CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, start=1):
        chunk = _clean_chunk(chunk)
        chunk = chunk[chunk["MktCoupons"] == NONSTOP_MKT_COUPONS]
        market = ["-".join(sorted((o, d))) for o, d in zip(chunk["Origin"], chunk["Dest"])]
        chunk = chunk.assign(market=market)
        chunk = chunk[chunk["market"].isin(target_market_to_endpoint)]

        for market_key, group in chunk.groupby("market"):
            endpoint = target_market_to_endpoint[market_key]
            fare_sums[endpoint] += float(group["MktFare"].sum())
            counts[endpoint] += len(group)

        if i % PROGRESS_EVERY_N_CHUNKS == 0:
            print(f"  ...processed {i} chunks (standalone fare pass)")

    rows = []
    for endpoint in endpoints:
        n = counts[endpoint]
        mean_fare = (fare_sums[endpoint] / n) if n > 0 else float("nan")
        flagged = n == 0 or (n > 0 and (mean_fare < FARE_OUTLIER_MIN_USD or mean_fare > FARE_OUTLIER_MAX_USD))
        rows.append({"beyond_endpoint": endpoint, "mean_standalone_fare": mean_fare, "n_observations": n, "flagged": flagged})
    return pd.DataFrame(rows)


def _verdict_from_contribution(total_contribution):
    return "go" if total_contribution >= 0 else "no_go"


def run_verdict3_mia_sea(
    db1b_csv_path, mia_sea_local_path, feed_econ_df, local_pax_annual, local_revenue_annual,
    feed_pax_annual, seats_per_departure, casm_cents, distance_miles, breakeven_load_factor,
):
    print("Computing MIA-SEA standalone coalition value v(A)...")
    v_a = layer3_standalone_fares.standalone_fare_aus_slc(mia_sea_local_path)
    print(f"  v(A) MIA-SEA standalone nonstop fare: ${v_a:.2f}")

    endpoints = sorted(feed_econ_df["beyond_endpoint"].unique())
    standalone_df = standalone_fares_spoke_beyond(db1b_csv_path, endpoints)

    flagged = standalone_df[standalone_df["flagged"]]
    if len(flagged):
        print(f"  {len(flagged)} endpoint(s) flagged (zero observations or fare outlier):")
        for _, row in flagged.iterrows():
            print(f"    {row['beyond_endpoint']}: n={row['n_observations']}, mean_fare={row['mean_standalone_fare']}")

    print("Computing mileage and Shapley attribution per feed itinerary...")
    attribution_df = layer3_attribution.attribute_all(feed_econ_df, standalone_df, v_a)
    os.makedirs(LAYER4_OUT_DIR, exist_ok=True)
    attribution_df.to_parquet(MIA_SEA_ATTRIBUTION_PATH, engine="pyarrow", index=False)
    print(f"Wrote {MIA_SEA_ATTRIBUTION_PATH}")

    negative_phi_a_count = int(attribution_df["phi_A_negative"].sum())
    valid_delta = attribution_df["delta"].dropna()
    mean_delta = float(valid_delta.mean()) if len(valid_delta) else float("nan")
    median_delta = float(valid_delta.median()) if len(valid_delta) else float("nan")

    assert attribution_df["MktID"].is_unique, "MktID must be the unique per-row key before joining"
    joined = feed_econ_df.merge(attribution_df[["MktID", "phi_A", "aus_slc_fare_mileage"]], on="MktID", how="left")
    joined["phi_A_filled"] = joined["phi_A"].fillna(joined["aus_slc_fare_mileage"])

    feed_revenue_mileage_sample = float((joined["delta_feed_passengers"] * joined["aus_slc_fare_mileage"]).sum())
    feed_revenue_shapley_sample = float((joined["delta_feed_passengers"] * joined["phi_A_filled"]).sum())

    feed_revenue_by_regime_annual = {
        "mileage": layer1_sizing.annualize_sample(feed_revenue_mileage_sample),
        "shapley": layer1_sizing.annualize_sample(feed_revenue_shapley_sample),
    }

    regime_pnls = layer3_pnl_by_regime.pnl_by_regime(
        local_pax_annual, local_revenue_annual, feed_pax_annual, feed_revenue_by_regime_annual,
        seats_per_departure, config.PROPOSED_FREQ_DAILY, config.QUARTER_DAYS, casm_cents, distance_miles,
    )

    attribution_regimes = []
    for regime in REGIMES:
        pnl_result = regime_pnls[regime]
        attribution_regimes.append(
            {
                "regime": regime,
                "feed_revenue_annual_usd": feed_revenue_by_regime_annual[regime],
                "total_revenue_annual_usd": pnl_result["total_revenue"],
                "total_contribution_annual_usd": pnl_result["total_contribution"],
                "expected_load_factor": pnl_result["total_load_factor"],
                "breakeven_load_factor": breakeven_load_factor,
                "verdict": _verdict_from_contribution(pnl_result["total_contribution"]),
            }
        )

    contribution_mileage = regime_pnls["mileage"]["total_contribution"]
    contribution_shapley = regime_pnls["shapley"]["total_contribution"]
    attribution_delta_usd = contribution_shapley - contribution_mileage
    attribution_leverage_pct = (
        abs(attribution_delta_usd) / abs(contribution_mileage) if contribution_mileage != 0 else float("inf")
    )
    verdict_flipped = attribution_regimes[0]["verdict"] != attribution_regimes[1]["verdict"]

    verdict3_output = {
        "market": config.MARKET_PAIR,
        "carrier": config.DOMINANT_CARRIER,
        "attribution_regimes": attribution_regimes,
        "attribution_delta_usd": attribution_delta_usd,
        "attribution_leverage_pct": attribution_leverage_pct,
        "verdict_flipped": verdict_flipped,
        "negative_phi_a_count": negative_phi_a_count,
        "mean_delta": mean_delta,
        "median_delta": median_delta,
    }

    sensitivities_context = {
        "feed_econ_df": feed_econ_df,
        "feed_pax_annual": feed_pax_annual,
        "feed_revenue_by_regime_annual": feed_revenue_by_regime_annual,
    }
    return verdict3_output, sensitivities_context


def run_verdict3_sensitivities_mia_sea(
    base_pax, predicted_delta_share, seats_per_departure, casm_cents, mean_fare, distance_miles,
    feed_pax_annual, feed_revenue_by_regime_annual,
):
    """Regime-aware 48-combination x 2-regime (96-row) sensitivity sweep --
    mirrors layer4/iteration5/verdict3_v5_sensitivities.py's main() logic.
    Feed revenue is grid-invariant (feed is purely observational, per Layer
    2/3's own design), so only the local side re-runs per grid point."""
    sensitivities = []
    for uplift, recapture, alpha in itertools.product(
        layer1_sizing.UPLIFT_SENSITIVITY_VALUES, layer1_spill.RECAPTURE_SENSITIVITY_VALUES, layer1_scurve.ALPHA_SENSITIVITY_VALUES
    ):
        _, boardings, pnl_result, _ = verdict1_mia_sea._run_scenario(
            base_pax, predicted_delta_share, uplift, recapture, seats_per_departure, casm_cents, mean_fare, distance_miles
        )
        days_per_year = config.QUARTER_DAYS * layer1_pnl.YEAR_QUARTERS
        sens_local_pax = boardings["expected_boarded"] * days_per_year
        sens_local_revenue = pnl_result["revenue"]

        for regime in REGIMES:
            sens_pnl = layer3_pnl_by_regime.pnl_by_regime(
                sens_local_pax, sens_local_revenue, feed_pax_annual, {regime: feed_revenue_by_regime_annual[regime]},
                seats_per_departure, config.PROPOSED_FREQ_DAILY, config.QUARTER_DAYS,
                casm_cents, distance_miles,
            )[regime]
            sensitivities.append(
                {
                    "uplift": uplift,
                    "recapture": recapture,
                    "alpha": alpha,
                    "regime": regime,
                    "verdict": _verdict_from_contribution(sens_pnl["total_contribution"]),
                    "contribution": sens_pnl["total_contribution"],
                }
            )
    return sensitivities
