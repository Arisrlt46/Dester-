"""Layer 1 Wave 2, Module 6: stochastic spill and recapture.

Daily demand isn't deterministic. Some days demand exceeds seat capacity and
excess passengers spill; some of those spilled passengers buy another Delta
ticket in the same market anyway (recapture). Expectations are computed in
closed form: Poisson for small means, Normal (mean-preserving,
variance-preserving Poisson approximation) once the mean is large enough that
the two distributions are indistinguishable in practice.
"""

import numpy as np
from scipy.stats import norm, poisson

DEFAULT_RECAPTURE_RATE = 0.15
RECAPTURE_SENSITIVITY_VALUES = [0.10, 0.15, 0.20, 0.30]

NORMAL_APPROX_MEAN_THRESHOLD = 30.0


def _expected_boarded_direct_poisson(mean_daily_pax, capacity):
    cap_int = int(np.floor(capacity))
    if cap_int <= 0:
        return 0.0
    k = np.arange(0, cap_int)
    pmf = poisson.pmf(k, mean_daily_pax)
    partial_sum = float(np.sum(k * pmf))
    tail_prob = float(poisson.sf(cap_int - 1, mean_daily_pax))
    return partial_sum + cap_int * tail_prob


def _expected_boarded_direct_normal(mean_daily_pax, capacity):
    sigma = np.sqrt(mean_daily_pax)
    if sigma == 0:
        return min(mean_daily_pax, capacity)
    z = (mean_daily_pax - capacity) / sigma
    expected_spill = sigma * (z * norm.cdf(z) + norm.pdf(z))
    return mean_daily_pax - expected_spill


def expected_boardings(mean_daily_pax, seats_per_departure, freq_per_day, recapture=DEFAULT_RECAPTURE_RATE):
    capacity = seats_per_departure * freq_per_day

    if mean_daily_pax >= NORMAL_APPROX_MEAN_THRESHOLD:
        expected_boarded_direct = _expected_boarded_direct_normal(mean_daily_pax, capacity)
    else:
        expected_boarded_direct = _expected_boarded_direct_poisson(mean_daily_pax, capacity)

    expected_spill = mean_daily_pax - expected_boarded_direct
    expected_recapture = expected_spill * recapture
    expected_boarded = expected_boarded_direct + expected_recapture
    expected_load_factor = expected_boarded / capacity if capacity > 0 else 0.0

    return {
        "expected_demand": float(mean_daily_pax),
        "expected_spill": float(expected_spill),
        "expected_recapture": float(expected_recapture),
        "expected_boarded": float(expected_boarded),
        "expected_load_factor": float(expected_load_factor),
    }
