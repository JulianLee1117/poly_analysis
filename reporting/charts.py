"""Phase 7: Plotly chart functions for the HTML report.

Each function takes phase-result data and returns a plotly Figure.
Returns None if data is insufficient.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Consistent palette ──
COLORS = {
    'primary': '#2563eb',
    'positive': '#16a34a',
    'negative': '#dc2626',
    'warning': '#d97706',
    'neutral': '#6b7280',
    'dark': '#1e293b',
}
ASSET_COLORS = {
    'Bitcoin': '#F7931A',
    'Ethereum': '#627EEA',
    'Solana': '#14F195',
    'XRP': '#555555',
}
TIER_LABELS = {
    'well_balanced': 'Well-balanced',
    'moderate': 'Moderate',
    'imbalanced': 'Imbalanced',
    'very_imbalanced': 'Very imbalanced',
}
TIER_COLORS = {
    'well_balanced': '#16a34a',
    'moderate': '#2563eb',
    'imbalanced': '#d97706',
    'very_imbalanced': '#dc2626',
}
TIER_ORDER = ['well_balanced', 'moderate', 'imbalanced', 'very_imbalanced']


def _layout(title, height=420, **kwargs):
    """Standard layout options."""
    layout = dict(
        title=dict(text=title, font=dict(size=15, color='#1e293b')),
        template='plotly_white',
        margin=dict(l=60, r=40, t=50, b=50),
        font=dict(family='-apple-system, BlinkMacSystemFont, sans-serif',
                  size=12, color='#374151'),
        height=height,
        plot_bgcolor='white',
    )
    layout.update(kwargs)
    return layout


# ── 1. Edge Leakage Waterfall ──

def edge_leakage_waterfall(pnl_summary):
    """THE central chart: theoretical spread → drag → sell → actual."""
    spread = pnl_summary['completeness_spread']
    drag = pnl_summary['directional_drag']
    sell = pnl_summary['sell_pnl']
    actual = pnl_summary['trade_derived_pnl']

    fig = go.Figure(go.Waterfall(
        x=['Theoretical<br>Spread', 'Directional<br>Drag',
           'Sell<br>Losses', 'Actual<br>P&L'],
        y=[spread, drag, sell, actual],
        measure=['absolute', 'relative', 'relative', 'total'],
        connector=dict(line=dict(color='#d1d5db', width=1)),
        increasing=dict(marker_color=COLORS['positive']),
        decreasing=dict(marker_color=COLORS['negative']),
        totals=dict(marker_color=COLORS['primary']),
        text=[f'${v:+,.0f}' for v in [spread, drag, sell, actual]],
        textposition='outside',
        textfont=dict(size=13, color='#1e293b'),
    ))
    pct = actual / spread * 100 if spread else 0
    fig.update_layout(
        **_layout(f'Edge Leakage: Only {pct:.0f}% of Theoretical Edge Captured'),
        yaxis_title='USD', showlegend=False)
    return fig


# ── 2. Cumulative P&L + Daily Bars ──

def cumulative_pnl_daily(daily_pnl):
    """Daily P&L bars with cumulative overlay line."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    colors = [COLORS['positive'] if v >= 0 else COLORS['negative']
              for v in daily_pnl['pnl']]

    fig.add_trace(
        go.Bar(x=daily_pnl.index, y=daily_pnl['pnl'], name='Daily P&L',
               marker_color=colors, opacity=0.7),
        secondary_y=False)
    fig.add_trace(
        go.Scatter(x=daily_pnl.index, y=daily_pnl['cumulative_pnl'],
                   name='Cumulative', line=dict(color=COLORS['primary'],
                                                width=2.5)),
        secondary_y=True)

    fig.update_layout(**_layout('Daily & Cumulative P&L (Position Resolution Dates)'))
    fig.update_yaxes(title_text='Daily P&L ($)', secondary_y=False)
    fig.update_yaxes(title_text='Cumulative P&L ($)', secondary_y=True)
    return fig


