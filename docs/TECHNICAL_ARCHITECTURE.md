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

### Wave 2 — Sizing, S-curve, spill, P&L, Verdict 1

Wave 2 turns the fitted logit from Wave 1 into Verdict 1 for the specific AUS-SLC market on Delta. Wave 1 is a prerequisite: `layer1/out/logit_coefficients.json` and Layer 0's `aus_slc_market.parquet` must exist before Wave 2 runs.

Consumes: `layer0/out/aus_slc_market.parquet`, `layer0/out/summary.json`, `layer1/out/logit_coefficients.json`, `layer1/data/T_F41SCHEDULE_P52.csv`, `layer1/data/T_T100D_SEGMENT_US_CARRIER_ONLY.csv`.

Produces: `layer1/out/verdict1.json`.

#### Module 4 — `layer1/sizing.py`

Turns Layer 0's 10% quarterly sample into an annualized total market size with stimulation uplift.

- `annualize_sample(quarter_passenger_sample) -> float` returns `sample * 10 * 4` (DB1B is 10% sample per quarter).
- `apply_stimulation(base_pax, uplift=0.15) -> float` returns `base_pax * (1 + uplift)`.
- `market_size(layer0_summary_path, uplift=0.15) -> dict` orchestrates and returns `{base_pax, uplift, sized_pax}`.

**Rationale for stimulation uplift.** A new nonstop stimulates demand that didn't previously exist: passengers who were formerly connecting upgrade to nonstop, some formerly-driving passengers now fly, and some previously-unmade trips now happen. Documented default: 15%. Sensitivity range: 10% to 25%.

#### Module 5 — `layer1/scurve.py`

Airline-industry-standard S-curve for the frequency-share effect: a carrier's share grows nonlinearly with its frequency share.

- `frequency_share(delta_freq, all_freqs) -> float` returns `delta_freq / sum(all_freqs)`.
- `scurve_share(delta_freq, all_freqs, alpha=1.6) -> float` returns `(delta_freq / sum(all_freqs))^alpha / sum((f / sum(all_freqs))^alpha for f in all_freqs)`.

**Delta's proposed AUS-SLC frequency.** Delta announced 2x-daily service. Incumbent frequencies (Southwest, Frontier, etc.) are computed from the T-100 file already on disk: sum of `DEPARTURES_PERFORMED` on the AUS-SLC segment in 2025 Q2, divided by weeks in the quarter.

**Documented default α = 1.6.** Sensitivity range 1.4 to 1.8.

#### Module 6 — `layer1/spill.py`

Stochastic spill and recapture. Demand isn't deterministic; some days you overshoot capacity and lose passengers; some of them buy another Delta ticket in the same market anyway.

- `expected_boardings(mean_daily_pax, seats_per_departure, freq_per_day, recapture=0.15) -> dict` models daily demand as Poisson (or Normal if mean is large enough to justify the approximation), caps at `seats_per_departure * freq_per_day`, applies `recapture` to spilled passengers, returns `{expected_demand, expected_spill, expected_recapture, expected_boarded, expected_load_factor}`.

**Documented default recapture = 15%.** Sensitivity range 10% to 30%.

#### Module 7 — `layer1/pnl.py`

Route P&L and breakeven load factor for Delta's proposed AUS-SLC service.

- `resolve_e175_aircraft_type_code(p52_csv_path, t100_csv_path) -> int` programmatically identifies the E175 aircraft type code by finding the `AIRCRAFT_TYPE` value that (a) Delta operates most heavily in 2025 Q2, and (b) has a fleet-average seats-per-departure between 70 and 82 (E175 is a 76-seat regional jet). Logs the identified code and the seats-per-departure for verification.

- `compute_delta_e175_casm(p52_csv_path, t100_csv_path, quarter=2, year=2025) -> dict` filters Form 41 P-5.2 to Delta + E175 + 2025 Q2 for the numerator (`TOT_AIR_OP_EXPENSES`), filters T-100 to the same carrier + aircraft + Q2 months for the denominator (`SEATS * DISTANCE` summed), returns `{opex_usd, asms, casm_cents_per_asm}`.

- `route_pnl(revenue, asms, casm) -> dict` returns `{revenue, cost, contribution, breakeven_lf}`.

- `main_pnl(expected_boardings, mean_fare, seats_per_departure, freq_per_day, quarter_days, distance_miles, casm_cents) -> dict` orchestrates the AUS-SLC P&L end-to-end.

