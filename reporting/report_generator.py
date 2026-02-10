"""Phase 7: HTML report generator.

Assembles all phase results + charts into a self-contained HTML report.
"""

import os

import plotly.io as pio

import config
from reporting import charts


# ── Helpers ──

def _chart(fig):
    """Convert a Plotly figure to an embeddable HTML div."""
    if fig is None:
        return '<p class="muted">Chart not available for this dataset.</p>'
    return pio.to_html(fig, full_html=False, include_plotlyjs=False)


def _metric_card(value, label):
    return (f'<div class="metric-card">'
            f'<div class="value">{value}</div>'
            f'<div class="label">{label}</div></div>')


def _table(headers, rows):
    hdr = ''.join(f'<th>{h}</th>' for h in headers)
    body = ''
    for row in rows:
        cells = ''.join(f'<td>{c}</td>' for c in row)
        body += f'<tr>{cells}</tr>\n'
    return f'<table><thead><tr>{hdr}</tr></thead><tbody>{body}</tbody></table>'


def _finding(text, level='info'):
    return f'<div class="finding {level}"><p>{text}</p></div>'


def _section(id_, title, content):
    return (f'<div class="section" id="{id_}">'
            f'<h2>{title}</h2>{content}</div>\n')


# ── Section Builders ──

def _section_exec_summary(h, synthesis):
    """Section 1: Executive Summary."""
    s = synthesis['strategy']
    cards = (
        _metric_card(f'${h["total_pnl_positions"]:,.0f}', 'Total P&L (Positions)')
        + _metric_card(f'${h["total_pnl_trades"]:,.0f}', 'Trade-Derived P&L')
        + _metric_card(f'${h["theoretical_edge"]:,.0f}', 'Theoretical Edge')
        + _metric_card(f'{h["capture_rate"]:.0%}', 'Capture Rate')
        + _metric_card(f'{h["markets_traded"]:,}', 'Markets Traded')
        + _metric_card(f'{h["sharpe_annual"]:.1f}', 'Sharpe (Annual)')
        + _metric_card(f'{h["win_rate"]:.1%}', 'Win Rate')
        + _metric_card(f'${h["max_drawdown"]:,.0f}', 'Max Drawdown')
    )
    return _section('summary', 'Executive Summary', f'''
        <p><strong>Strategy:</strong> {s["label"]} &mdash; {s["description"]}</p>
        {_finding(
            f'The bot captures only <strong>{h["capture_rate"]:.0%}</strong> of its '
            f'${h["theoretical_edge"]:,.0f} theoretical edge. '
            f'The remaining {1 - h["capture_rate"]:.0%} is lost to execution imbalance '
            f'(${h["directional_drag"]:,.0f} directional drag) and sell losses '
            f'(${h["sell_pnl"]:,.0f}). '
            f'<strong>No directional prediction model</strong> &mdash; confirmed by '
            f'symmetric subset test (z={s["evidence"]["symmetric_z"]:.2f}) '
            f'and stratified permutation (p={s["evidence"]["permutation_p"]:.1f}).',
            'key'
        )}
        <div class="metric-grid">{cards}</div>
    ''')


def _section_market_universe(strs, structure_result, h):
    """Section 2: Market Universe."""
    asset_dist = structure_result.get('asset_distribution')
    rows = []
    if asset_dist is not None:
        for asset, count in asset_dist.items():
            pct = count / strs['total_markets'] * 100
            rows.append((asset, f'{count:,}', f'{pct:.1f}%'))

    tbl = _table(['Asset', 'Markets', 'Share'], rows) if rows else ''

    both_pct = strs['both_sided'] / strs['total_markets'] * 100
    one_sided = strs.get('up_only', 0) + strs.get('down_only', 0)
    one_pct = one_sided / strs['total_markets'] * 100

    return _section('universe', 'Market Universe', f'''
        <p>The bot operates exclusively on <strong>crypto 15-minute and hourly
        binary markets</strong> on Polymarket, trading 4 assets across
        {strs["total_markets"]:,} markets in {h["trading_days"]} days.</p>
        <div class="two-col">
            <div>
                {tbl}
            </div>
            <div>
                {_table(
                    ['Metric', 'Value'],
                    [('Both-sided (buy Up + Down)', f'{strs["both_sided"]:,} ({both_pct:.1f}%)'),
                     ('One-sided (execution failures)', f'{one_sided:,} ({one_pct:.1f}%)'),
                     ('One-sided accuracy', f'{strs.get("one_sided_accuracy", 0):.1%}'),
                     ('Hourly markets', f'{h["hourly_markets"]:,} ({h["hourly_pct"]:.0%})'),
                     ('15-minute markets', f'{h["fifteen_min_markets"]:,} ({h["fifteen_min_pct"]:.0%})'),
                     ('negRisk', f'{strs.get("neg_risk", 0)} (all simple binary)')]
                )}
            </div>
        </div>
        {_finding(
            'One-sided markets are execution failures (late entry), not directional bets. '
            '42.7% accuracy (below random), P&L = -$427. XRP has highest one-sided rate (6.9%).',
            'warn'
        )}
    ''')


