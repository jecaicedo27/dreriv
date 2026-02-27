from app.core.database import SessionLocal
from sqlalchemy import text
from collections import defaultdict

db = SessionLocal()

rows = db.execute(text("""
    SELECT 
        EXTRACT(HOUR FROM entry_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/Bogota')::int as col_hour,
        engine_name,
        outcome,
        profit_loss
    FROM trades 
    WHERE outcome IN ('WIN','LOSS') 
      AND profit_loss IS NOT NULL
      AND engine_name IS NOT NULL
    ORDER BY engine_name, col_hour
""")).fetchall()

engines = defaultdict(lambda: defaultdict(lambda: {'w': 0, 'l': 0, 'pnl': 0.0}))
for r in rows:
    h = int(r[0])
    eng = r[1] or 'unknown'
    engines[eng][h]['pnl'] += float(r[3])
    if r[2] == 'WIN':
        engines[eng][h]['w'] += 1
    else:
        engines[eng][h]['l'] += 1

blocked = {
    'bear_reject_v1': {0, 3, 8, 9, 12, 13, 18, 20},
    'bullish_v5': {2, 3, 4, 5, 8, 9, 10, 12, 13, 16, 17, 18, 19},
    'bull_soldiers_v1': {5, 7, 10, 13, 16, 22, 23},
}

target_engines = ['bear_reject_v1', 'bullish_v5', 'bull_soldiers_v1']

for eng_name in target_engines:
    data = engines.get(eng_name, {})
    bh = blocked.get(eng_name, set())
    total_trades = sum(d['w']+d['l'] for d in data.values())
    
    if total_trades == 0:
        print(f"\n  {eng_name}: 0 trades (sin datos)")
        continue
    
    print(f'')
    print(f'══════════════════════════════════════════════════════════════')
    print(f'  {eng_name} ({total_trades} trades)')
    print(f'  Bloqueadas: {sorted(bh)}')
    print(f'══════════════════════════════════════════════════════════════')
    print(f'HORA   W    L   TOT   WR%      PnL     ESTADO  VEREDICTO')
    print(f'----  ---  ---  ---  -----  --------  ------  ---------')
    
    total_saved = 0
    total_missed = 0
    
    for h in range(24):
        d = data.get(h, {'w': 0, 'l': 0, 'pnl': 0.0})
        tot = d['w'] + d['l']
        if tot == 0:
            continue
        wr = d['w'] / tot * 100
        is_blocked = h in bh
        status = '🚫' if is_blocked else '✅'
        
        if is_blocked:
            if d['pnl'] < 0:
                verdict = f'CORRECTO (ahorra ${abs(d["pnl"]):.0f})'
                total_saved += abs(d['pnl'])
            else:
                verdict = f'⚠️ PIERDE ${d["pnl"]:.0f} de oportunidad'
                total_missed += d['pnl']
        else:
            if d['pnl'] >= 0:
                verdict = 'OK ✅'
            else:
                verdict = f'💡 BLOQUEAR? (pierde ${abs(d["pnl"]):.0f})'
        
        print(f'{h:02d}:00  {d["w"]:>3}  {d["l"]:>3}  {tot:>3}  {wr:>5.1f}  ${d["pnl"]:>+8.2f}  {status}  {verdict}')
    
    total_pnl = sum(d['pnl'] for d in data.values())
    blocked_pnl = sum(data.get(h, {'pnl':0})['pnl'] for h in bh if h in data)
    free_pnl = total_pnl - blocked_pnl
    
    print(f'')
    print(f'  💰 Dinero SALVADO por bloqueo correcto: ${total_saved:+,.2f}')
    print(f'  ❌ Costo oportunidad (bloqueó horas buenas): ${total_missed:+,.2f}')
    net = total_saved - total_missed
    print(f'  📊 Balance neto del bloqueo: ${net:+,.2f} ({"POSITIVO ✅" if net > 0 else "NEGATIVO ❌"})')
    print(f'  📈 PnL total del motor: ${total_pnl:+,.2f}')
    print(f'  📈 PnL horas libres: ${free_pnl:+,.2f}')
    print(f'  📈 PnL horas bloqueadas (no ejecutado): ${blocked_pnl:+,.2f}')

# Also check trades from old deleted engines
print(f'\n\n══════ NOTA: Motores históricos eliminados ══════')
for eng_name in sorted(engines.keys()):
    if eng_name in target_engines:
        continue
    data = engines[eng_name]
    total = sum(d['w']+d['l'] for d in data.values())
    pnl = sum(d['pnl'] for d in data.values())
    if total > 0:
        print(f'  {eng_name}: {total} trades, PnL=${pnl:+,.2f} (datos históricos, motor ya eliminado)')

db.close()
