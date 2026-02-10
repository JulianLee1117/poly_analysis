"""Phase 6: Temporal & behavioral patterns.

Focused on questions NOT already answered by Phases 3-5:
- When does the bot trade? (hour-of-day, day-of-week)
- Does it follow spreads or operator schedule?
- What triggers sell decisions?
- What drives the +5.34c spread expansion?
"""

import numpy as np
import pandas as pd
from scipy import stats

from storage.database import Database


def analyze_temporal(db: Database, completeness_result: dict,
                     structure_result: dict, pms: pd.DataFrame) -> dict:
    """Analyze temporal patterns and behavioral signals.

    Args:
        db: Database instance
        completeness_result: Output from analyze_completeness()
        structure_result: Output from analyze_market_structure()
        pms: Per-market summary DataFrame

    Returns dict with temporal findings.
    """
    both = completeness_result['per_market_df'].copy()
    resolved = completeness_result['resolved_df']
    markets_df = structure_result['markets_df']

    print("\n" + "=" * 60)
    print("PHASE 6: TEMPORAL & BEHAVIORAL PATTERNS")
    print("=" * 60)

    # ── 1. Hour-of-day activity profile ──
    hourly = db.hourly_activity()

    print(f"\n  Hour-of-day activity (UTC):")
    print(f"    {'Hour':>4s}  {'Fills':>8s}  {'Volume':>12s}  "
          f"{'Markets':>7s}  {'$/Fill':>7s}")
    for _, row in hourly.iterrows():
        avg_fill = row['volume'] / row['fills'] if row['fills'] > 0 else 0
        print(f"    {int(row['hour_utc']):4d}  {int(row['fills']):8,}  "
              f"${row['volume']:>11,.0f}  {int(row['markets']):7,}  "
              f"${avg_fill:>6.1f}")

    peak_hour = hourly.loc[hourly['fills'].idxmax()]
    quiet_hour = hourly.loc[hourly['fills'].idxmin()]
    fill_range = (peak_hour['fills'] / quiet_hour['fills']
                  if quiet_hour['fills'] > 0 else 0)
    print(f"\n  Peak: {int(peak_hour['hour_utc']):02d}:00 UTC "
          f"({int(peak_hour['fills']):,} fills)")
    print(f"  Quiet: {int(quiet_hour['hour_utc']):02d}:00 UTC "
          f"({int(quiet_hour['fills']):,} fills)")
    print(f"  Peak/quiet ratio: {fill_range:.1f}x")

    # ── 2. Spread-vs-hour cross-reference ──
    both['hour_utc'] = pd.to_datetime(
        both['first_fill_ts'], unit='s', utc=True).dt.hour
    spread_by_hour = both.groupby('hour_utc').agg(
        avg_spread=('spread', 'mean'),
        avg_vwap=('combined_vwap', 'mean'),
        market_count=('condition_id', 'count'),
    ).sort_index()

    # Merge with hourly fill data
    spread_hour = spread_by_hour.reset_index().merge(
        hourly[['hour_utc', 'fills', 'volume']],
        on='hour_utc', how='left')

    print(f"\n  Spread vs activity by hour:")
    print(f"    {'Hour':>4s}  {'Spread':>8s}  {'VWAP':>8s}  "
          f"{'Markets':>7s}  {'Fills':>8s}")
    for _, row in spread_hour.iterrows():
        print(f"    {int(row['hour_utc']):4d}  "
              f"${row['avg_spread']:.4f}  ${row['avg_vwap']:.4f}  "
              f"{int(row['market_count']):7,}  {int(row['fills']):8,}")

    # Fills-spread hourly correlation
    hour_corr = stats.spearmanr(spread_hour['fills'], spread_hour['avg_spread'])
    print(f"\n  Fills-spread hourly correlation: r={hour_corr.statistic:+.3f}, "
          f"p={hour_corr.pvalue:.3f}")

    # Operator schedule test: wide-spread vs tight-spread hours
    wide_hours = spread_hour.nlargest(6, 'avg_spread')
    tight_hours = spread_hour.nsmallest(6, 'avg_spread')
    wide_avg_fills = wide_hours['fills'].mean()
    tight_avg_fills = tight_hours['fills'].mean()

    print(f"  Wide-spread hours (6 widest): avg {wide_avg_fills:,.0f} fills, "
          f"avg spread ${wide_hours['avg_spread'].mean():.4f}")
    print(f"  Tight-spread hours (6 tightest): avg {tight_avg_fills:,.0f} fills, "
          f"avg spread ${tight_hours['avg_spread'].mean():.4f}")

    if wide_avg_fills > tight_avg_fills * 1.2:
        schedule_verdict = (
            "SYSTEMATIC: bot trades MORE when spreads are wider "
            "— spread-seeking behavior")
    elif tight_avg_fills > wide_avg_fills * 1.2:
        schedule_verdict = (
            "OPERATOR-DRIVEN: bot trades MORE when spreads are tight "
            "— follows human schedule, not optimal spreads")
    else:
        schedule_verdict = (
            "MARKET-CADENCE-DRIVEN: activity tracks market creation "
            "cadence, not spread width. The {:.1f}x peak/quiet ratio "
            "is too flat for human scheduling — consistent with "
            "fully automated bot modulated by Polymarket's market "
            "creation rate (more markets during US hours)".format(fill_range))
    print(f"  Verdict: {schedule_verdict}")

    # ── 3. Day-of-week pattern ──
    dow = db.day_of_week_activity()
    dow_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

    print(f"\n  Day-of-week pattern:")
    print(f"    {'Day':>3s}  {'Fills':>8s}  {'Volume':>12s}  {'Markets':>7s}")
    for _, row in dow.iterrows():
        day_name = dow_names[int(row['dow'])]
        print(f"    {day_name:>3s}  {int(row['fills']):8,}  "
              f"${row['volume']:>11,.0f}  {int(row['markets']):7,}")

    weekday = dow[dow['dow'].isin([1, 2, 3, 4, 5])]
    weekend = dow[dow['dow'].isin([0, 6])]
    weekday_avg = weekday['fills'].mean() if len(weekday) > 0 else 0
    weekend_avg = weekend['fills'].mean() if len(weekend) > 0 else 0

    if weekday_avg > 0:
        we_ratio = weekend_avg / weekday_avg
        print(f"  Weekend/weekday fill ratio: {we_ratio:.2f}x")
        if we_ratio < 0.7:
            print(f"  -> Human oversight pattern: reduced weekend activity")
        elif we_ratio > 0.9:
            print(f"  -> Fully automated: consistent across week")
        else:
            print(f"  -> Moderate weekend reduction")

    # ── 4. One-sided failure timing ──
    exec_detail = db.per_market_execution_detail()
    markets_meta = db.load_markets()

    from analyzers.execution import _parse_market_duration
    markets_meta['market_duration'] = markets_meta['question'].apply(
        _parse_market_duration)
    markets_meta['end_ts'] = pd.to_datetime(markets_meta['end_date']).apply(
        lambda x: int(x.timestamp()))
    markets_meta['open_ts'] = markets_meta['end_ts'] - markets_meta['market_duration']

    one_sided = completeness_result['one_sided_df'].copy()
    one_sided = one_sided.merge(
        exec_detail[['condition_id', 'first_buy_up_ts', 'first_buy_down_ts']],
        on='condition_id', how='left')
    one_sided = one_sided.merge(
        markets_meta[['condition_id', 'open_ts', 'market_duration']],
        on='condition_id', how='left')
    one_sided['entry_speed'] = one_sided['first_fill_ts'] - one_sided['open_ts']

    both_es = both.merge(
        markets_meta[['condition_id', 'open_ts']],
        on='condition_id', how='left')
    both_es['entry_speed'] = both_es['first_fill_ts'] - both_es['open_ts']
    both_valid = both_es[
        (both_es['entry_speed'] >= -10) & (both_es['entry_speed'] < 1800)]
    one_valid = one_sided[
        (one_sided['entry_speed'] >= -10) & (one_sided['entry_speed'] < 1800)]

    print(f"\n  One-sided failure mode ({len(one_sided):,} markets):")
    if len(one_valid) > 0 and len(both_valid) > 0:
        one_med = one_valid['entry_speed'].median()
        both_med = both_valid['entry_speed'].median()
        print(f"    Entry speed: one-sided median {one_med:.0f}s "
              f"vs both-sided {both_med:.0f}s")

        u_stat, u_p = stats.mannwhitneyu(
            one_valid['entry_speed'].dropna(),
            both_valid['entry_speed'].dropna(),
            alternative='greater')
        print(f"    Mann-Whitney (one-sided later?): U={u_stat:.0f}, p={u_p:.4f}")

        late_threshold = 60
        one_late = (one_valid['entry_speed'] > late_threshold).mean() * 100
        both_late = (both_valid['entry_speed'] > late_threshold).mean() * 100
        print(f"    Late entry (>{late_threshold}s): "
              f"one-sided {one_late:.1f}% vs both-sided {both_late:.1f}%")

    one_sided['total_buy'] = one_sided['buy_up_cost'] + one_sided['buy_down_cost']
    print(f"    Avg capital: one-sided ${one_sided['total_buy'].mean():,.0f} "
          f"vs both-sided ${(both['buy_up_cost'] + both['buy_down_cost']).mean():,.0f}")

    # Per-asset one-sided rate
    one_asset = one_sided.merge(
        markets_df[['condition_id', 'crypto_asset']].drop_duplicates('condition_id'),
        on='condition_id', how='left')
    both_asset_count = both.merge(
        markets_df[['condition_id', 'crypto_asset']].drop_duplicates('condition_id'),
        on='condition_id', how='left')['crypto_asset'].value_counts()

    print(f"    One-sided rate by asset:")
    for asset in ['Bitcoin', 'Ethereum', 'Solana', 'XRP']:
        one_count = len(one_asset[one_asset['crypto_asset'] == asset])
        both_count = both_asset_count.get(asset, 0)
        total = one_count + both_count
        if total > 0:
            rate = one_count / total * 100
            print(f"      {asset:12s}: {one_count:3,}/{total:,} ({rate:.1f}%)")

    # ── 5. Sell trigger identification ──
    sell_detail = db.sell_detail_by_market()

    if len(sell_detail) > 0:
        # Merge with buy VWAPs from both-sided markets
        sell_merged = sell_detail.merge(
            both[['condition_id', 'vwap_up', 'vwap_down', 'first_fill_ts',
                  'spread']],
            on='condition_id', how='inner')

        sell_merged['buy_vwap'] = np.where(
            sell_merged['outcome'] == 'Up',
            sell_merged['vwap_up'], sell_merged['vwap_down'])
        sell_merged['first_sell_ratio'] = (
            sell_merged['first_sell_price']
            / sell_merged['buy_vwap'].clip(lower=0.01))
        sell_merged['avg_sell_ratio'] = (
            sell_merged['avg_sell_price']
            / sell_merged['buy_vwap'].clip(lower=0.01))
        sell_merged['sell_delay'] = (
            sell_merged['first_sell_ts'] - sell_merged['first_fill_ts'])
        sell_merged['deterioration_pct'] = (
            (1 - sell_merged['first_sell_ratio']) * 100)

        print(f"\n  Sell trigger analysis "
              f"({len(sell_merged):,} market-outcome sell events):")

        # First sell price (the trigger point)
        fsp = sell_merged['first_sell_price']
        print(f"    First sell price (trigger):")
        print(f"      Mean: ${fsp.mean():.3f}, Median: ${fsp.median():.3f}")
        pctiles = fsp.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
        for p, v in pctiles.items():
            print(f"      p{int(p*100):2d}: ${v:.3f}")

        # Deterioration from entry
        det = sell_merged['deterioration_pct']
        print(f"    Deterioration from entry (first sell):")
        print(f"      Mean: {det.mean():.1f}%, Median: {det.median():.1f}%")
        det_pctiles = det.quantile([0.25, 0.50, 0.75])
        for p, v in det_pctiles.items():
            print(f"      p{int(p*100):2d}: {v:.1f}%")

        # Above-entry vs below-entry sells (different mechanisms?)
        above_entry = sell_merged[sell_merged['first_sell_ratio'] >= 1.0]
        below_entry = sell_merged[sell_merged['first_sell_ratio'] < 1.0]
        print(f"    Sell mechanism split:")
        print(f"      Below entry (loss-cutting): {len(below_entry):,} "
              f"({len(below_entry)/len(sell_merged)*100:.1f}%)"
              f"  avg first sell ${below_entry['first_sell_price'].mean():.3f}"
              f"  avg deterioration {below_entry['deterioration_pct'].mean():.1f}%")
        print(f"      Above entry (rebalancing):  {len(above_entry):,} "
              f"({len(above_entry)/len(sell_merged)*100:.1f}%)"
              f"  avg first sell ${above_entry['first_sell_price'].mean():.3f}"
              f"  avg ratio {above_entry['first_sell_ratio'].mean():.3f}")
        # Compare sell delay between mechanisms
        if len(above_entry) > 0 and len(below_entry) > 0:
            print(f"      Sell delay: loss-cutting {below_entry['sell_delay'].median():.0f}s "
                  f"vs rebalancing {above_entry['sell_delay'].median():.0f}s (median)")

        # Price threshold analysis
        print(f"    Price threshold analysis:")
        for thresh in [0.20, 0.25, 0.30, 0.35, 0.40, 0.50]:
            pct = (fsp <= thresh).mean() * 100
            print(f"      First sell <= ${thresh:.2f}: {pct:.1f}%")

        # Sell delay distribution
        delay = sell_merged['sell_delay']
        print(f"    Sell delay from first buy:")
        print(f"      Mean: {delay.mean():.0f}s, Median: {delay.median():.0f}s")
        delay_bins = [
            ('< 30s', 0, 30), ('30-120s', 30, 120),
            ('2-5 min', 120, 300), ('5-10 min', 300, 600),
            ('10+ min', 600, float('inf')),
        ]
        for label, lo, hi in delay_bins:
            cnt = ((delay >= lo) & (delay < hi)).sum()
            pct = cnt / len(delay) * 100
            print(f"      {label:12s} {cnt:5,} ({pct:5.1f}%)")

        # Resolution accuracy by first sell price bracket
        # Merge resolution to see if sold outcome actually lost
        resolution = resolved[['condition_id', 'winning_outcome']].drop_duplicates(
            'condition_id')
        sell_res = sell_merged.merge(resolution, on='condition_id', how='inner')
        sell_res['sold_loser'] = sell_res['outcome'] != sell_res['winning_outcome']

        print(f"    Resolution accuracy by sell price bracket:")
        price_brackets = [
            ('$0.00-0.20', 0.00, 0.20), ('$0.20-0.30', 0.20, 0.30),
            ('$0.30-0.40', 0.30, 0.40), ('$0.40-0.50', 0.40, 0.50),
            ('$0.50+', 0.50, 1.01),
        ]
        for label, lo, hi in price_brackets:
            bracket = sell_res[
                (sell_res['first_sell_price'] >= lo) &
                (sell_res['first_sell_price'] < hi)]
            if len(bracket) > 0:
                loser_rate = bracket['sold_loser'].mean() * 100
                print(f"      {label:12s}: {loser_rate:5.1f}% sold loser "
                      f"(n={len(bracket):,})")

    # ── 6. Spread expansion decomposition ──
    both_with_asset = both.merge(
        markets_df[['condition_id', 'crypto_asset']].drop_duplicates(
            'condition_id'),
        on='condition_id', how='left')
    both_with_asset['date'] = pd.to_datetime(
        both_with_asset['first_fill_ts'], unit='s', utc=True).dt.date

    print(f"\n  Spread expansion decomposition:")

    # Per-asset spread trend
    asset_daily = both_with_asset.groupby(['crypto_asset', 'date']).agg(
        avg_spread=('spread', 'mean'),
        markets=('condition_id', 'count'),
    ).reset_index()

    print(f"    Per-asset spread trend (first week -> last week):")
    asset_deltas = {}
    for asset in ['Bitcoin', 'Ethereum', 'Solana', 'XRP']:
        ad = asset_daily[asset_daily['crypto_asset'] == asset].sort_values('date')
        if len(ad) >= 7:
            first_w = ad.head(7)['avg_spread'].mean()
            last_w = ad.tail(7)['avg_spread'].mean()
            delta = last_w - first_w
            asset_deltas[asset] = delta
            print(f"      {asset:12s}: ${first_w:.4f} -> ${last_w:.4f} "
                  f"({delta:+.4f})")

    # Fills per market over time
    daily_avg = both_with_asset.groupby('date').agg(
        avg_fills=('total_fills', 'mean'),
        avg_spread=('spread', 'mean'),
        market_count=('condition_id', 'count'),
    ).sort_index()

    if len(daily_avg) >= 7:
        first_w_fills = daily_avg.head(7)['avg_fills'].mean()
        last_w_fills = daily_avg.tail(7)['avg_fills'].mean()
        print(f"    Fills/market: first week {first_w_fills:.0f} "
              f"-> last week {last_w_fills:.0f}")

    # Entry speed over time
    es_merged = both.merge(
        markets_meta[['condition_id', 'open_ts']],
        on='condition_id', how='left')
    es_merged['entry_speed'] = es_merged['first_fill_ts'] - es_merged['open_ts']
    es_merged['date'] = pd.to_datetime(
        es_merged['first_fill_ts'], unit='s', utc=True).dt.date
    valid_es = es_merged[
        (es_merged['entry_speed'] >= -10) & (es_merged['entry_speed'] < 1800)]

    es_daily = valid_es.groupby('date')['entry_speed'].median().sort_index()
    if len(es_daily) >= 7:
        first_w_es = es_daily.head(7).mean()
        last_w_es = es_daily.tail(7).mean()
        print(f"    Entry speed (median): first week {first_w_es:.1f}s "
              f"-> last week {last_w_es:.1f}s")

    # Markets per day
    if len(daily_avg) >= 7:
        first_w_mkts = daily_avg.head(7)['market_count'].mean()
        last_w_mkts = daily_avg.tail(7)['market_count'].mean()
        print(f"    Markets/day: first week {first_w_mkts:.0f} "
              f"-> last week {last_w_mkts:.0f}")

    # Daily spread-fills correlation
    if len(daily_avg) > 7:
        sf_corr = stats.spearmanr(
            daily_avg['avg_spread'], daily_avg['avg_fills'])
        print(f"    Daily spread-fills correlation: r={sf_corr.statistic:+.3f}, "
              f"p={sf_corr.pvalue:.3f}")

    print(f"    CAVEAT: 22-day window covers a single volatility regime.")
    print(f"    Strategy profitability is partially conditional on continued")
    print(f"    crypto volatility maintaining wide spreads. Spread compression")
    print(f"    in a low-volatility environment would reduce the arb edge.")

    return {
        'hourly_activity': hourly,
        'spread_by_hour': spread_hour,
        'day_of_week': dow,
        'sell_trigger': sell_merged if len(sell_detail) > 0 else pd.DataFrame(),
        'summary': {
            'peak_hour': int(peak_hour['hour_utc']),
            'quiet_hour': int(quiet_hour['hour_utc']),
            'fill_range': float(fill_range),
            'hour_spread_corr': float(hour_corr.statistic),
            'schedule_verdict': schedule_verdict,
            'weekend_weekday_ratio': float(we_ratio) if weekday_avg > 0 else 0,
            'asset_spread_deltas': asset_deltas,
        }
    }
