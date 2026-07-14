"""DESTER dashboard: read-only data access.

Reads the pre-existing JSON verdict outputs (and docs) from disk. Never
recomputes anything -- the dashboard is a viewer, not a compute engine.
Missing variant files degrade gracefully (the market's variant dict simply
omits that key) rather than raising.
"""

import json
import os

import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each market's variants map a short variant key -> {logical_name: file path}.
# "ATL-SAT"/"v5" and "v1" are single merged JSONs (Layer 4 Wave 2's own
# union-of-verdicts-1-3 output), so all three logical names point at the
# same file; get_verdict1/2/3 below just pull different sub-fields from it.
_VARIANT_PATHS = {
    "AUS-SLC": {
        "original": {
            "verdict1": os.path.join(ROOT, "layer1", "out", "verdict1.json"),
            "verdict2": os.path.join(ROOT, "layer2", "out", "verdict2.json"),
            "verdict3": os.path.join(ROOT, "layer3", "out", "verdict3.json"),
        },
        "cpa": {
            "verdict1": os.path.join(ROOT, "layer1", "out", "verdict1_cpa.json"),
            "verdict2": os.path.join(ROOT, "layer2", "out", "verdict2_cpa.json"),
            "verdict3": os.path.join(ROOT, "layer3", "out", "verdict3_cpa.json"),
        },
        "norm": {
            "verdict1": os.path.join(ROOT, "layer1", "out", "verdict1_norm.json"),
        },
    },
    "ATL-SAT": {
        "v5 (final)": {
            "merged": os.path.join(ROOT, "layer4", "out", "verdict4_v5.json"),
        },
        "v1 (pre-shrinkage)": {
            "merged": os.path.join(ROOT, "layer4", "out", "verdict4.json"),
        },
        "v5 + rule-normalized": {
            "verdict1": os.path.join(ROOT, "layer4", "out", "verdict1_atl_sat_v5_norm.json"),
        },
        "v1 + rule-normalized": {
            "verdict1": os.path.join(ROOT, "layer4", "out", "verdict1_atl_sat_norm.json"),
        },
    },
    # MIA-SEA ships with a single model variant today -- the other three
    # keys are declared (matching ATL-SAT's shape) so they light up for free
    # if those files are ever added later, but right now only "v5 (final)"
    # resolves; the rest degrade gracefully via the any(...) check below.
    "MIA-SEA": {
        "v5 (final)": {
            "merged": os.path.join(ROOT, "layer4", "out", "verdict4_mia_sea.json"),
        },
        "v1 (pre-shrinkage)": {
            "merged": os.path.join(ROOT, "layer4", "out", "verdict4_mia_sea_v1.json"),
        },
        "v5 + rule-normalized": {
            "verdict1": os.path.join(ROOT, "layer4", "out", "verdict1_mia_sea_v5_norm.json"),
        },
        "v1 + rule-normalized": {
            "verdict1": os.path.join(ROOT, "layer4", "out", "verdict1_mia_sea_norm.json"),
        },
    },
}

_DOCS_PATHS = {
    "research_findings": os.path.join(ROOT, "docs", "RESEARCH_FINDINGS.md"),
    "problems_and_solutions": os.path.join(ROOT, "docs", "PROBLEMS_AND_SOLUTIONS.md"),
}

_README_PATH = os.path.join(ROOT, "README.md")

# layer4/verdict3_atl_sat.py (reused unchanged by verdict4_v5.py) never computed
# a regime-aware sensitivity sweep for ATL-SAT the way layer3/verdict3.py did for
# AUS-SLC. This retroactive artifact supersedes verdict4_v5.json's own
# (load-factor-based, regime-agnostic) "sensitivities" field for the v5 variant
# only -- AUS-SLC's loading path is untouched.
_ATL_SAT_V5_SENSITIVITIES_PATH = os.path.join(ROOT, "layer4", "out", "verdict3_v5_sensitivities.json")

