# DESTER — Problems & Solutions Log

Living document. Every time something breaks, contradicts a design assumption, or forces a decision, it gets an entry here — in build order. This is also evidence, for a reader, of real engineering judgment rather than a project that worked on the first try.

---

## Setup phase

**Problem:** Renaming the project folder (routequant -> dester) broke the Python virtual environment.
**Cause:** A venv stores absolute paths internally at creation time; renaming the parent folder invalidates them.
**Solution:** Deleted and rebuilt the venv from scratch inside the renamed folder (`rm -rf venv && python3 -m venv venv`).

**Problem:** A `cat > README.md << 'EOF'` heredoc got interrupted mid-paste, leaving a corrupted file with a stray duplicate header line.
**Cause:** Commands were run out of order while the terminal was still waiting inside the heredoc block.
**Solution:** Deleted the corrupted file and re-ran the heredoc as a single uninterrupted paste.

**Problem:** GitHub would not allow the repository name "Dester" as typed.
**Cause:** Name collision or reserved-name rule on GitHub's side.
**Solution:** Accepted GitHub's auto-appended name, `Dester-`, and used that exact URL for the remote.

**Problem:** DB1B (the core free dataset) only contains domestic O&D fare data.
**Cause:** DOT does not require international fare reporting in the same dataset.
**Solution:** Pivoted the primary build to a domestic connecting market (Austin-Salt Lake City on Delta) and demoted the international alliance/JV variant to a documented expansion phase (see EXPANSION_ROADMAP.md).

---

## Market selection

**Decision point:** Which route should DESTER evaluate?
**Constraint:** Needed to be (a) domestic, for DB1B compatibility, (b) tied to a real, recent network-planning decision for credibility, and (c) structurally set up so a "local-only" verdict could plausibly fail and a "with feed" verdict could plausibly flip it.
**Resolution:** Locked on Austin (AUS) - Salt Lake City (SLC), Delta. Austin is a real, recently expanding Delta focus city; Salt Lake City is a genuine Delta hub, but small enough that the local market is a believable no-go case on its own, making the feed layer's contribution legible.

---

## [Future entries added here as each layer is built]

---

## Data acquisition (Layer 0)

**Problem:** DB1B was discontinued as the live data feed. BTS confirms O&D data collection moved to DB1C (monthly, 40% sample) effective July 2025; DB1B (quarterly, 10% sample) is archival only, with its last usable quarter being 2025 Q2.
**Resolution:** Used DB1B for now, since the historical archive is what's needed to validate a real-world route decision; noted that a future pass could re-point Layer 0 at DB1C for anything post-July-2025.

**Problem:** TranStats' individual field-selection download (choosing exact columns via checkboxes, then clicking Download) repeatedly failed with a dropped-connection error on the DL_SelectFields.aspx page.
**Cause:** The field-selector endpoint appears to be an older, fragile part of TranStats that times out under certain filter/field combinations.
**Solution:** Switched to the "Prezipped File" option instead, which downloads BTS's own pre-built full CSV for the quarter (all fields included). Column selection is done locally in pandas instead of via the TranStats UI.

**Problem:** The Filter Year dropdown silently reset from 2025 back to a default (2024) after changing Filter Period, so the first successful download was for 2024 Q2 rather than the intended, more recent 2025 Q2.
**Resolution:** Used the 2024 Q2 file to build and debug the Layer 0 pipeline first, with 2025 Q2 to be downloaded and swapped in once the pipeline is proven to work end-to-end.

**Problem:** The prezipped file auto-extracted on download (via Safari/macOS), leaving a folder in ~/Downloads rather than a .zip archive. A blind `mv *.zip` fallback command consequently grabbed unrelated zip files from Downloads (a large video file, an unrelated coding project, a resumes archive) into layer0/data/ by mistake.
**Solution:** Moved the unrelated files back to Downloads; located the actual CSV inside the auto-extracted folder and moved only that file (plus its readme.html) into
cat >> docs/PROBLEMS_AND_SOLUTIONS.md << 'EOF'

---

## Data acquisition (Layer 0)

**Problem:** DB1B was discontinued as the live data feed. BTS confirms O&D data collection moved to DB1C (monthly, 40% sample) effective July 2025; DB1B (quarterly, 10% sample) is archival only, with its last usable quarter being 2025 Q2.
**Resolution:** Used DB1B for now, since the historical archive is what's needed to validate a real-world route decision; noted that a future pass could re-point Layer 0 at DB1C for anything post-July-2025.

**Problem:** TranStats' individual field-selection download (choosing exact columns via checkboxes, then clicking Download) repeatedly failed with a dropped-connection error on the DL_SelectFields.aspx page.
**Cause:** The field-selector endpoint appears to be an older, fragile part of TranStats that times out under certain filter/field combinations.
**Solution:** Switched to the "Prezipped File" option instead, which downloads BTS's own pre-built full CSV for the quarter (all fields included). Column selection is done locally in pandas instead of via the TranStats UI.

