# DESTER — Research Findings

**Status:** Initial pass, after Layers 0-3 on the pre-registered running market (Austin - Salt Lake City, Delta Air Lines, DB1BMarket 2025 Q2). Layer 4 (second-market comparison) is planned but not yet implemented.

## Central research question

Does a proposed airline route's go/no-go verdict change depending on the rule used to attribute connecting-passenger revenue across the segments that carried the passenger?

Two attribution regimes were tested:

- **Mileage proration** — industry-standard for interline settlements. Each segment's share of the connecting fare equals its share of total itinerary miles.
- **Shapley value** — from cooperative game theory. Each segment's share equals its Shapley value in a two-player coalition where the coalition value is the fare paid and singleton values are the fares each segment could earn as standalone products.

The hypothesis: on a market where connecting ("feed") traffic is a meaningful share of the route's revenue, the choice of attribution rule can move the profit calculation enough to flip the go/no-go decision.

## Method

DESTER produces three sequential verdicts, each an independent test on the same running market:

- **Verdict 1 — Local viability.** Is the route profitable on point-to-point origin-destination demand alone, ignoring any connecting traffic? Answered via a multinomial-logit share model (calibrated against 219 comparable domestic markets, MAE 13.34pp on held-out test set), a stimulation uplift, a frequency-share S-curve, stochastic Poisson spill and recapture, and a route P&L using the aircraft operator's actual CASM from Form 41.
- **Verdict 2 — Feed contribution.** How much additional profit does the route capture from behind-and-beyond connecting itineraries routed through the hub end of the O&D? Answered by extracting connecting itineraries from DB1B, computing each carrier's observed share on those feed markets, and adding the resulting feed revenue to the Verdict 1 P&L.
- **Verdict 3 — Attribution sensitivity.** Does replacing mileage proration with Shapley on the feed itineraries change the total profit enough to flip the go/no-go verdict? Answered by recomputing Verdict 2's P&L under both attribution regimes side by side.

## Findings — AUS-SLC, Delta, 2025 Q2

### Verdict 1: GO, robust, but with a diagnostic reframing

Predicted Delta local passengers: 53,689 annually. Predicted revenue: $13.12M. Estimated cost using SkyWest E175 CASM at 6.57 cents per ASM: $4.02M. Contribution: $9.10M. Expected load factor 97%, breakeven load factor 30%. Robust across all 48 sensitivity combinations (stimulation uplift 10-25%, recapture rate 10-30%, S-curve alpha 1.4-1.8).

The pre-registered expectation was that Verdict 1 would come back **no-go** on local demand alone, then Verdict 2's feed layer would rescue it. That expectation was wrong. AUS-SLC's local origin-destination market is not thin — sized at approximately 267,000 annual passengers with stimulation uplift, it is a genuinely healthy market. What is thin is Delta's *product*: 2x daily on a 76-seat Embraer 175 provides roughly 54,000 annual seats. Even at a 20% share of the local market alone, the aircraft runs at capacity.

The reframing this forces: the interesting network-planning question for AUS-SLC is not "is the market viable" but "is Delta's chosen product size the right one." This is set aside for a later expansion layer.

### Verdict 2: Feed adds $1.99M, brings total to $11.09M

Extracted 2,572 connecting feed itineraries through SLC. Top feed markets by Delta revenue: Boise ($166K), Jackson Hole ($151K in the behind direction, $129K beyond), Boise beyond ($121K), then Spokane, Kalispell / Glacier, Missoula, and Portland — a clean signature of Delta's actual Mountain West and Pacific Northwest hub network from SLC.

Feed passengers annualize to 9,661 vs. 52,160 local — feed is 15.6% of passenger traffic. Feed revenue at $1.99M vs. local $13.12M — feed is 13.2% of revenue. AUS-SLC is fundamentally a local point-to-point market with a small but real hub-connecting overlay.

The pre-registered leverage threshold for Layer 3's attribution question was 20% of revenue. AUS-SLC came in below that at 13%, and this was flagged prominently as a diagnostic before Layer 3 was built.

### Verdict 3: Attribution does not flip the verdict (null result on the pre-registered central question)

Under mileage proration, Delta's total annual contribution on AUS-SLC is $11.09M. Under Shapley, it is $10.45M. The attribution swing is $636K — a 5.74% leverage on total contribution. Delta remains GO under both regimes, and the verdict does not flip on any of the 96 sensitivity combinations (48 parameter combinations × 2 regimes).

**This is the honest null result on DESTER's central research question for the pre-registered market.** The Shapley-vs-mileage attribution mechanism is mathematically active — Shapley reallocates real dollars — but the reallocation is bounded above by the size of the feed layer, which for AUS-SLC is too small to move a route that is decisively profitable on local demand alone.

