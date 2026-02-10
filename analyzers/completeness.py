"""Phase 3b: Completeness arbitrage analysis — quantify the core strategy."""

import numpy as np
import pandas as pd

from storage.database import Database


def analyze_completeness(db: Database, pms: pd.DataFrame) -> dict:
    """Quantify the completeness arbitrage strategy.

    Two passes: gross (buy-only VWAPs) and net (after sells).
    Tiers by balance ratio to avoid misleading aggregate stats.

    Args:
        db: Database instance
        pms: Per-market summary DataFrame from db.per_market_summary()

    Returns dict with per-market metrics, tier summaries, spread evolution,
    and P&L verification.
    """
    df = pms.copy()

    # ── Gross VWAPs (buy-only) ──
    df['vwap_up'] = np.where(
        df['buy_up_shares'] > 0, df['buy_up_cost'] / df['buy_up_shares'], np.nan)
    df['vwap_down'] = np.where(
        df['buy_down_shares'] > 0, df['buy_down_cost'] / df['buy_down_shares'], np.nan)

    df['is_both_sided'] = (df['buy_up_shares'] > 0) & (df['buy_down_shares'] > 0)
    both = df[df['is_both_sided']].copy()

    # Combined VWAP = cost of one Up share + one Down share
    both['combined_vwap'] = both['vwap_up'] + both['vwap_down']
    both['spread'] = 1.0 - both['combined_vwap']

    # ── Net shares after sells ──
    both['net_up_shares'] = (both['buy_up_shares'] - both['sell_up_shares']).clip(lower=0)
    both['net_down_shares'] = (both['buy_down_shares'] - both['sell_down_shares']).clip(lower=0)

    # ── Balance ratio and matched pairs ──
    both['max_net'] = both[['net_up_shares', 'net_down_shares']].max(axis=1)
    both['min_net'] = both[['net_up_shares', 'net_down_shares']].min(axis=1)
    both['balance_ratio'] = np.where(both['max_net'] > 0,
                                     both['min_net'] / both['max_net'], 0)
    both['matched_pairs'] = both['min_net']
    both['unmatched_shares'] = both['max_net'] - both['min_net']
    both['excess_side'] = np.where(
        both['net_up_shares'] >= both['net_down_shares'], 'Up', 'Down')

    # Guaranteed profit from matched pairs
    both['guaranteed_profit'] = both['matched_pairs'] * both['spread']

    # ── Balance tiers ──
    both['balance_tier'] = pd.cut(
        both['balance_ratio'],
        bins=[-0.001, 0.33, 0.50, 0.80, 1.001],
        labels=['very_imbalanced', 'imbalanced', 'moderate', 'well_balanced']
    )

    tier_order = ['well_balanced', 'moderate', 'imbalanced', 'very_imbalanced']
    tier_summary = both.groupby('balance_tier', observed=True).agg(
        count=('condition_id', 'count'),
        avg_combined_vwap=('combined_vwap', 'mean'),
        avg_spread=('spread', 'mean'),
        median_spread=('spread', 'median'),
        total_matched=('matched_pairs', 'sum'),
        total_unmatched=('unmatched_shares', 'sum'),
        avg_balance=('balance_ratio', 'mean'),
        total_guar_profit=('guaranteed_profit', 'sum'),
    ).reindex(tier_order)

    # ── Sell impact ──
    has_sells = both[both['sell_fills'] > 0]
    sell_proceeds_total = (has_sells['sell_up_proceeds'].sum()
                           + has_sells['sell_down_proceeds'].sum())
    sell_market_buy_cost = (has_sells['buy_up_cost'].sum()
                            + has_sells['buy_down_cost'].sum())

    # ── Daily spread evolution ──
    both['date'] = pd.to_datetime(both['first_fill_ts'], unit='s', utc=True).dt.date
    daily_spread = both.groupby('date').agg(
        avg_spread=('spread', 'mean'),
        avg_vwap=('combined_vwap', 'mean'),
        markets=('condition_id', 'count'),
    ).sort_index()

    # ── P&L verification via positions resolution ──
    # Use BOTH cur_price=1 and cur_price=0 to determine winner —
    # avoids survivorship bias on one-sided markets
    pos = db.load_positions(closed_only=True)
    pos_resolved = pos[pos['cur_price'].isin([0, 1])].copy()
    pos_resolved['winning_outcome'] = np.where(
        pos_resolved['cur_price'] == 1,
        pos_resolved['outcome'],
        pos_resolved['outcome'].map({'Up': 'Down', 'Down': 'Up'})
    )
    resolution = (pos_resolved[['condition_id', 'winning_outcome']]
                  .drop_duplicates('condition_id'))

    # Both-sided resolved
    both_resolved = both.merge(resolution, on='condition_id', how='inner')
    both_resolved['resolution_payout'] = np.where(
        both_resolved['winning_outcome'] == 'Up',
        both_resolved['net_up_shares'],
        both_resolved['net_down_shares'])
    both_resolved['total_buy'] = both_resolved['buy_up_cost'] + both_resolved['buy_down_cost']
    both_resolved['total_sell'] = (both_resolved['sell_up_proceeds']
                                   + both_resolved['sell_down_proceeds'])
    both_resolved['trade_pnl'] = (both_resolved['resolution_payout']
                                  + both_resolved['total_sell']
                                  - both_resolved['total_buy'])

    # One-sided resolved
    one_sided = df[~df['is_both_sided']].copy()
    one_sided['net_up_shares'] = (one_sided['buy_up_shares']
                                  - one_sided['sell_up_shares']).clip(lower=0)
    one_sided['net_down_shares'] = (one_sided['buy_down_shares']
                                    - one_sided['sell_down_shares']).clip(lower=0)
    one_resolved = one_sided.merge(resolution, on='condition_id', how='inner')
    one_resolved['resolution_payout'] = np.where(
        one_resolved['winning_outcome'] == 'Up',
        one_resolved['net_up_shares'],
        one_resolved['net_down_shares'])
    one_resolved['total_buy'] = one_resolved['buy_up_cost'] + one_resolved['buy_down_cost']
    one_resolved['total_sell'] = (one_resolved['sell_up_proceeds']
                                  + one_resolved['sell_down_proceeds'])
    one_resolved['trade_pnl'] = (one_resolved['resolution_payout']
                                 + one_resolved['total_sell']
                                 - one_resolved['total_buy'])

    both_pnl = both_resolved['trade_pnl'].sum()
    one_pnl = one_resolved['trade_pnl'].sum()
    total_pnl = both_pnl + one_pnl

    # ── Directional prediction test (three measures to avoid bias) ──
    # Share-weighted tilt is biased DOWN (cheaper side yields more shares).
    # Dollar-weighted tilt is biased UP (expensive side costs more per share).
    # Price-residual tilt controls for both: does the bot allocate beyond
    # what market prices dictate?
    both_resolved['share_excess'] = both_resolved['excess_side']
    both_resolved['share_tilt_correct'] = (
        both_resolved['share_excess'] == both_resolved['winning_outcome']
    )
    both_resolved['dollar_excess'] = np.where(
        both_resolved['buy_up_cost'] >= both_resolved['buy_down_cost'], 'Up', 'Down')
    both_resolved['dollar_tilt_correct'] = (
        both_resolved['dollar_excess'] == both_resolved['winning_outcome']
    )
    # Price-residual: does bot overweight the winner BEYOND vwap-implied allocation?
    both_resolved['price_implied_up_frac'] = (
        both_resolved['vwap_up']
        / (both_resolved['vwap_up'] + both_resolved['vwap_down']))
    both_resolved['actual_up_dollar_frac'] = (
        both_resolved['buy_up_cost']
        / (both_resolved['buy_up_cost'] + both_resolved['buy_down_cost']))
    both_resolved['residual_excess'] = np.where(
        both_resolved['actual_up_dollar_frac'] >= both_resolved['price_implied_up_frac'],
        'Up', 'Down')
    both_resolved['residual_correct'] = (
        both_resolved['residual_excess'] == both_resolved['winning_outcome']
    )
    share_tilt_acc = both_resolved['share_tilt_correct'].mean()
    dollar_tilt_acc = both_resolved['dollar_tilt_correct'].mean()
    residual_tilt_acc = both_resolved['residual_correct'].mean()

    # ── Print findings ──
    print("\n" + "=" * 60)
    print("PHASE 3b: COMPLETENESS ARBITRAGE")
    print("=" * 60)

    print(f"\nBoth-sided: {len(both):,} / {len(df):,} ({len(both)/len(df)*100:.1f}%)")

    print(f"\nGross buy-only metrics (both-sided):")
    print(f"  Avg combined VWAP: ${both['combined_vwap'].mean():.4f}")
    print(f"  Avg spread:        ${both['spread'].mean():.4f}")
    print(f"  Median spread:     ${both['spread'].median():.4f}")

    print(f"\nBy balance tier:")
    for tier in tier_order:
        if tier in tier_summary.index and pd.notna(tier_summary.loc[tier, 'count']):
            r = tier_summary.loc[tier]
            pct = r['count'] / len(both) * 100
            print(f"  {tier:20s} {int(r['count']):5,} ({pct:5.1f}%)  "
                  f"VWAP ${r['avg_combined_vwap']:.4f}  "
                  f"spread ${r['avg_spread']:.4f}  "
                  f"matched {r['total_matched']:,.0f}")

    print(f"\nNet position (after sells):")
    print(f"  Total matched pairs: {both['matched_pairs'].sum():,.0f}")
    print(f"  Total unmatched:     {both['unmatched_shares'].sum():,.0f}")
    print(f"  Total guar. profit:  ${both['guaranteed_profit'].sum():,.0f}")

    print(f"\nSell impact ({len(has_sells):,} markets with sells):")
    print(f"  Total sell proceeds:  ${sell_proceeds_total:,.0f}")
    if sell_market_buy_cost > 0:
        print(f"  Recovery rate:        "
              f"{sell_proceeds_total/sell_market_buy_cost*100:.1f}%")

    print(f"\nDirectional tilt accuracy ({len(both_resolved):,} resolved):")
    print(f"  Share-weighted:  {share_tilt_acc*100:.1f}%  (biased DOWN — cheaper side gets more shares)")
    print(f"  Dollar-weighted: {dollar_tilt_acc*100:.1f}%  (biased UP — expensive side costs more)")
    print(f"  Price-residual:  {residual_tilt_acc*100:.1f}%  (unbiased — controls for market prices)")
    print(f"  Conclusion: {'No prediction beyond market prices' if residual_tilt_acc < 0.50 else 'Evidence of directional prediction'}")

    print(f"\nSpread evolution (daily avg, both-sided):")
    if len(daily_spread) >= 7:
        first_w = daily_spread.head(7)['avg_spread'].mean()
        last_w = daily_spread.tail(7)['avg_spread'].mean()
        delta = last_w - first_w
        direction = ("compressing" if delta < -0.002
                     else "expanding" if delta > 0.002 else "stable")
        print(f"  First week avg: ${first_w:.4f}")
        print(f"  Last week avg:  ${last_w:.4f}")
        print(f"  Trend: {direction} ({delta:+.4f})")

    print(f"\nSpread distribution (both-sided):")
    bins = [-np.inf, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, np.inf]
    bin_labels = ['< -10c', '-10 to -5c', '-5 to 0c', '0 to 5c',
                  '5 to 10c', '10 to 15c', '15 to 20c', '> 20c']
    both['spread_bucket'] = pd.cut(both['spread'], bins=bins, labels=bin_labels)
    for bucket in bin_labels:
        cnt = (both['spread_bucket'] == bucket).sum()
        pct = cnt / len(both) * 100
        bar = '#' * int(pct / 2)
        print(f"  {bucket:14s} {cnt:5,} ({pct:5.1f}%) {bar}")

    print(f"\nP&L verification:")
    print(f"  Both-sided resolved: {len(both_resolved):,} -> ${both_pnl:,.0f}")
    print(f"  One-sided resolved:  {len(one_resolved):,} -> ${one_pnl:,.0f}")
    print(f"  Total trade-derived: ${total_pnl:,.0f}")
    print(f"  Expected: ~$281,000")

    return {
        'per_market_df': both,
        'one_sided_df': one_sided,
        'tier_summary': tier_summary,
        'daily_spread': daily_spread,
        'resolved_df': both_resolved,
        'tilt_accuracy': {
            'share_weighted': float(share_tilt_acc),
            'dollar_weighted': float(dollar_tilt_acc),
            'price_residual': float(residual_tilt_acc),
        },
        'summary': {
            'both_sided_count': len(both),
            'one_sided_count': len(one_sided),
            'avg_combined_vwap': float(both['combined_vwap'].mean()),
            'avg_spread': float(both['spread'].mean()),
            'total_matched_pairs': float(both['matched_pairs'].sum()),
            'total_unmatched': float(both['unmatched_shares'].sum()),
            'total_guaranteed_profit': float(both['guaranteed_profit'].sum()),
            'total_trade_pnl': float(total_pnl),
            'tilt_accuracy_share': float(share_tilt_acc),
            'tilt_accuracy_dollar': float(dollar_tilt_acc),
            'tilt_accuracy_residual': float(residual_tilt_acc),
            'sell_recovery_pct': (float(sell_proceeds_total / sell_market_buy_cost)
                                  if sell_market_buy_cost > 0 else 0),
        }
    }
