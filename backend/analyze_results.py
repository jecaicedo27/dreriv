
import json
import pandas as pd

def analyze():
    with open('/app/optimization_results.json', 'r') as f:
        data = json.load(f)
        
    results = data.get('all_results', [])
    
    # Filter trades >= 5
    valid = [r for r in results if r['total_trades'] >= 5]
    
    if not valid:
        print("No configs with >= 5 trades found.")
        # Try >= 1
        valid = [r for r in results if r['total_trades'] >= 1]
    
    # Sort by Win Rate desc, then PnL
    ranked = sorted(valid, key=lambda r: (r['win_rate'], r['total_pnl']), reverse=True)
    
    print(f"Loaded {len(results)} configs. Found {len(valid)} with sufficient trades.")
    
    print("\n🏆 TOP 10 BY WIN RATE:")
    print(f"{'ID':>3s} | {'Name':25s} | {'Trades':>6s} | {'Wins':>4s} | {'WR%':>5s} | {'P&L':>8s}")
    print("-" * 80)
    
    for r in ranked[:10]:
        print(f"{r['config_id']:3d} | {r['config_name']:25s} | {r['total_trades']:6d} | {r['wins']:4d} | {r['win_rate']:5.1f}% | ${r['total_pnl']:+7.2f}")
        
    # Also check worst
    print("\n💀 WORST 5:")
    for r in ranked[-5:]:
        print(f"{r['config_id']:3d} | {r['config_name']:25s} | {r['total_trades']:6d} | {r['wins']:4d} | {r['win_rate']:5.1f}% | ${r['total_pnl']:+7.2f}")

    if ranked:
        best = ranked[0]
        if best['win_rate'] >= 60:
            print(f"\n✅ Found hidden gem: Config #{best['config_id']} ({best['win_rate']}%)")
            print(f"Params: {best['params']}")
        else:
             print(f"\n❌ Best feasible config is only {best['win_rate']}%.")

if __name__ == "__main__":
    analyze()
