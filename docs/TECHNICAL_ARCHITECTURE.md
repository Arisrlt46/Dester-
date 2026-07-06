# DESTER — Technical Architecture

Layered specification. Layer 0 is fully specified. Layers 1–3 are placeholder skeletons and will be expanded just-in-time before each is built, once the preceding layer's output is on disk and inspected.

Design principles applied throughout:
- Each layer is an importable Python package with a small public API.
- Each layer writes an intermediate artifact to disk (Parquet or CSV) so downstream layers do not re-parse raw data.
- Each layer is independently runnable via `python -m layerN.<entry>` from the project root.
- Raw data lives under `layerN/data/` and is git-ignored.
- Intermediate outputs live under `layerN/out/` and are also git-ignored (regenerable from raw).
- Nothing in a layer imports from a higher-numbered layer.

---

## Layer 0 — Data pipeline

**Purpose.** Turn a raw DB1BMarket CSV (~2 GB, national, quarterly) into a small, clean, typed Parquet file containing only the O&D market DESTER is evaluating.

**Running market (locked).** Austin (AUS) and Salt Lake City (SLC), Delta. DB1BMarket is directional, so a roundtrip appears as two rows; Layer 0 keeps both directions and preserves the direction indicator.

**Inputs.**
- `layer0/data/Origin_and_Destination_Survey_DB1BMarket_<year>_<quarter>.csv` — the prezipped BTS national file. Not committed.

**Outputs.**
- `layer0/out/aus_slc_market.parquet` — the filtered, typed, cleaned dataframe.
- `layer0/out/summary.json` — a small human-readable summary (row count, passenger total, mean fare, mean distance, share by carrier).

**Public API.** All functions live in `layer0/pipeline.py` unless noted.

- `load_raw_chunks(csv_path, chunk_size=200000)` streams the raw CSV chunk by chunk. Never loads the whole file into memory. Yields raw chunks; no filtering yet.
- `filter_to_market(chunk, a, b)` keeps rows where the directional market is (a to b) or (b to a). Preserves both directions; adds a `Direction` column with values `A_TO_B` or `B_TO_A`.
- `clean_and_type(df)` enforces column dtypes; drops rows with null Passengers, MktFare, MktDistance, or NonStopMiles; drops rows with `MktFare <= 0` (DB1B convention: negative or zero fares are placeholder/erroneous); drops `BulkFare == 1` rows if present (bulk tickets have distorted fares); returns the cleaned frame.
- `build_market_dataset(csv_path, a="AUS", b="SLC")` is the orchestrator. Streams the raw CSV, filters each chunk to the market, concatenates matches, applies `clean_and_type`, and returns the final dataframe.
- `write_outputs(df, out_dir)` writes `aus_slc_market.parquet` and `summary.json`. Prints a short human-readable report to stdout.
- `main()` is the entry point for `python -m layer0.pipeline`. Reads config, calls `build_market_dataset`, calls `write_outputs`.

**Output dataframe schema (`aus_slc_market.parquet`).**

Columns and dtypes: ItinID (int64), MktID (int64), Year (int16), Quarter (int8), Origin (category), Dest (category), Direction (category, derived, values `A_TO_B` or `B_TO_A`), RPCarrier (category, reporting carrier), TkCarrier (category, ticketing carrier — 99 for interline), OpCarrier (category, operating carrier — 99 for interline), MktCoupons (int8; 1 = nonstop, greater than 1 = connecting), Passengers (float32), MktFare (float32, USD), MktDistance (float32, miles including ground), NonStopMiles (float32, great-circle miles).

**Summary JSON schema.**

Fields: `market` (string, e.g. "AUS-SLC"), `year` (int), `quarter` (int), `row_count` (int), `passenger_total_sample` (float), `passenger_total_annualized_estimate` (float, computed as sample * 10 * 4 since DB1B is a 10% sample per quarter), `mean_fare` (float), `median_fare` (float), `mean_distance_miles` (float), `nonstop_share_by_pax` (float, computed as pax on MktCoupons==1 divided by total pax), `carrier_share_by_pax` (object mapping carrier code to share, top 5 carriers), `generated_at` (ISO 8601 string).

