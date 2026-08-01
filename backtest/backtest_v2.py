#!/usr/bin/env python3
"""
Backtest v2 — LLM-in-the-loop with rolling windows (no target leakage).

Brian's fixes:
  1. Rolling window: every indicator at day D uses ONLY data from D-252 to D.
     No full-dataset min/max anywhere.
  2. LLM Judge + Rocky calls: real deepseek-r1:70b reasoning, not hardcoded stubs.

Usage:
  python3 backtest_v2.py [ticker] [start_date] [end_date]
  python3 backtest_v2.py OKLO 2025-08-01 2026-07-21
"""
import json, os, sys, datetime, time
sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import (
    ALLOC, calc_rsi, prepare_data,
    alpha_should_enter, alpha_should_exit,
    beta_should_enter, beta_should_exit
)
from llm_judge import (
    judge_evaluate_llm, rocky_tune_llm,
    reset_token_log, get_token_log
)
import yfinance as yf
import pandas as pd
import numpy as np

OUT_DIR = "/Users/johntytko/trading-arena/state/backtests"

# ─── STRATEGY METADATA ───
STRATEGIES = {
    'alpha': {
        'name': 'Renaissance / Mean Reversion',
        'stop_pct': 3, 'holding': '3-5 days',
        'max_position_pct': 15,
        'past_init': {'risk_tolerance': 3, 'impulsivity': 2, 'conviction': 2,
                      'patience': 3, 'adaptability': 4, 'technical_focus': 7,
                      'sector_specialization': 1, 'position_concentration': 4}
    },
    'beta': {
        'name': 'Aschenbrenner / AI Infra Thesis',
        'stop_pct': 10, 'holding': 'weeks-months',
        'max_position_pct': 25,
        'past_init': {'risk_tolerance': 6, 'impulsivity': 3, 'conviction': 7,
                      'patience': 7, 'adaptability': 5, 'technical_focus': 2,
                      'sector_specialization': 7, 'position_concentration': 6}
    }
}


# ════════════════════════════════════════════════════════════
# FIX #1: ROLLING-WINDOW DATA FETCH (no leakage)
# ════════════════════════════════════════════════════════════
def fetch_rolling_data(ticker, backtest_start, backtest_end, lookback_weeks=52):
    """
    Download historical data with EXTRA lookback before the backtest window
    so that rolling indicators at day 1 of the backtest have full context.

    Brian: 'the day that is traded should look at the 52 weeks prior to that same day.'
    We pull 52 weeks BEFORE backtest_start, compute indicators on the full series,
    then trim to the backtest window. No future data leaks backward.
    """
    # Add lookback buffer BEFORE the backtest start
    start_dt = pd.Timestamp(backtest_start)
    buffer_start = start_dt - pd.Timedelta(weeks=lookback_weeks + 4)  # +4 wks safety

    t = yf.Ticker(ticker)
    df = t.history(start=buffer_start, end=backtest_end, auto_adjust=True)
    if df.empty:
        return None

    # Compute ALL indicators on the full buffered series (no future leak within the series)
    df = prepare_data(df, ticker)

    # Now trim to the actual backtest window — indicators at each row already
    # used only PAST data (rolling looks backward by construction)
    df = df.loc[backtest_start:backtest_end].copy()
    return df