#### Module 8 — `layer1/verdict1.py`

Wave 2 orchestrator and Verdict 1 output.

Runs: market sizing → logit predict on Delta's proposed AUS-SLC itinerary → S-curve adjustment → spill model → P&L → verdict.

**Verdict rule.** `go` if `expected_load_factor >= breakeven_load_factor`. `no_go` otherwise.

**Sensitivities.** Re-runs the full chain across three axes at their documented sensitivity ranges:
- Stimulation uplift: 10%, 15%, 20%, 25%.
- Recapture rate: 10%, 15%, 20%, 30%.
- S-curve α: 1.4, 1.6, 1.8.

Reports the verdict at every combination, plus a summary noting whether the verdict is robust (same under all combinations) or fragile (flips under some).

**Output file `layer1/out/verdict1.json` schema:**

Fields in `layer1/out/verdict1.json`: `market` ("AUS-SLC"), `carrier` ("DL"), `verdict` ("go" or "no_go"), `robust` (bool), `expected_load_factor` (float), `breakeven_load_factor` (float), `revenue_annual_usd` (float), `cost_annual_usd` (float), `contribution_annual_usd` (float), `delta_e175_casm_cents` (float), `sizing` (object with `base_pax`, `uplift`, `sized_pax`), `predicted_delta_share` (float), `sensitivities` (list of objects each with `uplift`, `recapture`, `alpha`, `verdict`, `expected_lf`, `breakeven_lf`), and `generated_at` (ISO 8601 string).

Runnable via `python -m layer1.verdict1`. Prints a human-readable summary to stdout.

**Expected Verdict 1 outcome.** DESTER's research design assumes Verdict 1 comes back **no-go**. AUS-SLC's local O&D is thin, Southwest is entrenched, and Delta's fixed costs at 2x daily are non-trivial. If Verdict 1 comes back go on local demand alone, that materially undermines the three-verdict thesis and requires a separate investigation before proceeding to Layer 2. This outcome expectation is stated for transparency, not to bias the model.

---

## Layer 2 — Feed as addition to viable local market

**Redefined purpose.** The original Layer 2 framing ("does connecting feed rescue a thin local market from no-go?") does not apply, because Wave 2 established that AUS-SLC is viable on local demand alone (Verdict 1 = GO). Layer 2 is therefore reframed: quantify how much *additional* Delta economic value comes from behind-and-beyond passengers routed through SLC, and produce the passenger-mix split (local vs. feed) that Layer 3's Shapley attribution question depends on.

Consumes: `layer0/data/Origin_and_Destination_Survey_DB1BMarket_2025_2.csv` (reparsed with a coupon-touching filter, not the market-pair filter Layer 0 used), `layer0/out/aus_slc_market.parquet`, `layer0/out/summary.json`, and `layer1/out/verdict1.json`.

Produces: `layer2/out/feed_itineraries.parquet`, `layer2/out/feed_economics.parquet`, `layer2/out/verdict2.json`.

Reuses Layer 0's raw DB1B file directly. Layer 2 does not require a separate TranStats download.

### Module 1 — `layer2/feed_extraction.py`

Streams the raw DB1BMarket CSV chunk-by-chunk and extracts feed itineraries — those where the AUS-SLC segment appears as one coupon of a two-coupon itinerary, and the itinerary's market pair is *not* AUS-SLC directly.

Rule: keep row if `MktCoupons == 2` and `AirportGroup` contains `"AUS:SLC"` or `"SLC:AUS"` as a substring, and the market pair (sorted `[Origin, Dest]`) is not `["AUS", "SLC"]`.

Feed extraction is intentionally permissive (option 1A in the design discussion): all feasible connections through SLC are included, even routings that appear as geographic detours. Real observed passenger behavior is the honest count; a "sensible-routing" filter would introduce judgment calls.

Adds derived columns:
- `feed_direction`: `"BEHIND"` if the itinerary's true origin is AUS (routings AUS → SLC → X), `"BEYOND"` if the true destination is AUS (routings X → SLC → AUS).
- `beyond_endpoint`: the far end of the feed (the non-AUS, non-SLC airport in the AirportGroup).
- `aus_slc_leg_direction`: `"A_TO_B"` (AUS→SLC) or `"B_TO_A"` (SLC→AUS).

Writes `layer2/out/feed_itineraries.parquet`.

