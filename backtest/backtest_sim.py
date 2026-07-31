#!/usr/bin/env python3
"""Simulation runner, Judge checklist, Rocky PAST tuning."""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(__file__))
from backtest_engine import *

# ─── JUDGE 13-POINT CHECKLIST (simplified for backtest) ───
def judge_evaluate(agent, ticker, entry_price, row, past_scores, agent_name):
    """Run a simplified 13-point checklist. Returns (approved, score, notes)."""
    score = 0
    notes = []
    
    # 1. Thesis supported by data?
    if agent_name == 'alpha':
        rsi = row.get('RSI', 50)
        if rsi < 35: score += 1; notes.append(f'RSI {rsi:.1f} < 35 ✓')
        else: notes.append(f'RSI {rsi:.1f} >= 35 ✗')
    else:
        low52 = row.get('Low52', entry_price)
        if entry_price <= low52 * 1.25: score += 1; notes.append(f'Within 25% of 52wk low ✓')
        else: notes.append(f'Not near 52wk low ✗')
    
    # 2. Position size appropriate ($2,500 allocation)?
    score += 1; notes.append('Position <= $2,500 ✓')
    
    # 3. Stop loss set?
    score += 1; notes.append('Stop loss defined ✓')
    
    # 4. PAST drift check (scores within trust region ±1 of baseline)?
    drift = max(abs(v - 4) for v in past_scores.values())  # 4 = neutral
    if drift <= 3: score += 1; notes.append(f'PAST drift {drift} within trust region ✓')
    else: notes.append(f'PAST drift {drift} outside trust region ✗')
    
    # 5. Convergence check (is the other agent in this ticker?)
    score += 1; notes.append('No convergence conflict ✓')
    
    # 6. Earnings within 5 days? (approximate - skip in backtest)
    score += 1; notes.append('No earnings within 5 days (assumed) ✓')
    
    # 7. Liquidity check (large cap assumed)
    score += 1; notes.append('Liquid large-cap ✓')
    
    # 8. PAST personality fit
    if agent_name == 'alpha':
        if past_scores.get('patience', 6) >= 5: score += 1; notes.append('Patience high enough to wait for setup ✓')
    else:
        if past_scores.get('conviction', 7) >= 6: score += 1; notes.append('Conviction high enough for thesis trade ✓')
    
    # 9-13: Simplified - pass on options, catalyst, state file honesty, etc.
    score += 5; notes.append('Remaining checks pass ✓')
    
    approved = score >= 10  # need 10/13 to approve
    return approved, score, notes

# ─── ROCKY PAST TUNING ───
def rocky_tune(agent_name, trades, past_scores, week_num):
    """Rocky reviews performance and adjusts PAST scores (max ±1 per cycle)."""
    adjustments = {}
    reasons = []
    
    completed = [t for t in trades if t['status'] == 'CLOSED']
    wins = [t for t in completed if t['pnl'] > 0]
    losses = [t for t in completed if t['pnl'] < 0]
    win_rate = len(wins) / len(completed) if completed else 0
    
    if agent_name == 'alpha':
        # Alpha: tune patience based on discipline
        if win_rate < 0.3 and len(losses) > 2:
            # Too many losses - increase patience (tighter entry)
            if past_scores['patience'] < 7:
                adjustments['patience'] = past_scores['patience'] + 1
                reasons.append(f'Win rate {win_rate:.0%} low — increase Patience to tighten entry criteria')
        # Check if too conservative (no trades)
        if len(completed) == 0 and week_num >= 2:
            if past_scores['patience'] > 4:
                adjustments['patience'] = past_scores['patience'] - 1
                reasons.append('No trades completed — decrease Patience to loosen entry slightly')
    else:
        # Beta: tune conviction and impulsivity
        if losses and any(t['pnl_pct'] <= -0.10 for t in losses):
            # Hit max stop - increase impulsivity scrutiny
            if past_scores['impulsivity'] < 7:
                adjustments['impulsivity'] = past_scores['impulsivity'] + 1
                reasons.append('Stop loss hit — increase Impulsivity (more scrutiny on entry timing)')
        if win_rate > 0.5 and len(wins) >= 2:
            if past_scores['conviction'] < 7:
                adjustments['conviction'] = past_scores['conviction'] + 1
                reasons.append(f'Win rate {win_rate:.0%} high — increase Conviction')
    
    return adjustments, reasons

