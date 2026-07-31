#!/usr/bin/env python3
"""Run the full backtest across multiple stocks and generate HTML report."""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(__file__))
from backtest_engine import *
from backtest_sim import run_simulation, rocky_tune

import yfinance as yf
import pandas as pd

# ─── CONFIG ───
TICKERS = {
    'SPCX': {'name': 'SpaceX', 'thesis': 'Space economy backbone, Starlink, Starship'},
    'OKLO': {'name': 'Oklo Inc', 'thesis': 'SMR nuclear for AI data centers, power bottleneck'},
    'NVDA': {'name': 'NVIDIA', 'thesis': 'GPU monopoly, AI compute backbone (Beta banned, Alpha only)'},
    'APLD': {'name': 'Applied Digital', 'thesis': 'AI data center / HPC infrastructure'},
    'CCJ': {'name': 'Cameco', 'thesis': 'Uranium for nuclear power, AI data center fuel'},
    'MU': {'name': 'Micron', 'thesis': 'Memory chips, AI training demand'},
}
START = '2026-01-01'
END = '2026-07-21'

def fetch_data(ticker):
    """Download historical data from Yahoo Finance."""
    t = yf.Ticker(ticker)
    df = t.history(start=START, end=END, auto_adjust=True)
    if df.empty:
        print(f'  WARNING: No data for {ticker}')
        return None
    df = prepare_data(df, ticker)
    low52 = df['Close'].min()
    high52 = df['Close'].max()
    return df, {'low_52': low52, 'high_52': high52}

def run_all():
    all_results = {}
    print(f'Running backtest from {START} to {END}...')
    print(f'Tickers: {list(TICKERS.keys())}')
    print()
    
    for ticker, info in TICKERS.items():
        print(f'--- {ticker} ({info["name"]}) ---')
        result = fetch_data(ticker)
        if result is None:
            continue
        df, ticker_info = result
        
        # Run Alpha
        alpha_res = run_simulation(df, ticker, ticker_info, 'alpha', START, END)
        print(f'  Alpha: {alpha_res["num_trades"]} trades, P&L: ${alpha_res["final_pnl"]:.2f} ({alpha_res["final_pnl_pct"]:.1%})')
        
        # Run Beta
        beta_res = run_simulation(df, ticker, ticker_info, 'beta', START, END)
        print(f'  Beta: {beta_res["num_trades"]} trades, P&L: ${beta_res["final_pnl"]:.2f} ({beta_res["final_pnl_pct"]:.1%})')
        
        all_results[ticker] = {
            'name': info['name'],
            'thesis': info['thesis'],
            'alpha': alpha_res,
            'beta': beta_res
        }
    
    return all_results

def go_nogo(all_results):
    """Generate go/no-go recommendation based on results."""
    total_alpha_pnl = sum(r['alpha']['final_pnl'] for r in all_results.values())
    total_beta_pnl = sum(r['beta']['final_pnl'] for r in all_results.values())
    total_alpha_trades = sum(r['alpha']['num_trades'] for r in all_results.values())
    total_beta_trades = sum(r['beta']['num_trades'] for r in all_results.values())
    alpha_win_rate = sum(r['alpha']['wins'] for r in all_results.values()) / max(total_alpha_trades, 1)
    beta_win_rate = sum(r['beta']['wins'] for r in all_results.values()) / max(total_beta_trades, 1)
    
    reasons = []
    go = True
    
    if total_alpha_pnl < 0 and total_beta_pnl < 0:
        go = False
        reasons.append(f'Both agents negative: Alpha ${total_alpha_pnl:.2f}, Beta ${total_beta_pnl:.2f}')
    elif total_alpha_pnl < 0:
        reasons.append(f'Alpha negative (${total_alpha_pnl:.2f}) but Beta positive (${total_beta_pnl:.2f}) — partial go')
    elif total_beta_pnl < 0:
        reasons.append(f'Beta negative (${total_beta_pnl:.2f}) but Alpha positive (${total_alpha_pnl:.2f}) — partial go')
    
    if alpha_win_rate < 0.3 and total_alpha_trades > 3:
        reasons.append(f'Alpha win rate {alpha_win_rate:.0%} below 30% threshold')
    if beta_win_rate < 0.3 and total_beta_trades > 3:
        reasons.append(f'Beta win rate {beta_win_rate:.0%} below 30% threshold')
    
    if total_alpha_trades + total_beta_trades < 5:
        reasons.append(f'Only {total_alpha_trades + total_beta_trades} total trades — insufficient data')
        go = False
    
    return {
        'go': go,
        'total_alpha_pnl': total_alpha_pnl,
        'total_beta_pnl': total_beta_pnl,
        'total_alpha_trades': total_alpha_trades,
        'total_beta_trades': total_beta_trades,
        'alpha_win_rate': alpha_win_rate,
        'beta_win_rate': beta_win_rate,
        'reasons': reasons or ['Both agents showing positive or acceptable performance']
    }

if __name__ == '__main__':
    results = run_all()
    recommendation = go_nogo(results)
    
    # Save JSON
    os.makedirs('/Users/johntytko/trading-arena/state/backtests', exist_ok=True)
    with open('/Users/johntytko/trading-arena/state/backtests/backtest_results.json', 'w') as f:
        json.dump({'results': results, 'recommendation': recommendation, 
                      'start': START, 'end': END}, f, indent=2, default=str)
    
    print('\n' + '='*60)
    print('BACKTEST COMPLETE')
    print('='*60)
    print(f'Alpha total P&L: ${recommendation["total_alpha_pnl"]:.2f} ({recommendation["total_alpha_trades"]} trades)')
    print(f'Beta total P&L:  ${recommendation["total_beta_pnl"]:.2f} ({recommendation["total_beta_trades"]} trades)')
    print(f'Alpha win rate:  {recommendation["alpha_win_rate"]:.0%}')
    print(f'Beta win rate:   {recommendation["beta_win_rate"]:.0%}')
    print(f'\nGO/NO-GO: {"GO" if recommendation["go"] else "NO-GO"}')
    for r in recommendation['reasons']:
        print(f'  - {r}')
    print(f'\nResults saved to state/backtests/backtest_results.json')
    print(f'Run: /Users/johntytko/trading-arena/bt-venv/bin/python3 scripts/generate_backtest_report.py for HTML report')
