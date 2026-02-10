"""Phase 8b: Counterparty & Competitive Landscape Analysis.

Maps the bot's trading counterparties using on-chain maker/taker addresses.
Computes concentration metrics, repeat opponent analysis, bot vs human heuristics.
"""

import numpy as np
import pandas as pd

from config import CTF_EXCHANGE_ADDRESS, NEGRISK_CTF_EXCHANGE_ADDRESS
from storage.database import Database

# Exchange contract addresses (not real counterparties)
_EXCHANGE_CONTRACTS = {
    CTF_EXCHANGE_ADDRESS.lower(),
    NEGRISK_CTF_EXCHANGE_ADDRESS.lower(),
}


def analyze_counterparties(db: Database) -> dict:
    """Analyze the bot's counterparty universe from on-chain data.

    Returns dict with counterparty summary, concentration metrics,
    top counterparties table, and bot classification.
    """
    print("\n" + "=" * 60)
    print("PHASE 8b: COUNTERPARTY & COMPETITIVE LANDSCAPE")
    print("=" * 60)

    onchain_count = db.onchain_fill_count()
    if onchain_count == 0:
        print("  No on-chain data available — skipping")
        return {'summary': {}, 'available': False}

    cp = db.counterparty_summary()
    if cp.empty:
        print("  No counterparty data available")
        return {'summary': {}, 'available': False}

    # ── Filter out exchange contracts ──
    cp['is_exchange'] = cp['counterparty'].str.lower().isin(_EXCHANGE_CONTRACTS)
    exchange_cp = cp[cp['is_exchange']]
    cp_real = cp[~cp['is_exchange']].copy()

    # ── 1. Universe size ──
    print(f"\n  1. COUNTERPARTY UNIVERSE")

    n_raw = len(cp)
    n_exchange = len(exchange_cp)
    exchange_fills = exchange_cp['fills'].sum() if not exchange_cp.empty else 0
    exchange_vol = exchange_cp['volume'].sum() if not exchange_cp.empty else 0

    n_counterparties = len(cp_real)
    total_fills = cp_real['fills'].sum()
    total_volume = cp_real['volume'].sum()
    total_markets = cp_real['markets'].max()  # max since markets overlap

    print(f"    Raw counterparty addresses: {n_raw:,}")
    if n_exchange > 0:
        print(f"    Exchange contract fills:    {exchange_fills:,} "
              f"({exchange_fills/(exchange_fills+total_fills)*100:.1f}%) — "
              f"filtered out")
    print(f"    Real counterparties:        {n_counterparties:,}")
    print(f"    Total matched fills:        {total_fills:,}")
    print(f"    Total matched volume:       ${total_volume:,.0f}")

    # ── 2. Concentration metrics ──
    print(f"\n  2. CONCENTRATION METRICS")

    # Volume shares (on real counterparties only)
    cp_real['volume_share'] = cp_real['volume'] / total_volume
    cp_real['fill_share'] = cp_real['fills'] / total_fills

    # HHI (Herfindahl-Hirschman Index) — sum of squared market shares
    hhi = (cp_real['volume_share'] ** 2).sum()
    hhi_normalized = (hhi - 1/n_counterparties) / (1 - 1/n_counterparties) \
        if n_counterparties > 1 else 1.0

    print(f"    HHI (volume): {hhi:.6f}")
    print(f"    HHI normalized: {hhi_normalized:.6f}")
    if hhi < 0.01:
        print(f"    → Highly fragmented (HHI < 0.01)")
    elif hhi < 0.15:
        print(f"    → Moderately concentrated")
    else:
        print(f"    → Highly concentrated (HHI > 0.15)")

    # Top-N share
    cp_sorted = cp_real.sort_values('volume', ascending=False).reset_index(
        drop=True)
    top1_share = cp_sorted.iloc[0]['volume_share'] * 100
    top10_share = cp_sorted.head(10)['volume_share'].sum() * 100
    top50_share = cp_sorted.head(50)['volume_share'].sum() * 100

    print(f"    Top-1 share:  {top1_share:.1f}%")
    print(f"    Top-10 share: {top10_share:.1f}%")
    print(f"    Top-50 share: {top50_share:.1f}%")

    # Gini coefficient
    n = len(cp_real)
    sorted_volumes = np.sort(cp_real['volume'].values)
    index = np.arange(1, n + 1)
    gini = (2 * np.sum(index * sorted_volumes) / (n * np.sum(sorted_volumes))
            - (n + 1) / n)

    print(f"    Gini coefficient: {gini:.3f}")
    if gini > 0.8:
        print(f"    → High inequality (few counterparties dominate)")
    elif gini > 0.5:
        print(f"    → Moderate inequality")
    else:
        print(f"    → Relatively equal distribution")

    # ── 3. Top counterparties table ──
    print(f"\n  3. TOP 20 COUNTERPARTIES")

    top20 = cp_sorted.head(20).copy()
    top20['addr_short'] = top20['counterparty'].apply(
        lambda x: f"{x[:8]}...{x[-6:]}" if isinstance(x, str) and len(x) > 14
        else str(x))

    print(f"    {'Rank':>4s}  {'Address':15s}  {'Fills':>8s}  "
          f"{'Volume':>12s}  {'Share':>6s}  {'Markets':>7s}")
    print(f"    {'─'*4}  {'─'*15}  {'─'*8}  {'─'*12}  {'─'*6}  {'─'*7}")
    for i, (_, row) in enumerate(top20.iterrows()):
        print(f"    {i+1:4d}  {row['addr_short']:15s}  "
              f"{int(row['fills']):8,}  ${row['volume']:11,.0f}  "
              f"{row['volume_share']*100:5.1f}%  {int(row['markets']):7,}")

    # ── 4. Repeat opponent analysis ──
    print(f"\n  4. REPEAT OPPONENT ANALYSIS")

    # Distribution of fills per counterparty
    fill_pcts = [1, 5, 10, 25, 50]
    for pct in fill_pcts:
        n_cp = max(1, int(n_counterparties * pct / 100))
        top_n = cp_sorted.head(n_cp)
        vol_share = top_n['volume'].sum() / total_volume * 100
        fill_share = top_n['fills'].sum() / total_fills * 100
        print(f"    Top {pct:2d}% ({n_cp:,} addrs): "
              f"{vol_share:.1f}% volume, {fill_share:.1f}% fills")

    # Fill count distribution
    print(f"\n    Fill count distribution:")
    fill_brackets = [(1, 1), (2, 10), (11, 100), (101, 1000), (1001, None)]
    for lo, hi in fill_brackets:
        if hi:
            mask = (cp_real['fills'] >= lo) & (cp_real['fills'] <= hi)
            label = f"{lo:,}-{hi:,}"
        else:
            mask = cp_real['fills'] >= lo
            label = f"{lo:,}+"
        bracket_cp = cp_real[mask]
        n_bracket = len(bracket_cp)
        vol_bracket = bracket_cp['volume'].sum()
        print(f"      {label:>10s} fills: {n_bracket:,} counterparties, "
              f"${vol_bracket:,.0f} volume")

    # ── 5. Bot vs human heuristics ──
    print(f"\n  5. BOT vs HUMAN CLASSIFICATION")

    # For counterparties with >50 fills, compute activity metrics
    # NOTE: thresholds (fills>1000, fills_per_hour>10) are heuristic;
    # time_span from 20K sample is noisy. Classification is approximate.
    active_cp = cp_real[cp_real['fills'] > 50].copy()

    if not active_cp.empty:
        active_cp['time_span_hours'] = (
            (active_cp['last_seen'] - active_cp['first_seen']) / 3600
        ).clip(lower=1)
        active_cp['fills_per_hour'] = (
            active_cp['fills'] / active_cp['time_span_hours'])

        # Classification: likely_bot if fills > 1000 OR fills_per_hour > 10
        active_cp['likely_bot'] = (
            (active_cp['fills'] > 1000)
            | (active_cp['fills_per_hour'] > 10))

        n_likely_bot = active_cp['likely_bot'].sum()
        n_likely_human = len(active_cp) - n_likely_bot

        bot_volume = active_cp[active_cp['likely_bot']]['volume'].sum()
        human_volume = active_cp[~active_cp['likely_bot']]['volume'].sum()

        print(f"    Active counterparties (>50 fills): {len(active_cp):,}")
        print(f"    (Heuristic classification — thresholds are approximate)")
        print(f"    Likely bots: {n_likely_bot:,} "
              f"(${bot_volume:,.0f}, "
              f"{bot_volume/total_volume*100:.1f}% of volume)")
        print(f"    Likely humans: {n_likely_human:,} "
              f"(${human_volume:,.0f}, "
              f"{human_volume/total_volume*100:.1f}% of volume)")

        # Bot characteristics
        bots = active_cp[active_cp['likely_bot']]
        if not bots.empty:
            print(f"\n    Bot counterparty characteristics:")
            print(f"      Avg fills: {bots['fills'].mean():,.0f}")
            print(f"      Avg markets: {bots['markets'].mean():,.0f}")
            print(f"      Avg fills/hour: {bots['fills_per_hour'].mean():,.1f}")
            print(f"      Median time span: "
                  f"{bots['time_span_hours'].median():,.0f} hours")

        # Inactive counterparties volume (single interaction)
        inactive_cp = cp_real[cp_real['fills'] <= 50]
        inactive_vol = inactive_cp['volume'].sum()
        print(f"\n    Inactive counterparties (<=50 fills): "
              f"{len(inactive_cp):,}")
        print(f"      Volume: ${inactive_vol:,.0f} "
              f"({inactive_vol/total_volume*100:.1f}%)")

        classification_df = active_cp
    else:
        classification_df = pd.DataFrame()
        print("    (no counterparties with >50 fills)")

    concentration = {
        'hhi': float(hhi),
        'hhi_normalized': float(hhi_normalized),
        'gini': float(gini),
        'top1_share': float(top1_share),
        'top10_share': float(top10_share),
        'top50_share': float(top50_share),
    }

    summary = {
        'n_counterparties': n_counterparties,
        'total_fills': int(total_fills),
        'total_volume': float(total_volume),
        **concentration,
    }

    print(f"\n  Summary: {n_counterparties:,} real counterparties "
          f"(exchange contracts filtered), "
          f"top-10 = {top10_share:.1f}%, "
          f"Gini = {gini:.3f}")

    return {
        'summary': summary,
        'top_counterparties': top20,
        'concentration': concentration,
        'classification_df': classification_df,
        'full_cp': cp_sorted,
        'available': True,
    }
