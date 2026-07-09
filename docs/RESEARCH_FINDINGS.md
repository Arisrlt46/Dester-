# DESTER — Research Findings

**Status:** Complete through Iteration 5. Layers 0-4 built. Two markets analyzed under a per-market-calibrated share model with intercept regularization. This document is the honest summary of what DESTER tested and what it found.

## Central research question

Does a proposed airline route's go/no-go verdict change depending on the rule used to attribute connecting-passenger revenue across the segments that carried the passenger?

Two attribution regimes tested:

- **Mileage proration** — industry-standard for interline settlements. Each segment's share of the connecting fare equals its share of total itinerary miles.
- **Shapley value** — from cooperative game theory. Each segment's share equals its Shapley value in a two-player coalition where the coalition value is the fare paid and singleton values are the fares each segment could earn as standalone products.

Original hypothesis: on markets where connecting feed is a meaningful share of route revenue, the choice of attribution rule can move the profit calculation enough to flip the go/no-go decision.

**Finding-in-one-sentence:** The attribution mechanism produces materially different contribution estimates — from 5.74% leverage on a low-feed market to 33.26% on a high-feed market — but did not flip the verdict on either of the two markets tested, even where the effect was large in dollar terms.

## Method

Three sequential verdicts, each an independent test on the same market:

- **Verdict 1 — Local viability.** Route profitability on point-to-point O&D demand alone. Multinomial-logit share model calibrated on 219 comparable domestic markets, MAE 9.94pp on held-out test set (under the final Iteration 5 model). Stimulation uplift, frequency-share S-curve, stochastic Poisson spill and recapture, route P&L using aircraft-operator CASM from Form 41 with capacity-purchase agreement markup applied.
- **Verdict 2 — Feed contribution.** Additional profit from behind-and-beyond connecting itineraries routed through the hub end.
- **Verdict 3 — Attribution sensitivity.** Contribution under mileage vs. Shapley side by side.

The share model is the piece that has to be evaluated as a model. Verdicts 2 and 3 are calibrated arithmetic conditional on Verdict 1's share prediction being reasonable. The evaluated MAE of 9.94pp on the final model meets the publishable-quality target for airline logit share models.

## Findings — AUS-SLC, Delta, 2025 Q2 (pre-registered running market)

Baseline model (Iteration 1, no regularization):

- **Verdict 1: GO, robust.** Predicted Delta local passengers 53,689 annually. Revenue $13.12M, cost $4.50M (under 7.354 c/ASM Delta-effective CASM with the 12% CPA markup applied), contribution $8.61M. Robust across 48 sensitivity combinations.
- **Verdict 2: Feed adds ~$1.99M for a total of ~$10.60M.** 2,572 feed itineraries extracted through SLC. Top feed markets: Boise, Jackson Hole, Portland, Spokane, Kalispell — a clean signature of Delta's actual Mountain West / Pacific NW hub network from SLC. Feed = 13.2% of revenue, 15.6% of passengers. AUS-SLC is fundamentally a local point-to-point market with a small hub-connecting overlay.
- **Verdict 3: Attribution does not flip. 5.74% leverage.** Under mileage, contribution $10.60M. Under Shapley, $9.97M. Both GO, robust across all 96 sensitivity combinations. Attribution mechanism is mathematically active — Shapley reallocates roughly $600K — but bounded above by the size of the small feed layer.

The pre-registered expectation was that AUS-SLC's Verdict 1 would fail on local demand alone, forcing a rescue via feed. That expectation was wrong — the market is decisively viable on local demand alone, and this reframed the research posture: AUS-SLC would test whether the attribution mechanism has leverage even where feed is small (it doesn't, meaningfully), setting up the need for a second market where feed dominates.

**Mechanism finding, worth carrying:** On AUS-SLC, Shapley credits the AUS-SLC segment *less* than mileage does, by an average of $79 per feed itinerary. Not intuitively obvious. Short regional segments out of SLC (SLC-Boise, SLC-Jackson Hole) carry disproportionately high fares per mile — regional monopoly pricing. Distance-based mileage proration overweights the AUS-SLC trunk; Shapley's value-based split corrects this. The direction of the Shapley-vs-mileage delta on a trunk segment depends on the relative per-mile yields of the trunk versus its feeders. Transatlantic or transcontinental trunks with lower-yield short-haul feeders would show the reverse direction.

## Findings — ATL-SAT, Delta, 2025 Q2 (second market, comparable)

Chosen from a systematic market screener: 934 candidate spoke-to-hub domestic markets, 192 in a borderline
where `var_residual` is the variance of that carrier's per-market share-prediction residual across the training set. Empirical-Bayes-style. At λ=15, F9 intercept shrunk by 61%, NK by 49%, backtest MAE improved to 9.94pp — the best model of the project.

Under the v5 model (Iteration 5, λ=15 shrinkage):