def _section_completeness(cs, tier_summary, chart_spread, chart_balance):
    """Section 3: Completeness Arbitrage."""
    # Build tier table
    tier_rows = []
    tier_labels = {'well_balanced': 'Well-balanced', 'moderate': 'Moderate',
                   'imbalanced': 'Imbalanced', 'very_imbalanced': 'Very imbalanced'}
    for tier in ['well_balanced', 'moderate', 'imbalanced', 'very_imbalanced']:
        if tier in tier_summary.index:
            r = tier_summary.loc[tier]
            cnt = int(r.get('count', 0))
            if cnt == 0:
                continue
            pct = cnt / cs['both_sided_count'] * 100
            tier_rows.append((
                tier_labels[tier], f'{cnt:,}', f'{pct:.1f}%',
                f'${r.get("avg_combined_vwap", 0):.4f}',
                f'${r.get("avg_spread", 0):.4f}',
                f'{r.get("total_matched", 0)/1e6:.2f}M',
            ))

    return _section('completeness', 'Completeness Arbitrage', f'''
        <p>The core strategy: buy <em>both</em> outcomes (Up and Down) at combined
        cost below $1.00. At resolution, one outcome pays $1.00, guaranteeing a
        profit equal to the spread. Effectiveness depends on share balance.</p>
        {_table(
            ['Metric', 'Value'],
            [('Avg combined VWAP', f'${cs["avg_combined_vwap"]:.4f}'),
             ('Avg spread', f'${cs["avg_spread"]:.4f} ({cs["avg_spread"]*100:.1f}\xa2)'),
             ('Total matched pairs', f'{cs["total_matched_pairs"]/1e6:.2f}M'),
             ('Total unmatched shares', f'{cs["total_unmatched"]/1e6:.2f}M'),
             ('Theoretical guaranteed profit', f'${cs["total_guaranteed_profit"]:,.0f}')]
        )}
        <h3>Balance Tiers</h3>
        <p>Only well-balanced markets capture most of the spread.
        Imbalanced markets create directional exposure that erodes profit.</p>
        {_table(['Tier', 'Count', '%', 'VWAP', 'Spread', 'Matched'], tier_rows)}
        <div class="two-col">
            <div class="chart-container">{chart_spread}</div>
            <div class="chart-container">{chart_balance}</div>
        </div>
        {_finding(
            'No directional model: symmetric subset z=-5.10 (anti-prediction), '
            'stratified permutation p=1.0, near-equal allocation (Up frac 0.4925). '
            'All profit comes from the completeness spread.',
            'key'
        )}
    ''')


