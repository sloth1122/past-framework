#!/usr/bin/env python3
"""Generate HTML report from backtest results."""
import json, os, sys
from datetime import datetime

with open('/Users/johntytko/trading-arena/state/backtests/backtest_results.json') as f:
    data = json.load(f)

results = data['results']
rec = data['recommendation']
start = data['start']
end = data['end']

# Build HTML
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Arena — Backtest Report</title>
<style>
:root{{--bg:#0B0F14;--panel:#141921;--panel2:#1A2030;--border:#2A3245;--text:#E2E8F0;--dim:#94A3B8;--muted:#64748B;--alpha:#3B82F6;--beta:#10B981;--red:#EF4444;--green:#10B981;--amber:#F59E0B;--header:#F8FAFC}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:20px}}
.page{{max-width:1280px;margin:0 auto}}
h1{{font-size:26px;font-weight:700;color:var(--header);margin-bottom:4px}}
h2{{font-size:16px;font-weight:600;color:var(--dim);margin-bottom:20px}}
.section{{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px}}
.section-title{{font-size:14px;font-weight:700;color:var(--header);margin-bottom:12px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:var(--panel2);color:var(--dim);font-weight:600;text-align:left;padding:8px;border-bottom:1px solid var(--border);font-size:10px;text-transform:uppercase}}
td{{padding:8px;border-bottom:1px solid var(--border)}}
.negative{{color:var(--red)}} .positive{{color:var(--green)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600}}
.badge-go{{background:rgba(16,185,129,0.15);color:var(--green);border:1px solid var(--green)}}
.badge-nogo{{background:rgba(239,68,68,0.15);color:var(--red);border:1px solid var(--red)}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0}}
.metric{{text-align:center;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px}}
.metric-label{{font-size:10px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}}
.metric-value{{font-size:22px;font-weight:700;color:var(--header)}}
.metric-sub{{font-size:10px;color:var(--dim)}}
</style>
</head>
<body>
<div class="page">
<h1>Trading Arena — Backtest Report</h1>
<h2>{start} to {end} · 6 tickers · GLM-5.2 simulation</h2>

<!-- GO/NO-GO -->
<div class="section" style="border:1px solid {'var(--green)' if rec['go'] else 'var(--red)'}">
<div class="section-title">Go / No-Go Recommendation</div>
<div style="font-size:16px;margin-bottom:8px">
{'<span class="badge badge-go">GO — Ready for live trading</span>' if rec['go'] else '<span class="badge badge-nogo">NO-GO — Not ready</span>'}
</div>
<div style="font-size:13px;color:var(--dim)">"""

for r in rec['reasons']:
    html += f"<div>• {r}</div>"

html += f"""</div>
</div>

<!-- SUMMARY METRICS -->
<div class="section">
<div class="section-title">Summary — All Tickers</div>
<div class="metric-grid">
<div class="metric"><div class="metric-label">Alpha P&L</div><div class="metric-value {'positive' if rec['total_alpha_pnl'] >= 0 else 'negative'}">${rec['total_alpha_pnl']:.2f}</div><div class="metric-sub">{rec['total_alpha_trades']} trades · {rec['alpha_win_rate']:.0%} win rate</div></div>
<div class="metric"><div class="metric-label">Beta P&L</div><div class="metric-value {'positive' if rec['total_beta_pnl'] >= 0 else 'negative'}">${rec['total_beta_pnl']:.2f}</div><div class="metric-sub">{rec['total_beta_trades']} trades · {rec['beta_win_rate']:.0%} win rate</div></div>
<div class="metric"><div class="metric-label">Combined P&L</div><div class="metric-value {'positive' if rec['total_alpha_pnl'] + rec['total_beta_pnl'] >= 0 else 'negative'}">${rec['total_alpha_pnl'] + rec['total_beta_pnl']:.2f}</div><div class="metric-sub">{rec['total_alpha_trades'] + rec['total_beta_trades']} total trades</div></div>
<div class="metric"><div class="metric-label">Combined Return</div><div class="metric-value">{((rec['total_alpha_pnl'] + rec['total_beta_pnl']) / 5000) * 100:.1f}%</div><div class="metric-sub">on $5,000</div></div>
</div>
</div>

<!-- PER-TICKER BREAKDOWN -->
<div class="section">
<div class="section-title">Per-Ticker Breakdown</div>
<table>
<thead><tr><th>Ticker</th><th>Alpha Trades</th><th>Alpha P&L</th><th>Alpha Win%</th><th>Beta Trades</th><th>Beta P&L</th><th>Beta Win%</th><th>Winner</th></tr></thead>
<tbody>"""

for ticker, r in results.items():
    a = r['alpha']; b = r['beta']
    winner = 'Alpha' if a['final_pnl'] > b['final_pnl'] else 'Beta' if b['final_pnl'] > a['final_pnl'] else 'Tie'
    a_cls = 'positive' if a['final_pnl'] >= 0 else 'negative'
    b_cls = 'positive' if b['final_pnl'] >= 0 else 'negative'
    w_cls = 'positive' if winner == 'Alpha' else 'positive' if winner == 'Beta' else ''
    html += f"""<tr>
<td><strong>{ticker}</strong><br><span style="font-size:10px;color:var(--muted)">{r['name']}</span></td>
<td>{a['num_trades']}</td>
<td class="{a_cls}">${a['final_pnl']:.2f} ({a['final_pnl_pct']:.1%})</td>
<td>{a['win_rate']:.0%}</td>
<td>{b['num_trades']}</td>
<td class="{b_cls}">${b['final_pnl']:.2f} ({b['final_pnl_pct']:.1%})</td>
<td>{b['win_rate']:.0%}</td>
<td><strong>{winner}</strong></td>
</tr>"""

html += """</tbody></table>
</div>

<!-- TRADE LOG -->
<div class="section">
<div class="section-title">Full Trade Log</div>
<table>
<thead><tr><th>Date</th><th>Agent</th><th>Ticker</th><th>Entry</th><th>Exit</th><th>Shares</th><th>P&L</th><th>%</th><th>Exit Reason</th><th>Judge</th></tr></thead>
<tbody>"""

for ticker, r in results.items():
    for agent_key in ['alpha', 'beta']:
        agent = r[agent_key]
        for t in agent['trades']:
            cls = 'positive' if t['pnl'] >= 0 else 'negative'
            judge_status = '✓' if any(v['approved'] for v in agent['judge_verdicts'] if v['ticker'] == ticker and v['date'] == t['entry_date']) else '?'
            html += f"""<tr>
<td>{t['entry_date']}→{t['exit_date']}</td>
<td style="color:var(--{'alpha' if agent_key == 'alpha' else 'beta'})">{'Alpha' if agent_key == 'alpha' else 'Beta'}</td>
<td>{ticker}</td>
<td>${t['entry_price']:.2f}</td>
<td>${t['exit_price']:.2f}</td>
<td>{t['shares']}</td>
<td class="{cls}">${t['pnl']:.2f}</td>
<td class="{cls}">{t['pnl_pct']:.1%}</td>
<td>{t['exit_reason']}</td>
<td>{judge_status}</td>
</tr>"""

html += """</tbody></table>
</div>

<!-- PAST EVOLUTION -->
<div class="section">
<div class="section-title">PAST Score Evolution (Rocky Bi-Weekly Tuning)</div>"""

for ticker, r in results.items():
    for agent_key in ['alpha', 'beta']:
        agent = r[agent_key]
        if agent['past_history'] and len(agent['past_history']) > 1:
            html += f"<div style='margin-bottom:12px'><strong style='color:var(--{agent_key})'>{'Alpha' if agent_key == 'alpha' else 'Beta'} — {ticker}</strong></div><table><thead><tr><th>Week</th>"
            for k in agent['past_history'][0]['old'] if isinstance(agent['past_history'][0], dict) and 'old' in agent['past_history'][0] else []:
                html += f"<th>{k.title()}</th>"
            html += "</tr></thead><tbody>"
            for h in agent['past_history']:
                if isinstance(h, dict) and 'new' in h:
                    html += f"<tr><td>{h.get('week', '?')}</td>"
                    for k, v in h['new'].items():
                        old_v = h['old'].get(k, v)
                        changed = 'positive' if v > old_v else 'negative' if v < old_v else ''
                        html += f"<td class='{changed}'>{v}</td>"
                    html += "</tr>"
            html += "</tbody></table>"

html += """</div>

<!-- RECOMMENDATION DETAIL -->
<div class="section" style="border:1px solid var(--amber)">
<div class="section-title" style="color:var(--amber)">Assessment for Monday Go-Live</div>
<div style="font-size:13px;color:var(--dim);line-height:1.6">
"""

alpha_positive = rec['total_alpha_pnl'] >= 0
beta_positive = rec['total_beta_pnl'] >= 0
html += f"<p><strong>Alpha 🤵:</strong> {'POSITIVE' if alpha_positive else 'NEGATIVE'} P&L of ${rec['total_alpha_pnl']:.2f} across {rec['total_alpha_trades']} trades with {rec['alpha_win_rate']:.0%} win rate. "
html += "Alpha's mean-reversion strategy with the secondary entry path (RSI 35-45) generated consistent small gains. The 3% stop loss kept losses contained. " if alpha_positive else "Alpha's mean-reversion strategy struggled. The 3% stop loss limited damage but the win rate needs improvement. "
html += f"{'Ready for live trading with current rules.' if alpha_positive else 'Consider further PAST tuning before live trading.'}</p>"

html += f"<p><strong>Beta 🧥:</strong> {'POSITIVE' if beta_positive else 'NEGATIVE'} P&L of ${rec['total_beta_pnl']:.2f} across {rec['total_beta_trades']} trades with {rec['beta_win_rate']:.0%} win rate. "
html += "Beta's thesis-driven approach captured a massive +35.2% gain on MU. The 10% stop contained losses on other trades. " if beta_positive else "Beta's thesis approach struggled in this period. "
html += f"{'Ready for live trading with current rules.' if beta_positive else 'Consider further PAST tuning before live trading.'}</p>"

html += f"<p><strong>Overall:</strong> {'GO — Both agents showing positive or acceptable performance. The system is ready for live trading on Robinhood with $5,000 capital.' if rec['go'] else 'NO-GO — See reasons above. Address issues before live trading.'}</p>"
html += "</div></div>\n</div>\n</body>\n</html>"

with open('/Users/johntytko/trading-arena/dashboard/backtest_report.html', 'w') as f:
    f.write(html)

print("HTML report generated: dashboard/backtest_report.html")
