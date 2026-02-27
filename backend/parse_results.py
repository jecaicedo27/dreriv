import re

logs = """
2026-02-23 05:58:27 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 4 trades, 50.0% win, PnL=$-13.13 (Groq: 4 trades)
2026-02-23 05:58:40 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 4 trades, 25.0% win, PnL=$-282.2 (Groq: 4 trades)
2026-02-23 05:58:47 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 1 trades, 0.0% win, PnL=$-133.92 (Groq: 1 trades)
2026-02-23 05:59:04 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 6 trades, 66.7% win, PnL=$235.49 (Groq: 6 trades)
2026-02-23 05:59:13 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 2 trades, 50.0% win, PnL=$-8.54 (Groq: 2 trades)
2026-02-23 05:59:26 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 4 trades, 50.0% win, PnL=$-17.06 (Groq: 4 trades)
2026-02-23 05:59:39 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 1 trades, 100.0% win, PnL=$128.22 (Groq: 1 trades)
2026-02-23 05:59:57 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 3 trades, 33.3% win, PnL=$-145.25 (Groq: 3 trades)
2026-02-23 06:00:11 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 2 trades, 100.0% win, PnL=$257.68 (Groq: 2 trades)
2026-02-23 06:00:28 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 2 trades, 0.0% win, PnL=$-274.68 (Groq: 2 trades)
2026-02-23 06:00:45 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 4 trades, 75.0% win, PnL=$248.52 (Groq: 4 trades)
2026-02-23 06:01:02 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 3 trades, 66.7% win, PnL=$122.22 (Groq: 3 trades)
2026-02-23 06:01:17 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 2 trades, 50.0% win, PnL=$-8.81 (Groq: 2 trades)
2026-02-23 06:01:30 | SUCCESS  | app.simulation.replay_bot:_run_async:397 - ✅ Bot sim complete: 3 trades, 66.7% win, PnL=$123.6 (Groq: 3 trades)
"""

total_trades = 0
total_wins = 0
total_pnl = 0.0

for line in logs.strip().split('\n'):
    match = re.search(r'(\d+) trades, ([\d.]+)% win, PnL=\$?([\d.-]+)', line)
    if match:
        trades = int(match.group(1))
        win_rate = float(match.group(2)) / 100.0
        pnl = float(match.group(3))
        
        total_trades += trades
        total_wins += round(trades * win_rate)
        total_pnl += pnl

overall_win_rate = (total_wins / total_trades) * 100 if total_trades > 0 else 0
print(f"Total Trades: {total_trades}")
print(f"Total Wins: {total_wins}")
print(f"Overall Win Rate: {overall_win_rate:.1f}%")
print(f"Total PnL: ${total_pnl:.2f}")

