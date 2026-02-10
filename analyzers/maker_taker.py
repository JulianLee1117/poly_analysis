"""Phase 8a: Maker/Taker & Fee Analysis — resolve the $40.7K rebate mystery.

Uses on-chain OrderFilled events to classify each fill as maker or taker,
compute actual fees, and re-attribute the P&L decomposition with fee drag.
"""

import numpy as np
import pandas as pd

from storage.database import Database


def analyze_maker_taker(db: Database, completeness_result: dict,
                        structure_result: dict) -> dict:
    """Analyze maker/taker split and fee structure from on-chain data.

    Args:
        db: Database instance
        completeness_result: Output from analyze_completeness()
        structure_result: Output from analyze_market_structure()

    Returns dict with maker/taker splits, fee analysis, and self-impact.
    """
    print("\n" + "=" * 60)
    print("PHASE 8a: MAKER/TAKER & FEE ANALYSIS")
    print("=" * 60)

    # Check if on-chain data exists
    onchain_count = db.onchain_fill_count()
    if onchain_count == 0:
        print("  No on-chain data available — skipping")
        return {'summary': {}, 'available': False}

    # Load joined data
    joined = db.onchain_join_summary()
    print(f"\n  Joined fills: {len(joined):,} (on-chain matched to trades)")

    with db._get_conn() as conn:
        trade_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE activity_type='TRADE'"
        ).fetchone()["cnt"]
    coverage = len(joined) / trade_count * 100 if trade_count > 0 else 0
    print(f"  Coverage: {len(joined):,}/{trade_count:,} = {coverage:.1f}%")

    # ── 1. Maker/taker split ──
    print(f"\n  1. MAKER/TAKER SPLIT")

    maker_fills = joined[joined['bot_role'] == 'maker']
    taker_fills = joined[joined['bot_role'] == 'taker']

    n_maker = len(maker_fills)
    n_taker = len(taker_fills)
    n_total = len(joined)

    maker_vol = maker_fills['usdc_value'].sum()
    taker_vol = taker_fills['usdc_value'].sum()
    total_vol = joined['usdc_value'].sum()

    print(f"    Maker fills: {n_maker:,} ({n_maker/n_total*100:.1f}%)")
    print(f"    Taker fills: {n_taker:,} ({n_taker/n_total*100:.1f}%)")
    print(f"    Maker volume: ${maker_vol:,.0f} ({maker_vol/total_vol*100:.1f}%)")
    print(f"    Taker volume: ${taker_vol:,.0f} ({taker_vol/total_vol*100:.1f}%)")

    # ── 2. Split by side (BUY vs SELL) ──
    print(f"\n  2. MAKER/TAKER BY TRADE SIDE")

    by_side = joined.groupby(['side', 'bot_role']).agg(
        fills=('usdc_value', 'count'),
        volume=('usdc_value', 'sum'),
    ).reset_index()

    for side in ['BUY', 'SELL']:
        side_data = by_side[by_side['side'] == side]
        side_total = side_data['fills'].sum()
        print(f"    {side}:")
        for _, row in side_data.iterrows():
            pct = row['fills'] / side_total * 100 if side_total > 0 else 0
            print(f"      {row['bot_role']:6s}: {int(row['fills']):>8,} fills "
                  f"({pct:.1f}%), ${row['volume']:>12,.0f}")

    # ── 3. Split by crypto asset ──
    print(f"\n  3. MAKER/TAKER BY CRYPTO ASSET")

    markets_df = structure_result.get('markets_df', pd.DataFrame())
    if not markets_df.empty and 'crypto_asset' in markets_df.columns:
        joined_asset = joined.merge(
            markets_df[['condition_id', 'crypto_asset']].drop_duplicates(
                'condition_id'),
            on='condition_id', how='left')

        by_asset = joined_asset.groupby(
            ['crypto_asset', 'bot_role']).agg(
            fills=('usdc_value', 'count'),
            volume=('usdc_value', 'sum'),
        ).reset_index()

        by_asset_df = by_asset.copy()

        for asset in sorted(by_asset['crypto_asset'].dropna().unique()):
            asset_data = by_asset[by_asset['crypto_asset'] == asset]
            asset_total = asset_data['fills'].sum()
            maker_row = asset_data[asset_data['bot_role'] == 'maker']
            maker_pct = (maker_row['fills'].sum() / asset_total * 100
                         if asset_total > 0 else 0)
            print(f"    {asset:12s}: {maker_pct:5.1f}% maker "
                  f"({asset_total:,} fills)")
    else:
        by_asset_df = pd.DataFrame()
        print("    (market metadata not available)")

    # ── 4. Split by hour of day ──
    print(f"\n  4. MAKER/TAKER BY HOUR OF DAY")

    joined['hour'] = pd.to_datetime(
        joined['timestamp'], unit='s', utc=True).dt.hour

    by_hour = joined.groupby(['hour', 'bot_role']).agg(
        fills=('usdc_value', 'count'),
    ).reset_index()

    by_hour_pivot = by_hour.pivot_table(
        index='hour', columns='bot_role', values='fills',
        fill_value=0).reset_index()

    if 'maker' in by_hour_pivot.columns and 'taker' in by_hour_pivot.columns:
        by_hour_pivot['total'] = (by_hour_pivot['maker']
                                  + by_hour_pivot['taker'])
        by_hour_pivot['maker_pct'] = (by_hour_pivot['maker']
                                      / by_hour_pivot['total'] * 100)

        peak_maker_hour = by_hour_pivot.loc[
            by_hour_pivot['maker_pct'].idxmax()]
        trough_maker_hour = by_hour_pivot.loc[
            by_hour_pivot['maker_pct'].idxmin()]
        print(f"    Peak maker hour:   {int(peak_maker_hour['hour']):02d}:00 UTC "
              f"({peak_maker_hour['maker_pct']:.1f}%)")
        print(f"    Trough maker hour: {int(trough_maker_hour['hour']):02d}:00 UTC "
              f"({trough_maker_hour['maker_pct']:.1f}%)")
        print(f"    Range: {by_hour_pivot['maker_pct'].min():.1f}% – "
              f"{by_hour_pivot['maker_pct'].max():.1f}%")

    by_hour_df = by_hour_pivot if 'maker' in by_hour_pivot.columns else pd.DataFrame()

    # ── 5. Split by balance tier ──
    print(f"\n  5. MAKER/TAKER BY BALANCE TIER")

    resolved = completeness_result.get('resolved_df', pd.DataFrame())
    if not resolved.empty and 'balance_tier' in resolved.columns:
        tier_map = resolved[['condition_id', 'balance_tier']].drop_duplicates(
            'condition_id')
        joined_tier = joined.merge(tier_map, on='condition_id', how='left')

        by_tier = joined_tier.groupby(
            ['balance_tier', 'bot_role']).agg(
            fills=('usdc_value', 'count'),
        ).reset_index()

        tier_order = ['well_balanced', 'moderate', 'imbalanced',
                      'very_imbalanced']
        for tier in tier_order:
            tier_data = by_tier[by_tier['balance_tier'] == tier]
            tier_total = tier_data['fills'].sum()
            maker_row = tier_data[tier_data['bot_role'] == 'maker']
            maker_pct = (maker_row['fills'].sum() / tier_total * 100
                         if tier_total > 0 else 0)
            print(f"    {tier:20s}: {maker_pct:5.1f}% maker "
                  f"({tier_total:,} fills)")

        by_tier_df = by_tier.copy()
    else:
        by_tier_df = pd.DataFrame()
        print("    (completeness data not available)")

    # ── 6. Fee analysis ──
    print(f"\n  6. FEE ANALYSIS (approximate — 22% join mismatch noise)")

    total_fee = joined['onchain_fee'].sum()
    nonzero_fees = joined[joined['onchain_fee'] > 0]
    avg_fee_rate = (total_fee / total_vol * 100 if total_vol > 0 else 0)

    print(f"    Total fees paid: ~${total_fee:,.0f} (approximate)")
    print(f"    Fills with fee > 0: {len(nonzero_fees):,} "
          f"({len(nonzero_fees)/n_total*100:.1f}%)")
    print(f"    Avg fee rate: ~{avg_fee_rate:.4f}% of volume")

    # Fee by maker/taker
    maker_fee = maker_fills['onchain_fee'].sum()
    taker_fee = taker_fills['onchain_fee'].sum()
    print(f"    Maker fee total: ~${maker_fee:,.0f}")
    print(f"    Taker fee total: ~${taker_fee:,.0f}")

    # Fee-adjusted P&L: revise decomposition to 4 components
    with db._get_conn() as conn:
        rebate_row = conn.execute(
            "SELECT SUM(usdc_value) as total FROM trades "
            "WHERE activity_type='MAKER_REBATE'"
        ).fetchone()
    maker_rebates = rebate_row['total'] or 0

    pnl_summary = completeness_result.get('summary', {})
    trade_pnl = pnl_summary.get('total_trade_pnl',
                                 pnl_summary.get('theoretical_profit', 0))

    print(f"\n    Fee-adjusted P&L revision:")
    print(f"      Trade-derived P&L:  ${trade_pnl:>+12,.0f}")
    print(f"      On-chain fees:      ${-total_fee:>+12,.2f}")
    print(f"      Maker rebates:      ${maker_rebates:>+12,.0f}")
    print(f"      Net fee impact:     ${maker_rebates - total_fee:>+12,.2f}")

    # Maker rebate reconciliation
    if maker_vol > 0:
        implied_rebate_rate = maker_rebates / maker_vol * 100
        print(f"\n    Maker rebate reconciliation:")
        print(f"      Maker volume: ${maker_vol:,.0f}")
        print(f"      Actual rebates: ${maker_rebates:,.0f}")
        print(f"      Implied rebate rate: {implied_rebate_rate:.4f}%")

    # ── 7. Self-impact re-attribution ──
    # NOTE: Low statistical power with 1.5% tx coverage. A null result means
    # "can't detect effect with this sample", not "no effect exists."
    print(f"\n  7. SELF-IMPACT RE-ATTRIBUTION (low power — 1.5% sample)")

    if not resolved.empty and 'condition_id' in joined.columns:
        # Get price trajectory data split by maker vs taker
        traj = db.price_trajectory_summary()

        # Join maker/taker to per-market stats
        mk_summary = db.maker_taker_summary()
        if not mk_summary.empty:
            mk_merged = mk_summary.merge(
                resolved[['condition_id', 'balance_ratio', 'trade_pnl',
                          'combined_vwap', 'spread']],
                on='condition_id', how='inner')

            mk_merged['maker_frac'] = (
                mk_merged['maker_fills']
                / (mk_merged['maker_fills'] + mk_merged['taker_fills'])
            ).clip(0, 1)

            # High-maker vs high-taker markets
            high_maker = mk_merged[mk_merged['maker_frac'] > 0.5]
            high_taker = mk_merged[mk_merged['maker_frac'] <= 0.5]

            print(f"    High-maker markets (>50%): {len(high_maker):,}")
            print(f"      Avg balance: {high_maker['balance_ratio'].mean():.3f}")
            print(f"      Avg P&L: ${high_maker['trade_pnl'].mean():+.2f}")

            print(f"    High-taker markets (<=50%): {len(high_taker):,}")
            print(f"      Avg balance: {high_taker['balance_ratio'].mean():.3f}")
            print(f"      Avg P&L: ${high_taker['trade_pnl'].mean():+.2f}")

            # Taker fills should show more price impact
            if len(high_taker) > 100 and len(high_maker) > 100:
                from scipy import stats
                t_stat, p_val = stats.ttest_ind(
                    high_maker['balance_ratio'],
                    high_taker['balance_ratio'],
                    equal_var=False)
                print(f"    Balance diff t-test: t={t_stat:.2f}, p={p_val:.4f}")
                if p_val > 0.05:
                    print(f"    → Not significant (low power — consistent with "
                          f"Phase 4 null result, not proof of no effect)")

            self_impact_df = mk_merged
        else:
            self_impact_df = pd.DataFrame()
            print("    (maker/taker summary empty)")
    else:
        self_impact_df = pd.DataFrame()
        print("    (insufficient data for self-impact analysis)")

    summary = {
        'maker_fills': n_maker,
        'taker_fills': n_taker,
        'maker_pct': n_maker / n_total * 100 if n_total > 0 else 0,
        'taker_pct': n_taker / n_total * 100 if n_total > 0 else 0,
        'maker_volume': float(maker_vol),
        'taker_volume': float(taker_vol),
        'total_fee': float(total_fee),
        'avg_fee_rate': float(avg_fee_rate),
        'maker_rebates': float(maker_rebates),
        'net_fee_impact': float(maker_rebates - total_fee),
        'coverage_pct': float(coverage),
    }

    print(f"\n  Summary: {n_maker/n_total*100:.1f}% maker / "
          f"{n_taker/n_total*100:.1f}% taker, "
          f"${total_fee:,.0f} fees, "
          f"${maker_rebates:,.0f} rebates")

    return {
        'summary': summary,
        'by_side': by_side,
        'by_asset': by_asset_df,
        'by_hour': by_hour_df,
        'by_tier': by_tier_df,
        'fee_summary': {
            'total_fee': float(total_fee),
            'maker_fee': float(maker_fee),
            'taker_fee': float(taker_fee),
            'avg_fee_rate': float(avg_fee_rate),
            'maker_rebates': float(maker_rebates),
        },
        'self_impact_df': self_impact_df,
        'available': True,
    }
