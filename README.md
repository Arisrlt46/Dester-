# DESTER

**Feed-dependent airline route business-case engine with game-theoretic revenue attribution.**

**Thesis (one line):** *Whether a proposed new route is a "go" can flip depending on how connecting ("feed") revenue is split between the segments/partners that carry the passenger.*

DESTER evaluates a proposed airline route the way a network-planning desk does — size the market, predict share, model spill, build a P&L — and then exposes a mechanism most analyses ignore: the route's verdict is sensitive to the revenue-attribution rule applied to connecting traffic. The conclusion is not "profitable / not profitable" but "here is the attribution rule that decides it."

## Research framing

DESTER is a research project, not just a calculator. It incorporates known, citable models and tests a falsifiable hypothesis.

- **Models incorporated:** multinomial logit discrete-choice model (QSI / share), the frequency S-curve, stochastic spill & recapture, and the Shapley value from cooperative game theory.
- **What it predicts:** each competing itinerary's share of an O&D market (-> projected passengers) and expected spill under stochastic demand.
- **How it is evaluated:** the logit share model is backtested against *realized* DB1B market shares on existing routes. Predictive accuracy on observed markets is what licenses forecasting an unbuilt route.
- **Research hypothesis:** does a proposed route's go/no-go verdict change depending on the connecting-revenue attribution regime — standard mileage proration vs. Shapley-value proration?

## Core narrative — three verdicts

- **Verdict 1 — local-only.** Go/no-go on point-to-point O&D demand alone. Thin markets typically fail here.
- **Verdict 2 — with feed.** Add behind/beyond connecting traffic (validated by minimum connect time). Total traffic and revenue rise; the verdict often flips to viable on a *network* basis.
- **Verdict 3 — attribution.** Split the connecting fare across segments two ways — mileage proration vs. Shapley — and ask whether the route's verdict depends on which regime applies to your metal. This is the contribution.

## Architecture

Layered Python modules (layer0 ... layer3), each independently testable, mirroring the POLYQUANT convention.

- **Layer 0 — Foundations (data pipeline).** Raw DB1B into clean O&D itineraries for a chosen market. Output: current O&D volume, fares, routings for any city pair.
- **Layer 1 — Local-only business case.** Market sizing (DB1B + stimulation uplift, gravity OLS cross-check); logit / QSI share model; frequency S-curve; stochastic spill & recapture; route P&L and breakeven load factor. Output: Verdict 1.
- **Layer 2 — Add the feed.** Enumerate behind/beyond connecting markets; validate sellable connections by minimum connect time; re-run demand & P&L on a network basis. Output: Verdict 2.
- **Layer 3 — Revenue attribution.** Model each connecting itinerary as a cooperative game (coalition value = fare); compute Shapley value per segment; compare against mileage proration. Output: Verdict 3.

## Repository structure

    dester/
    |-- layer0/      # data pipeline: DB1B -> clean O&D
    |-- layer1/      # local-only business case -> Verdict 1
    |-- layer2/      # feed / connecting markets -> Verdict 2
    |-- layer3/      # Shapley attribution -> Verdict 3
    |-- docs/        # design & research documentation
    |-- requirements.txt
    |-- .gitignore
    |-- README.md

**docs/**: ROADMAP, TECHNICAL_ARCHITECTURE, EVALUATION, RESEARCH_FINDINGS, PROBLEMS_AND_SOLUTIONS, EXPANSION_ROADMAP.

## Data sources (all free, US DOT BTS)

- **DB1B** — O&D itineraries and fares. *Domestic only.*
- **T-100** — segment traffic and capacity.
- **On-Time Performance** — schedule and reliability.
- **Form 41** — carrier financials (unit costs).

## Running example & the domestic pivot

DB1B contains **domestic** O&D fares only, so the primary build substrate is a **domestic connecting market** routed over a US hub. The **international alliance JV variant** (e.g. a thin transatlantic route under a metal-neutral JV, where proration between partners is real money) is retained as a documented **expansion phase**, pending an international O&D data source.

## Roadmap (phases)

- **Phase 0 — Foundations:** repo + tooling; DB1B -> clean dataframe for one city pair.
- **Phase 1 — Layer 1:** local-only business case -> Verdict 1.
- **Phase 2 — Layer 2:** add the feed -> Verdict 2.
- **Phase 3 — Layer 3:** Shapley attribution -> Verdict 3.
- **Stretch:** S-curve frequency optimizer; carbon-cost route economics; competitive-response Nash game; route-portfolio ranking mode.

## Status

Scaffolding. Repo initialized; docs/ to be populated; Layer 0 data pipeline is the immediate next build.