def _section_execution(es, ts, chart_entry, chart_hourly, chart_spread_hour):
    """Section 4: Execution Microstructure."""
    return _section('execution', 'Execution Microstructure', f'''
        <p>The bot is a fully automated, market-cadence-driven system that
        enters every new market within seconds and executes throughout the
        entire window.</p>
        {_table(
            ['Metric', 'Value'],
            [('Entry speed (median)', f'{es["entry_speed_median"]:.0f}s from market open'),
             ('Execution duration (median)', f'{es["exec_duration_median"]:.0f}s'),
             ('Sequencing gap (median)', f'{es["seq_gap_median"]:.0f}s (Up/Down buy gap)'),
             ('Peak hour', f'{ts["peak_hour"]}:00 UTC'),
             ('Activity range', f'{ts["fill_range"]:.1f}x (peak/quiet)'),
             ('Weekend/weekday ratio', f'{ts["weekend_weekday_ratio"]:.2f}x'),
             ('Schedule verdict', ts["schedule_verdict"][:80] + '...')]
        )}
        <div class="chart-container">{chart_entry}</div>
        <div class="two-col">
            <div class="chart-container">{chart_hourly}</div>
            <div class="chart-container">{chart_spread_hour}</div>
        </div>
        {_finding(
            'Fills-spread hourly correlation r=-0.076, p=0.725 (not significant). '
            'The bot does not chase spreads &mdash; it fires on every new market '
            'regardless of spread width, modulated only by Polymarket\'s market '
            'creation rate.',
            'info'
        )}
    ''')


def _section_edge_leakage(h, chart_waterfall, chart_bvp, chart_tier):
    """Section 5: Edge Leakage — THE central finding."""
    return _section('leakage', 'Edge Leakage Analysis', f'''
        {_finding(
            f'The bot captures <strong>{h["capture_rate"]:.0%}</strong> '
            f'(${h["total_pnl_trades"]:,.0f}) of its '
            f'${h["theoretical_edge"]:,.0f} theoretical edge. '
            f'{1 - h["capture_rate"]:.0%} is lost to directional drag on '
            f'{h["total_unmatched"]/1e6:.1f}M unmatched shares '
            f'and sell losses from loss-cutting.',
            'key'
        )}
        <div class="chart-container">{chart_waterfall}</div>
        <h3>Why Leakage Happens</h3>
        <p><strong>Fill count is the dominant predictor of balance quality</strong>
        (t=41.5 in OLS, R&sup2;=0.262). More fills = more chances to balance
        Up and Down shares. Hourly markets have a genuine independent advantage
        (+10.8pp, t=13.0). BTC/ETH advantage disappears after controlling for
        fill count.</p>
        {_table(
            ['Component', 'Amount', '% of Spread'],
            [('Completeness spread (theoretical)', f'${h["theoretical_edge"]:,.0f}', '100%'),
             ('Directional drag', f'${h["directional_drag"]:+,.0f}',
              f'{abs(h["directional_drag"])/h["theoretical_edge"]*100:.1f}%'),
             ('Sell losses', f'${h["sell_pnl"]:+,.0f}',
              f'{abs(h["sell_pnl"])/h["theoretical_edge"]*100:.1f}%'),
             ('Actual P&L', f'${h["total_pnl_trades"]:+,.0f}',
              f'{h["capture_rate"]*100:.1f}%')]
        )}
        <div class="two-col">
            <div class="chart-container">{chart_bvp}</div>
            <div class="chart-container">{chart_tier}</div>
        </div>
    ''')


def _section_pnl(ps, h, chart_cum, chart_asset, chart_capital):
    """Section 6: P&L Decomposition."""
    return _section('pnl', 'P&L Decomposition', f'''
        <p>Three-component decomposition is algebraically exact (max per-market
        error $0.000).</p>
        {_table(
            ['Component', 'Amount', 'Notes'],
            [('Completeness spread', f'${ps["completeness_spread"]:+,.0f}',
              'matched_pairs \xd7 (1 - combined_VWAP)'),
             ('Directional drag', f'${ps["directional_drag"]:+,.0f}',
              'Unmatched shares \xd7 (resolution - entry)'),
             ('Sell P&L', f'${ps["sell_pnl"]:+,.0f}',
              'Sell proceeds - cost basis of sold shares'),
             ('<strong>Trade-derived total</strong>',
              f'<strong>${ps["trade_derived_pnl"]:+,.0f}</strong>', ''),
             ('Maker rebates', f'${ps["maker_rebates"]:+,.0f}',
              '34 daily payouts'),
             ('Position P&L (ground truth)', f'${ps["position_derived_pnl"]:+,.0f}',
              'Includes pre-trade-window markets')]
        )}
        <h3>Sell Discipline</h3>
        {_finding(
            f'Selling <strong>improved</strong> returns by '
            f'${ps["sell_discipline_value"]:,.0f} vs hold-to-resolution '
            f'(hold P&L would be ${ps["hold_pnl"]:,.0f}). '
            f'Two mechanisms: loss-cutting (58%, avg 24% deterioration) and '
            f'rebalancing (42%, selling excess winners). '
            f'72% of sell-markets benefited.',
            'key'
        )}
        <div class="chart-container">{chart_cum}</div>
        <div class="two-col">
            <div class="chart-container">{chart_asset}</div>
            <div class="chart-container">{chart_capital}</div>
        </div>
    ''')