**Edge cases and decisions Layer 0 handles explicitly.**
- **Directionality.** DB1BMarket rows are directional. Both directions are kept, tagged, and can be aggregated or separated downstream.
- **10% sample.** DB1B is a 10% ticket sample. Layer 0 does not upscale row-level values; it exposes the sample size honestly and provides a single annualized passenger estimate in the summary for sanity-check purposes only. All downstream layers use the sample and apply their own scaling where relevant.
- **Bulk fares.** `BulkFare == 1` rows have distorted (often zero) fares and are dropped.
- **Zero or negative fares.** Dropped — DB1B convention treats these as data errors.
- **Interline itineraries.** `TkCarrier == 99` or `OpCarrier == 99` indicates an interline ticket. Kept, not dropped; they are legitimate itineraries and matter for connecting-market analysis in Layer 2.
- **Missing values.** Rows with null in any required economic field (Passengers, MktFare, MktDistance, NonStopMiles) are dropped.

**Success criteria for Layer 0.**
- Parquet file exists and loads in under 1 second.
- Row count is nonzero and dominated by both AUS to SLC and SLC to AUS rows in roughly balanced proportions.
- Summary JSON shows a plausible mean fare (roughly $200 to $500 one-way-equivalent for a domestic market of this stage length) and mean distance (great-circle AUS to SLC is ~1085 miles).
- Delta appears in `carrier_share_by_pax`.

---

## Layer 1 — Local-only business case  *(placeholder; expand before build)*

Consumes `layer0/out/aus_slc_market.parquet`. Produces Verdict 1.

Planned components: market sizing (base plus stimulation uplift; gravity model OLS cross-check); multinomial logit share model calibrated against realized DB1B shares on comparable existing markets (the evaluation step that licenses the model); frequency S-curve; stochastic spill and recapture (Poisson demand vs. seat capacity); route P&L and breakeven load factor.

Detailed spec to be written after Layer 0's output has been inspected on real data.

---

## Layer 2 — Add the feed  *(placeholder; expand before build)*

Consumes Layer 0 output plus additional DB1BMarket pulls for connecting O&Ds routed via SLC. Produces Verdict 2.

Planned components: enumeration of behind/beyond markets from SLC; minimum-connect-time validation against OAG/schedule data or a documented heuristic; network-level demand and P&L including feed traffic; comparison of Verdict 2 against Verdict 1.

Detailed spec to be written after Layer 1 is built.

---

## Layer 3 — Revenue attribution  *(placeholder; expand before build)*

Consumes Layer 2's connecting-itinerary set. Produces Verdict 3.

Planned components: for each connecting itinerary, model the segments as players in a cooperative game with coalition value equal to the fare paid; compute the Shapley value per segment; compare Shapley-attributed revenue for the AUS-SLC segment against mileage-prorated revenue; report the delta and the resulting verdict change (if any).

Detailed spec to be written after Layer 2 is built.

---

## Layer 1 — Local-only business case *(Wave 1 detailed; Wave 2 placeholder)*

Layer 1 is built in two waves. **Wave 1** produces the fitted, backtested multinomial logit share model — the piece that makes DESTER a research project rather than calibrated arithmetic. Wave 2 (market sizing, S-curve, spill/recapture, P&L, and the final Verdict 1) is specified only after Wave 1's backtest results are in hand.

### Wave 1 — Calibration, logit, backtest

Consumes: `layer0/data/Origin_and_Destination_Survey_DB1BMarket_2025_2.csv` (re-parsed for many markets, not just AUS-SLC), and `layer1/data/T_T100D_SEGMENT_US_CARRIER_ONLY.csv` (for frequency and seat-capacity features).

Produces: `layer1/out/calibration_markets.parquet`, `layer1/out/logit_coefficients.json`, `layer1/out/backtest_report.json`.

#### Module 1 — `layer1/calibration.py`

Selects comparable markets from the DB1BMarket source using an automatic rule. AUS-SLC itself is always excluded from calibration (we never train on the market we predict).

Selection rule (all conditions must hold, per directional market):
- Stage length between 800 and 1,500 non-stop miles.
- At least one carrier holds ≥ 40% of passenger share.
- At least one competing carrier holds ≥ 10% of passenger share.
- Total sampled passengers in the quarter ≥ 5,000.

Rationale: bounds the "similar market" set to short-to-medium haul spoke-to-hub routes with real competition, structurally comparable to AUS-SLC.

