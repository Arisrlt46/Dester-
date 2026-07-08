"""Layer 3, Module 2: mileage vs. Shapley attribution per feed itinerary.

Two-player Shapley on the coalition {A = AUS-SLC, B = SLC-beyond}. The
two-player formula is exact:
    phi_A = 0.5 * (v(A) + (v(A,B) - v(B)))
    phi_B = 0.5 * (v(B) + (v(A,B) - v(A)))
so phi_A + phi_B == v(A,B) always, by construction.

Negative phi_A values are reported honestly, not floored -- this can happen
when the connecting fare is unusually low relative to the sum of standalone
fares (distressed inventory, promotional pricing). Flooring would hide a
real economic phenomenon.
"""

import numpy as np
import pandas as pd

AUS_SLC_MILES = 1085

SHAPLEY_SUM_TOLERANCE = 1e-6


def mileage_attribution(feed_itineraries_df, aus_slc_miles=AUS_SLC_MILES):
    return feed_itineraries_df["MktFare"] * (aus_slc_miles / feed_itineraries_df["NonStopMiles"])


def shapley_attribution(feed_itineraries_df, standalone_fares_df, v_a):
    merged = feed_itineraries_df.reset_index(drop=True).merge(
        standalone_fares_df[["beyond_endpoint", "mean_standalone_fare"]], on="beyond_endpoint", how="left"
    )
    v_b = merged["mean_standalone_fare"]
    v_ab = merged["MktFare"]

    phi_a = 0.5 * (v_a + (v_ab - v_b))
    phi_b = 0.5 * (v_b + (v_ab - v_a))

    valid = v_b.notna()
    if valid.any():
        assert np.allclose((phi_a + phi_b)[valid], v_ab[valid], atol=SHAPLEY_SUM_TOLERANCE), (
            "Shapley split does not sum to v(A,B); phi_A + phi_B must equal the connecting fare exactly."
        )

    phi_a_negative = phi_a < 0

    return pd.DataFrame({"phi_A": phi_a, "phi_B": phi_b, "phi_A_negative": phi_a_negative})


def attribute_all(feed_itineraries_df, standalone_fares_df, v_a):
    """Combines mileage and Shapley attribution, plus the per-itinerary delta."""
    df = feed_itineraries_df.reset_index(drop=True).copy()
    df["aus_slc_fare_mileage"] = mileage_attribution(df).values

    shapley_df = shapley_attribution(df, standalone_fares_df, v_a)
    df["phi_A"] = shapley_df["phi_A"].values
    df["phi_B"] = shapley_df["phi_B"].values
    df["phi_A_negative"] = shapley_df["phi_A_negative"].values

    df["delta"] = df["phi_A"] - df["aus_slc_fare_mileage"]
    return df
