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

    # ── Directional prediction test ──
    # All share-count tilts are biased by price asymmetry: cheaper side yields
    # more shares per dollar AND is more likely to lose → systematic downward bias.
    # Dollar-weighted is biased upward for the mirror reason.
    # Must compare to analytical null baseline or use symmetric-market subset.

    # Biased reference measures
    both_resolved['net_share_excess'] = both_resolved['excess_side']
    both_resolved['net_share_correct'] = (
        both_resolved['net_share_excess'] == both_resolved['winning_outcome']
    )
    both_resolved['gross_share_excess'] = np.where(
        both_resolved['buy_up_shares'] >= both_resolved['buy_down_shares'], 'Up', 'Down')
    both_resolved['gross_share_correct'] = (
        both_resolved['gross_share_excess'] == both_resolved['winning_outcome']
    )
    both_resolved['dollar_excess'] = np.where(
        both_resolved['buy_up_cost'] >= both_resolved['buy_down_cost'], 'Up', 'Down')
    both_resolved['dollar_tilt_correct'] = (
        both_resolved['dollar_excess'] == both_resolved['winning_outcome']
    )
    net_share_acc = both_resolved['net_share_correct'].mean()
    gross_share_acc = both_resolved['gross_share_correct'].mean()
    dollar_tilt_acc = both_resolved['dollar_tilt_correct'].mean()

    # Analytical null: under equal-dollar buying, share excess falls on the
    # cheaper side. Null accuracy = rate at which cheaper side actually won.
    both_resolved['cheaper_side'] = np.where(
        both_resolved['vwap_up'] <= both_resolved['vwap_down'], 'Up', 'Down')
    both_resolved['null_correct'] = (
        both_resolved['cheaper_side'] == both_resolved['winning_outcome']
    )
    null_baseline_acc = both_resolved['null_correct'].mean()
    # Gross share excess should nearly always match cheaper side (given ~equal dollars)
    gross_null_agreement = (
        both_resolved['gross_share_excess'] == both_resolved['cheaper_side']).mean()

    # Symmetric subset: |VWAP_up - VWAP_down| < 5¢ reduces price-asymmetry bias.
    both_resolved['vwap_gap'] = (both_resolved['vwap_up'] - both_resolved['vwap_down']).abs()
    symmetric = both_resolved[both_resolved['vwap_gap'] < 0.05]
    symmetric_count = len(symmetric)
    symmetric_net_acc = (symmetric['net_share_correct'].mean()
                         if symmetric_count > 0 else float('nan'))
    symmetric_gross_acc = (symmetric['gross_share_correct'].mean()
                           if symmetric_count > 0 else float('nan'))
    sym_null_acc = (symmetric['null_correct'].mean()
                    if symmetric_count > 0 else float('nan'))
    # z-test: gross share tilt vs subset's own null (not 50%)
    if symmetric_count > 0 and 0 < sym_null_acc < 1:
        sym_se = np.sqrt(sym_null_acc * (1 - sym_null_acc) / symmetric_count)
        symmetric_z = (symmetric_gross_acc - sym_null_acc) / sym_se
    else:
        symmetric_z = float('nan')

    # Dollar allocation: per-market fraction spent on Up
    both_resolved['actual_up_dollar_frac'] = (
        both_resolved['buy_up_cost']
        / (both_resolved['buy_up_cost'] + both_resolved['buy_down_cost']))
    both_resolved['price_implied_up_frac'] = (
        both_resolved['vwap_up']
        / (both_resolved['vwap_up'] + both_resolved['vwap_down']))
    dollar_frac_mean = both_resolved['actual_up_dollar_frac'].mean()
    dollar_frac_std = both_resolved['actual_up_dollar_frac'].std()

    # Dollar allocation conditional on outcome.
    # Raw gap is biased: when Up wins, Up tends to be expensive, so equal-shares
    # buying mechanically puts more dollars on Up. Must compare actual gap to
    # price-implied gap (what an equal-shares, no-prediction buyer would produce).
    # Prediction only if actual gap > implied gap.
    up_won = both_resolved[both_resolved['winning_outcome'] == 'Up']
    down_won = both_resolved[both_resolved['winning_outcome'] == 'Down']
    dollar_frac_up_wins = up_won['actual_up_dollar_frac'].mean()
    dollar_frac_down_wins = down_won['actual_up_dollar_frac'].mean()
    dollar_frac_gap = dollar_frac_up_wins - dollar_frac_down_wins
    price_frac_up_wins = up_won['price_implied_up_frac'].mean()
    price_frac_down_wins = down_won['price_implied_up_frac'].mean()
    implied_gap = price_frac_up_wins - price_frac_down_wins
    excess_gap = dollar_frac_gap - implied_gap

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

    print(f"\nDirectional prediction test ({len(both_resolved):,} resolved):")
    print(f"  Biased measures (for reference):")
    print(f"    Net share tilt:    {net_share_acc*100:.1f}%  (DOWN bias — sells improve balance)")
    print(f"    Gross share tilt:  {gross_share_acc*100:.1f}%  (DOWN bias — raw cheap-side excess)")
    print(f"    Dollar tilt:       {dollar_tilt_acc*100:.1f}%  (UP bias — expensive side costs more)")
    print(f"  Null baseline (overall cheaper-side win rate): {null_baseline_acc*100:.1f}%")
    print(f"    Gross-null agreement: {gross_null_agreement*100:.1f}% of markets")
    print(f"  Symmetric subset (|VWAP gap| < 5c, n={symmetric_count:,}):")
    if symmetric_count > 0:
        print(f"    Subset null (cheaper wins): {sym_null_acc*100:.1f}%")
        print(f"    Gross share tilt: {symmetric_gross_acc*100:.1f}%  "
              f"(z={symmetric_z:+.2f} vs subset null)")
        print(f"    Net share tilt:   {symmetric_net_acc*100:.1f}%")
    print(f"  Dollar allocation conditional on outcome:")
    print(f"    Actual:        Up wins {dollar_frac_up_wins:.4f} / "
          f"Down wins {dollar_frac_down_wins:.4f}  (gap {dollar_frac_gap:+.4f})")
    print(f"    Price-implied: Up wins {price_frac_up_wins:.4f} / "
          f"Down wins {price_frac_down_wins:.4f}  (gap {implied_gap:+.4f})")
    print(f"    Excess gap: {excess_gap:+.4f} (actual - implied; >0 = prediction)")
    print(f"  Overall dollar alloc: mean Up frac {dollar_frac_mean:.4f} "
          f"(std {dollar_frac_std:.4f})")
    has_sym = symmetric_count >= 100
    # One-tailed: only flag prediction if bot does BETTER than null (z > 1.96).
    # Negative z = anti-prediction (consistent with equal-dollar buying noise).
    sym_predicts = has_sym and symmetric_z > 1.96
    # Prediction only if actual gap exceeds price-implied gap.
    dollar_predicts = excess_gap > 0.01
    if not has_sym:
        conclusion = "Inconclusive (insufficient symmetric markets)"
    elif sym_predicts or dollar_predicts:
        conclusion = "Evidence of directional prediction"
    else:
        conclusion = "No directional prediction"
    print(f"  Conclusion: {conclusion}")

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
            'net_share': float(net_share_acc),
            'gross_share': float(gross_share_acc),
            'dollar': float(dollar_tilt_acc),
            'null_baseline': float(null_baseline_acc),
            'gross_null_agreement': float(gross_null_agreement),
            'symmetric_gross': float(symmetric_gross_acc),
            'symmetric_net': float(symmetric_net_acc),
            'symmetric_null': float(sym_null_acc),
            'symmetric_count': symmetric_count,
            'symmetric_z': float(symmetric_z),
            'dollar_frac_gap': float(dollar_frac_gap),
            'implied_gap': float(implied_gap),
            'excess_gap': float(excess_gap),
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
            'tilt_net_share': float(net_share_acc),
            'tilt_gross_share': float(gross_share_acc),
            'tilt_dollar': float(dollar_tilt_acc),
            'tilt_null_baseline': float(null_baseline_acc),
            'tilt_symmetric_gross': float(symmetric_gross_acc),
            'tilt_symmetric_null': float(sym_null_acc),
            'tilt_symmetric_z': float(symmetric_z),
            'dollar_frac_mean': float(dollar_frac_mean),
            'dollar_frac_std': float(dollar_frac_std),
            'dollar_frac_gap': float(dollar_frac_gap),
            'implied_gap': float(implied_gap),
            'excess_gap': float(excess_gap),
            'sell_recovery_pct': (float(sell_proceeds_total / sell_market_buy_cost)
                                  if sell_market_buy_cost > 0 else 0),
        }
    }
