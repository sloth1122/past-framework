#!/usr/bin/env python3
"""
Trading Arena Backtesting Harness
Runs simulated trades for Alpha + Beta across historical data,
applies Judge 13-point checklist, runs Rocky bi-weekly PAST tuning.
Outputs: P&L, trade log, PAST evolution, go/no-go recommendation.
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(__file__))

# We'll use the bt-venv python: /Users/johntytko/trading-arena/bt-venv/bin/python3
import yfinance as yf
import pandas as pd
import numpy as np

# ─── CONFIG ───
ALLOC = 2500.0  # per agent
JUDGE_BUDGET = 250  # options budget for Beta

# ─── ALPHA RULES (Renaissance / Mean Reversion) ───
def alpha_should_enter(row, position):
    """Alpha enters when RSI < 35 AND 50-day MA is rising.
    Secondary entry: RSI 35-45 + rising 50-day MA at reduced size (Rocky proposal)."""
    if position is not None:
        return False  # already in a position
    rsi = row.get('RSI', 50)
    ma50 = row.get('MA50', 0)
    ma50_prev = row.get('MA50_prev', 0)
    price = row['Close']
    rising_ma = ma50 > ma50_prev
    # Primary: RSI < 35 + rising 50-day MA
    if rsi < 35 and rising_ma and price > ma50 * 0.85:
        return 'PRIMARY'
    # Secondary (Rocky-approved): RSI 35-45 + rising 50-day MA
    if 35 <= rsi <= 45 and rising_ma and price > ma50 * 0.90:
        return 'SECONDARY'
    return False

def alpha_should_exit(row, entry, days_held):
    """Alpha exits on 3% stop, RSI > 55, or 5-day time limit."""
    price = row['Close']
    stop = entry['entry_price'] * 0.97  # 3% stop
    rsi = row.get('RSI', 50)
    if price <= stop:
        return 'STOP_LOSS'
    if rsi > 55:
        return 'RSI_EXIT'
    if days_held >= 5:
        return 'TIME_EXIT'
    return None

# ─── BETA RULES (Aschenbrenner / AI Infra Thesis) ───
def beta_should_enter(row, position, ticker_info):
    """Beta (Baker/Atreides) enters near 52-week low with architecture thesis intact.
    No banned list — Baker owns NVDA when reasonable. Diversified across architecture layers."""
    if position is not None:
        return False
    price = row['Close']
    low_52 = ticker_info.get('low_52', price)
    high_52 = ticker_info.get('high_52', price)
    # Entry rule: within 25% of 52-week low OR pulled back >15% from 52-week high
    near_low = price <= low_52 * 1.25
    pulled_back = price <= high_52 * 0.85
    return near_low or pulled_back

def beta_should_exit(row, entry, days_held):
    """Beta exits on 10% stop only (thesis holds, weeks-months timeframe)."""
    price = row['Close']
    stop = entry['entry_price'] * 0.90  # 10% stop
    if price <= stop:
        return 'STOP_LOSS'
    return None  # no time limit for Beta

# ─── INDICATOR CALCULATIONS ───
def calc_rsi(prices, period=14):
    """Calculate RSI (Relative Strength Index)."""
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 100
    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.0
        else:
            upval = 0.0
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 100
        rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def prepare_data(df, ticker):
    """Add RSI, MA50, MA50 slope to the dataframe."""
    prices = df['Close'].values
    df = df.copy()
    df['RSI'] = calc_rsi(prices)
    df['MA50'] = df['Close'].rolling(50).mean()
    df['MA50_prev'] = df['MA50'].shift(5)  # 5 days ago
    df['Low52'] = df['Close'].rolling(252).min()
    df['High52'] = df['Close'].rolling(252).max()
    # Forward fill for early days
    df['MA50'] = df['MA50'].fillna(df['Close'].expanding().mean())
    df['MA50_prev'] = df['MA50_prev'].fillna(df['MA50'])
    df['Low52'] = df['Low52'].fillna(df['Close'].expanding().min())
    df['High52'] = df['High52'].fillna(df['Close'].expanding().max())
    return df

print("Core engine loaded. Use run_backtest.py to execute.")
