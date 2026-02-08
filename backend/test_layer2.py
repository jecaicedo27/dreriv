#!/usr/bin/env python3
"""Test Layer 2 formatting with exact Layer 1 signal structure"""
import sys
import traceback

# Exact structure from Layer 1 
layer1_signal = {
    'final_signal': 'HOLD',  
    'final_confidence': 0.0,
    'reasoning': 'Hurst exponent 0.686 indicates TRENDING | Mean reversion NOT favorable - HOLD',
    'hurst_exponent': 0.6865,
    'ou_signal': -0.21,
    'ou_zscore': -1.85,
    'current_volatility': 0.000150,
    'forecast_volatility': 0.000145,
    'indicators': {
        'rsi': 48.5,
        'bb_position': 0.42,
        'macd_histogram': -0.0003,
        'ema_20': 1129.5,
        'ema_50': 1130.2
    }
}

try:
    from app.analysis.layer2_groq import Layer2GroqEngine
    engine = Layer2GroqEngine()
    context = engine._format_market_context(layer1_signal, [])
    print('✅ FORMAT SUCCESS!')
    print(f'Context length: {len(context)} chars')
    print('First 200 chars:', context[:200])
except Exception as e:
    print(f'❌ ERROR: {e}')
    print('\nFull traceback:')
    traceback.print_exc()
    sys.exit(1)
