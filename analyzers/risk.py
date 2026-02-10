"""Phase 5b: Risk metrics — Sharpe, drawdown, loss streaks, capital efficiency."""

import numpy as np
import pandas as pd


def analyze_risk(pnl_result: dict, sizing_result: dict) -> dict:
    """Compute risk-adjusted return metrics.

    Args:
        pnl_result: Output from analyze_pnl()
        sizing_result: Output from analyze_sizing()

    Returns dict with risk metrics.
    """
    daily_pnl = pnl_result['daily_pnl']
    resolved = pnl_result['resolved_df']

    print("\n" + "=" * 60)
    print("PHASE 5b: RISK METRICS")
    print("=" * 60)

    daily_returns = daily_pnl['pnl']
    trading_days = len(daily_returns)

    # ── 1. Sharpe ratio ──
    daily_mean = daily_returns.mean()
    daily_std = daily_returns.std()
    sharpe_daily = daily_mean / daily_std if daily_std > 0 else 0
    # Crypto markets are 365 days/year
    sharpe_annual = sharpe_daily * np.sqrt(365)

    print(f"\n  Sharpe ratio (RESOLUTION-BASED — see caveat):")
    print(f"    Daily mean P&L: ${daily_mean:,.0f}")
    print(f"    Daily std:      ${daily_std:,.0f}")
    print(f"    Daily Sharpe:   {sharpe_daily:.3f}")
    print(f"    Annualized:     {sharpe_annual:.2f} (x sqrt(365))")
    print(f"    CAVEAT: P&L recognized at market resolution, not mark-to-market.")
    print(f"    Open positions carry unrealized exposure not captured here.")
    print(f"    High Sharpe confirms consistent arb, not low real-time risk.")

    # ── 2. Maximum drawdown ──
    cum = daily_pnl['cumulative_pnl']
    running_max = cum.cummax()
    drawdown = cum - running_max
    max_dd = drawdown.min()
    max_dd_idx = drawdown.idxmin()
    # Find peak before the max drawdown
    peak_idx = cum[:max_dd_idx].idxmax() if pd.notna(max_dd_idx) else None

    print(f"\n  Drawdown:")
    print(f"    Max drawdown: ${max_dd:,.0f}")
    if peak_idx:
        print(f"    Peak: {peak_idx} → Trough: {max_dd_idx}")
    # Current drawdown from peak
    current_dd = cum.iloc[-1] - running_max.iloc[-1]
    print(f"    Current drawdown: ${current_dd:,.0f}")

    # Drawdown / peak exposure ratio (more practical risk metric)
    sizing_summary = sizing_result['summary']
    peak_exposure = sizing_summary['peak_exposure']
    if peak_exposure > 0:
        dd_exposure_pct = abs(max_dd) / peak_exposure * 100
        print(f"    Drawdown / peak exposure: {dd_exposure_pct:.1f}%  "
              f"(${abs(max_dd):,.0f} / ${peak_exposure:,.0f})")
        print(f"    → More meaningful than Sharpe for real-time risk sizing")

    # ── 3. Calmar ratio ──
    total_pnl = daily_returns.sum()
    annualized_return = total_pnl * (365 / max(trading_days, 1))
    calmar = (annualized_return / abs(max_dd)
              if max_dd != 0 else float('inf'))

    print(f"\n  Calmar ratio:")
    print(f"    Total P&L: ${total_pnl:,.0f} over {trading_days} days")
    print(f"    Annualized: ${annualized_return:,.0f}")
    print(f"    Calmar: {calmar:.2f}")

    # ── 4. Loss streaks (chronological market order) ──
    sorted_resolved = resolved.sort_values('first_fill_ts')
    pnl_seq = sorted_resolved['trade_pnl'].values
    is_loss = pnl_seq <= 0

    max_loss_streak = 0
    current = 0
    for loss in is_loss:
        if loss:
            current += 1
            max_loss_streak = max(max_loss_streak, current)
        else:
            current = 0

    max_win_streak = 0
    current = 0
    for loss in is_loss:
        if not loss:
            current += 1
            max_win_streak = max(max_win_streak, current)
        else:
            current = 0

    print(f"\n  Streaks (chronological market order):")
    print(f"    Max loss streak: {max_loss_streak} consecutive markets")
    print(f"    Max win streak:  {max_win_streak} consecutive markets")

    # ── 5. Tail risk ──
    market_pnl = resolved['trade_pnl'].values
    pctiles = np.percentile(market_pnl, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    worst_10 = np.sort(market_pnl)[:10]

    print(f"\n  Per-market P&L distribution:")
    for p, v in zip([1, 5, 10, 25, 50, 75, 90, 95, 99], pctiles):
        print(f"    p{p:2d}: ${v:>+10,.2f}")
    print(f"    Worst 10 markets: ${worst_10.sum():,.0f} "
          f"(avg ${worst_10.mean():,.2f})")

    # ── 6. Capital efficiency ──
    avg_exposure = sizing_summary['avg_exposure']

    # Use trade-derived P&L against trade-window exposure (apples to apples)
    trade_pnl = pnl_result['summary']['trade_derived_pnl']

    print(f"\n  Capital efficiency:")
    if avg_exposure > 0:
        roi_period = trade_pnl / avg_exposure * 100
        print(f"    Trade P&L / avg exposure: {roi_period:.1f}% "
              f"(over trade window)")
    if peak_exposure > 0:
        print(f"    Trade P&L / peak exposure: "
              f"{trade_pnl / peak_exposure * 100:.1f}%")
    total_buy = sizing_summary['total_buy_outlay']
    if total_buy > 0:
        print(f"    Trade P&L / total buy outlay: "
              f"{trade_pnl / total_buy * 100:.2f}%")
    # Position P&L for broader context
    pos_pnl = pnl_result['summary']['position_derived_pnl']
    maker = pnl_result['summary']['maker_rebates']
    print(f"    Position P&L + rebates: ${pos_pnl + maker:,.0f}")

    dd_exposure_ratio = (abs(max_dd) / peak_exposure
                         if peak_exposure > 0 else 0)

    return {
        'daily_pnl': daily_pnl,
        'summary': {
            'sharpe_daily': float(sharpe_daily),
            'sharpe_annual': float(sharpe_annual),
            'max_drawdown': float(max_dd),
            'dd_exposure_ratio': float(dd_exposure_ratio),
            'calmar': float(calmar),
            'max_loss_streak': max_loss_streak,
            'max_win_streak': max_win_streak,
            'tail_p5': float(pctiles[1]),
            'tail_p1': float(pctiles[0]),
            'total_pnl_positions': float(total_pnl),
        }
    }
