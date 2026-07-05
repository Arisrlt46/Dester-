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
