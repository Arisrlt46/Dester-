"""Layer 4 Wave 1 follow-up: borderline shortlist comparable to AUS-SLC in size.

Wave 1's screener found 192 candidates in the [0.25, 0.45] borderline
feed-share band, but they vary hugely in absolute local market size. This
narrows that list to markets that are also structurally comparable to
AUS-SLC (~2,933 local sample passengers in the same quarter), so Wave 2
picks a comparable second market rather than a dramatic outlier.
"""

import os

import pandas as pd

LAYER4_OUT_DIR = os.path.join(os.path.dirname(__file__), "out")
MARKET_SCREENER_PATH = os.path.join(LAYER4_OUT_DIR, "market_screener.parquet")
SHORTLIST_PATH = os.path.join(LAYER4_OUT_DIR, "shortlist.parquet")

LOCAL_PAX_MIN = 1500
LOCAL_PAX_MAX = 5000

TOP_N_PRINTED = 10


def build_shortlist(market_screener_df):
    filtered = market_screener_df[
        market_screener_df["flag_borderline"]
        & (market_screener_df["local_pax_sample"] >= LOCAL_PAX_MIN)
        & (market_screener_df["local_pax_sample"] <= LOCAL_PAX_MAX)
    ]
    return filtered.sort_values("local_pax_sample", ascending=False).reset_index(drop=True)


def main():
    df = pd.read_parquet(MARKET_SCREENER_PATH)
    shortlist = build_shortlist(df)

    shortlist.to_parquet(SHORTLIST_PATH, engine="pyarrow", index=False)
    print(f"Wrote {SHORTLIST_PATH} ({len(shortlist)} rows)")

    print()
    print("=== Layer 4 borderline shortlist ===")
    print(f"Borderline candidates (flag_borderline): source table has {int(df['flag_borderline'].sum())}")
    print(f"Shortlist after local_pax_sample in [{LOCAL_PAX_MIN}, {LOCAL_PAX_MAX}]: {len(shortlist)}")

    if len(shortlist) == 0:
        print()
        print(
            "*** No borderline candidates fall within AUS-SLC's size band. This is itself a genuine "
            "finding: markets with meaningful feed leverage (feed_share 0.25-0.45) do not naturally occur "
            "at AUS-SLC's local scale in this data -- Wave 2's market choice would need to either relax "
            "the size band, relax the borderline band, or accept a size-mismatched comparison market. ***"
        )
    else:
        print(f"Top {min(TOP_N_PRINTED, len(shortlist))} by local_pax_sample descending:")
        cols = ["market_pair", "dominant_carrier", "dominant_carrier_share", "local_pax_sample", "feed_share"]
        for _, row in shortlist[cols].head(TOP_N_PRINTED).iterrows():
            print(
                f"  {row['market_pair']:10s} {row['dominant_carrier']:3s} "
                f"share={row['dominant_carrier_share']:.3f}  local_pax={row['local_pax_sample']:,.0f}  "
                f"feed_share={row['feed_share']:.3f}"
            )


if __name__ == "__main__":
    main()