# ── 3. Spread Distribution ──

def spread_distribution(per_market_df):
    """Histogram of completeness spread per market."""
    spreads = per_market_df['spread']
    fig = go.Figure(go.Histogram(
        x=spreads, nbinsx=60, marker_color=COLORS['primary'], opacity=0.8))
    fig.add_vline(x=spreads.mean(), line_dash='dash', line_color=COLORS['negative'],
                  annotation_text=f'Mean: ${spreads.mean():.3f}')
    fig.add_vline(x=0, line_color='black', line_width=1)
    fig.update_layout(**_layout(
        'Completeness Spread Distribution (1.00 − Combined VWAP)',
        xaxis_title='Spread ($)', yaxis_title='Markets'))
    return fig


# ── 4. Balance Ratio Distribution ──

def balance_distribution(per_market_df):
    """Histogram of share balance ratio across markets."""
    ratios = per_market_df['balance_ratio']
    fig = go.Figure(go.Histogram(
        x=ratios, nbinsx=50, marker_color=COLORS['primary'], opacity=0.8))
    fig.add_vline(x=ratios.mean(), line_dash='dash', line_color=COLORS['negative'],
                  annotation_text=f'Mean: {ratios.mean():.3f}')
    fig.update_layout(**_layout(
        'Share Balance Ratio Distribution (min/max shares per market)',
        xaxis_title='Balance Ratio', yaxis_title='Markets'))
    return fig


# ── 5. Balance vs P&L Scatter ──

def balance_vs_pnl(resolved_df):
    """Scatter of balance ratio vs market P&L, colored by tier."""
    df = resolved_df.copy()
    tier_col = 'balance_tier' if 'balance_tier' in df.columns else 'tier'

    fig = go.Figure()
    if tier_col in df.columns:
        for tier in TIER_ORDER:
            mask = df[tier_col] == tier
            if mask.sum() == 0:
                continue
            sub = df[mask]
            fig.add_trace(go.Scattergl(
                x=sub['balance_ratio'], y=sub['trade_pnl'],
                mode='markers', name=TIER_LABELS.get(tier, tier),
                marker=dict(color=TIER_COLORS.get(tier, COLORS['neutral']),
                            size=4, opacity=0.35)))
    else:
        fig.add_trace(go.Scattergl(
            x=df['balance_ratio'], y=df['trade_pnl'], mode='markers',
            marker=dict(color=COLORS['primary'], size=4, opacity=0.35)))

    fig.add_hline(y=0, line_color='#9ca3af', line_width=0.5)
    fig.update_layout(**_layout(
        'Balance Ratio vs Market P&L — Balance Determines Profitability',
        xaxis_title='Balance Ratio (min/max shares)',
        yaxis_title='Market P&L ($)'))
    return fig


# ── 6. Per-Asset P&L + Win Rate ──

def per_asset_pnl(asset_pnl_df):
    """Per-asset P&L bars with win rate line."""
    assets = asset_pnl_df.index.tolist()
    colors = [ASSET_COLORS.get(a, COLORS['neutral']) for a in assets]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=assets, y=asset_pnl_df['total_pnl'], name='Total P&L',
               marker_color=colors, opacity=0.85),
        secondary_y=False)
    fig.add_trace(
        go.Scatter(x=assets, y=asset_pnl_df['win_rate'] * 100,
                   name='Win Rate %', mode='lines+markers',
                   line=dict(color=COLORS['dark'], width=2),
                   marker=dict(size=8, color=COLORS['dark'])),
        secondary_y=True)

    fig.update_layout(**_layout('P&L and Win Rate by Crypto Asset'))
    fig.update_yaxes(title_text='Total P&L ($)', secondary_y=False)
    fig.update_yaxes(title_text='Win Rate (%)', secondary_y=True,
                     range=[30, 70])
    return fig


# ── 7. Spread Evolution ──

