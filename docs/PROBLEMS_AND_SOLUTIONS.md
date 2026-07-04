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
