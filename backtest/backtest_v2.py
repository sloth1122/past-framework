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
import json, os, sys, datetime, time, math
sys.path.insert(0, os.path.dirname(__file__))

def safe_path(path, base_dir=None):
    """Canonicalize and validate a path to prevent path traversal.

    Resolves the path to its canonical form and ensures it stays
    within the allowed base directory.  Raises ValueError if the
    resolved path escapes base_dir.
    """
    if base_dir is None:
        base_dir = os.path.realpath(os.getcwd())
    else:
        base_dir = os.path.realpath(base_dir)
    resolved = os.path.realpath(path)
    # Ensure base_dir ends with a separator to prevent partial-path bypass
    # (e.g. "/data/resources-secret" must NOT match base "/data/resources")
    if resolved != base_dir and not resolved.startswith(base_dir + os.sep):
        raise ValueError(f"path {path!r} resolves outside the allowed directory {base_dir!r}")
    return resolved


def safe_filename(name, base_dir):
    """Sanitize a user-supplied filename component and join it to base_dir.

    Strips directory separators from *name* so it cannot escape base_dir,
    then validates the resulting full path with safe_path().
    """
    # Remove any path separators or parent-directory components
    clean = os.path.basename(name)
    if clean != name:
        raise ValueError(f"filename {name!r} contains path separators — rejected")
    full = os.path.join(base_dir, clean)
    return safe_path(full, base_dir)

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
def _process_exit(position, agent, row, ticker, day_str, days_held, verbose):
    """Check if an existing position should exit. Returns (exit_trade, new_position, cash_delta) or (None, position, 0)."""
    if not position:
        return None, position, 0

    if agent == 'alpha':
        exit_reason = alpha_should_exit(row, position, days_held)
    else:
        exit_reason = beta_should_exit(row, position, days_held)

    if not exit_reason:
        return None, position, 0

    exit_price = row['Close']
    shares = position['shares']
    pnl = (exit_price - position['entry_price']) * shares
    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
    cash_delta = exit_price * shares

    trade = {
        'ticker': ticker, 'agent': agent,
        'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
        'exit_date': day_str,
        'entry_price': position['entry_price'],
        'exit_price': exit_price, 'shares': shares,
        'pnl': pnl, 'pnl_pct': pnl_pct,
        'exit_reason': exit_reason, 'status': 'CLOSED'
    }
    if verbose:
        print(f"    [{day_str}] EXIT {ticker} @ ${exit_price:.2f} "
              f"({pnl_pct*100:+.1f}%) [{exit_reason}]")
    return trade, None, cash_delta


def _process_entry(position, just_exited, trades_today_count, agent, row, ticker,
                   day_str, past, max_pos, stop_pct, holding, strategy, call_log,
                   cash, ALLOC_val, verbose):
    """Check for a new entry signal. Returns (position, cash_delta, verdict, trades_today_delta) or (None, 0, None, 0)."""
    if position is not None or just_exited or trades_today_count >= 2:
        return None, 0, None, 0

    row_info = {'low_52': row.get('Low52', row['Close']),
                'high_52': row.get('High52', row['Close'])}

    if agent == 'alpha':
        should_enter = alpha_should_enter(row, position)
    else:
        should_enter = beta_should_enter(row, position, row_info)

    if not should_enter:
        return None, 0, None, 0

    size_pct = 8 if (agent == 'alpha' and should_enter == 'SECONDARY') else max_pos

    approved, judge_score, judge_notes, usage = judge_evaluate_llm(
        agent_name=agent, ticker=ticker, entry_price=row['Close'],
        row=row, past_scores=past,
        position_size_pct=size_pct, stop_pct=stop_pct,
        holding=holding, strategy=strategy, call_log=call_log
    )

    verdict = {
        'date': day_str, 'ticker': ticker, 'agent': agent,
        'approved': approved, 'score': judge_score,
        'notes': '; '.join(judge_notes[-3:])
    }

    if verbose:
        status = "APPROVED" if approved else "REJECTED"
        print(f"    [{day_str}] JUDGE {status} {ticker} "
              f"(score {judge_score}/13)")

    if not approved:
        return None, 0, verdict, 0

    entry_price = row['Close']
    shares = min(cash / entry_price, ALLOC_val * size_pct / 100 / entry_price)
    shares = max(0, math.floor(shares * 10) / 10)
    if shares <= 0:
        return None, 0, verdict, 0

    cost = entry_price * shares
    new_position = {
        'entry_price': entry_price, 'shares': shares,
        'entry_date': row.name, 'entry_row': row
    }
    if verbose:
        print(f"    [{day_str}] ENTER {ticker} @ ${entry_price:.2f} "
              f"({shares} shares, {size_pct}% size)")
    return new_position, -cost, verdict, 1