**Problem:** The Filter Year dropdown silently reset from 2025 back to a default (2024) after changing Filter Period, so the first successful download was for 2024 Q2 rather than the intended, more recent 2025 Q2.
**Resolution:** Used the 2024 Q2 file to build and debug the Layer 0 pipeline first, with 2025 Q2 to be downloaded and swapped in once the pipeline is proven to work end-to-end.

**Problem:** The prezipped file auto-extracted on download (via Safari/macOS), leaving a folder in ~/Downloads rather than a .zip archive. A blind `mv *.zip` fallback command consequently grabbed unrelated zip files from Downloads (a large video file, an unrelated coding project, a resumes archive) into layer0/data/ by mistake.


**Solution:** Moved the unrelated files back to Downloads; located the actual CSV inside the auto-extracted folder and moved only that file (plus its readme.html) into layer0/data/.
**Follow-up safeguard:** Added layer0/data/ to .gitignore immediately, since the raw CSV is 2.15 GB, far too large for git, and raw data shouldn't be version-controlled regardless.

---

## Layer 0 build

**Non-obvious behavior (no fix required):** The first `pd.read_parquet` call in a fresh Python process takes roughly 2.25 seconds due to one-time pyarrow engine initialization, not file I/O. A warm second read of the same file completes in ~2 ms.
**Why it matters:** The Layer 0 success criterion "parquet loads in under 1 second" refers to steady-state read performance, not the cold-start of the pyarrow engine. Anyone benchmarking Layer 0's output should time a second read, not the first.

**Problem (resolved):** The `README.md` file was found to still contain heredoc-corruption artifacts — a stray `cat > README.md << 'EOF'` line near the top and a trailing `EOF` line at the bottom, plus a duplicated `# DESTER` header. These matched the same class of paste-interruption bug already logged in the setup-phase section of this document.
**Cause:** Multiple mid-paste interruptions during earlier heredoc-based file writes left orphan opener/closer lines that were never cleaned up.
**Solution:** Removed the artifacts surgically with three `sed -i ''` deletions targeting the exact offending lines. Verified the file with `head` and `tail` before committing.
**Pattern to avoid going forward:** For any docs longer than ~30 lines, prefer editing directly in the VS Code editor rather than terminal heredocs, or check `head`/`tail` immediately after every heredoc write.

---

## Data year swap: 2024 Q2 → 2025 Q2

**Decision point:** Layer 0 was initially built and tested against DB1BMarket 2024 Q2 to keep development moving. That worked, but 2024 Q2 predates the actual Delta AUS-SLC network-planning decision (announced early 2026 for Nov 2026 launch), which weakens DESTER's research posture — the model was running on data an airline planner making the real decision would not yet have leaned on.
**Resolution:** Re-downloaded DB1BMarket for 2025 Q2 (the last quarter of DB1B before it was replaced by DB1C in July 2025), placed it in `layer0/data/`, deleted the 2024 Q2 file, and re-ran `python -m layer0.pipeline`. Because Layer 0's pipeline was correctly built to glob for `layer0/data/*.csv` rather than hardcode a filename, no code changes were needed.
**What changed in the data:** Row count 3,381 → 2,933 (-13%); passenger sample flat at ~5,800; mean fare $281 → $251 (-11%); Frontier's share doubled (3% → 6%), displacing American from fourth to fifth in carrier ranking. Interpretation: the AUS-SLC market softened on price between the two years, consistent with more ultra-low-cost carrier presence — legitimate texture for Verdict 2's eventual feed-rescue argument.
**Follow-up:** Form 41 P-5.2 was downloaded for 2024 Q2 during initial data acquisition, but immediately discarded and will be re-downloaded for 2025 Q2 to match.

---

## Layer 1 Wave 1

**Problem:** During Wave 1 implementation, statsmodels' default Newton solver silently diverged when fitting the multinomial logit. Every non-base-carrier coefficient came back as NaN, but the solver still printed "Optimization terminated successfully" and returned a fitted model. Downstream, this produced a backtest with a suspiciously uniform ablation table (every feature contributed +0.00pp) — the tell that the underlying fit was degenerate.
**Cause:** The feature scales were badly mismatched (`seats_per_departure` ranged 0–260 while `hub_dominance` was 0–1), which is a well-known cause of divergence in Newton-based logit solvers. The solver's success message referred to the optimization loop terminating, not to the parameters being finite.
**Solution:** Standardize features before fitting; switch the solver to `lbfgs` which is more robust to scale mismatch; transform the fitted coefficients back to the raw-feature scale before saving, so `logit_coefficients.json` and `predict_shares()` remain interpretable and honest.
**Why this matters for the log:** A future implementer or reviewer running the pipeline needs to know that statsmodels can succeed-in-form while failing-in-substance. The uniform ablation table is the diagnostic; treat it as the signal.