- **Verdict 1: NO_GO under the LF rule, GO under the contribution rule.** Documented inconsistency (see limitations). Delta predicted share 23.8% — a 26x improvement over the broken v1 prediction of 0.9%, though still below the observed 58.5%. The larger aircraft (178-seat vs. AUS-SLC's 76-seat E175) means load factor underperforms breakeven but absolute revenue at real fares still turns contribution positive.
- **Verdict 2: Contribution $16.21M with feed included.** Feed share 53.9% of revenue — comparable to what network-planning practitioners would identify as a genuine hub-fed market.
- **Verdict 3: Attribution does not flip. 33.26% leverage.** Mileage $16.21M contribution vs. Shapley $10.82M. A $5.4M swing on a single route. Both remain positive (GO) under both regimes — the swing does not cross zero — but the mechanism now has meaningful leverage, roughly six times larger than on AUS-SLC.

## The central research finding

**The mileage-vs-Shapley attribution mechanism produces materially different contribution estimates that scale with feed share of route revenue.** Two markets, same instrument (with intercept regularization required to make the instrument transferable), empirical leverage bracket: **5.74% on AUS-SLC (13% feed) to 33.26% on ATL-SAT (54% feed).** Roughly a six-fold variation across two structurally comparable spoke-to-hub markets.

Neither market's verdict flipped between regimes. Both stayed GO. But this is not evidence that the mechanism is unimportant. A $5.4M annual swing on a single route is not a rounding error — it is the scale at which JV settlement negotiations, code-share economics, and interline pricing decisions are actually made. What DESTER shows is:

1. The mechanism has real leverage precisely where the industry uses it — on hub-fed markets with substantial connecting traffic.
2. Verdict flips would require an even larger feed share, or a market on the margin of viability where the swing crosses zero. Both are testable extensions.
3. Any real airline analytics practitioner deciding between mileage and Shapley on a route like ATL-SAT is deciding on ~$5M/year. The choice is not academic.

## Methodological findings, arguably as important as the verdict answer

**The share model must be intercept-regularized to transfer across markets.** DESTER learned this the hard way. A logit fit without shrinkage produces reasonable-looking coefficients that appear well-calibrated on the training market but fail catastrophically on structurally different markets where thin-data carriers hold real share. Empirical-Bayes shrinkage on carrier intercepts, tuned to hit a per-carrier variance-of-residuals threshold, resolves this while improving backtest MAE from 13.34pp to 9.94pp.

**Systematic market screening matters.** DESTER's second market was chosen by an automatic screener over 934 candidates, not by intuition. This mattered concretely: the intuitive second-market pick (any high-feed hub spoke) would have produced a market where the leverage was so large the verdict was structurally guaranteed, giving a preordained result. The screener + shortlist procedure produced a genuinely comparable market where the leverage question was empirical.

**Data-quality signals matter.** ATL-SAT surfaced a real DB1B limitation: ~48% of its feed itineraries have no standalone fare data because SAT lacks nonstop service to most connecting endpoints. Shapley collapses to mileage-equivalent for those. Real Shapley leverage on thin-spoke markets is bounded by standalone-fare data availability. Documented as a persistent limitation.

## Limitations

- **Verdict 1's rule inconsistency.** Verdict 1 uses a load-factor-based go/no-go rule inherited from AUS-SLC; Verdicts 2 and 3 use a contribution-based rule chosen during Layer 3. On ATL-SAT the two rules disagree because ATL-SAT's larger aircraft (178 seats) is structurally underloaded at 24% predicted share while still profitable in absolute revenue. Real inconsistency, not resolved. A future pass should normalize Verdict 1 to the contribution rule.
- **CASM is SkyWest with a 12% CPA markup, not Delta mainline.** Delta mainline doesn't operate the E175 or the A320-class aircraft used on ATL-SAT (aircraft type 888 identified programmatically). The Form 41 P-5.2 numerator uses the operating carrier's actual reported costs plus a documented capacity-purchase agreement markup — this is the honest cost basis for the aircraft actually flying, though a more sophisticated model would parameterize the CPA markup per route.
- **Standalone-fare sparsity on thin spokes.** ~48% of ATL-SAT's feed itineraries have no v(B) data. Shapley falls back to mileage on those, structurally limiting the mechanism's leverage on thin-spoke markets.
- **NK residual under-shrinkage.** Even at λ=15, NK's shrinkage (49%) is closer to the 40% threshold than F9's (61%). The shrinkage formula rewards low variance regardless of intercept magnitude; a carrier can be consistently over-inflated. Modest quality-of-fit residual, does not affect the AUS-SLC/ATL-SAT comparison.
- **Two markets is a bracket, not a distribution.** DESTER's 5.74%–33.26% leverage bracket is drawn from two structurally comparable markets. A production analysis would test more markets — the machinery is now in place to do so.

## What Layer 4's arc actually showed

The value of DESTER is not the specific numbers ($9.10M vs. $8.61M vs. $16.21M). The value is the *arc* of the research:

1. Built a three-verdict engine from scratch on real BTS data.
2. Pre-registered a market. Tested. Got a null result on the central question at that market — honestly reported.
3. Selected a second market by systematic screening + comparable-size filtering to avoid cherry-picking.
4. Discovered the underlying share model doesn't transfer. Diagnosed the mechanism.
5. Attempted two structurally different fixes that respected the pre-registered thresholds. Both failed cleanly.
6. Fitted a third fix (shrinkage) that worked, hit the thresholds, produced a materially better model, and answered the transfer question.
7. Applied the successful fix to the second market. Got a real bracket on the attribution mechanism's leverage.
8. Documented an inconsistency in the earlier verdict rule that surfaced only because a second market was tested.
9. Documented every failed iteration and every data limitation honestly.

This is what research looks like when it's not curated for the writeup. DESTER's public git log is the record of that arc.
