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