# ════════════════════════════════════════════════════════════
# FIX #2: LLM-IN-THE-LOOP SIMULATION
# ════════════════════════════════════════════════════════════
def run_simulation_llm(df, ticker, agent_name, strategy_meta, call_log, verbose=False):
    """
    Run full simulation with LLM Judge + Rocky.
    Every Judge call is a real Ollama query to deepseek-r1:70b.
    """
    agent = agent_name
    past = strategy_meta['past_init'].copy()
    strategy = strategy_meta['name']
    stop_pct = strategy_meta['stop_pct']
    holding = strategy_meta['holding']
    max_pos = strategy_meta['max_position_pct']

    cash = ALLOC
    position = None
    trades = []
    past_history = [{
        'cycle': 0, 'scores': past.copy(),
        'note': 'Initial PAST profile', 'adjustments': {}
    }]
    judge_verdicts = []
    bi_weekly_counter = 0
    trades_today_count = 0
    current_day = None

    for i, (date, row) in enumerate(df.iterrows()):
        day_str = date.strftime('%Y-%m-%d')
        # Reset daily trade counter
        if day_str != current_day:
            trades_today_count = 0
            current_day = day_str

        days_held = (date - position['entry_date']).days if position else 0

        # ── CHECK EXIT ON EXISTING POSITION ──
        if position:
            if agent == 'alpha':
                exit_reason = alpha_should_exit(row, position, days_held)
            else:
                exit_reason = beta_should_exit(row, position, days_held)

            if exit_reason:
                exit_price = row['Close']
                shares = position['shares']
                pnl = (exit_price - position['entry_price']) * shares
                pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                cash += exit_price * shares
                trades.append({
                    'ticker': ticker, 'agent': agent,
                    'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
                    'exit_date': day_str,
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price, 'shares': shares,
                    'pnl': pnl, 'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason, 'status': 'CLOSED'
                })
                if verbose:
                    print(f"    [{day_str}] EXIT {ticker} @ ${exit_price:.2f} "
                          f"({pnl_pct*100:+.1f}%) [{exit_reason}]")
                position = None

        # ── CHECK ENTRY ──
        if position is None and trades_today_count < 2:
            # BRIAN FIX #1: use row-level rolling values, NOT ticker_info (which leaked)
            # Build a ticker_info from the CURRENT ROW only — no future data
            row_info = {'low_52': row.get('Low52', row['Close']),
                        'high_52': row.get('High52', row['Close'])}

            if agent == 'alpha':
                should_enter = alpha_should_enter(row, position)
            else:
                should_enter = beta_should_enter(row, position, row_info)

            if should_enter:
                # Determine position size
                if agent == 'alpha':
                    size_pct = 8 if should_enter == 'SECONDARY' else max_pos
                else:
                    size_pct = max_pos

                # BRIAN FIX #2: Real LLM Judge call
                approved, judge_score, judge_notes, usage = judge_evaluate_llm(
                    agent_name=agent, ticker=ticker, entry_price=row['Close'],
                    row=row, past_scores=past,
                    position_size_pct=size_pct, stop_pct=stop_pct,
                    holding=holding, strategy=strategy, call_log=call_log
                )

                judge_verdicts.append({
                    'date': day_str, 'ticker': ticker, 'agent': agent,
                    'approved': approved, 'score': judge_score,
                    'notes': '; '.join(judge_notes[-3:])  # keep concise
                })

                if verbose:
                    status = "APPROVED" if approved else "REJECTED"
                    print(f"    [{day_str}] JUDGE {status} {ticker} "
                          f"(score {judge_score}/13)")

                if approved:
                    entry_price = row['Close']
                    shares = min(cash / entry_price, ALLOC * size_pct / 100 / entry_price)
                    shares = round(shares, 1)
                    if shares > 0:
                        cost = entry_price * shares
                        cash -= cost
                        position = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_row': row
                        }
                        trades_today_count += 1
                        if verbose:
                            print(f"    [{day_str}] ENTER {ticker} @ ${entry_price:.2f} "
                                  f"({shares} shares, {size_pct}% size)")

        # ── BI-WEEKLY ROCKY TUNING (LLM) ──
        if i > 0 and i % 10 == 0:
            bi_weekly_counter += 1
            new_past, info, usage = rocky_tune_llm(
                agent_name=agent, trades=trades, past_scores=past,
                week_num=bi_weekly_counter, strategy=strategy, call_log=call_log
            )
            if info.get('adjustments'):
                past_history.append({
                    'cycle': bi_weekly_counter,
                    'scores': new_past.copy(),
                    'note': info.get('note', ''),
                    'adjustments': info.get('adjustments', {}),
                    'cascade': info.get('cascade', '')
                })
                past = new_past
                if verbose:
                    for trait, adj in info['adjustments'].items():
                        print(f"    ROCKY: {trait} {adj['old']}→{adj['new']}")

    # Close remaining position at last price
    if position:
        last_row = df.iloc[-1]
        exit_price = last_row['Close']
        pnl = (exit_price - position['entry_price']) * position['shares']
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        cash += exit_price * position['shares']
        trades.append({
            'ticker': ticker, 'agent': agent,
            'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
            'exit_date': df.index[-1].strftime('%Y-%m-%d'),
            'entry_price': position['entry_price'],
            'exit_price': exit_price, 'shares': position['shares'],
            'pnl': pnl, 'pnl_pct': pnl_pct,
            'exit_reason': 'END_OF_PERIOD', 'status': 'CLOSED'
        })

    final_pnl = cash - ALLOC
    return {
        'agent': agent, 'ticker': ticker, 'strategy': strategy,
        'trades': trades, 'judge_verdicts': judge_verdicts,
        'past_history': past_history,
        'final_pnl': round(final_pnl, 2),
        'final_pnl_pct': round(final_pnl / ALLOC * 100, 2),
        'final_cash': round(cash, 2),
        'num_trades': len(trades),
        'wins': len([t for t in trades if t['pnl'] > 0]),
        'losses': len([t for t in trades if t['pnl'] < 0]),
        'win_rate': round(len([t for t in trades if t['pnl'] > 0]) / len(trades), 3) if trades else 0,
        'judge_approvals': len([v for v in judge_verdicts if v['approved']]),
        'judge_rejections': len([v for v in judge_verdicts if not v['approved']])
    }


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]
    ticker = args[0] if len(args) > 0 else "OKLO"
    start = args[1] if len(args) > 1 else "2025-08-01"
    end = args[2] if len(args) > 2 else "2026-07-21"

    print(f"{'═' * 60}")
    print(f"  BACKTEST v2 — LLM-in-the-loop (deepseek-r1:70b local)")
    print(f"  Rolling window: no target leakage")
    print(f"{'═' * 60}")
    print(f"  Ticker: {ticker}")
    print(f"  Window: {start} → {end}")
    print(f"  Model:  deepseek-r1:32b (Ollama, free)")
    print()

    reset_token_log()
    call_log = []

    # Fetch rolling-window data
    print(f"Fetching rolling data for {ticker} (with 52-week lookback)...")
    df = fetch_rolling_data(ticker, start, end)
    if df is None or df.empty:
        print(f"ERROR: No data for {ticker}")
        return
    print(f"  Loaded {len(df)} trading days ({df.index[0].date()} → {df.index[-1].date()})")
    print()

    all_results = {}

    for agent_key in ['alpha', 'beta']:
        meta = STRATEGIES[agent_key]
        print(f"--- {agent_key.upper()} ({meta['name']}) ---")
        t0 = time.time()
        result = run_simulation_llm(df, ticker, agent_key, meta, call_log, verbose=True)
        elapsed = time.time() - t0
        print(f"  Result: {result['num_trades']} trades, "
              f"P&L ${result['final_pnl']:+.2f} ({result['final_pnl_pct']:+.1f}%), "
              f"win rate {result['win_rate']:.0%}")
        print(f"  Judge: {result['judge_approvals']} approved, "
              f"{result['judge_rejections']} rejected")
        print(f"  Elapsed: {elapsed:.0f}s")
        print()
        all_results[agent_key] = result

    # Token usage summary
    tokens = get_token_log()
    total_tokens = sum(t.get('total_tokens', 0) for t in tokens)
    total_calls = len(tokens)
    print(f"{'─' * 60}")
    print(f"LLM COST SUMMARY")
    print(f"  Total calls: {total_calls}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Cost: $0.00 (local model)")

    # Save
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(OUT_DIR, f"backtest_v2_{ticker}_{timestamp}.json")
    with open(out_file, 'w') as f:
        json.dump({
            'ticker': ticker, 'start': start, 'end': end,
            'model': 'deepseek-r1:70b (local)',
            'fixes_applied': ['rolling_window_no_leakage', 'llm_judge_in_loop'],
            'results': all_results,
            'call_log': call_log,
            'token_usage': {'total_tokens': total_tokens, 'total_calls': total_calls}
        }, f, indent=2, default=str)
    print(f"\nSaved: {out_file}")


if __name__ == '__main__':
    main()
