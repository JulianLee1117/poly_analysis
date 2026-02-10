"""Phase 3a: Market structure analysis — categorize the crypto market universe."""

import re

import numpy as np
import pandas as pd

from storage.database import Database


def parse_market_questions(markets_df: pd.DataFrame) -> pd.DataFrame:
    """Parse crypto asset and time window from market question text.

    Format: "Solana Up or Down - January 19, 7:45AM-8:00AM ET"
    """
    def _parse(q):
        m = re.match(r'^(.+?)\s+Up or Down', q)
        asset = m.group(1).strip() if m else 'Unknown'
        tm = re.search(r'(\d{1,2}:\d{2}[AP]M)\s*[-\u2013\u2014]\s*(\d{1,2}:\d{2}[AP]M)', q)
        start = tm.group(1) if tm else ''
        end = tm.group(2) if tm else ''
        return pd.Series({'crypto_asset': asset, 'start_time': start, 'end_time': end})

    parsed = markets_df['question'].apply(_parse)
    return pd.concat([markets_df, parsed], axis=1)


def analyze_market_structure(db: Database, pms: pd.DataFrame) -> dict:
    """Categorize the crypto market universe.

    Args:
        db: Database instance
        pms: Per-market summary DataFrame from db.per_market_summary()

    Returns dict with markets_df, asset_distribution, and summary.
    """
    markets_df = db.load_markets()
    markets_df = parse_market_questions(markets_df)

    # Asset distribution
    asset_dist = markets_df['crypto_asset'].value_counts()

    # Sidedness from per-market summary
    pms = pms.copy()
    pms['is_both_sided'] = (pms['buy_up_shares'] > 0) & (pms['buy_down_shares'] > 0)
    pms['is_up_only'] = (pms['buy_up_shares'] > 0) & (pms['buy_down_shares'] == 0)
    pms['is_down_only'] = (pms['buy_up_shares'] == 0) & (pms['buy_down_shares'] > 0)

    both_sided = int(pms['is_both_sided'].sum())
    up_only = int(pms['is_up_only'].sum())
    down_only = int(pms['is_down_only'].sum())

    # Cross-reference: one-sided markets by crypto asset
    sidedness = pms[['condition_id', 'is_both_sided', 'is_up_only', 'is_down_only']]
    merged = markets_df.merge(sidedness, on='condition_id', how='left')
    one_sided = merged[merged['is_up_only'] | merged['is_down_only']]
    one_sided_by_asset = one_sided['crypto_asset'].value_counts()

    # One-sided win rate (did directional bet pay off?)
    pos = db.load_positions(closed_only=True)
    # Determine winning outcome from BOTH cur_price=1 and cur_price=0 positions
    # to avoid survivorship bias on one-sided markets
    pos_resolved = pos[pos['cur_price'].isin([0, 1])].copy()
    pos_resolved['winning_outcome'] = np.where(
        pos_resolved['cur_price'] == 1,
        pos_resolved['outcome'],
        pos_resolved['outcome'].map({'Up': 'Down', 'Down': 'Up'})
    )
    resolution = (pos_resolved[['condition_id', 'winning_outcome']]
                  .drop_duplicates('condition_id'))

    one_sided_pms = pms[pms['is_up_only'] | pms['is_down_only']].copy()
    one_sided_pms['bet_side'] = np.where(one_sided_pms['buy_up_shares'] > 0, 'Up', 'Down')
    one_sided_resolved = one_sided_pms.merge(resolution, on='condition_id', how='inner')
    one_sided_resolved['bet_correct'] = (
        one_sided_resolved['bet_side'] == one_sided_resolved['winning_outcome']
    )
    one_sided_win_rate = one_sided_resolved['bet_correct'].mean() if len(one_sided_resolved) > 0 else 0

    # NegRisk
    neg_risk_count = int(markets_df['neg_risk'].sum())

    # Volume/liquidity
    vol_stats = markets_df['volume'].describe()
    liq_stats = markets_df['liquidity'].describe()

    # Print findings
    print("\n" + "=" * 60)
    print("PHASE 3a: MARKET STRUCTURE")
    print("=" * 60)
    print(f"\nTotal markets: {len(markets_df):,}")

    print(f"\nCrypto assets ({len(asset_dist)} unique):")
    for asset, count in asset_dist.items():
        pct = count / len(markets_df) * 100
        print(f"  {asset:20s} {count:5,} ({pct:.1f}%)")

    print(f"\nSidedness:")
    print(f"  Both-sided: {both_sided:,} ({both_sided/len(pms)*100:.1f}%)")
    print(f"  Up-only:    {up_only:,} ({up_only/len(pms)*100:.1f}%)")
    print(f"  Down-only:  {down_only:,} ({down_only/len(pms)*100:.1f}%)")

    if not one_sided_by_asset.empty:
        print(f"\nOne-sided markets by asset:")
        for asset, count in one_sided_by_asset.head(5).items():
            total = asset_dist.get(asset, 0)
            print(f"  {asset:20s} {count:3,} / {total:,}")

    if len(one_sided_resolved) > 0:
        print(f"\nOne-sided directional accuracy:")
        print(f"  Resolved: {len(one_sided_resolved):,}, "
              f"correct: {one_sided_resolved['bet_correct'].sum():.0f} "
              f"({one_sided_win_rate*100:.1f}%)")

    print(f"\nNeg-risk markets: {neg_risk_count}")
    print(f"\nPer-market volume  — mean: ${vol_stats['mean']:,.0f}, "
          f"median: ${vol_stats['50%']:,.0f}, max: ${vol_stats['max']:,.0f}")
    print(f"Per-market liquidity — mean: ${liq_stats['mean']:,.0f}, "
          f"median: ${liq_stats['50%']:,.0f}, max: ${liq_stats['max']:,.0f}")

    return {
        'markets_df': merged,
        'asset_distribution': asset_dist,
        'one_sided_win_rate': one_sided_win_rate,
        'summary': {
            'total_markets': len(markets_df),
            'unique_assets': len(asset_dist),
            'both_sided': both_sided,
            'up_only': up_only,
            'down_only': down_only,
            'neg_risk': neg_risk_count,
            'one_sided_accuracy': float(one_sided_win_rate),
        }
    }
