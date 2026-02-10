"""Phase 7: Strategy synthesis — cross-phase aggregation for the report."""


def synthesize(phase3_result, phase4_result, phase5_result, phase6_result):
    """Aggregate findings from all phases into a unified synthesis dict.

    No new computation — just organizes existing results into a
    report-friendly structure with strategy classification, headline
    metrics, bot fingerprint, and replication feasibility.
    """
    structure = phase3_result['structure']
    completeness = phase3_result['completeness']
    execution = phase4_result['execution']
    sizing = phase4_result['sizing']
    pnl = phase5_result['pnl']
    risk = phase5_result['risk']
    temporal = phase6_result['temporal']

    cs = completeness['summary']
    ps = pnl['summary']
    rs = risk['summary']
    ss = sizing['summary']
    es = execution['summary']
    ts = temporal['summary']
    strs = structure['summary']

    # ── 1. Strategy classification ──
    strategy = {
        'type': 'completeness_arbitrage',
        'label': 'Pure Completeness Arbitrage',
        'description': (
            'Buys both Up and Down outcomes on crypto 15-minute binary '
            'markets at combined cost below $1.00, capturing the spread '
            'at resolution. No directional prediction model.'
        ),
        'evidence': {
            'symmetric_z': cs.get('tilt_symmetric_z', 0),
            'permutation_p': cs.get('perm_p_value', 0),
            'one_sided_accuracy': strs.get('one_sided_accuracy', 0),
        },
    }

    # ── 2. Headline metrics ──
    theoretical = ps['completeness_spread']
    actual_trade = ps['trade_derived_pnl']
    capture_rate = actual_trade / theoretical if theoretical > 0 else 0

    # Compute dynamic stats that were previously hardcoded in the report
    daily_pnl = pnl['daily_pnl']
    positive_days = int((daily_pnl['pnl'] > 0).sum()) if len(daily_pnl) > 0 else 0
    trading_days = len(daily_pnl)
    positive_days_pct = positive_days / trading_days if trading_days > 0 else 0

    # Hourly vs 15-min market split (from execution sequencing_df)
    seq = execution['sequencing_df']
    if 'market_duration' in seq.columns:
        hourly_markets = int((seq['market_duration'] == 3600).sum())
        fifteen_min_markets = int((seq['market_duration'] == 900).sum())
    else:
        hourly_markets = 0
        fifteen_min_markets = strs['total_markets']
    total_classified = hourly_markets + fifteen_min_markets
    hourly_pct = hourly_markets / total_classified if total_classified > 0 else 0
    fifteen_min_pct = fifteen_min_markets / total_classified if total_classified > 0 else 0

    headline = {
        'total_pnl_positions': ps['position_derived_pnl'],
        'total_pnl_trades': actual_trade,
        'maker_rebates': ps['maker_rebates'],
        'theoretical_edge': theoretical,
        'capture_rate': capture_rate,
        'directional_drag': ps['directional_drag'],
        'sell_pnl': ps['sell_pnl'],
        'sell_discipline_value': ps['sell_discipline_value'],
        'hold_pnl': ps['hold_pnl'],
        'markets_traded': strs['total_markets'],
        'both_sided': strs['both_sided'],
        'one_sided': strs.get('up_only', 0) + strs.get('down_only', 0),
        'avg_spread': cs['avg_spread'],
        'total_matched_pairs': cs['total_matched_pairs'],
        'total_unmatched': cs['total_unmatched'],
        'win_rate': ps['win_rate'],
        'profit_factor': ps['profit_factor'],
        'expectancy': ps['expectancy'],
        'sharpe_annual': rs['sharpe_annual'],
        'max_drawdown': rs['max_drawdown'],
        'calmar': rs['calmar'],
        'dd_exposure_ratio': rs['dd_exposure_ratio'],
        'max_loss_streak': rs['max_loss_streak'],
        'max_win_streak': rs['max_win_streak'],
        'tail_p5': rs['tail_p5'],
        'positive_days': positive_days,
        'trading_days': trading_days,
        'positive_days_pct': positive_days_pct,
        'hourly_markets': hourly_markets,
        'fifteen_min_markets': fifteen_min_markets,
        'hourly_pct': hourly_pct,
        'fifteen_min_pct': fifteen_min_pct,
    }

    # ── 3. Bot fingerprint ──
    fingerprint = {
        'entry_speed_median_s': es['entry_speed_median'],
        'exec_duration_median_s': es['exec_duration_median'],
        'seq_gap_median_s': es['seq_gap_median'],
        'avg_buy_outlay': ss['avg_buy_outlay'],
        'total_buy_outlay': ss['total_buy_outlay'],
        'total_sell_recovery': ss['total_sell_recovery'],
        'peak_concurrent_exposure': ss['peak_exposure'],
        'avg_concurrent_exposure': ss['avg_exposure'],
        'peak_concurrent_markets': ss['peak_concurrent_markets'],
        'active_hours': 24,
        'peak_hour_utc': ts['peak_hour'],
        'weekend_weekday_ratio': ts['weekend_weekday_ratio'],
        'schedule_type': 'market_cadence_driven',
        'sell_trigger': 'price_based (loss-cutting 58% + rebalancing 42%)',
    }

    # ── 4. Replication feasibility ──
    improvement_multiple = theoretical / actual_trade if actual_trade > 0 else 0

    replication = {
        'capital_required': ss['peak_exposure'],
        'improvement_potential': improvement_multiple,
        'key_drivers': [
            f'Execution balance (fill count t=41.5 in OLS, R²=0.262)',
            f'Market selection (hourly markets +10.8pp balance)',
            f'Sell discipline (+${ps["sell_discipline_value"]:,.0f} vs hold)',
            f'Speed ({es["entry_speed_median"]:.0f}s median entry)',
            f'Coverage (~370 markets/day across 4 assets)',
        ],
        'not_required': 'Directional price prediction model',
        'spread_trend': 'expanding (+5.34¢ over 22 days)',
        'regime_caveat': (
            '22-day window covers a single volatility regime. '
            'Strategy profitability conditional on continued wide spreads.'
        ),
        'asset_spread_deltas': ts.get('asset_spread_deltas', {}),
    }

    # ── 5. Data limitations ──
    limitations = [
        'No order book snapshots — cannot measure execution quality vs BBO',
        'maker_address empty for all 1.3M trades — no per-fill maker/taker',
        'Price trajectory observable but attribution ambiguous (self-impact vs organic)',
        'Counterparty identity unknown — competitive landscape not assessable',
        f'Trade window covers {strs["total_markets"]:,} of ~13,500 total markets; '
        f'P&L gap ${ps["position_derived_pnl"] - actual_trade:,.0f} from pre-window',
    ]

    # ── Console summary ──
    print("\n" + "=" * 60)
    print("STRATEGY SYNTHESIS")
    print("=" * 60)
    print(f"  Strategy: {strategy['label']}")
    print(f"  Position P&L: ${headline['total_pnl_positions']:,.0f}")
    print(f"  Trade P&L:    ${headline['total_pnl_trades']:,.0f} "
          f"({capture_rate:.1%} of ${theoretical:,.0f} theoretical)")
    print(f"  Maker rebates: ${headline['maker_rebates']:,.0f}")
    print(f"  Leakage: drag ${headline['directional_drag']:,.0f} "
          f"+ sell ${headline['sell_pnl']:,.0f}")
    print(f"  Improvement: {improvement_multiple:.1f}x if perfectly balanced")
    print(f"  Sharpe: {headline['sharpe_annual']:.1f} | "
          f"Max DD: ${headline['max_drawdown']:,.0f} | "
          f"Win rate: {headline['win_rate']:.1%}")
    print(f"  Bot: {es['entry_speed_median']:.0f}s entry, 24/7, "
          f"{strs['total_markets']:,} markets, "
          f"${ss['peak_exposure']:,.0f} peak exposure")
    print("=" * 60)

    return {
        'strategy': strategy,
        'headline': headline,
        'fingerprint': fingerprint,
        'replication': replication,
        'limitations': limitations,
    }
