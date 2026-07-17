# DESTER

**Feed-dependent airline route business-case engine with game-theoretic revenue attribution.**

**Thesis (one line):** *The dollar value an airline attributes to a route can move materially depending on how connecting ("feed") revenue is split between the segments that carry the passenger — mileage proration vs. Shapley value.*

DESTER evaluates a proposed airline route the way a network-planning desk does — size the market, predict carrier share, model stochastic spill, build a route P&L — and then exposes a mechanism most analyses ignore: the route's economics are sensitive to the revenue-attribution rule applied to connecting traffic. The output is not simply "profitable / not profitable" but a characterization of *how much the attribution rule moves the answer, and when it matters.*

## Key documents

The three core research documents live in [`deliverables/`](deliverables/), each in both PDF and Markdown:

| Document | PDF | Markdown |
|----------|-----|----------|
| **Research Findings** — the full research paper: method, results, three-market study, population screener | [PDF](deliverables/RESEARCH_FINDINGS.pdf) | [MD](deliverables/RESEARCH_FINDINGS.md) |
| **Technical Architecture** — layer-by-layer system reference | [PDF](deliverables/TECHNICAL_ARCHITECTURE.pdf) | [MD](deliverables/TECHNICAL_ARCHITECTURE.md) |
| **Problems & Solutions** — the substantive obstacles, decisions, and honest research findings | [PDF](deliverables/PROBLEMS_AND_SOLUTIONS.pdf) | [MD](deliverables/PROBLEMS_AND_SOLUTIONS.md) |

## Research framing

DESTER is a research project, not just a calculator. It incorporates known, citable models and tests a falsifiable hypothesis.

- **Models incorporated:** multinomial logit discrete-choice model (share), the frequency S-curve, stochastic spill & recapture, and the Shapley value from cooperative game theory.
- **What it predicts:** each competing itinerary's share of an O&D market (-> projected passengers) and expected spill under stochastic demand.
- **How it is evaluated:** the logit share model is backtested against *realized* DB1B market shares on existing routes (backtest MAE 9.94pp after empirical-Bayes shrinkage on carrier intercepts).
- **Research hypothesis:** does a proposed route's go/no-go verdict change depending on the connecting-revenue attribution regime — standard mileage proration vs. Shapley-value proration?

## Core narrative — three verdicts

- **Verdict 1 — local-only.** Go/no-go on point-to-point O&D demand alone.
- **Verdict 2 — with feed.** Add behind/beyond connecting traffic. Total traffic and revenue rise.
- **Verdict 3 — attribution.** Split the connecting fare across segments two ways — mileage proration vs. Shapley — and measure whether, and by how much, the route's economics depend on which regime applies.

## Headline findings

- Attribution leverage is real and material — up to **$5.4M annually** on a single route (ATL-SAT).
- Across three rigorously analyzed markets (AUS-SLC, ATL-SAT, MIA-SEA), spanning 9%-54% feed share, **no verdict flips** — the mechanism is bounded, not decisive.
- **Feed share is necessary but not sufficient** for attribution leverage: MIA-SEA (9% feed, 1.3% leverage) vs. AUS-SLC (13% feed, 5.7% leverage).
- A population screener flags **106 of 921 markets (11.5%)** as containing possible flips; rigorous re-analysis shows this is an **upper bound** (fast screening overestimates leverage).

## Architecture

Layered Python modules (`layer0` ... `layer4`), each independently testable.

- **Layer 0 — Data pipeline.** Raw DB1BMarket -> clean, typed O&D dataset for a chosen market.
- **Layer 1 — Local-only business case.** Market sizing; multinomial logit share model; frequency S-curve; stochastic spill & recapture; route P&L. -> Verdict 1.
- **Layer 2 — Add the feed.** Enumerate behind/beyond connecting markets; re-run demand & P&L on a network basis. -> Verdict 2.
- **Layer 3 — Revenue attribution.** Model each connecting itinerary as a cooperative game; compute Shapley value per segment; compare against mileage proration. -> Verdict 3.
- **Layer 4 — Second-market comparison & screener.** Systematic screen of US spoke-to-hub markets; rigorous case studies (ATL-SAT, MIA-SEA); population-scale sensitivity characterization.

## Repository structure

    dester/
    |-- layer0/         # data pipeline: DB1BMarket -> clean O&D
    |-- layer1/         # local-only business case -> Verdict 1
    |-- layer2/         # feed / connecting markets -> Verdict 2
    |-- layer3/         # Shapley attribution -> Verdict 3
    |-- layer4/         # second market + screener
    |-- preprocess/     # aggregation for population-scale on-demand analysis
    |-- dashboard/      # Streamlit interactive dashboard
    |-- data/           # committed lightweight aggregates
    |-- deliverables/   # research paper, architecture, problems & solutions (PDF + MD)
    |-- requirements.txt
    |-- README.md

## Dashboard

An interactive Streamlit dashboard exposes DESTER on three featured markets, a browsable market catalog, and any custom O&D pair on demand.

    streamlit run dashboard/app.py

## Data sources (all free, US DOT BTS)

- **DB1BMarket** — O&D itineraries and fares (10% ticket sample). *Domestic only.*
- **T-100 Segment** — segment traffic and capacity.
- **Form 41 Schedule P-5.2** — carrier operating expenses (unit costs).

## The domestic pivot

DB1BMarket contains **domestic** O&D fares only, so the build substrate is a **domestic connecting market** routed over a US hub. The **international alliance JV variant** (a thin transatlantic route under a metal-neutral JV, where proration between partners is real money) is retained as a documented **expansion phase**, pending an international O&D data source.