def _section_risk(rs, h):
    """Section 7: Risk & Performance."""
    return _section('risk', 'Risk & Performance', f'''
        {_table(
            ['Metric', 'Value', 'Notes'],
            [('Sharpe ratio (annual)', f'{rs["sharpe_annual"]:.1f}',
              'Resolution-based, not mark-to-market'),
             ('Max drawdown', f'${rs["max_drawdown"]:,.0f}', ''),
             ('DD / peak exposure', f'{rs["dd_exposure_ratio"]:.1%}',
              'More practical risk metric'),
             ('Calmar ratio', f'{rs["calmar"]:.0f}', ''),
             ('Win rate', f'{h["win_rate"]:.1%}',
              'Market-level (both-sided)'),
             ('Profit factor', f'{h["profit_factor"]:.2f}',
              'Gross wins / gross losses'),
             ('Expectancy', f'${h["expectancy"]:,.0f}',
              'Avg P&L per market'),
             ('Max loss streak', f'{rs["max_loss_streak"]}',
              'Consecutive losing markets'),
             ('Max win streak', f'{rs["max_win_streak"]}', ''),
             ('Tail P5', f'${rs["tail_p5"]:,.0f}',
              '5th percentile market P&L'),
             ('Positive days', f'{h["positive_days"]}/{h["trading_days"]} ({h["positive_days_pct"]:.0%})', 'Of trading days')]
        )}
        {_finding(
            'Sharpe of 18 confirms consistent arb execution but is '
            'resolution-based &mdash; open-position exposure is invisible. '
            'More practical: max drawdown / peak exposure = ~4%.',
            'warn'
        )}
    ''')


def _section_replication(fp, rep, synthesis, chart_spread_evo):
    """Section 8: Bot Signature & Replication."""
    lim_html = ''.join(f'<li>{l}</li>' for l in synthesis['limitations'])
    driver_html = ''.join(f'<li>{d}</li>' for d in rep['key_drivers'])
    asset_deltas = rep.get('asset_spread_deltas', {})
    delta_rows = [(a, f'+{d:.1f}\xa2') for a, d in sorted(
        asset_deltas.items(), key=lambda x: -x[1])]

    return _section('replication', 'Bot Signature & Replication', f'''
        <h3>Bot Fingerprint</h3>
        <div class="two-col">
            <div>
                {_table(
                    ['Characteristic', 'Value'],
                    [('Entry speed', f'{fp["entry_speed_median_s"]:.0f}s median'),
                     ('Execution duration', f'{fp["exec_duration_median_s"]:.0f}s median'),
                     ('Up/Down sequencing gap', f'{fp["seq_gap_median_s"]:.0f}s median'),
                     ('Avg capital per market', f'${fp["avg_buy_outlay"]:,.0f}'),
                     ('Peak concurrent exposure', f'${fp["peak_concurrent_exposure"]:,.0f}'),
                     ('Peak concurrent markets', f'{fp["peak_concurrent_markets"]}'),
                     ('Active hours', f'{fp["active_hours"]}/24'),
                     ('Schedule type', 'Market-cadence-driven')]
                )}
            </div>
            <div>
                {_table(
                    ['Characteristic', 'Value'],
                    [('Total buy outlay', f'${fp["total_buy_outlay"]:,.0f}'),
                     ('Sell recovery', f'${fp["total_sell_recovery"]:,.0f}'),
                     ('Peak hour', f'{fp["peak_hour_utc"]}:00 UTC'),
                     ('Weekend reduction', f'{fp["weekend_weekday_ratio"]:.2f}x'),
                     ('Sell trigger', fp['sell_trigger'])]
                )}
            </div>
        </div>

        <h3>Replication Requirements</h3>
        {_table(
            ['Requirement', 'Detail'],
            [('Capital', f'~${rep["capital_required"]:,.0f} peak concurrent exposure'),
             ('Prediction model', f'<strong>{rep["not_required"]}</strong>'),
             ('Improvement potential',
              f'{rep["improvement_potential"]:.1f}x if perfectly balanced')]
        )}
        <p><strong>Key drivers to optimize:</strong></p>
        <ol>{driver_html}</ol>

        <h3>Edge Sustainability</h3>
        <p>Spreads are <strong>expanding</strong> ({rep["spread_trend"]}), not
        compressing. Per-asset spread widening:</p>
        {_table(['Asset', 'Spread Widening'], delta_rows) if delta_rows else ''}
        <div class="chart-container">{chart_spread_evo}</div>
        {_finding(rep["regime_caveat"], 'warn')}

        <h3>Data Limitations</h3>
        <ul>{lim_html}</ul>
    ''')