Public API:
- `extract_feed_itineraries(db1b_csv_path) -> pd.DataFrame`
- `resolve_csv_path(pattern)` — same glob-and-error pattern used in Layer 0 and Layer 1.

### Module 2 — `layer2/feed_economics.py`

For each feed itinerary, computes the passenger economics on the AUS-SLC segment.

**Delta's share of each feed market comes from observed DB1B data, not the Wave 1 logit** (option 2B in the design discussion). The rationale is that Verdict 2 answers a factual question about the passenger flow Delta actually captures; the logit is reserved for Layer 3's counterfactuals.

For each unique feed market (defined by the sorted airport pair excluding SLC, e.g. AUS-SEA, AUS-BOI), Delta's share is `sum(Passengers where operating carrier is DL) / sum(Passengers)` computed on that market's rows in DB1B.

**Fare allocation to the AUS-SLC segment is provisional mileage proration for Layer 2.** Layer 3 will replace this with Shapley. For each feed itinerary, `aus_slc_allocated_fare = MktFare * (aus_slc_miles / total_mkt_miles)`, where `aus_slc_miles` is the great-circle AUS-SLC distance (~1085 mi, taken from Layer 0's typed schema) and `total_mkt_miles` is `NonStopMiles` for the two-coupon itinerary.

Public API:
- `compute_feed_shares(feed_df, raw_db1b_csv_path) -> pd.DataFrame` — one row per (beyond_endpoint, direction), with Delta's observed share.
- `allocate_fares(feed_df, aus_slc_miles=1085) -> pd.DataFrame` — adds `aus_slc_allocated_fare`.
- `feed_economics(feed_df, shares_df) -> pd.DataFrame` — joins share and fare, returns per-itinerary Delta feed passenger and revenue estimates.

Writes `layer2/out/feed_economics.parquet`.

### Module 3 — `layer2/pnl_with_feed.py`

Replays Verdict 1's P&L math but with total AUS-SLC passengers = local + feed and total revenue = local revenue + Delta's feed-allocated revenue.

Reuses `layer1/pnl.compute_delta_e175_casm` and `layer1/pnl.route_pnl` for the cost side — feed does not change the cost of flying the aircraft. Only the revenue side and passenger mix change.

Handles the capacity interaction honestly: the 2x-daily E175 provides ~54,000 annual seats. Local demand at ~53,000 already fills near capacity, so the meaningful Verdict 2 output is not "does the LF change" (it can't much) but "how is the passenger mix split between local and feed, and what does that mean for total contribution?"

Public API:
- `combined_pnl(local_pax, local_revenue, feed_pax, feed_revenue, seats_per_departure, freq_per_day, quarter_days, casm_cents) -> dict`

### Module 4 — `layer2/verdict2.py`

Orchestrator and Verdict 2 output. Runs feed extraction → feed shares → feed fare allocation → combined P&L → sensitivities → verdict.

**Verdict 2 rule.** `verdict2` records the total contribution and the local-vs-feed split. There is no go/no-go flip here — Verdict 1 already established viability. Verdict 2 answers: what fraction of Delta's AUS-SLC economic case is local vs. feed?

**Sensitivities.** Recomputes the mix under the same three axes as Verdict 1 (uplift 10–25%, recapture 10–30%, S-curve α 1.4–1.8), so the local-vs-feed split can be reported with error bars.

**Output file `layer2/out/verdict2.json` schema:**

Fields: `market` ("AUS-SLC"), `carrier` ("DL"), `local_contribution_annual_usd` (float, matches Verdict 1's contribution), `feed_contribution_annual_usd` (float, additional contribution from feed), `total_contribution_annual_usd` (float, sum), `feed_share_of_total_revenue` (float, 0-1), `feed_share_of_total_pax` (float, 0-1), `top_feed_markets` (list of objects with `endpoint`, `direction`, `passengers`, `revenue`, sorted by revenue descending, top 10), `local_vs_feed_by_sensitivity` (list of objects each with `uplift`, `recapture`, `alpha`, `local_pax`, `feed_pax`, `local_rev`, `feed_rev`), `generated_at` (ISO 8601 string).

Runnable via `python -m layer2.verdict2`. Prints a human-readable summary to stdout: total feed itineraries extracted, top 10 feed markets by revenue, local-vs-feed passenger split, local-vs-feed revenue split, and the Layer 3 leverage note ("Layer 3's Shapley-vs-mileage attribution question has X% leverage on Delta's AUS-SLC economics" where X = feed revenue share).

**Expected outcome.** Verdict 2 is expected to reveal that a non-trivial share of Delta's AUS-SLC economics comes from feed (plausibly 30–60% based on the fact that SLC is a genuine Delta hub connecting to a large Mountain West and West Coast network). The larger this share, the more leverage Layer 3's attribution question carries. If feed share is under 20%, Layer 3's attribution flip question would be small potatoes and worth flagging.

---

## Layer 3 — Shapley vs. mileage revenue attribution

**Purpose.** Answer DESTER's central research question: does Delta's AUS-SLC verdict change depending on the connecting-revenue attribution regime? Specifically, replace Layer 2's provisional mileage-prorated feed revenue with a Shapley-value allocation, recompute the P&L, and compare.

**Expected result (honest, per Layer 2's findings).** Given Layer 2 established that feed = 13% of Delta's AUS-SLC revenue, Verdict 3 is expected to *not* flip the go/no-go for this specific market. The Shapley-vs-mileage delta on the AUS-SLC segment is bounded by the feed layer's total size. The honest null result on the pre-registered market is a legitimate research finding; Layer 4 will apply the same three-verdict engine to a hub-heavy market where the attribution mechanism has more leverage.

Consumes: `layer2/out/feed_itineraries.parquet`, `layer2/out/feed_economics.parquet`, `layer0/out/summary.json`, `layer0/data/Origin_and_Destination_Survey_DB1BMarket_2025_2.csv` (reparsed a third time with a new filter — SLC-beyond nonstop O&Ds), and `layer1/out/verdict1.json`.

Produces: `layer3/out/standalone_fares.parquet`, `layer3/out/attribution_by_itinerary.parquet`, `layer3/out/verdict3.json`.

Reuses Layer 0's raw DB1B file directly (third distinct filter over the same source). No new TranStats download.

### Module 1 — `layer3/standalone_fares.py`

Computes the singleton coalition values `v(A)` and `v(B)` that Shapley needs.

`v(A)` — mean standalone fare for AUS-SLC on nonstop-only itineraries. Taken directly from Layer 0's `summary.json` as `mean_fare` filtered further to `MktCoupons == 1` at read time (Layer 0's summary already reports the mean over the full AUS-SLC parquet, which includes both nonstop and connecting itineraries; Layer 3 needs the nonstop-only value specifically because the singleton is priced as a standalone nonstop). Add a helper `standalone_fare_aus_slc(aus_slc_parquet_path) -> float` that computes this from the Layer 0 parquet in one pass.

`v(B)` — for each unique `beyond_endpoint` observed in Layer 2's feed itineraries (Boise, Jackson Hole, Portland, etc.), compute the mean standalone fare on the SLC-endpoint nonstop O&D market by streaming the raw DB1B a third time, filtered to `MktCoupons == 1` and the correct market pair. Values below $50 or above $2,000 flagged as data-quality outliers (same reasoning as Wave 1's fare-distribution diagnostic).

Public API:
- `standalone_fare_aus_slc(aus_slc_parquet_path) -> float`
- `standalone_fares_slc_beyond(db1b_csv_path, endpoints: list[str]) -> pd.DataFrame` — one row per endpoint with `mean_standalone_fare`, `n_observations`, `flagged` (bool).

Writes `layer3/out/standalone_fares.parquet`.

### Module 2 — `layer3/attribution.py`

For each feed itinerary from Layer 2, computes both the mileage-prorated and Shapley-attributed AUS-SLC fare.

**Mileage proration** (already computed by Layer 2, re-computed here for consistency and side-by-side comparison):
`aus_slc_fare_mileage = MktFare * (AUS_SLC_MILES / total_market_miles)` where `AUS_SLC_MILES = 1085` (great-circle) and `total_market_miles` is the itinerary's `NonStopMiles`.

**Shapley two-player attribution** on the coalition of segments `{A = AUS-SLC, B = SLC-beyond}`:
- `v(A)` from Module 1.
- `v(B)` from Module 1, joined on the itinerary's `beyond_endpoint`.
- `v(A,B) = MktFare` (the connecting fare actually paid).
- `phi_A = 0.5 * (v(A) + (v(A,B) - v(B)))` = AUS-SLC's Shapley-attributed fare.
- `phi_B = 0.5 * (v(B) + (v(A,B) - v(A)))`.
- `phi_A + phi_B = v(A,B)` by construction — the split is exact.

**Negative Shapley values are reported honestly**, not floored at zero. This can occur when the connecting fare is unusually low relative to the sum of standalone fares (distressed inventory, promotional pricing, etc.). Floor-at-zero would hide a real economic phenomenon. Flag any itinerary with `phi_A < 0` in the output for transparency.

**Attribution delta per itinerary**:
`delta = phi_A - aus_slc_fare_mileage`. Positive means Shapley credits AUS-SLC more than mileage; negative means less.

Public API:
- `mileage_attribution(feed_itineraries_df, aus_slc_miles=1085) -> pd.Series`
- `shapley_attribution(feed_itineraries_df, standalone_fares_df, v_a) -> pd.DataFrame` returning `phi_A`, `phi_B`, `phi_A_negative` (bool) per itinerary.
- `attribute_all(feed_itineraries_df, standalone_fares_df, v_a) -> pd.DataFrame` combining both regimes.

Writes `layer3/out/attribution_by_itinerary.parquet`.

### Module 3 — `layer3/pnl_by_regime.py`

Replays Layer 2's `combined_pnl` twice — once with feed revenue computed under mileage attribution, once under Shapley. Reuses `layer1.pnl.compute_delta_e175_casm` and `layer2.pnl_with_feed.combined_pnl` unchanged (cost side and combination logic are attribution-regime-neutral).

Public API:
- `pnl_by_regime(local_pax, local_revenue, feed_pax, feed_revenue_by_regime: dict, seats_per_departure, freq_per_day, quarter_days, casm_cents, distance_miles) -> dict` — returns both regime P&Ls in a single dict keyed by regime.

### Module 4 — `layer3/verdict3.py`

Orchestrator and Verdict 3 output. Runs standalone fares → attribution → both P&Ls → sensitivity grid → verdict comparison.

**Verdict 3 rule.** `verdict3` reports both regime verdicts (go/no-go), the contribution under each regime, the attribution delta, the leverage percentage (`|contribution_shapley - contribution_mileage| / contribution_mileage`), and a `verdict_flipped` bool.

**Sensitivities.** The same 48-combination grid used in Verdicts 1 and 2, run under both attribution regimes, so we can see whether any combination flips the verdict under one regime but not the other.

**Output file `layer3/out/verdict3.json` schema:**


Fields in `layer3/out/verdict3.json`: `market` ("AUS-SLC"), `carrier` ("DL"), `attribution_regimes` (list of two objects, one per regime, each with `regime` ("mileage" or "shapley"), `feed_revenue_annual_usd`, `total_revenue_annual_usd`, `total_contribution_annual_usd`, `expected_load_factor`, `breakeven_load_factor`, `verdict` ("go" or "no_go")), `attribution_delta_usd` (float, shapley minus mileage on contribution), `attribution_leverage_pct` (float, absolute delta divided by mileage contribution), `verdict_flipped` (bool), `negative_phi_a_count` (int, itineraries where the Shapley AUS-SLC allocation went negative), `sensitivities` (list of objects each with `uplift`, `recapture`, `alpha`, `regime`, `verdict`, `contribution`), and `generated_at` (ISO 8601 string).

Runnable via `python -m layer3.verdict3`. Prints a human-readable summary to stdout: total feed itineraries attributed, mean and median Shapley-vs-mileage delta per itinerary, count of negative Shapley values, revenue and contribution under each regime, headline attribution leverage percentage, verdict under each regime, and whether the verdict flipped.

If the verdict flips, flag it prominently. Given Layer 2's 13% feed leverage, a flip on AUS-SLC would be a genuinely surprising result worth diagnosing carefully before publication. If the verdict does not flip, that is the expected honest null result on the pre-registered market and should be reported cleanly, not apologetically. Layer 4 will characterize the mechanism in a market where the attribution mechanism has more leverage.

---

## Layer 4 — Second-market comparison

**Purpose.** Apply DESTER's three-verdict engine to a second, hub-heavy connecting market where feed represents a substantially larger share of total revenue than AUS-SLC's 13%. Pair with the AUS-SLC findings to characterize *when* the attribution mechanism has enough leverage to flip a verdict, producing a concrete empirical bracket from two contrasting real markets.

**Staged spec.** Layer 4 is built in two waves.

- **Wave 1 (this section)** — market screener. Systematically scan the raw DB1B for candidate spoke-to-hub markets, compute each candidate's feed revenue share, return a ranked table. No verdict logic yet. Wave 2 is designed once Wave 1's output is on disk and reviewed.
- **Wave 2 (placeholder)** — apply Verdicts 1-3 to the chosen market. Detailed spec written after Wave 1 results are inspected.

### Wave 1 — Market screener

Consumes: `layer0/data/Origin_and_Destination_Survey_DB1BMarket_2025_2.csv` (fourth distinct filter over the same source file).

Produces: `layer4/out/market_screener.parquet`, `layer4/out/screener_summary.json`.

Reuses Layer 0's raw DB1B file directly. No new TranStats download.

#### Module 1 — `layer4/screener.py`

Streams the raw DB1B in chunks (same pattern as Layer 0 and Layer 2), builds per-market accumulators for local and feed passenger counts and revenue, and returns a ranked candidate table.

**Candidate market definition.** A market is a candidate if it is a **spoke-to-major-hub domestic O&D**:
- One endpoint is on the top-10 US hub list: ATL, DFW, ORD, DEN, LAX, CLT, LAS, PHX, SEA, MSP.
- The other endpoint is not on that list.
- The market's dominant carrier — the carrier with the largest passenger share on the *local* itineraries (`MktCoupons == 1`) — holds at least 40% share.
- Total sampled local passengers in the quarter is at least 500 (below that, share estimates are too noisy).

**Feed extraction rule.** A feed itinerary for a candidate market is a `MktCoupons == 2` row whose `AirportGroup` contains both endpoints as an ordered subsequence, where the hub endpoint is the connecting airport. Same logical rule Layer 2 applied for AUS-SLC, generalized.

**Feed share definition.** For each (candidate market, dominant carrier) pair:
- `local_revenue = sum(MktFare * Passengers)` on nonstop rows for the dominant carrier.
- `feed_revenue_allocated` = sum over feed itineraries touching that market of `MktFare * (segment_miles / total_miles) * Passengers * dominant_carrier_share_on_feed_market`. Provisional mileage proration (matching Layer 2's convention), applied here purely for screening — Wave 2 will use Shapley if the chosen market is built out.
- `feed_share = feed_revenue_allocated / (local_revenue + feed_revenue_allocated)`.

**Output ranking.** The full candidate list is returned ranked by `feed_share` ascending, so the reviewer can see the full distribution and identify natural gaps or clusters rather than pre-committing to a target band. A `flag_borderline` column marks rows with `0.25 <= feed_share <= 0.45` as candidates likely to be in the mechanism-flip zone, but the flag is diagnostic, not prescriptive.

Public API:
- `resolve_csv_path(pattern)` — same glob-and-error pattern used in Layers 0-3.
- `stream_candidate_stats(db1b_csv_path, hub_airports: list[str], min_pax: int = 500) -> pd.DataFrame` streams the CSV and returns per-(market, dominant_carrier) accumulators.
- `compute_feed_shares(candidate_stats_df) -> pd.DataFrame` adds `local_revenue`, `feed_revenue_allocated`, `feed_share`, `flag_borderline`.
- `write_outputs(df, out_dir)` writes the ranked parquet plus a JSON summary noting total candidates screened, how many fell into the borderline band, the top 10 candidates by feed share overall, and the top 5 within the borderline band specifically.

Runnable via `python -m layer4.screener`. Prints a human-readable summary to stdout: total markets screened, distribution of feed shares (as decile buckets), top 5 borderline candidates with their dominant carrier and feed share, and a flag if the borderline band is empty (would be a genuine finding — feed shares are bimodal — worth noting before Wave 2 is designed).

**Success criteria for Wave 1.** The screener runs to completion on the 2 GB DB1B file without loading it fully into memory. The output parquet contains at least a few dozen candidate markets. Whether the borderline band contains any markets is an empirical question — either outcome is a valid Wave 1 result.

### Wave 2 — Verdicts 1-3 on the chosen market *(placeholder; spec after Wave 1)*

Applies the same three-verdict engine used for AUS-SLC to whichever borderline market is selected from Wave 1's ranked output. The four Layer 1 Wave 2 modules, the four Layer 2 modules, and the four Layer 3 modules are reused directly by import — Layer 4 Wave 2 is largely orchestration, not new implementation. Detailed spec written after Wave 1 output is reviewed.