**Problem:** Wave 1's backtest missed its ≤15pp MAE validation target, coming in at 16.12pp pooled MAE and 32.23pp RMSE. Diagnostic tracing points at the `hub_dominance` feature as the leading cause.
**Cause:** The Wave 1 spec defined `hub_dominance = 0 for nonstop itineraries`. The intent was to capture the hub carrier's connecting-market advantage. But for a nonstop out of a carrier's own hub — e.g. Delta operating ATL–MSP nonstop from its ATL hub — this is exactly where the hub advantage is strongest, and the feature is being switched off precisely there. The model consequently predicted 85% F9 share and ~0% DL share on ATL–MSP, where DL actually holds 68%.
**Solution:** Revise the Wave 1 spec so `hub_dominance` fires for nonstops based on the *origin airport's* dominance for the operating carrier, keeping the existing connecting-hub definition for one-stop itineraries. Also drop `seats_per_departure` from the feature set (ablation showed it worsens test MAE by 2.58pp) and inspect the log_fare pipeline for data-cleaning irregularities before the re-fit. Wave 1 is not considered validated until MAE clears the threshold on a re-run.

---

## Wave 1 iteration findings

**Finding (research-level limitation, accepted):** Wave 1 backtest MAE settled at 13.34pp — inside the pre-registered 15pp validation target — but the error distribution is bimodal: median per-market-carrier error is 0.99pp while the worst 10 predictions are all 80–96pp misses, and every one of those catastrophic misses is the model predicting an ultra-low-cost carrier (Frontier, Spirit) at 80–98% share in a market where the ULCC actually holds under 2%.
**Diagnosis:** With `y=carrier` as MNLogit's classification target, thin-data carriers (e.g. MX with 27 rows, F9 with 805) get large positive fixed-effect intercepts fit to the few niche markets where they do hold high share. At predict time those intercepts dominate the softmax in unrelated test markets. The fitted intercepts illustrate this: MX = 26.5, G4 = 13.6, F9 = 6.8, NK = 6.0, while DL, UA, AA (the incumbents that actually dominate most hub markets) sit between −1.0 and +0.9.
**Decision:** Wave 1 is considered validated per the pre-registered criterion (≤15pp MAE). The ULCC distortion is accepted as a documented limitation rather than fixed now, for two reasons. First, moving the validation goalpost after seeing the data would be a bigger research-integrity concern than a diagnosed known weakness. Second, AUS-SLC's real Frontier share (~6%) sits inside the range where the model performs well, so the specific market DESTER answers for is not on the catastrophic tail. A minimum-support threshold or partial-pooling regularization on carrier intercepts is documented as a future refinement.

**Finding (data-quality signal, no fix now):** Wave 1's log-fare diagnostic flagged 156 of ~5,290 training rows with fares below $10 (some as low as $2.86). Layer 0 already drops non-positive fares, but doesn't drop implausibly-low positive fares. Likely explanations: companion tickets, distressed inventory, or DB1B artifacts not caught by the BulkFare flag.
**Decision:** Not treated as a blocking issue for Wave 1 (the log transform compresses the effect of these rows), but flagged as a candidate refinement for Layer 0's `clean_and_type` if backtest accuracy becomes a binding constraint in future iterations.

---

## Wave 2 findings

**Finding (research-level, changes downstream design):** Wave 2 produced Verdict 1 = GO for AUS-SLC on Delta, robust across all 48 sensitivity combinations (uplift 10–25%, recapture 10–30%, S-curve α 1.4–1.8). This contradicts the pre-registered expectation that local demand alone would fail, which was explicitly documented in the Wave 2 spec as the "expected Verdict 1 outcome."
**Diagnosis:** AUS-SLC's local market is not thin in absolute terms — 267K annual O&D passengers with stimulation. What is small is Delta's proposed *product*: 2x-daily 76-seat E175 provides ~54K annual seats, which even at a 20% share of a 267K-pax market runs at 94–97% load factor. The GO verdict reflects a healthy market oversubscribing a small aircraft, not a thin market being viable on Delta metal.
**Implication for Layer 2:** The original Layer 2 framing ("does feed rescue Verdict 1's no-go?") is no longer meaningful because Verdict 1 does not fail on local demand. Layer 2 must be redefined before build. Two candidates: (a) feed as an *addition* to already-viable local demand, quantifying how much of Delta's economic case is local vs. feed; or (b) a frequency/capacity optimization asking whether 2x-daily E175 is the right product size given the demand this market already shows. Choice deferred to next session.