Layer 4 will apply the same three-verdict engine to a hub-heavy market where feed represents a substantially larger share of total revenue. The hypothesis moves from "the mechanism can flip verdicts" to "the mechanism flips verdicts *when* feed exceeds some empirical share threshold." That is a sharper, more falsifiable hypothesis than the original.

## Mechanism finding

Shapley credits the AUS-SLC segment *less* than mileage proration does. Mean per-itinerary delta: -$79.02. Median: -$62.40. 115 of 2,572 itineraries received a strictly negative Shapley allocation on the AUS-SLC segment — reported honestly, not floored at zero.

The direction of this effect was not intuitively obvious a priori. The reason: short regional segments departing SLC — SLC-Boise, SLC-Jackson Hole, SLC-Kalispell — carry disproportionately high fares per mile relative to the AUS-SLC trunk. This is a regional monopoly pricing effect. Distance-based mileage proration therefore *overweights* the AUS-SLC trunk relative to what the segments could earn independently. Shapley's value-based split corrects this by giving each segment credit proportional to its standalone value contribution.

This has an implication worth flagging for Layer 4: the direction of the Shapley-vs-mileage delta on any given trunk segment depends on the relative per-mile yields of the trunk versus its feeder segments. On a market where the trunk is long-haul high-yield (transatlantic, transcontinental premium) and the feeders are short-haul lower-yield, the direction reverses — Shapley credits the trunk more, not less. This is the exact kind of nuance that makes the mileage-vs-Shapley question non-trivial for real airline alliance settlement work.

## Limitations

The findings above are honest for AUS-SLC in 2025 Q2, but four known limitations should be recorded.

- **Wave 1 logit — thin-carrier intercept distortion.** The multinomial logit share model shows large positive fixed-effect intercepts for ultra-low-cost carriers with few calibration observations (Frontier, Spirit, Silver). These intercepts inflate predicted ULCC share in markets where those carriers are not real competitors. Documented in `PROBLEMS_AND_SOLUTIONS.md`. Does not undermine Verdict 1 GO for AUS-SLC — if anything, correcting the distortion would shift predicted share toward incumbents like Delta and Southwest, strengthening the verdict — but a future refinement pass should apply a minimum-support threshold or partial-pooling regularization on carrier intercepts.
- **SkyWest CPA markup not yet applied.** Delta mainline does not operate the E175; the aircraft is flown by SkyWest under a capacity-purchase agreement, and Delta pays SkyWest at approximately SkyWest's operating cost plus a documented markup of roughly 8-15%. DESTER currently uses SkyWest's raw CASM at 6.57 cents per ASM. Applying an industry-standard 12% CPA markup would raise Delta's effective CASM to approximately 7.35 cents per ASM. Contribution shrinks proportionally but the GO verdict does not change. A future pass should apply this markup.
- **Near-zero fare rows in Wave 1 training data.** The fare-distribution diagnostic flagged 156 of ~5,290 training rows with fares below $10, some as low as $2.86. Layer 0's `clean_and_type` drops non-positive fares but does not drop implausibly-low positive ones. Likely explanations: companion tickets, distressed inventory, DB1B artifacts not caught by the BulkFare flag. Not a blocking issue — log-fare transformation compresses the effect — but a candidate refinement for Layer 0.
- **Pre-registered expectation on Verdict 1 was wrong.** The Wave 2 spec explicitly documented an expectation that Verdict 1 would fail. It did not. This is not a bug; it is a genuine research finding about the running market, and it is recorded honestly here rather than papered over.

## What Layer 4 will add

The AUS-SLC null result on Verdict 3 is credible precisely because AUS-SLC was pre-registered as the running market before any code was written. Switching markets after seeing that finding would be moving the goalposts.

Layer 4 will apply DESTER's three-verdict engine unchanged to a second market — a hub-heavy connecting route where feed represents a substantially larger share of total revenue (target: 50% or higher). Candidates include short-to-medium spokes into ATL (Delta's largest hub), DFW (American's largest hub), or ORD (United's largest hub). The specific market will be selected on the same automatic criterion Layer 1 used, with the addition of a minimum feed share to ensure the attribution mechanism has real leverage.

The Layer 4 output pairs with Verdict 3 above to characterize the mechanism: **the Shapley-vs-mileage attribution mechanism produces a verdict flip when feed share exceeds some empirical threshold, and produces a null result below that threshold.** DESTER's contribution is not to claim the mechanism always flips verdicts — that would be false and DESTER has already shown it — but to characterize *when* it does and does not, with a concrete empirical bracket from two contrasting real markets.
