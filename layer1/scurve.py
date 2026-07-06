"""Layer 1 Wave 2, Module 5: airline-industry-standard frequency S-curve.

A carrier's demand share grows nonlinearly with its share of market
frequency: an entrant below its "fair" frequency share typically gets less
than a proportional share of demand, and above it, more.
"""

DEFAULT_ALPHA = 1.6
ALPHA_SENSITIVITY_VALUES = [1.4, 1.6, 1.8]


def frequency_share(delta_freq, all_freqs):
    return delta_freq / sum(all_freqs)


def scurve_share(delta_freq, all_freqs, alpha=DEFAULT_ALPHA):
    total = sum(all_freqs)
    numerator = (delta_freq / total) ** alpha
    denominator = sum((f / total) ** alpha for f in all_freqs)
    return numerator / denominator