def spread_evolution(daily_spread):
    """Daily average spread trend over time."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_spread.index, y=daily_spread['avg_spread'],
        mode='lines+markers', name='Avg Spread',
        line=dict(color=COLORS['primary'], width=2), marker=dict(size=4)))

    x_num = np.arange(len(daily_spread))
    if len(x_num) > 2:
        z = np.polyfit(x_num, daily_spread['avg_spread'].values, 1)
        trend = np.polyval(z, x_num)
        per_week = z[0] * 7
        fig.add_trace(go.Scatter(
            x=daily_spread.index, y=trend, mode='lines',
            name=f'Trend ({per_week:+.4f}/wk)',
            line=dict(color=COLORS['negative'], dash='dash', width=1.5)))

    fig.update_layout(**_layout(
        'Spread Evolution — Expanding Over 22 Days',
        xaxis_title='Date', yaxis_title='Avg Spread ($)'))
    return fig


# ── 8. Hour-of-Day Activity ──

def hourly_activity(hourly_df):
    """Fill count by hour of day (UTC)."""
    fig = go.Figure(go.Bar(
        x=hourly_df['hour_utc'], y=hourly_df['fills'],
        marker_color=COLORS['primary'], opacity=0.8))
    fig.update_layout(**_layout(
        'Activity by Hour of Day (UTC)',
        xaxis_title='Hour (UTC)', yaxis_title='Total Fills',
        xaxis=dict(dtick=2)))
    return fig


# ── 9. Spread by Hour (dual axis) ──

def spread_by_hour(spread_hour_df):
    """Fills + spread by hour — shows no correlation."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=spread_hour_df['hour_utc'], y=spread_hour_df['fills'],
               name='Fills', marker_color=COLORS['primary'], opacity=0.4),
        secondary_y=False)
    fig.add_trace(
        go.Scatter(x=spread_hour_df['hour_utc'],
                   y=spread_hour_df['avg_spread'],
                   name='Avg Spread', mode='lines+markers',
                   line=dict(color=COLORS['negative'], width=2.5),
                   marker=dict(size=6)),
        secondary_y=True)

    fig.update_layout(**_layout(
        'Spread vs Activity by Hour — No Correlation (r\u22480)',
        xaxis=dict(dtick=2, title='Hour (UTC)')))
    fig.update_yaxes(title_text='Fills', secondary_y=False)
    fig.update_yaxes(title_text='Avg Spread ($)', secondary_y=True)
    return fig


# ── 10. Capital Deployment ──

def capital_deployment(daily_summary_df):
    """Daily buy volume — shows +82% scaling trend."""
    # Handle both index-based and column-based date
    if 'trade_date' in daily_summary_df.columns:
        x = daily_summary_df['trade_date']
    else:
        x = daily_summary_df.index

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=daily_summary_df['buy_volume'],
        mode='lines', fill='tozeroy', name='Daily Buy Volume',
        line=dict(color=COLORS['primary']),
        fillcolor='rgba(37, 99, 235, 0.15)'))

    fig.update_layout(**_layout(
        'Daily Capital Deployment (+82% Over 22 Days)',
        xaxis_title='Date', yaxis_title='Buy Volume ($)'))
    return fig


# ── 11. Edge Capture by Balance Tier ──