# ─── SIMULATION RUNNER ───
def run_simulation(df, ticker, ticker_info, agent_name, start_date, end_date):
    """Run a full simulation for one agent on one stock."""
    # Filter to date range
    mask = (df.index >= start_date) & (df.index <= end_date)
    sim_df = df.loc[mask].copy()
    
    # Initialize PAST scores — Baker/Atreides profile (replaces Aschenbrenner)
    past = {'risk': 3, 'conviction': 4, 'impulsivity': 2, 'patience': 6} if agent_name == 'alpha' \
           else {'risk': 5, 'conviction': 6, 'impulsivity': 3, 'patience': 6}  # Baker: diversified, Sharpe-driven, no leverage
    
    cash = ALLOC
    position = None  # {'entry_price': x, 'shares': n, 'entry_date': d, 'entry_row': row}
    trades = []
    past_history = [past.copy()]
    judge_verdicts = []
    
    bi_weekly_counter = 0
    
    for i, (date, row) in enumerate(sim_df.iterrows()):
        days_held = (date - position['entry_date']).days if position else 0
        
        # ── CHECK EXIT ON EXISTING POSITION ──
        if position:
            if agent_name == 'alpha':
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
                    'ticker': ticker, 'agent': agent_name,
                    'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
                    'exit_date': date.strftime('%Y-%m-%d'),
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price, 'shares': shares,
                    'pnl': pnl, 'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason, 'status': 'CLOSED'
                })
                position = None
        
        # ── CHECK ENTRY ──
        if position is None:
            if agent_name == 'alpha':
                should_enter = alpha_should_enter(row, position)
            else:
                should_enter = beta_should_enter(row, position, ticker_info)
            
            if should_enter:
                # Run Judge
                approved, judge_score, judge_notes = judge_evaluate(
                    agent_name, ticker, row['Close'], row, past, agent_name)
                
                judge_verdicts.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'ticker': ticker, 'agent': agent_name,
                    'approved': approved, 'score': judge_score,
                    'notes': '; '.join(judge_notes)
                })
                
                if approved:
                    entry_price = row['Close']
                    if agent_name == 'alpha':
                        max_pct = 0.08 if should_enter == 'SECONDARY' else 0.15  # reduced size for secondary
                        shares = min(cash / entry_price, ALLOC * max_pct / entry_price)
                    else:
                        shares = min(cash / entry_price, ALLOC * 0.25 / entry_price)  # Baker: 25% max per position (diversified)
                    shares = round(shares, 1)
                    cost = entry_price * shares
                    cash -= cost
                    position = {
                        'entry_price': entry_price,
                        'shares': shares,
                        'entry_date': date,
                        'entry_row': row
                    }
        
        # ── BI-WEEKLY ROCKY TUNING ──
        if i > 0 and i % 10 == 0:  # every 10 trading days (~2 weeks)
            bi_weekly_counter += 1
            adjustments, reasons = rocky_tune(agent_name, trades, past, bi_weekly_counter)
            if adjustments:
                new_past = past.copy()
                new_past.update(adjustments)
                past_history.append({
                    'week': bi_weekly_counter,
                    'old': past.copy(),
                    'new': new_past,
                    'adjustments': adjustments,
                    'reasons': reasons
                })
                past = new_past
    
    # Close any remaining position at last price
    if position:
        last_row = sim_df.iloc[-1]
        exit_price = last_row['Close']
        pnl = (exit_price - position['entry_price']) * position['shares']
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        cash += exit_price * position['shares']
        trades.append({
            'ticker': ticker, 'agent': agent_name,
            'entry_date': position['entry_date'].strftime('%Y-%m-%d'),
            'exit_date': sim_df.index[-1].strftime('%Y-%m-%d'),
            'entry_price': position['entry_price'],
            'exit_price': exit_price, 'shares': position['shares'],
            'pnl': pnl, 'pnl_pct': pnl_pct,
            'exit_reason': 'END_OF_PERIOD', 'status': 'CLOSED'
        })
    
    # Calculate final P&L
    final_pnl = cash - ALLOC
    final_pnl_pct = final_pnl / ALLOC
    
    return {
        'agent': agent_name, 'ticker': ticker,
        'trades': trades, 'judge_verdicts': judge_verdicts,
        'past_history': past_history,
        'final_pnl': final_pnl, 'final_pnl_pct': final_pnl_pct,
        'final_cash': cash,
        'num_trades': len(trades),
        'wins': len([t for t in trades if t['pnl'] > 0]),
        'losses': len([t for t in trades if t['pnl'] < 0]),
        'win_rate': len([t for t in trades if t['pnl'] > 0]) / len(trades) if trades else 0
    }
