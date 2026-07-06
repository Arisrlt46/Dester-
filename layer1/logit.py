"""Layer 1 Wave 1, Module 2: multinomial logit carrier-share model.

Fits statsmodels.discrete.discrete_model.MNLogit with y = carrier (the
categorical alternative label) and X = the itinerary-level features below.
MNLogit natively fits one intercept + one slope set per non-base carrier
category; the intercept serves as that carrier's fixed effect ("carrier_fe").
Coefficients are flattened to a JSON-serializable dict keyed "feature::carrier"
so they can be saved to disk and reused by predict_shares without holding a
live statsmodels results object.
"""

import json

import numpy as np
import pandas as pd
import statsmodels.api as sm

DEFAULT_FEATURES = [
    "log_fare",
    "n_stops",
    "routing_efficiency",
    "frequency_weekly",
    "seats_per_departure",
    "hub_dominance",
]

INTERCEPT_KEY = "carrier_fe"

FIT_METHOD = "lbfgs"
FIT_MAXITER = 1000


def fit(train_df, features=None):
    """Fit MNLogit with y=carrier, X=features (+intercept). Returns a coefficients dict.

    Features are standardized before fitting (statsmodels' default Newton solver
    diverges to NaN on this many categories with unscaled features like
    seats_per_departure vs. hub_dominance); the fitted coefficients are then
    transformed back to raw-feature scale so predict_shares and the saved JSON
    operate on the features as-is.
    """
    if features is None:
        features = DEFAULT_FEATURES

    df = train_df.dropna(subset=list(features) + ["carrier"]).copy()
    carrier_codes, carrier_categories = pd.factorize(df["carrier"], sort=True)

    raw_X = df[list(features)].astype(float)
    means = raw_X.mean()
    stds = raw_X.std().replace(0, 1.0)
    standardized_X = sm.add_constant((raw_X - means) / stds, has_constant="add")

    model = sm.MNLogit(carrier_codes, standardized_X)
    result = model.fit(method=FIT_METHOD, maxiter=FIT_MAXITER, disp=0)
    if not result.mle_retvals.get("converged", False):
        print("  WARNING: MNLogit fit did not converge within maxiter; coefficients may be unstable")

    standardized_params = result.params
    params = pd.DataFrame(index=["const"] + list(features), columns=standardized_params.columns, dtype=float)
    for col in standardized_params.columns:
        std_const = standardized_params.loc["const", col]
        std_slopes = standardized_params.loc[features, col]
        raw_slopes = std_slopes / stds
        raw_const = std_const - (std_slopes * means / stds).sum()
        params.loc["const", col] = raw_const
        params.loc[features, col] = raw_slopes

    base_carrier = str(carrier_categories[0])
    coefficients = {
        "_features": list(features),
        "_base_carrier": base_carrier,
        "_carriers": [str(c) for c in carrier_categories],
    }

    for row_name in [INTERCEPT_KEY] + list(features):
        coefficients[f"{row_name}::{base_carrier}"] = 0.0

    for col in params.columns:
        carrier_name = str(carrier_categories[int(col) + 1])
        for row_name in params.index:
            key_feature = INTERCEPT_KEY if row_name == "const" else row_name
            coefficients[f"{key_feature}::{carrier_name}"] = float(params.loc[row_name, col])

    return coefficients


def _utility(row, carrier, coefficients, features):
    utility = coefficients.get(f"{INTERCEPT_KEY}::{carrier}", 0.0)
    for feat in features:
        utility += coefficients.get(f"{feat}::{carrier}", 0.0) * row[feat]
    return utility


def predict_shares(itineraries_df, coefficients):
    """Predicted share per itinerary-alternative within its market (softmax over utility)."""
    features = coefficients["_features"]
    df = itineraries_df.copy()

    df["_utility"] = [
        _utility(row, row["carrier"], coefficients, features)
        for _, row in df[features + ["carrier"]].iterrows()
    ]

    def _softmax(group):
        exp_u = np.exp(group - group.max())
        return exp_u / exp_u.sum()

    predicted = df.groupby("market")["_utility"].transform(_softmax)
    predicted.name = "predicted_share"
    return predicted


def save_coefficients(coefficients, path):
    with open(path, "w") as f:
        json.dump(coefficients, f, indent=2)


def load_coefficients(path):
    with open(path) as f:
        return json.load(f)
