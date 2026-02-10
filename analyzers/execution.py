"""Phase 4a: Execution microstructure — how the bot executes and what causes edge leakage."""

import re

import numpy as np
import pandas as pd
from scipy import stats

from storage.database import Database


def _parse_market_duration(question: str) -> int:
    """Return market duration in seconds from question text.

    15-min format: "Solana Up or Down - January 19, 7:45AM-8:00AM ET"  -> 900
    Hourly format: "Bitcoin Up or Down - February 8, 6PM ET"           -> 3600
    """
    if re.search(r'\d{1,2}:\d{2}[AP]M\s*[-\u2013\u2014]\s*\d{1,2}:\d{2}[AP]M', question):
        return 900
    return 3600


def analyze_execution(db: Database, pms: pd.DataFrame,
                      completeness_result: dict) -> dict:
    """Analyze intra-market execution patterns.

    Central question: What creates the 5.13M unmatched shares?
    Tests: sequencing gap, entry speed, price trajectory, sell patterns.

    Args:
        db: Database instance
        pms: Per-market summary DataFrame
        completeness_result: Output from analyze_completeness()

    Returns dict with execution findings.
    """
    # ── Load and merge data ──
    exec_detail = db.per_market_execution_detail()
    markets = db.load_markets()
    both = completeness_result['per_market_df'].copy()

    # Merge execution timestamps onto both-sided markets
    df = both.merge(exec_detail, on='condition_id', how='left')

    # Market open time from end_date
    markets['market_duration'] = markets['question'].apply(_parse_market_duration)
    markets['end_ts'] = pd.to_datetime(markets['end_date']).apply(
        lambda x: int(x.timestamp()))
    markets['open_ts'] = markets['end_ts'] - markets['market_duration']
    df = df.merge(
        markets[['condition_id', 'open_ts', 'end_ts', 'market_duration']],
        on='condition_id', how='left')

    print("\n" + "=" * 60)
    print("PHASE 4a: EXECUTION MICROSTRUCTURE")
    print("=" * 60)

    # ── 1. Sequencing analysis (both-sided only) ──
    has_both_buys = df['first_buy_up_ts'].notna() & df['first_buy_down_ts'].notna()
    seq = df[has_both_buys].copy()

    seq['seq_gap'] = (seq['first_buy_up_ts'] - seq['first_buy_down_ts']).abs()
    seq['first_side'] = np.where(
        seq['first_buy_up_ts'] <= seq['first_buy_down_ts'], 'Up', 'Down')
    seq['first_side_equal'] = seq['first_buy_up_ts'] == seq['first_buy_down_ts']

    # Sequencing gap buckets
    gap_bins = [
        ('Simultaneous (0-2s)', 0, 2),
        ('Fast (2-10s)', 2, 10),
        ('Moderate (10-60s)', 10, 60),
        ('Slow (60-300s)', 60, 300),
        ('Very slow (300s+)', 300, float('inf')),
    ]

    print(f"\nUp/Down buy sequencing ({len(seq):,} both-sided markets):")
    print(f"  First side: Up {(seq['first_side']=='Up').sum():,} / "
          f"Down {(seq['first_side']=='Down').sum():,} / "
          f"Same-second {seq['first_side_equal'].sum():,}")
    print(f"  Gap distribution:")
    for label, lo, hi in gap_bins:
        cnt = ((seq['seq_gap'] >= lo) & (seq['seq_gap'] < hi)).sum()
        pct = cnt / len(seq) * 100
        print(f"    {label:25s} {cnt:5,} ({pct:5.1f}%)")
    print(f"  Gap stats: mean {seq['seq_gap'].mean():.1f}s, "
          f"median {seq['seq_gap'].median():.1f}s, "
          f"p75 {seq['seq_gap'].quantile(0.75):.1f}s")

    # Sequencing gap → balance impact (KEY test)
    valid = seq[seq['balance_ratio'].notna() & seq['seq_gap'].notna()]
    gap_balance_corr = stats.spearmanr(valid['seq_gap'], valid['balance_ratio'])
    print(f"\n  Gap → balance correlation:")
    print(f"    Spearman r={gap_balance_corr.statistic:.4f}, "
          f"p={gap_balance_corr.pvalue:.2e}")

    # Gap terciles → avg balance ratio
    seq['gap_tercile'] = pd.qcut(seq['seq_gap'], 3, labels=['fast', 'mid', 'slow'],
                                  duplicates='drop')
    gap_tercile_balance = seq.groupby('gap_tercile', observed=True)['balance_ratio'].mean()
    print(f"    By gap tercile:")
    for tercile in ['fast', 'mid', 'slow']:
        if tercile in gap_tercile_balance.index:
            print(f"      {tercile:6s}: avg balance {gap_tercile_balance[tercile]:.4f}")

    # Does first side predict excess side?
    seq['first_is_excess'] = seq['first_side'] == seq['excess_side']
    first_excess_rate = seq[~seq['first_side_equal']]['first_is_excess'].mean()
    print(f"\n  First side = excess side: {first_excess_rate*100:.1f}% "
          f"(50% = no effect)")

    # ── 2. Entry speed ──
    df['entry_speed'] = df['first_fill_ts'] - df['open_ts']
    # Filter to reasonable values (some markets may have misaligned timestamps)
    reasonable = df[(df['entry_speed'] >= -10) & (df['entry_speed'] < 1800)]

    print(f"\nEntry speed ({len(reasonable):,} markets with valid timing):")
    print(f"  Median: {reasonable['entry_speed'].median():.0f}s, "
          f"Mean: {reasonable['entry_speed'].mean():.1f}s")
    speed_bins = [
        ('< 5s', -10, 5),
        ('5-15s', 5, 15),
        ('15-30s', 15, 30),
        ('30-60s', 30, 60),
        ('60-300s', 60, 300),
        ('300s+', 300, float('inf')),
    ]
    for label, lo, hi in speed_bins:
        cnt = ((reasonable['entry_speed'] >= lo) & (reasonable['entry_speed'] < hi)).sum()
        pct = cnt / len(reasonable) * 100
        print(f"    {label:12s} {cnt:5,} ({pct:5.1f}%)")

    # Entry speed by market duration type
    for dur, dur_label in [(900, '15-min'), (3600, 'Hourly')]:
        subset = reasonable[reasonable['market_duration'] == dur]
        if len(subset) > 0:
            print(f"  {dur_label}: median {subset['entry_speed'].median():.0f}s, "
                  f"n={len(subset):,}")

    # Entry speed → balance
    valid_es = reasonable[reasonable['balance_ratio'].notna()]
    es_balance_corr = stats.spearmanr(valid_es['entry_speed'], valid_es['balance_ratio'])
    print(f"  Entry speed → balance: r={es_balance_corr.statistic:.4f}, "
          f"p={es_balance_corr.pvalue:.2e}")

    # ── 3. Execution duration ──
    df['exec_duration'] = df['last_fill_ts'] - df['first_fill_ts']

    print(f"\nExecution duration (first fill to last fill):")
    print(f"  Median: {df['exec_duration'].median():.0f}s, "
          f"Mean: {df['exec_duration'].mean():.1f}s")
    dur_bins = [
        ('< 60s', 0, 60),
        ('1-5 min', 60, 300),
        ('5-10 min', 300, 600),
        ('10-15 min', 600, 900),
        ('15+ min', 900, float('inf')),
    ]
    for label, lo, hi in dur_bins:
        cnt = ((df['exec_duration'] >= lo) & (df['exec_duration'] < hi)).sum()
        pct = cnt / len(df) * 100
        print(f"    {label:12s} {cnt:5,} ({pct:5.1f}%)")

    # ── 4. Price trajectory ──
    price_traj = db.price_trajectory_summary()

    # Pivot to per-market: first_5_avg_up, last_5_avg_up, first_5_avg_down, last_5_avg_down
    up_traj = price_traj[price_traj['outcome'] == 'Up'].set_index('condition_id')
    down_traj = price_traj[price_traj['outcome'] == 'Down'].set_index('condition_id')

    traj_df = pd.DataFrame({
        'first_5_up': up_traj['first_5_avg'],
        'last_5_up': up_traj['last_5_avg'],
        'range_up': up_traj['max_price'] - up_traj['min_price'],
        'up_buy_fills': up_traj['buy_fills'],
        'first_5_down': down_traj['first_5_avg'],
        'last_5_down': down_traj['last_5_avg'],
        'range_down': down_traj['max_price'] - down_traj['min_price'],
        'down_buy_fills': down_traj['buy_fills'],
    })

    traj_df['drift_up'] = traj_df['last_5_up'] - traj_df['first_5_up']
    traj_df['drift_down'] = traj_df['last_5_down'] - traj_df['first_5_down']
    # Combined drift: prices should move in opposite directions for crypto markets
    # Positive drift = price increased over execution window
    traj_both = traj_df.dropna(subset=['drift_up', 'drift_down'])

    print(f"\nPrice trajectory ({len(traj_both):,} both-sided markets):")
    print(f"  Up outcome: first-5 avg ${traj_both['first_5_up'].mean():.3f} "
          f"→ last-5 avg ${traj_both['last_5_up'].mean():.3f} "
          f"(drift {traj_both['drift_up'].mean():+.4f})")
    print(f"  Down outcome: first-5 avg ${traj_both['first_5_down'].mean():.3f} "
          f"→ last-5 avg ${traj_both['last_5_down'].mean():.3f} "
          f"(drift {traj_both['drift_down'].mean():+.4f})")
    print(f"  Avg intra-market price range: Up ${traj_both['range_up'].mean():.3f}, "
          f"Down ${traj_both['range_down'].mean():.3f}")

    # Price trajectory by fill count (proxy for self-impact)
    traj_both['total_buy_fills'] = traj_both['up_buy_fills'] + traj_both['down_buy_fills']
    fill_tercile = pd.qcut(traj_both['total_buy_fills'], 3,
                            labels=['low', 'mid', 'high'], duplicates='drop')
    traj_both = traj_both.copy()
    traj_both['fill_tercile'] = fill_tercile

    # Per-fill drift normalization: random walk expects |drift| ∝ √n,
    # so |drift|/fill ∝ 1/√n (decreasing). If drift/fill is constant or
    # increasing with fill count → genuine self-impact beyond random walk.
    print(f"  Drift by fill count (self-impact test):")
    print(f"    {'tier':4s} {'n':>6s}  {'avg fills':>9s}  "
          f"{'|drift|':>8s}  {'|drift|/fill':>12s}  {'range':>8s}")
    drift_per_fill_by_tier = {}
    for tercile in ['low', 'mid', 'high']:
        sub = traj_both[traj_both['fill_tercile'] == tercile]
        if len(sub) > 0:
            abs_drift = (sub['drift_up'].abs().mean() + sub['drift_down'].abs().mean()) / 2
            avg_fills = sub['total_buy_fills'].mean()
            dpf_up = (sub['drift_up'].abs() / sub['up_buy_fills'].clip(lower=1)).mean()
            dpf_down = (sub['drift_down'].abs() / sub['down_buy_fills'].clip(lower=1)).mean()
            dpf = (dpf_up + dpf_down) / 2
            avg_range = (sub['range_up'].mean() + sub['range_down'].mean()) / 2
            drift_per_fill_by_tier[tercile] = dpf
            print(f"    {tercile:4s} {len(sub):6,}  {avg_fills:9.0f}  "
                  f"${abs_drift:.4f}  ${dpf:.6f}  ${avg_range:.3f}")
    if 'low' in drift_per_fill_by_tier and 'high' in drift_per_fill_by_tier:
        dpf_ratio = drift_per_fill_by_tier['high'] / drift_per_fill_by_tier['low']
        if dpf_ratio > 1.1:
            verdict = f"INCREASING ({dpf_ratio:.2f}x) — evidence of self-impact"
        elif dpf_ratio < 0.9:
            verdict = f"DECREASING ({dpf_ratio:.2f}x) — consistent with random walk"
        else:
            verdict = f"FLAT ({dpf_ratio:.2f}x) — borderline"
        print(f"    Drift/fill trend: {verdict}")

    # ── 5. Sell execution patterns ──
    has_sells = df[df['first_sell_ts'].notna()].copy()

    if len(has_sells) > 0:
        has_sells['sell_delay'] = has_sells['first_sell_ts'] - has_sells['first_fill_ts']
        has_sells['sell_pct_of_window'] = np.where(
            has_sells['exec_duration'] > 0,
            has_sells['sell_delay'] / has_sells['exec_duration'],
            np.nan)

        # Which side gets sold more? (Up vs Down sell fills)
        has_sells['sell_up_frac'] = np.where(
            (has_sells['sell_up_fills'] + has_sells['sell_down_fills']) > 0,
            has_sells['sell_up_fills'] / (has_sells['sell_up_fills'] + has_sells['sell_down_fills']),
            0.5)

        print(f"\nSell execution ({len(has_sells):,} markets with sells):")
        print(f"  Sell delay from first buy: "
              f"mean {has_sells['sell_delay'].mean():.1f}s, "
              f"median {has_sells['sell_delay'].median():.1f}s")
        sell_pct = has_sells['sell_pct_of_window'].dropna()
        if len(sell_pct) > 0:
            print(f"  Sell at % of exec window: "
                  f"mean {sell_pct.mean()*100:.1f}%, "
                  f"median {sell_pct.median()*100:.1f}%")
        print(f"  Sell Up/Down split: "
              f"Up {has_sells['sell_up_fills'].sum():,} / "
              f"Down {has_sells['sell_down_fills'].sum():,}")

        # Does selling improve balance? Two tests:
        # (1) Cross-market (CONFOUNDED by selection — sell-markets are higher-fill)
        no_sells = df[df['first_sell_ts'].isna()]
        bal_with_sells = has_sells['balance_ratio'].mean()
        bal_without = no_sells['balance_ratio'].mean()
        print(f"  Cross-market balance: sell-markets {bal_with_sells:.4f} vs "
              f"no-sell {bal_without:.4f} (selection-biased)")

        # (2) Within-market (CLEAN): compare gross (pre-sell) vs net (post-sell)
        #     balance in the SAME markets. Isolates the causal effect of selling.
        gross_max = has_sells[['buy_up_shares', 'buy_down_shares']].max(axis=1)
        gross_min = has_sells[['buy_up_shares', 'buy_down_shares']].min(axis=1)
        has_sells['gross_balance'] = np.where(
            gross_max > 0, gross_min / gross_max, 0)
        gross_bal = has_sells['gross_balance'].mean()
        net_bal = has_sells['balance_ratio'].mean()
        delta = net_bal - gross_bal
        print(f"  Within-market: pre-sell {gross_bal:.4f} → "
              f"post-sell {net_bal:.4f} "
              f"({'improved' if delta > 0.001 else 'worsened' if delta < -0.001 else 'unchanged'}"
              f" by {abs(delta):.4f})")

        # Sell side vs excess side: does bot sell the excess (rebalancing) or short side (worsening)?
        has_sells['more_sell_side'] = np.where(
            has_sells['sell_up_fills'] >= has_sells['sell_down_fills'], 'Up', 'Down')
        sell_is_excess = (has_sells['more_sell_side'] == has_sells['excess_side']).mean()
        print(f"  Sells heavier on excess side: {sell_is_excess*100:.1f}% "
              f"(>50% = rebalancing)")

    # ── 6. Balance correlations (KEY) ──
    print(f"\nBalance ratio correlations (what drives execution quality):")

    # Merge sequencing gap and price trajectory onto main df for correlation
    df_corr = df.copy()
    # Add seq_gap from the sequencing analysis
    seq_gap_map = seq.set_index('condition_id')['seq_gap']
    df_corr['seq_gap'] = df_corr['condition_id'].map(seq_gap_map)

    if 'drift_up' in traj_both.columns:
        traj_merge = traj_both[['range_up', 'range_down', 'total_buy_fills']].copy()
        traj_merge.index.name = 'condition_id'
        traj_merge = traj_merge.reset_index()
        df_corr = df_corr.merge(traj_merge, on='condition_id', how='left')

    # Add market volume as book depth proxy
    vol_map = markets.set_index('condition_id')['volume']
    df_corr['market_volume'] = df_corr['condition_id'].map(vol_map)

    correlates = [
        ('seq_gap', 'Sequencing gap'),
        ('entry_speed', 'Entry speed'),
        ('total_fills', 'Total fills'),
        ('exec_duration', 'Exec duration'),
        ('market_volume', 'Market volume'),
    ]

    print(f"  Bivariate (each potentially confounded):")
    for col, label in correlates:
        if col in df_corr.columns:
            valid_c = df_corr[df_corr[col].notna() & df_corr['balance_ratio'].notna()]
            if len(valid_c) > 30:
                r, p = stats.spearmanr(valid_c[col], valid_c['balance_ratio'])
                sig = '*' if p < 0.01 else ''
                print(f"    {label:20s}: r={r:+.4f}  p={p:.2e} {sig}")

    # Fill count vs balance by tier
    df['fill_count_tier'] = pd.qcut(df['total_fills'], 4,
                                     labels=['Q1_low', 'Q2', 'Q3', 'Q4_high'],
                                     duplicates='drop')
    fill_balance = df.groupby('fill_count_tier', observed=True)['balance_ratio'].mean()
    print(f"\n  Balance by fill count quartile:")
    for tier in ['Q1_low', 'Q2', 'Q3', 'Q4_high']:
        if tier in fill_balance.index:
            print(f"    {tier:10s}: {fill_balance[tier]:.4f}")

    # Crypto asset vs balance (merge market metadata)
    from analyzers.market_structure import parse_market_questions
    markets_parsed = parse_market_questions(markets)
    df_asset = df.merge(markets_parsed[['condition_id', 'crypto_asset']],
                        on='condition_id', how='left')
    asset_balance = df_asset.groupby('crypto_asset')['balance_ratio'].agg(['mean', 'count'])
    print(f"\n  Balance by crypto asset:")
    for asset, row in asset_balance.sort_values('mean', ascending=False).iterrows():
        print(f"    {asset:12s}: {row['mean']:.4f}  (n={int(row['count']):,})")

    # Market duration vs balance
    dur_balance = df.groupby('market_duration')['balance_ratio'].agg(['mean', 'count'])
    print(f"\n  Balance by market duration:")
    for dur, row in dur_balance.iterrows():
        label = '15-min' if dur == 900 else 'Hourly'
        print(f"    {label:12s}: {row['mean']:.4f}  (n={int(row['count']):,})")

    # ── 7. Multivariate decomposition ──
    # Bivariate correlations are confounded: fill count, duration, asset,
    # market duration are all correlated (deeper markets → more fills AND
    # better balance). OLS separates independent effects.
    df_reg = df_asset.copy()
    df_reg['seq_gap'] = df_reg['condition_id'].map(seq_gap_map)
    df_reg['log_fills'] = np.log1p(df_reg['total_fills'])
    df_reg['is_hourly'] = (df_reg['market_duration'] == 3600).astype(float)
    df_reg['is_btc_eth'] = df_reg['crypto_asset'].isin(
        ['Bitcoin', 'Ethereum']).astype(float)
    df_reg['log_volume'] = np.log1p(df_reg['condition_id'].map(vol_map))

    features = ['log_fills', 'is_hourly', 'is_btc_eth', 'seq_gap', 'log_volume']
    target = 'balance_ratio'
    reg_data = df_reg[features + [target]].dropna()

    X = reg_data[features].values
    X = np.column_stack([np.ones(len(X)), X])
    y = reg_data[target].values

    beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r_sq = 1 - ss_res / ss_tot
    n_reg, k_reg = X.shape
    sigma_sq = ss_res / (n_reg - k_reg)
    try:
        cov = sigma_sq * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
        t_stats = beta / se
    except np.linalg.LinAlgError:
        se = np.full(k_reg, np.nan)
        t_stats = np.full(k_reg, np.nan)

    print(f"\n  Multivariate OLS: balance ~ features "
          f"(n={n_reg:,}, R²={r_sq:.3f})")
    feature_names = ['intercept'] + features
    for i, fname in enumerate(feature_names):
        sig = '*' if abs(t_stats[i]) > 2.576 else ''
        print(f"    {fname:15s}: β={beta[i]:+.5f}  "
              f"se={se[i]:.5f}  t={t_stats[i]:+6.2f} {sig}")

    # Interpretation helper
    sig_factors = [
        feature_names[i] for i in range(1, len(feature_names))
        if abs(t_stats[i]) > 2.576
    ]
    if sig_factors:
        print(f"    Significant (|t|>2.58): {', '.join(sig_factors)}")
    print(f"    Note: log_volume (lifetime traded volume) is a poor proxy for")
    print(f"    instantaneous book depth. log_fills retaining t={t_stats[1]:+.1f}")
    print(f"    after this control suggests some independent causal role")
    print(f"    (more fills = more rebalancing chances), but confounding")
    print(f"    with unmeasured depth cannot be fully ruled out.")

    return {
        'sequencing_df': seq,
        'price_trajectory_df': traj_both,
        'has_sells_df': has_sells if len(has_sells) > 0 else pd.DataFrame(),
        'summary': {
            'seq_gap_mean': float(seq['seq_gap'].mean()),
            'seq_gap_median': float(seq['seq_gap'].median()),
            'gap_balance_r': float(gap_balance_corr.statistic),
            'gap_balance_p': float(gap_balance_corr.pvalue),
            'first_is_excess_rate': float(first_excess_rate),
            'entry_speed_median': float(reasonable['entry_speed'].median()),
            'exec_duration_median': float(df['exec_duration'].median()),
            'drift_up': float(traj_both['drift_up'].mean()),
            'drift_down': float(traj_both['drift_down'].mean()),
            'sell_delay_mean': float(has_sells['sell_delay'].mean()) if len(has_sells) > 0 else 0,
        }
    }
