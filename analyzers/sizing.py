"""Phase 4b: Position sizing & capital deployment — portfolio-level execution patterns."""

import numpy as np
import pandas as pd

from storage.database import Database


def analyze_sizing(db: Database, pms: pd.DataFrame,
                   completeness_result: dict) -> dict:
    """Analyze capital deployment, edge capture, and concurrent exposure.

    Args:
        db: Database instance
        pms: Per-market summary DataFrame
        completeness_result: Output from analyze_completeness()

    Returns dict with sizing findings.
    """
    both = completeness_result['per_market_df'].copy()
    resolved = completeness_result['resolved_df'].copy()

    print("\n" + "=" * 60)
    print("PHASE 4b: POSITION SIZING & CAPITAL DEPLOYMENT")
    print("=" * 60)

    # ── 1. Per-market capital ──
    both['total_buy_cost'] = both['buy_up_cost'] + both['buy_down_cost']
    both['total_sell_proceeds'] = both['sell_up_proceeds'] + both['sell_down_proceeds']
    both['net_capital'] = both['total_buy_cost'] - both['total_sell_proceeds']

    print(f"\nPer-market capital ({len(both):,} both-sided markets):")
    print(f"  Buy outlay:  mean ${both['total_buy_cost'].mean():,.0f}, "
          f"median ${both['total_buy_cost'].median():,.0f}")
    print(f"  Net capital: mean ${both['net_capital'].mean():,.0f}, "
          f"median ${both['net_capital'].median():,.0f}")
    print(f"  Total buy outlay:   ${both['total_buy_cost'].sum():,.0f}")
    print(f"  Total sell recovery: ${both['total_sell_proceeds'].sum():,.0f}")

    # Capital distribution
    cap_pctiles = both['total_buy_cost'].quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    print(f"  Distribution (buy outlay):")
    for p, v in cap_pctiles.items():
        print(f"    p{int(p*100):2d}: ${v:,.0f}")

    # ── 2. Dollar balance ratio ──
    both['dollar_balance'] = np.where(
        both['total_buy_cost'] > 0,
        np.minimum(both['buy_up_cost'], both['buy_down_cost']) /
        np.maximum(both['buy_up_cost'], both['buy_down_cost']),
        0)
    both['up_dollar_frac'] = np.where(
        both['total_buy_cost'] > 0,
        both['buy_up_cost'] / both['total_buy_cost'],
        0.5)

    print(f"\nDollar balance (Up cost / total cost):")
    print(f"  Mean Up fraction: {both['up_dollar_frac'].mean():.4f}")
    print(f"  Mean dollar balance ratio: {both['dollar_balance'].mean():.4f}")
    bal_dist = [
        ('Very balanced (>0.90)', 0.90, 1.01),
        ('Balanced (0.70-0.90)', 0.70, 0.90),
        ('Moderate (0.50-0.70)', 0.50, 0.70),
        ('Imbalanced (<0.50)', 0.0, 0.50),
    ]
    for label, lo, hi in bal_dist:
        cnt = ((both['dollar_balance'] >= lo) & (both['dollar_balance'] < hi)).sum()
        pct = cnt / len(both) * 100
        print(f"    {label:30s} {cnt:5,} ({pct:5.1f}%)")

    # ── 3. Edge capture efficiency ──
    resolved['total_buy'] = resolved['buy_up_cost'] + resolved['buy_down_cost']
    resolved['total_sell'] = resolved['sell_up_proceeds'] + resolved['sell_down_proceeds']
    # Theoretical profit: matched pairs × spread
    valid_theoretical = resolved[resolved['guaranteed_profit'] > 0.01].copy()

    if len(valid_theoretical) > 0:
        valid_theoretical['edge_capture'] = (
            valid_theoretical['trade_pnl'] / valid_theoretical['guaranteed_profit'])
        # Clip extreme outliers for summary stats
        clipped = valid_theoretical['edge_capture'].clip(-5, 5)

        print(f"\nEdge capture efficiency ({len(valid_theoretical):,} resolved, "
              f"theoretical > $0.01):")
        print(f"  Mean: {clipped.mean()*100:.1f}%")
        print(f"  Median: {clipped.median()*100:.1f}%")
        print(f"  Positive (captured some edge): "
              f"{(clipped > 0).sum():,} ({(clipped > 0).mean()*100:.1f}%)")

        # Edge capture by balance tier
        if 'balance_tier' in valid_theoretical.columns:
            tier_order = ['well_balanced', 'moderate', 'imbalanced', 'very_imbalanced']
            ec_by_tier = valid_theoretical.groupby('balance_tier', observed=True).agg(
                count=('edge_capture', 'count'),
                mean_capture=('edge_capture', lambda x: x.clip(-5, 5).mean()),
                median_capture=('edge_capture', lambda x: x.clip(-5, 5).median()),
                mean_pnl=('trade_pnl', 'mean'),
            ).reindex(tier_order)

            print(f"  By balance tier:")
            for tier in tier_order:
                if tier in ec_by_tier.index and pd.notna(ec_by_tier.loc[tier, 'count']):
                    r = ec_by_tier.loc[tier]
                    print(f"    {tier:20s}: "
                          f"mean {r['mean_capture']*100:6.1f}%, "
                          f"median {r['median_capture']*100:6.1f}%, "
                          f"avg P&L ${r['mean_pnl']:+.2f}  "
                          f"(n={int(r['count']):,})")
    else:
        valid_theoretical = pd.DataFrame()

    # ── 4. Concurrent capital (peak exposure) ──
    # Capital is locked from first fill to market resolution
    pos = db.load_positions(closed_only=True)
    # Map close_timestamp per condition_id (use max across Up/Down positions)
    close_ts = (pos.groupby('condition_id')['close_timestamp']
                .max().reset_index()
                .rename(columns={'close_timestamp': 'close_ts'}))

    capital_events = both.merge(close_ts, on='condition_id', how='left')
    capital_events = capital_events[capital_events['close_ts'].notna()].copy()

    if len(capital_events) > 0:
        # Build event series: +capital at first_fill_ts, -capital at close_ts
        opens = capital_events[['first_fill_ts', 'net_capital']].copy()
        opens.columns = ['ts', 'delta']
        closes = capital_events[['close_ts', 'net_capital']].copy()
        closes.columns = ['ts', 'delta']
        closes['delta'] = -closes['delta']

        events = pd.concat([opens, closes]).sort_values('ts').reset_index(drop=True)
        events['cumulative'] = events['delta'].cumsum()

        peak_exposure = events['cumulative'].max()
        avg_exposure = events['cumulative'].mean()

        # Peak concurrent markets
        market_opens = capital_events[['first_fill_ts']].copy()
        market_opens['event'] = 1
        market_opens.columns = ['ts', 'event']
        market_closes = capital_events[['close_ts']].copy()
        market_closes['event'] = -1
        market_closes.columns = ['ts', 'event']
        mkt_events = pd.concat([market_opens, market_closes]).sort_values('ts')
        mkt_events['concurrent'] = mkt_events['event'].cumsum()
        peak_concurrent = int(mkt_events['concurrent'].max())

        print(f"\nConcurrent capital:")
        print(f"  Peak exposure: ${peak_exposure:,.0f}")
        print(f"  Avg exposure:  ${avg_exposure:,.0f}")
        print(f"  Peak concurrent markets: {peak_concurrent}")

        # Daily peak exposure
        events['date'] = pd.to_datetime(events['ts'], unit='s', utc=True).dt.date
        daily_peak = events.groupby('date')['cumulative'].max()
        if len(daily_peak) >= 7:
            first_w = daily_peak.head(7).mean()
            last_w = daily_peak.tail(7).mean()
            print(f"  Daily peak: first week ${first_w:,.0f}, "
                  f"last week ${last_w:,.0f}")
    else:
        peak_exposure = 0
        avg_exposure = 0
        peak_concurrent = 0

    # ── 5. Daily deployment ──
    daily = db.daily_summary()

    print(f"\nDaily deployment ({len(daily)} days):")
    print(f"  Avg daily buy volume:  ${daily['buy_volume'].mean():,.0f}")
    print(f"  Avg daily sell volume: ${daily['sell_volume'].mean():,.0f}")
    print(f"  Avg daily markets:     {daily['markets'].mean():.0f}")
    if len(daily) >= 7:
        first_w = daily.head(7)['buy_volume'].mean()
        last_w = daily.tail(7)['buy_volume'].mean()
        trend_pct = (last_w - first_w) / first_w * 100
        direction = 'increasing' if trend_pct > 10 else 'decreasing' if trend_pct < -10 else 'stable'
        print(f"  First week buy vol: ${first_w:,.0f}")
        print(f"  Last week buy vol:  ${last_w:,.0f}")
        print(f"  Trend: {direction} ({trend_pct:+.1f}%)")

    # ── 6. Fill size distribution ──
    # Use per_market_summary to compute avg fill size per market
    both['avg_fill_size'] = both['total_buy_cost'] / both['buy_fills'].clip(lower=1)

    print(f"\nFill sizes:")
    print(f"  Per-fill: mean ${both['total_buy_cost'].sum() / both['buy_fills'].sum():.2f}")
    print(f"  Per-market avg fill: mean ${both['avg_fill_size'].mean():.2f}, "
          f"median ${both['avg_fill_size'].median():.2f}")

    return {
        'per_market_df': both,
        'edge_capture_df': valid_theoretical,
        'daily_summary': daily,
        'summary': {
            'avg_buy_outlay': float(both['total_buy_cost'].mean()),
            'total_buy_outlay': float(both['total_buy_cost'].sum()),
            'total_sell_recovery': float(both['total_sell_proceeds'].sum()),
            'dollar_balance_mean': float(both['dollar_balance'].mean()),
            'edge_capture_mean': float(clipped.mean()) if len(valid_theoretical) > 0 else 0,
            'edge_capture_median': float(clipped.median()) if len(valid_theoretical) > 0 else 0,
            'peak_exposure': float(peak_exposure),
            'avg_exposure': float(avg_exposure),
            'peak_concurrent_markets': peak_concurrent,
        }
    }