def edge_capture_by_tier(edge_capture_df):
    """Mean edge capture and avg P&L by balance tier."""
    tier_col = 'balance_tier' if 'balance_tier' in edge_capture_df.columns else 'tier'
    if tier_col not in edge_capture_df.columns:
        return None

    stats = edge_capture_df.groupby(tier_col, observed=True).agg(
        mean_capture=('edge_capture', lambda x: x.clip(-5, 5).mean()),
        mean_pnl=('trade_pnl', 'mean'),
        count=('edge_capture', 'count'),
    )
    stats = stats.reindex([t for t in TIER_ORDER if t in stats.index])
    labels = [TIER_LABELS.get(t, t) for t in stats.index]
    colors = [TIER_COLORS.get(t, COLORS['neutral']) for t in stats.index]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=labels, y=stats['mean_capture'] * 100, name='Edge Capture %',
               marker_color=colors, opacity=0.85,
               text=[f'{v:.0f}%' for v in stats['mean_capture'] * 100],
               textposition='outside'),
        secondary_y=False)
    fig.add_trace(
        go.Scatter(x=labels, y=stats['mean_pnl'], name='Avg P&L ($)',
                   mode='lines+markers',
                   line=dict(color=COLORS['dark'], width=2),
                   marker=dict(size=8, color=COLORS['dark'])),
        secondary_y=True)

    fig.add_hline(y=0, line_color='#9ca3af', line_width=0.5, secondary_y=False)
    fig.update_layout(**_layout(
        'Edge Capture by Balance Tier — Balance Is Everything'))
    fig.update_yaxes(title_text='Mean Edge Capture (%)', secondary_y=False)
    fig.update_yaxes(title_text='Avg P&L ($)', secondary_y=True)
    return fig


# ── 12. Entry Speed Histogram ──

def entry_speed_histogram(sequencing_df):
    """Distribution of entry speed (market open to first fill)."""
    # entry_speed may not be pre-computed; derive from available columns
    if 'entry_speed' not in sequencing_df.columns:
        if 'first_fill_ts' in sequencing_df.columns and 'open_ts' in sequencing_df.columns:
            speeds = (sequencing_df['first_fill_ts']
                      - sequencing_df['open_ts']).dropna()
        else:
            return None
    else:
        speeds = sequencing_df['entry_speed'].dropna()
    speeds = speeds[(speeds >= 0) & (speeds <= 120)]
    if len(speeds) == 0:
        return None

    fig = go.Figure(go.Histogram(
        x=speeds, nbinsx=40, marker_color=COLORS['primary'], opacity=0.8))
    fig.add_vline(x=speeds.median(), line_dash='dash',
                  line_color=COLORS['negative'],
                  annotation_text=f'Median: {speeds.median():.0f}s')
    fig.update_layout(**_layout(
        'Entry Speed: Market Open to First Fill',
        xaxis_title='Entry Speed (seconds)', yaxis_title='Markets'))
    return fig


# ── 13. Example Market Fill Timeline ──

def example_fill_timeline(db, resolved_df):
    """Scatter of fills within a single well-balanced market."""
    tier_col = 'balance_tier' if 'balance_tier' in resolved_df.columns else 'tier'
    if tier_col in resolved_df.columns:
        well = resolved_df[resolved_df[tier_col] == 'well_balanced']
    else:
        well = resolved_df[resolved_df['balance_ratio'] > 0.8]

    if len(well) == 0:
        return None

    # Pick market near median fill count
    if 'buy_fills' in well.columns:
        median_f = well['buy_fills'].median()
        idx = (well['buy_fills'] - median_f).abs().idxmin()
    else:
        idx = well.index[len(well) // 2]

    cid = well.loc[idx, 'condition_id'] if 'condition_id' in well.columns else idx

    try:
        fills = db.market_fills(cid)
    except Exception:
        return None
    if fills is None or len(fills) == 0:
        return None

    fig = go.Figure()
    color_map = {'Up': '#16a34a', 'Down': '#dc2626'}
    symbol_map = {'BUY': 'circle', 'SELL': 'x'}

    for (side, outcome), group in fills.groupby(['side', 'outcome']):
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(group['timestamp'], unit='s'),
            y=group['price'],
            mode='markers',
            name=f'{side} {outcome}',
            marker=dict(
                color=color_map.get(outcome, COLORS['neutral']),
                symbol=symbol_map.get(side, 'circle'),
                size=5 if side == 'BUY' else 8,
                opacity=0.6)))

    fig.update_layout(**_layout(
        'Example Market: Fill Timeline Within a 15-Min Window',
        xaxis_title='Time', yaxis_title='Price ($)', height=380))
    return fig