UPLIFT_GRID = [0.10, 0.15, 0.20, 0.25]
RECAPTURE_GRID = [0.10, 0.15, 0.20, 0.30]
ALPHA_GRID = [1.4, 1.6, 1.8]


def _load_json_safe(path):
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data
def load_all_data():
    """Returns {market: {variant_key: {logical_name: parsed_json_or_None}}}.
    A variant is dropped entirely for a market if none of its files exist."""
    data = {}
    for market, variants in _VARIANT_PATHS.items():
        market_data = {}
        for variant_key, files in variants.items():
            loaded = {name: _load_json_safe(path) for name, path in files.items()}
            if any(v is not None for v in loaded.values()):
                market_data[variant_key] = loaded
        data[market] = market_data

    _supersede_atl_sat_v5_sensitivities(data)
    return data


def _supersede_atl_sat_v5_sensitivities(data):
    """Replaces ATL-SAT's v5 "merged" blob's regime-agnostic sensitivities
    with the retroactively-computed regime-aware grid, if present on disk.
    A no-op (degrades gracefully) if the file doesn't exist."""
    v5_sensitivities = _load_json_safe(_ATL_SAT_V5_SENSITIVITIES_PATH)
    if v5_sensitivities is None:
        return
    atl_sat_v5 = data.get("ATL-SAT", {}).get("v5 (final)", {}).get("merged")
    if atl_sat_v5 is not None:
        atl_sat_v5["sensitivities"] = v5_sensitivities["sensitivities"]


@st.cache_data
def load_docs():
    docs = {}
    for name, path in _DOCS_PATHS.items():
        if os.path.exists(path):
            with open(path) as f:
                docs[name] = f.read()
        else:
            docs[name] = f"*{os.path.basename(path)} not found.*"
    return docs


@st.cache_data
def load_readme_pitch():
    """First non-blank, non-heading line of README.md -- the bolded
    one-line thesis statement right under the H1 title."""
    if not os.path.exists(_README_PATH):
        return ""
    with open(_README_PATH) as f:
        content = f.read()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.strip("*")
    return ""


def available_variants(data, market):
    return list(data.get(market, {}).keys())


def _variant_blob(data, market, variant):
    return data.get(market, {}).get(variant, {})


def get_verdict1(data, market, variant):
    blob = _variant_blob(data, market, variant)
    return blob.get("merged") or blob.get("verdict1")


def get_verdict2(data, market, variant):
    blob = _variant_blob(data, market, variant)
    return blob.get("merged") or blob.get("verdict2")


def get_verdict3(data, market, variant):
    blob = _variant_blob(data, market, variant)
    return blob.get("merged") or blob.get("verdict3")


def get_regime(verdict3_dict, regime):
    """Pulls the {mileage|shapley} entry from a verdict3-shaped dict's
    attribution_regimes list."""
    if not verdict3_dict or "attribution_regimes" not in verdict3_dict:
        return None
    for entry in verdict3_dict["attribution_regimes"]:
        if entry["regime"] == regime:
            return entry
    return None


def nearest(value, options):
    return min(options, key=lambda o: abs(o - value))


def nearest_sensitivity(sensitivities, uplift, recapture, alpha, regime=None):
    """Snaps (uplift, recapture, alpha[, regime]) to the closest
    pre-computed grid point in a sensitivities list. If the list has no
    "regime" field (ATL-SAT's Verdict 1-only, load-factor-based grid --
    Layer 4 Wave 2 never computed a regime-aware sweep for ATL-SAT),
    regime is ignored."""
    if not sensitivities:
        return None
    has_regime = "regime" in sensitivities[0]
    candidates = sensitivities
    if has_regime and regime is not None:
        candidates = [s for s in sensitivities if s["regime"] == regime]
    return min(
        candidates,
        key=lambda s: abs(s["uplift"] - uplift) + abs(s["recapture"] - recapture) + abs(s["alpha"] - alpha),
    )