Public API:
- `select_calibration_markets(db1b_csv_path, t100_csv_path) -> pd.DataFrame` returns one row per (market, carrier, itinerary_type, connecting_hub) with observed share as the outcome variable and all features (see Module 2) as columns.
- `train_test_split(df, test_frac=0.30, random_state=42) -> (train_df, test_df)` splits stratified by market so that no market appears in both sets.

Writes `layer1/out/calibration_markets.parquet` with a `split` column set to `"train"` or `"test"`.

#### Module 2 — `layer1/logit.py`

The multinomial logit share model. Uses `statsmodels.discrete.discrete_model.MNLogit`.

Features (utility inputs per itinerary), all defensibly derivable from data on disk:

- `log_fare` — natural log of `MktFare`.
- `n_stops` — 0 for nonstop (`MktCoupons == 1`), 1 for single connect (`MktCoupons == 2`); connects with more coupons are dropped as edge cases.
- `routing_efficiency` — `MktDistance / NonStopMiles`. Values near 1.0 indicate near-direct routing; higher values indicate detours.
- `frequency_weekly` — weekly `DEPARTURES_PERFORMED` on the operating segment from T-100 (2025 Q2 average).
- `hub_dominance` — 1 if the operating carrier's overall passenger share at the relevant hub airport is ≥ 40% (computed within the calibration set), else 0. For nonstops, the "relevant hub airport" is the origin. For one-stop itineraries, it is the connecting airport. This corrects a Wave 1 spec bug where the feature was switched off precisely where hub dominance is strongest (a carriers own nonstops from its own hub).
- `carrier_fe_<code>` — carrier fixed-effect dummies, one per carrier present in the calibration set (drop-first encoding).

Public API:
- `fit(train_df, features: list[str] | None = None) -> LogitCoefficients` — if `features` is None, uses all features above. Returns a JSON-serializable coefficients object.
- `predict_shares(itineraries_df, coefficients) -> pd.Series` — returns predicted share per itinerary within a market (softmax over the utility scores).
- `save_coefficients(coefficients, path)` and `load_coefficients(path)`.

Writes `layer1/out/logit_coefficients.json`.

#### Module 3 — `layer1/backtest.py`

Takes the fitted coefficients and the held-out test set. For each test market: predict shares per itinerary, aggregate to carrier-level shares, compare to observed.

Reports:
- **MAE on carrier share** (percentage points), pooled across test markets. Headline metric.
- **RMSE on carrier share**, same pooling.
- **Per-market breakdown table**, one row per test market, listing predicted-vs-observed share for each carrier.
- **Feature ablation table** — refits the logit dropping one feature at a time, reports the resulting test MAE, so we can honestly see which features are pulling weight.

Success target: pooled MAE ≤ 10 percentage points, matching typical published airline logit share models. If MAE exceeds 15pp, Wave 1 is not considered validated and the model is revised before Wave 2 is spec'd.

Public API:
- `run_backtest(train_df, test_df, features: list[str] | None = None) -> dict`
- `write_backtest_report(report, path)`

Writes `layer1/out/backtest_report.json` and prints a summary to stdout.

#### Wave 1 orchestrator

`layer1/verdict1_wave1.py` — runs the three modules in order end-to-end. Runnable via `python -m layer1.verdict1_wave1`.

### Wave 2 — Sizing, S-curve, spill, P&L, Verdict 1 *(placeholder; spec after Wave 1 results)*

Consumes Wave 1's coefficients plus Layer 0's AUS-SLC parquet. Applies the model to AUS-SLC, adds stimulation uplift, S-curve frequency effects, stochastic spill and recapture, and Delta E175 CASM from Form 41 P-5.2 + T-100 to produce a route P&L and Verdict 1. Specified after Wave 1's backtest results are reviewed, since the backtest may indicate a different feature set or a different downstream treatment.

**Wave 1 iteration note (added after first-run backtest):** During re-fits, inspect the fare distribution reaching the logit at fit time. All fares should be strictly positive (Layer 0 already drops non-positive fares) and roughly log-normal. If the distribution is bimodal or truncated in an unexpected way, an interaction with feature standardization is a likely cause of coefficient instability. Log any anomalies to `PROBLEMS_AND_SOLUTIONS.md`.