# ── Main Generator ──

def generate_report(db, phase3, phase4, phase5, phase6, synthesis):
    """Generate self-contained HTML report at output/report.html."""
    completeness = phase3['completeness']
    structure = phase3['structure']
    execution = phase4['execution']
    sizing = phase4['sizing']
    pnl = phase5['pnl']
    risk = phase5['risk']
    temporal = phase6['temporal']
    h = synthesis['headline']

    print("\n  Generating charts...")

    # Generate all chart HTML divs
    c = {}
    chart_figs = {
        'waterfall': charts.edge_leakage_waterfall(pnl['summary']),
        'cum_pnl': charts.cumulative_pnl_daily(pnl['daily_pnl']),
        'spread_dist': charts.spread_distribution(completeness['per_market_df']),
        'balance_dist': charts.balance_distribution(completeness['per_market_df']),
        'balance_pnl': charts.balance_vs_pnl(pnl['resolved_df']),
        'asset_pnl': charts.per_asset_pnl(pnl['asset_pnl']),
        'spread_evo': charts.spread_evolution(completeness['daily_spread']),
        'hourly': charts.hourly_activity(temporal['hourly_activity']),
        'spread_hour': charts.spread_by_hour(temporal['spread_by_hour']),
        'capital': charts.capital_deployment(sizing['daily_summary']),
        'edge_tier': charts.edge_capture_by_tier(sizing['edge_capture_df']),
        'entry_speed': charts.entry_speed_histogram(execution['sequencing_df']),
        'timeline': charts.example_fill_timeline(db, pnl['resolved_df']),
    }
    for name, fig in chart_figs.items():
        c[name] = _chart(fig)

    chart_count = sum(1 for fig in chart_figs.values() if fig is not None)
    print(f"  Generated {chart_count} charts")

    # Build sections
    strs = structure['summary']
    cs = completeness['summary']
    es = execution['summary']
    ts = temporal['summary']
    ps = pnl['summary']
    rs = risk['summary']
    fp = synthesis['fingerprint']
    rep = synthesis['replication']

    sections = (
        _section_exec_summary(h, synthesis)
        + _section_market_universe(strs, structure, h)
        + _section_completeness(cs, completeness['tier_summary'],
                                c['spread_dist'], c['balance_dist'])
        + _section_execution(es, ts, c['entry_speed'], c['hourly'],
                             c['spread_hour'])
        + _section_edge_leakage(h, c['waterfall'], c['balance_pnl'],
                                c['edge_tier'])
        + _section_pnl(ps, h, c['cum_pnl'], c['asset_pnl'], c['capital'])
        + _section_risk(rs, h)
        + _section_replication(fp, rep, synthesis, c['spread_evo'])
    )

    # Example fill timeline in appendix (illustrative, not core)
    if chart_figs.get('timeline'):
        sections += _section('appendix', 'Appendix: Example Market',
                             f'<div class="chart-container">{c["timeline"]}</div>')

    # Assemble full HTML
    html = _html_template(sections)

    output_path = os.path.join(config.OUTPUT_DIR, 'report.html')
    with open(output_path, 'w') as f:
        f.write(html)

    print(f"  Report written to {output_path}")
    return output_path


