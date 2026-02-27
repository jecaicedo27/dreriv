import re
import subprocess

# Get the last 10000 lines of docker logs
result = subprocess.run(['docker', 'logs', '--tail', '10000', 'deriv-backend'], capture_output=True, text=True)

lines = result.stderr.split('\n') + result.stdout.split('\n')
sim_lines = [line for line in lines if "Bot sim complete" in line and "(Groq" in line]

# Take the last 53 lines, assuming that's the latest batch run of 53 days
if len(sim_lines) > 53:
    sim_lines = sim_lines[-53:]

total_trades = 0
total_wins = 0
total_pnl = 0.0
days_counted = len(sim_lines)

for line in sim_lines:
    match = re.search(r'(\d+) trades, ([\d.]+)% win, PnL=\$?([\d.-]+)', line)
    if match:
        trades = int(match.group(1))
        win_rate = float(match.group(2)) / 100.0
        pnl = float(match.group(3))
        
        total_trades += trades
        total_wins += round(trades * win_rate)
        total_pnl += pnl

overall_win_rate = (total_wins / total_trades) * 100 if total_trades > 0 else 0
print(f"Days Evaluated: {days_counted}")
print(f"Total Trades: {total_trades}")
print(f"Total Wins: {total_wins}")
print(f"Overall Win Rate: {overall_win_rate:.1f}%")
print(f"Total PnL: ${total_pnl:.2f}")

