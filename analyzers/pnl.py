"""Phase 5a: P&L decomposition — where does the $713K come from?

Three-component decomposition (sums exactly to trade_pnl per market):
1. Completeness spread: matched_pairs × (1 - combined_VWAP)
2. Directional drag: unmatched_shares × (resolution_price - excess_VWAP)
3. Sell P&L: sell_proceeds - sell_shares × buy_VWAP per side

Plus: maker rebates (separate — not in per-market trade P&L).
Plus: sell discipline counterfactual (what if no sells?).
"""

import numpy as np
import pandas as pd

from storage.database import Database


def analyze_pnl(db: Database, completeness_result: dict,
                structure_result: dict) -> dict:
    """Decompose P&L into components and reconcile with position ground truth.

    Args:
        db: Database instance
        completeness_result: Output from analyze_completeness()
        structure_result: Output from analyze_market_structure()

    Returns dict with decomposition, reconciliation, daily P&L, win/loss stats.
    """
    resolved = completeness_result['resolved_df'].copy()
    markets_df = structure_result['markets_df']

    print("\n" + "=" * 60)
    print("PHASE 5a: P&L DECOMPOSITION")
    print("=" * 60)

    # ── 1. Three-component decomposition ──
    # Component 1: Completeness spread (already computed in Phase 3)
    resolved['completeness_spread'] = resolved['guaranteed_profit']

    # Component 2: Directional drag on unmatched shares
    # excess_side wins → bonus profit; excess_side loses → loss
    resolved['excess_vwap'] = np.where(
        resolved['excess_side'] == 'Up',
        resolved['vwap_up'], resolved['vwap_down'])
    resolved['excess_wins'] = (
        resolved['excess_side'] == resolved['winning_outcome'])
    resolved['directional_drag'] = np.where(
        resolved['excess_wins'],
        resolved['unmatched_shares'] * (1.0 - resolved['excess_vwap']),
        resolved['unmatched_shares'] * (0.0 - resolved['excess_vwap']))

    # Component 3: Sell P&L (proceeds minus cost basis at buy VWAP)
    resolved['sell_pnl'] = (
        (resolved['sell_up_proceeds']
         - resolved['sell_up_shares'] * resolved['vwap_up'])
        + (resolved['sell_down_proceeds']
           - resolved['sell_down_shares'] * resolved['vwap_down']))

    # Verify decomposition sums exactly
    resolved['decomp_sum'] = (resolved['completeness_spread']
                              + resolved['directional_drag']
                              + resolved['sell_pnl'])
    decomp_error = (resolved['decomp_sum'] - resolved['trade_pnl']).abs()
    max_error = decomp_error.max()

    total_spread = resolved['completeness_spread'].sum()
    total_drag = resolved['directional_drag'].sum()
    total_sell_pnl = resolved['sell_pnl'].sum()
    total_trade_pnl = resolved['trade_pnl'].sum()

    print(f"\n  Decomposition ({len(resolved):,} resolved both-sided markets):")
    print(f"    1. Completeness spread: ${total_spread:>+12,.0f}  "
          f"(matched pairs x spread)")
    print(f"    2. Directional drag:    ${total_drag:>+12,.0f}  "
          f"(unmatched share P&L)")
    print(f"    3. Sell P&L:            ${total_sell_pnl:>+12,.0f}  "
          f"(proceeds - cost basis)")
    print(f"    {'─' * 50}")
    print(f"       Trade-derived total: ${total_trade_pnl:>+12,.0f}")
    print(f"    Decomposition error: ${max_error:.6f} max per market")

    capture_rate = total_trade_pnl / total_spread * 100 if total_spread else 0
    print(f"\n  Edge capture: ${total_trade_pnl:,.0f} / ${total_spread:,.0f} "
          f"= {capture_rate:.1f}%")
    print(f"  Directional drag: "
          f"{abs(total_drag) / total_spread * 100:.1f}% of spread "
          f"(no offset — pure balance cost)")

    # Net sell drag: accounting loss offset by economic benefit of selling
    # sell_pnl is the accounting loss (valued at buy VWAP)
    # sell_discipline_value (computed in section 5) offsets part of it
    # For now, preview the framing; exact numbers filled after section 5
    print(f"  Sell accounting loss: "
          f"{abs(total_sell_pnl) / total_spread * 100:.1f}% of spread "
          f"(partially offset by sell discipline — see below)")

    # Directional drag breakdown: excess on winner vs loser
    excess_winner = resolved[resolved['excess_wins']]
    excess_loser = resolved[~resolved['excess_wins']]
    print(f"\n  Directional drag breakdown:")
    print(f"    Excess on winner: {len(excess_winner):,} mkts, "
          f"${excess_winner['directional_drag'].sum():+,.0f}")
    print(f"    Excess on loser:  {len(excess_loser):,} mkts, "
          f"${excess_loser['directional_drag'].sum():+,.0f}")

    # Drag by balance tier
    tier_order = ['well_balanced', 'moderate', 'imbalanced', 'very_imbalanced']
    drag_by_tier = resolved.groupby('balance_tier', observed=True).agg(
        count=('directional_drag', 'count'),
        total_drag=('directional_drag', 'sum'),
        avg_drag=('directional_drag', 'mean'),
    )
    print(f"    By balance tier:")
    for tier in tier_order:
        if tier in drag_by_tier.index:
            r = drag_by_tier.loc[tier]
            print(f"      {tier:20s}: ${r['total_drag']:>+10,.0f}  "
                  f"(avg ${r['avg_drag']:+.2f}, n={int(r['count']):,})")

    # ── 2. Maker rebates ──
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT SUM(usdc_value) as total FROM trades "
            "WHERE activity_type='MAKER_REBATE'"
        ).fetchone()
        maker_total = row['total'] or 0

    print(f"\n  Maker rebates: ${maker_total:,.0f}  "
          f"(separate — not in trade P&L)")
    print(f"  Total with rebates: ${total_trade_pnl + maker_total:,.0f}")

    # ── 3. Position-derived P&L (ground truth) ──
    pos_pnl = db.position_pnl_by_condition()
    total_pos_pnl = pos_pnl['position_pnl'].sum()

    print(f"\n  Position-derived P&L (ground truth):")
    print(f"    Condition IDs: {len(pos_pnl):,}")
    print(f"    Total realized P&L: ${total_pos_pnl:,.0f}")
    print(f"    Trade-derived P&L:  ${total_trade_pnl:,.0f}")
    print(f"    Gap: ${total_pos_pnl - total_trade_pnl:,.0f} "
          f"(pre-trade-window + one-sided)")

    # ── 4. Reconciliation ──
    trade_cids = set(resolved['condition_id'])
    pos_outside = pos_pnl[~pos_pnl['condition_id'].isin(trade_cids)]

    # 4a. Unit test: is total_bought SHARES or USDC?
    # Definitive algebraic test on no-sell positions:
    #   If shares: realized_pnl = total_bought × (cur_price - avg_price)
    #   If USDC:   realized_pnl = total_bought × (cur_price/avg_price - 1)
    # One produces near-zero residuals, the other doesn't.
    with db._get_conn() as conn:
        all_pos = pd.read_sql_query(
            "SELECT condition_id, outcome, avg_price, total_bought, "
            "realized_pnl, cur_price FROM positions WHERE is_closed=1",
            conn)
    # Identify no-sell positions via trade data
    with db._get_conn() as conn:
        sell_pos = pd.read_sql_query(
            "SELECT condition_id, outcome, "
            "SUM(CASE WHEN side='SELL' THEN size ELSE 0 END) as sell_shares "
            "FROM trades WHERE activity_type='TRADE' "
            "GROUP BY condition_id, outcome HAVING sell_shares > 0", conn)
    sell_keys = set(zip(sell_pos['condition_id'], sell_pos['outcome']))
    no_sell = all_pos[~all_pos.apply(
        lambda r: (r['condition_id'], r['outcome']) in sell_keys, axis=1
    )].copy()

    no_sell['pred_shares'] = no_sell['total_bought'] * (
        no_sell['cur_price'] - no_sell['avg_price'])
    no_sell['pred_usdc'] = no_sell['total_bought'] * (
        no_sell['cur_price'] / no_sell['avg_price'].clip(lower=0.001) - 1)
    no_sell['resid_shares'] = (no_sell['realized_pnl'] - no_sell['pred_shares']).abs()
    no_sell['resid_usdc'] = (no_sell['realized_pnl'] - no_sell['pred_usdc']).abs()

    shares_exact = (no_sell['resid_shares'] < 0.01).mean() * 100
    usdc_exact = (no_sell['resid_usdc'] < 0.01).mean() * 100

    print(f"\n  Reconciliation:")
    print(f"\n  4a. Unit test — total_bought is SHARES or USDC?")
    print(f"    Test: realized_pnl vs algebraic prediction on "
          f"{len(no_sell):,} no-sell positions")
    print(f"    Shares: pnl = total_bought × (cur_price - avg_price)")
    print(f"      Median residual: ${no_sell['resid_shares'].median():.4f}, "
          f"exact (<$0.01): {shares_exact:.1f}%")
    print(f"    USDC:   pnl = total_bought × (cur_price/avg_price - 1)")
    print(f"      Median residual: ${no_sell['resid_usdc'].median():.2f}, "
          f"exact (<$0.01): {usdc_exact:.1f}%")
    is_shares = shares_exact > usdc_exact
    print(f"    → total_bought is {'SHARES' if is_shares else 'USDC'} "
          f"(definitive)")

    # 4b. Fill coverage: compare total_bought (shares) to trade buy shares
    recon = resolved[['condition_id', 'trade_pnl',
                       'buy_up_shares', 'buy_down_shares']].merge(
        pos_pnl[['condition_id', 'position_pnl', 'total_bought']],
        on='condition_id', how='inner')
    recon['pnl_diff'] = recon['trade_pnl'] - recon['position_pnl']
    recon['trade_buy_shares'] = recon['buy_up_shares'] + recon['buy_down_shares']
    recon['share_ratio'] = (recon['total_bought'] /
                            recon['trade_buy_shares'].clip(lower=0.01))

    print(f"\n  4b. Fill coverage ({len(recon):,} overlapping markets):")
    within_5pct = ((recon['share_ratio'] - 1.0).abs() < 0.05).mean() * 100
    median_ratio = recon['share_ratio'].median()
    print(f"    pos_shares / trade_shares: median {median_ratio:.2f} "
          f"({within_5pct:.0f}% within 5%)")
    print(f"    → Activity endpoint captures ~{1/median_ratio*100:.0f}% of fills")

    # 4c. P&L comparison
    print(f"\n  4c. P&L comparison:")
    print(f"    Trade P&L sum:    ${recon['trade_pnl'].sum():,.0f}")
    print(f"    Position P&L sum: ${recon['position_pnl'].sum():,.0f}")
    pnl_gap = recon['position_pnl'].sum() - recon['trade_pnl'].sum()
    print(f"    Gap: ${pnl_gap:,.0f}")
    exact_match = (recon['pnl_diff'].abs() < 0.01).mean() * 100
    close_match = (recon['pnl_diff'].abs() < 1.00).mean() * 100
    print(f"    Exact (<$0.01): {exact_match:.1f}%")
    print(f"    Close (<$1.00): {close_match:.1f}%")
    print(f"    P&L gap is from position API using different avg_price "
          f"(methodology, not missing fills)")

    print(f"\n    Pre-trade-window ({len(pos_outside):,} condition_ids):")
    print(f"    P&L: ${pos_outside['position_pnl'].sum():,.0f}")

    # ── 5. Hold-to-resolution counterfactual ──
    resolved['buy_winning_shares'] = np.where(
        resolved['winning_outcome'] == 'Up',
        resolved['buy_up_shares'], resolved['buy_down_shares'])
    resolved['hold_pnl'] = (
        resolved['buy_winning_shares'] - resolved['total_buy'])
    resolved['sell_discipline_value'] = (
        resolved['trade_pnl'] - resolved['hold_pnl'])
    # Equivalent to: total_sell - sell_winning_shares

    resolved['sell_winning_shares'] = np.where(
        resolved['winning_outcome'] == 'Up',
        resolved['sell_up_shares'], resolved['sell_down_shares'])
    resolved['sell_losing_shares'] = np.where(
        resolved['winning_outcome'] == 'Up',
        resolved['sell_down_shares'], resolved['sell_up_shares'])

    total_hold_pnl = resolved['hold_pnl'].sum()
    total_sdv = resolved['sell_discipline_value'].sum()

    has_sells = resolved[resolved['total_sell'] > 0]
    sell_helped = (has_sells['sell_discipline_value'] > 0).sum()
    sell_hurt = (has_sells['sell_discipline_value'] <= 0).sum()

    print(f"\n  Sell discipline counterfactual:")
    print(f"    Hold-to-resolution P&L: ${total_hold_pnl:,.0f}")
    print(f"    Actual P&L (with sells): ${total_trade_pnl:,.0f}")
    print(f"    Sell discipline value: ${total_sdv:+,.0f}")
    if total_sdv > 0:
        print(f"    → Selling IMPROVED returns by ${total_sdv:,.0f}")
    else:
        print(f"    → Selling REDUCED returns by ${abs(total_sdv):,.0f}")

    if len(has_sells) > 0:
        print(f"    Per-market ({len(has_sells):,} with sells): "
              f"helped {sell_helped:,} ({sell_helped/len(has_sells)*100:.1f}%), "
              f"hurt {sell_hurt:,} ({sell_hurt/len(has_sells)*100:.1f}%)")
        print(f"    Winning shares sold: "
              f"{has_sells['sell_winning_shares'].sum():,.0f} "
              f"(forfeited ${has_sells['sell_winning_shares'].sum():,.0f} payout)")
        print(f"    Losing shares sold: "
              f"{has_sells['sell_losing_shares'].sum():,.0f} "
              f"(avoided worthless holds)")
        print(f"    Total sell proceeds: ${has_sells['total_sell'].sum():,.0f}")

    # ── Net sell drag (accounting loss - economic offset) ──
    net_sell_drag = total_sell_pnl + total_sdv  # sell_pnl is negative
    print(f"\n  Net sell drag (the avoidable sell cost):")
    print(f"    Accounting sell loss:   ${total_sell_pnl:>+12,.0f}")
    print(f"    Sell discipline offset: ${total_sdv:>+12,.0f}")
    print(f"    {'─' * 50}")
    print(f"    Net sell drag:          ${net_sell_drag:>+12,.0f}  "
          f"({abs(net_sell_drag) / total_spread * 100:.1f}% of spread)")
    print(f"    → Directional drag (from imbalance): "
          f"${total_drag:>+12,.0f}  "
          f"({abs(total_drag) / total_spread * 100:.1f}% of spread)")
    print(f"    → Total avoidable leakage: "
          f"${total_drag + net_sell_drag:>+12,.0f}  "
          f"({abs(total_drag + net_sell_drag) / total_spread * 100:.1f}%)")

    # Replication priority
    print(f"\n  Replication priority (leakage sources):")
    print(f"    1. Balance optimization (fills/depth): "
          f"${abs(total_drag):,.0f} drag + indirect sell losses")
    print(f"    2. Sell timing refinement: "
          f"${abs(net_sell_drag):,.0f} net sell drag")

    # Perfect balance upper bound
    if total_trade_pnl > 0:
        print(f"\n  Perfect balance counterfactual: ${total_spread:,.0f} "
              f"({total_spread/total_trade_pnl:.1f}x actual)")

    # ── 6. Win/loss statistics ──
    wins = resolved[resolved['trade_pnl'] > 0]
    losses = resolved[resolved['trade_pnl'] <= 0]

    gross_wins = wins['trade_pnl'].sum()
    gross_losses = abs(losses['trade_pnl'].sum())
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    win_rate = len(wins) / len(resolved)
    expectancy = resolved['trade_pnl'].mean()

    print(f"\n  Win/loss statistics ({len(resolved):,} both-sided resolved):")
    print(f"    Win rate: {len(wins):,}/{len(resolved):,} "
          f"= {win_rate*100:.1f}%")
    print(f"    Avg win:  ${wins['trade_pnl'].mean():,.2f}")
    print(f"    Avg loss: ${losses['trade_pnl'].mean():,.2f}")
    print(f"    Profit factor: {profit_factor:.2f}")
    print(f"    Expectancy: ${expectancy:,.2f} per market")
    print(f"    Gross wins:   ${gross_wins:,.0f}")
    print(f"    Gross losses: ${gross_losses:,.0f}")

    # Win rate by balance tier
    win_by_tier = resolved.groupby('balance_tier', observed=True).agg(
        count=('trade_pnl', 'count'),
        wins=('trade_pnl', lambda x: (x > 0).sum()),
        avg_pnl=('trade_pnl', 'mean'),
    )
    print(f"    By balance tier:")
    for tier in tier_order:
        if tier in win_by_tier.index:
            r = win_by_tier.loc[tier]
            wr = r['wins'] / r['count'] * 100
            print(f"      {tier:20s}: {wr:5.1f}% win  "
                  f"avg ${r['avg_pnl']:+.2f}  "
                  f"(n={int(r['count']):,})")

    # ── 7. By-asset P&L breakdown ──
    resolved_asset = resolved.merge(
        markets_df[['condition_id', 'crypto_asset']].drop_duplicates('condition_id'),
        on='condition_id', how='left')

    asset_pnl = resolved_asset.groupby('crypto_asset').agg(
        count=('trade_pnl', 'count'),
        total_pnl=('trade_pnl', 'sum'),
        avg_pnl=('trade_pnl', 'mean'),
        win_rate=('trade_pnl', lambda x: (x > 0).mean()),
        total_spread=('completeness_spread', 'sum'),
        total_drag=('directional_drag', 'sum'),
    ).sort_values('total_pnl', ascending=False)

    print(f"\n  P&L by crypto asset:")
    for asset, r in asset_pnl.iterrows():
        cap_rate = (r['total_pnl'] / r['total_spread'] * 100
                    if r['total_spread'] > 0 else 0)
        print(f"    {asset:12s}: ${r['total_pnl']:>+10,.0f}  "
              f"({int(r['count']):,} mkts, {r['win_rate']*100:.1f}% win, "
              f"{cap_rate:.0f}% capture)")
    print(f"    NOTE: BTC/ETH dominance is from deeper order books → more fills"
          f" → better balance,")
    print(f"    not an intrinsic BTC property. Phase 4 OLS: is_btc_eth t=-1.4 "
          f"(not significant")
    print(f"    after controlling for fill count). "
          f"For replication: target depth, not asset.")

    # ── 8. Daily P&L series (using position close_timestamp) ──
    # Covers all 13,543 condition_ids for the full $713K account curve
    valid_pos = pos_pnl[pos_pnl['close_ts'] > 0].copy()
    valid_pos['date'] = pd.to_datetime(
        valid_pos['close_ts'], unit='s', utc=True).dt.date
    daily_pnl = valid_pos.groupby('date').agg(
        pnl=('position_pnl', 'sum'),
        markets_resolved=('condition_id', 'count'),
    ).sort_index()
    daily_pnl['cumulative_pnl'] = daily_pnl['pnl'].cumsum()

    print(f"\n  Daily P&L (from position close timestamps):")
    print(f"    Date range: {daily_pnl.index.min()} to {daily_pnl.index.max()}")
    print(f"    Trading days: {len(daily_pnl)}")
    print(f"    Avg daily P&L: ${daily_pnl['pnl'].mean():,.0f}")
    print(f"    Best day:  ${daily_pnl['pnl'].max():,.0f}")
    print(f"    Worst day: ${daily_pnl['pnl'].min():,.0f}")
    positive_days = (daily_pnl['pnl'] > 0).sum()
    print(f"    Positive days: {positive_days}/{len(daily_pnl)} "
          f"({positive_days/len(daily_pnl)*100:.0f}%)")
    if len(daily_pnl) >= 7:
        first_w = daily_pnl.head(7)['pnl'].sum()
        last_w = daily_pnl.tail(7)['pnl'].sum()
        print(f"    First week: ${first_w:,.0f}")
        print(f"    Last week:  ${last_w:,.0f}")

    return {
        'resolved_df': resolved,
        'pos_pnl': pos_pnl,
        'recon_df': recon,
        'daily_pnl': daily_pnl,
        'asset_pnl': asset_pnl,
        'summary': {
            'completeness_spread': float(total_spread),
            'directional_drag': float(total_drag),
            'sell_pnl': float(total_sell_pnl),
            'trade_derived_pnl': float(total_trade_pnl),
            'position_derived_pnl': float(total_pos_pnl),
            'maker_rebates': float(maker_total),
            'hold_pnl': float(total_hold_pnl),
            'sell_discipline_value': float(total_sdv),
            'win_rate': float(win_rate),
            'profit_factor': float(profit_factor),
            'expectancy': float(expectancy),
        }
    }