def _process_rocky_tuning(i, agent, trades, past, strategy, call_log, bi_weekly_counter,
                          past_history, verbose):
    """Run bi-weekly Rocky LLM tuning. Returns (new_past, new_history_entries, new_counter)."""
    if i <= 0 or i % 10 != 0:
        return past, [], bi_weekly_counter

    new_counter = bi_weekly_counter + 1
    new_past, info, usage = rocky_tune_llm(
        agent_name=agent, trades=trades, past_scores=past,
        week_num=new_counter, strategy=strategy, call_log=call_log
    )
    if not info.get('adjustments'):
        return past, [], new_counter

    history_entry = {
        'cycle': new_counter,
        'scores': new_past.copy(),
        'note': info.get('note', ''),
        'adjustments': info.get('adjustments', {}),
        'cascade': info.get('cascade', '')
    }
    if verbose:
        for trait, adj in info['adjustments'].items():
            print(f"    ROCKY: {trait} {adj['old']}→{adj['new']}")
    return new_past, [history_entry], new_counter


def _close_final_position(position, ticker, agent, df, ALLOC_val, trades):
    """Close any remaining position at the last bar. Returns (cash_delta, trade)."""
    if not position:
        return 0, None

    last_row = df.iloc[-1]
    exit_price = last_row['Close']
    pnl = (exit_price - position['entry_price']) * position['shares']
    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
    cash_delta = exit_price * position['shares']
    trade = {
        'ticker': ticker, 'agent': agent,
        'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
        'exit_date': df.index[-1].strftime('%Y-%m-%d'),
        'entry_price': position['entry_price'],
        'exit_price': exit_price, 'shares': position['shares'],
        'pnl': pnl, 'pnl_pct': pnl_pct,
        'exit_reason': 'END_OF_PERIOD', 'status': 'CLOSED'
    }
    return cash_delta, trade


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
        if day_str != current_day:
            trades_today_count = 0
            current_day = day_str
        just_exited = False

        days_held = (date - position['entry_date']).days if position else 0

        # ── EXIT ──
        exit_trade, position, exit_cash = _process_exit(
            position, agent, row, ticker, day_str, days_held, verbose)
        if exit_trade:
            trades.append(exit_trade)
            cash += exit_cash
            just_exited = True

        # ── ENTRY ──
        new_pos, entry_cash, verdict, trades_delta = _process_entry(
            position, just_exited, trades_today_count, agent, row, ticker,
            day_str, past, max_pos, stop_pct, holding, strategy, call_log,
            cash, ALLOC, verbose)
        if new_pos:
            position = new_pos
            cash += entry_cash
            trades_today_count += trades_delta
        if verdict:
            judge_verdicts.append(verdict)

        # ── ROCKY TUNING ──
        past, new_history, bi_weekly_counter = _process_rocky_tuning(
            i, agent, trades, past, strategy, call_log, bi_weekly_counter,
            past_history, verbose)
        past_history.extend(new_history)

    # ── CLOSE REMAINING POSITION ──
    final_cash, final_trade = _close_final_position(position, ticker, agent, df, ALLOC, trades)
    if final_trade:
        trades.append(final_trade)
        cash += final_cash

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
    print("  BACKTEST v2 — LLM-in-the-loop (deepseek-r1:70b local)")
    print("  Rolling window: no target leakage")
    print(f"{'═' * 60}")
    print(f"  Ticker: {ticker}")
    print(f"  Window: {start} → {end}")
    print("  Model:  deepseek-r1:32b (Ollama, free)")
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
    print("LLM COST SUMMARY")
    print(f"  Total calls: {total_calls}")
    print(f"  Total tokens: {total_tokens:,}")
    print("  Cost: $0.00 (local model)")

    # Save
    os.makedirs(OUT_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = safe_filename(f"backtest_v2_{ticker}_{timestamp}.json", OUT_DIR)
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
