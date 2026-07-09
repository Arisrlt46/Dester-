"""Layer 1 Wave 1 Iteration 5 orchestrator: shrinkage strength sweep.

Calls fit_and_shrink at lambda=15 and lambda=20, since Iteration 4's
lambda=10 left NK's shrinkage (39.1%) just under the 40% threshold while F9
passed (51.1%). Selects the lower passing lambda per the pre-registered
tie-break rule (less aggressive shrinkage preferred when both pass).
Runnable via `python -m layer1.iteration5.verdict1_wave1_v5`.
"""

from layer1.iteration5 import logit_v5

LAMBDA_VALUES = [15.0, 20.0]
ULCC_CARRIERS_OF_INTEREST = ["F9", "NK"]
MIN_PCT_REDUCTION = 0.40


def _check_stop_conditions(result):
    shrinkage_by_carrier = {row["carrier"]: row for row in result["shrinkage_table"]}
    ulcc_status = {c: shrinkage_by_carrier[c]["pct_reduction"] >= MIN_PCT_REDUCTION for c in ULCC_CARRIERS_OF_INTEREST}
    passes_a = not result["exceeds_danger_threshold"]
    passes_b = passes_a and all(ulcc_status.values())
    return passes_a, passes_b, ulcc_status


def main():
    results = {}
    for lambda_val in LAMBDA_VALUES:
        print(f"=== Fitting and shrinking at lambda={lambda_val} ===")
        result = logit_v5.fit_and_shrink(lambda_val)
        passes_a, passes_b, ulcc_status = _check_stop_conditions(result)
        result["passes_a"] = passes_a
        result["passes_b"] = passes_b
        result["ulcc_status"] = ulcc_status
        results[lambda_val] = result

        shrinkage_by_carrier = {row["carrier"]: row for row in result["shrinkage_table"]}
        print(f"  MAE={result['mae_pp']:.2f}pp  RMSE={result['rmse_pp']:.2f}pp")
        for carrier in ULCC_CARRIERS_OF_INTEREST:
            row = shrinkage_by_carrier[carrier]
            print(
                f"    {carrier}: fitted={row['fitted_intercept']:+.3f} -> shrunk={row['shrunk_intercept']:+.3f} "
                f"(reduction={row['pct_reduction']:.1%}, meets >= {MIN_PCT_REDUCTION:.0%}: {ulcc_status[carrier]})"
            )

        if not passes_a:
            print(f"  *** STOP CONDITION A at lambda={lambda_val}: MAE ({result['mae_pp']:.2f}pp) exceeds 15pp. Disqualified. ***")
        elif not passes_b:
            print(f"  *** STOP CONDITION B at lambda={lambda_val}: MAE holds but F9/NK not both >= {MIN_PCT_REDUCTION:.0%}. ***")
        else:
            print(f"  lambda={lambda_val} PASSES both stop conditions.")
        print()

    passing = sorted(lv for lv in LAMBDA_VALUES if results[lv]["passes_b"])

    print("=== Iteration 5 summary ===")
    for lambda_val in LAMBDA_VALUES:
        r = results[lambda_val]
        print(
            f"  lambda={lambda_val}: MAE={r['mae_pp']:.2f}pp  F9={r['ulcc_status']['F9']}  "
            f"NK={r['ulcc_status']['NK']}  passes={r['passes_b']}"
        )

    if not passing:
        print()
        print(
            "*** Neither lambda=15 nor lambda=20 passes both stop conditions. Not proceeding to Layer 4. "
            "See per-lambda detail above to diagnose whether shrinkage is the wrong lever or lambda needs "
            "to go higher yet. ***"
        )
        selected = None
    else:
        selected = passing[0]
        print()
        print(f"Selected lambda={selected} for Layer 4 (lowest passing value).")

    return selected, results


if __name__ == "__main__":
    main()