**Problem (real unit-scale silent bug, resolved):** Form 41 Schedule P-5.2's `TOT_AIR_OP_EXPENSES` column is reported in thousands of dollars — a standard BTS convention not surfaced in the field-selector UI. The initial Wave 2 build treated the value as raw dollars, producing a CASM of ~0.007 cents/ASM (three orders of magnitude too low) and an implied annual route cost of ~$4,000. That alone would have manufactured a GO verdict regardless of demand.
**Resolution:** Detected during Claude Code's own sanity check of the CASM magnitude; fixed by scaling `TOT_AIR_OP_EXPENSES` by 1000 in `pnl.compute_delta_e175_casm`. Corrected CASM = 6.566 cents/ASM, which is in the expected range for a 76-seat regional jet.
**Pattern worth noting:** BTS financial fields with the suffix "(000)" in the field description are always in thousands of dollars. Any future Form 41 field reads should check this before use.

**Discovery (industry structure, worth documenting):** Delta mainline (`CARRIER=DL`) has no aircraft type in the 70–82 seat band in either T-100 or Form 41 P-5.2 for 2025 Q2. E175 flying under the "Delta Connection" brand is filed under the operating regional partner's own carrier code — primarily SkyWest (`OO`), with lesser presence from Endeavor (`9E`), Republic (`YX`), and Mesa (`YV`). Delta pays these operators under capacity-purchase agreements at approximately their operating cost plus a documented markup (typically 8–15%).
**Implication for the model:** DESTER's cost side must use the *regional partner's* CASM plus a documented CPA markup, not Delta mainline's cost basis. Wave 2 currently uses SkyWest's raw CASM without the markup applied, which understates Delta's true effective cost. Applying the industry-standard ~12% CPA markup would raise the CASM to ~7.35 cents/ASM, still comfortably below the revenue side — the GO verdict does not change, but the reported contribution shrinks. Worth revisiting in a future refinement pass.

---

## Layer 2 findings

**Finding (research-level, changes Layer 3's expected result):** Feed represents 13% of Delta's AUS-SLC revenue and 15.6% of passengers — below the 20% Layer 3-leverage threshold pre-registered in the Layer 2 spec. Top feed markets are Boise, Jackson Hole, Spokane, Kalispell, Missoula, and Portland — genuine SLC hub connections, not spurious. AUS-SLC is fundamentally a local point-to-point market (84% of passengers are true AUS↔SLC O&D), not a hub-feeder market.
**Implication for Layer 3:** Because feed is small, the Shapley-vs-mileage attribution question can only shift Delta's total contribution by at most ~15% (upper bound: reassigning all feed revenue). This is unlikely to flip the go/no-go verdict for AUS-SLC. Layer 3 will still be built and run per the pre-registered thesis — the honest answer to a pre-registered question, even a negative one, is a legitimate research finding — but Layer 4 will apply the same three-verdict engine to a hub-heavy market with much higher feed share, so the attribution mechanism can be characterized in the regime where it matters.
**Why not switch markets:** Switching Layer 3's evaluation market after seeing that AUS-SLC's feed is small would be moving the goalposts. Pre-registered hypotheses that return null results are more valuable, not less. AUS-SLC's null result on Verdict 3 combined with a positive result on a hub-heavy market in Layer 4 is a stronger contribution than either alone.

**Problem (real bug, resolved during Layer 2 build):** The literal feed extraction rule (`MktCoupons == 2` + `AirportGroup` substring match + market pair != AUS-SLC) admitted itineraries where AUS or SLC was a routing waypoint rather than a true endpoint — e.g. an SLC-PIT itinerary routed via AUS (`AirportGroup = "SLC:AUS:PIT"`) contains "SLC:AUS" as a substring but has nothing to do with AUS-SLC feed. This showed up as 409 rows with a bogus "SLC" `beyond_endpoint` in the first run.
**Solution:** Added `Origin == "AUS" or Dest == "AUS"` as an additional filter condition, consistent with the spec's own `feed_direction` and `beyond_endpoint` definitions which only make sense under that assumption.

**Problem (real bug, resolved during Layer 2 build):** The first version of `combined_pnl` used Layer 2's great-circle constant (1,085 mi, meant only for Layer 2's mileage-proration fare allocation) to compute ASMs for the cost side, rather than the mean market distance (1,139.6 mi) that Verdict 1 used. This silently produced a slightly different cost figure than Verdict 1's, contradicting the spec's explicit "feed does not change the cost of flying the aircraft."
**Solution:** Threaded `distance_miles` through from Layer 0's `summary.json`, matching Wave 2's cost computation exactly. Added a sanity-check assertion that the recomputed local contribution matches Verdict 1's stored `$9,097,265` figure, so a similar regression cannot go unnoticed in future refactors.