def _html_template(body_sections):
    """Full HTML document with inline CSS and Plotly CDN."""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Bot Analysis &mdash; {config.WALLET_LABEL}</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f0f2f5;
            color: #1e293b;
            line-height: 1.65;
            margin: 0;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: white;
            padding: 48px 0 40px;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            margin: 0;
        }}
        .header .subtitle {{
            color: #94a3b8;
            margin-top: 6px;
            font-size: 15px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
            padding: 0 24px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
            margin-top: 28px;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.07);
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }}
        .metric-card .value {{
            font-size: 24px;
            font-weight: 700;
            margin-bottom: 2px;
        }}
        .metric-card .label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            opacity: 0.65;
        }}
        /* Override for metric cards inside white sections */
        .section .metric-card {{
            background: #f1f5f9;
        }}
        .section .metric-card .value {{
            color: #0f172a;
        }}
        .section .metric-card .label {{
            color: #64748b;
            opacity: 1;
        }}
        nav.toc {{
            background: white;
            border-bottom: 1px solid #e2e8f0;
            padding: 12px 0;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        nav.toc .container {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        nav.toc a {{
            color: #475569;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
        }}
        nav.toc a:hover {{ color: #2563eb; }}
        .content {{ padding: 24px 0 48px; }}
        .section {{
            background: white;
            border-radius: 10px;
            padding: 32px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }}
        .section h2 {{
            font-size: 20px;
            margin: 0 0 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid #f1f5f9;
            color: #0f172a;
        }}
        .section h3 {{
            font-size: 16px;
            color: #334155;
            margin: 24px 0 12px;
        }}
        .section p {{ margin: 8px 0; font-size: 14px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0;
            font-size: 13px;
        }}
        th {{
            background: #f8fafc;
            text-align: left;
            padding: 9px 14px;
            font-weight: 600;
            color: #475569;
            border-bottom: 2px solid #e2e8f0;
        }}
        td {{
            padding: 8px 14px;
            border-bottom: 1px solid #f1f5f9;
        }}
        tr:hover td {{ background: #fafbfc; }}
        .finding {{
            border-left: 4px solid #2563eb;
            background: #f8fafc;
            padding: 12px 16px;
            margin: 14px 0;
            border-radius: 0 6px 6px 0;
            font-size: 13px;
        }}
        .finding.key {{ border-left-color: #16a34a; background: #f0fdf4; }}
        .finding.warn {{ border-left-color: #d97706; background: #fffbeb; }}
        .finding p {{ margin: 0; }}
        .chart-container {{ margin: 16px 0; }}
        .two-col {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        .muted {{ color: #94a3b8; font-style: italic; font-size: 13px; }}
        footer {{
            text-align: center;
            padding: 32px;
            color: #94a3b8;
            font-size: 12px;
        }}
        @media (max-width: 768px) {{
            .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .two-col {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>

<div class="header">
    <div class="container">
        <h1>Polymarket Bot Analysis</h1>
        <p class="subtitle">{config.WALLET_LABEL}
            &mdash; Pure Completeness Arbitrage on Crypto Binary Markets
            &mdash; {config.WALLET_ADDRESS[:10]}...{config.WALLET_ADDRESS[-6:]}</p>
    </div>
</div>

<nav class="toc">
    <div class="container">
        <a href="#summary">Summary</a>
        <a href="#universe">Markets</a>
        <a href="#completeness">Arbitrage</a>
        <a href="#execution">Execution</a>
        <a href="#leakage">Edge Leakage</a>
        <a href="#pnl">P&amp;L</a>
        <a href="#risk">Risk</a>
        <a href="#replication">Replication</a>
    </div>
</nav>

<div class="content">
    <div class="container">
        {body_sections}
    </div>
</div>

<footer>
    <div class="container">
        Generated by poly_analysis pipeline &mdash;
        {config.WALLET_LABEL} ({config.WALLET_ADDRESS})
    </div>
</footer>

</body>
</html>'''
