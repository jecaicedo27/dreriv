#!/usr/bin/env python3
"""
Test script to verify dynamic duration implementation
"""
import sys
import os
sys.path.insert(0, '/app')

import pandas as pd
import numpy as np
from app.analysis.layer1_engine import Layer1SignalEngine

# Create test data
np.random.seed(42)
n_candles = 250

# Test 1: Mean Reversion scenario (prices oscillating around mean)
print("=" * 60)
print("TEST 1: MEAN REVERSION SCENARIO")
print("=" * 60)

mean_reversion_prices = 1070 + np.cumsum(np.random.randn(n_candles) * 0.5)
mean_reversion_prices = pd.Series(mean_reversion_prices)

# Add strong deviation at the end
mean_reversion_prices.iloc[-1] = 1090  # Price spikes up 2-3 sigma

df_mean_rev = pd.DataFrame({
    'open_time': pd.date_range('2026-02-09', periods=n_candles, freq='1min'),
    'open': mean_reversion_prices.shift(1).fillna(mean_reversion_prices.iloc[0]),
    'high': mean_reversion_prices + 0.5,
    'low': mean_reversion_prices - 0.5,
    'close': mean_reversion_prices,
    'volume': 30.0
})

# Analyze
engine = Layer1SignalEngine()
result = engine.analyze(df_mean_rev, 'R_100')

print(f"\n📊 Regime: {result['hurst_signal']['regime']}")
print(f"   Hurst: {result['hurst_signal']['hurst']:.3f}")
print(f"🎯 Signal: {result['final_signal']}")
print(f"⏱️  Duration: {result['duration']}s ({result['duration']//60}min {result['duration']%60}s)")
print(f"💡 Reasoning: {result['reasoning']}")

# Test 2: Trending scenario (strong uptrend)
print("\n" + "=" * 60)
print("TEST 2: TRENDING SCENARIO (Strong Uptrend)")
print("=" * 60)

trending_prices = pd.Series(1060 + np.cumsum(np.random.randn(n_candles) * 0.3 + 0.15))  # Drift upward
df_trend = pd.DataFrame({
    'open_time': pd.date_range('2026-02-09', periods=n_candles, freq='1min'),
    'open': trending_prices.shift(1).fillna(trending_prices.iloc[0]),
    'high': trending_prices + 0.5,
    'low': trending_prices - 0.5,
    'close': trending_prices,
    'volume': 30.0
})

result2 = engine.analyze(df_trend, 'R_100')

print(f"\n📊 Regime: {result2['hurst_signal']['regime']}")
print(f"   Hurst: {result2['hurst_signal']['hurst']:.3f}")
print(f"🎯 Signal: {result2['final_signal']}")
print(f"⏱️  Duration: {result2['duration']}s ({result2['duration']//60}min {result2['duration']%60}s)")
print(f"💡 Reasoning: {result2['reasoning']}")

# Test 3: Very strong trend
print("\n" + "=" * 60)
print("TEST 3: VERY STRONG TREND")
print("=" * 60)

very_strong_trend = pd.Series(1060 + np.cumsum(np.random.randn(n_candles) * 0.2 + 0.25))  # Strong drift
df_vstrong = pd.DataFrame({
    'open_time': pd.date_range('2026-02-09', periods=n_candles, freq='1min'),
    'open': very_strong_trend.shift(1).fillna(very_strong_trend.iloc[0]),
    'high': very_strong_trend + 0.5,
    'low': very_strong_trend - 0.5,
    'close': very_strong_trend,
    'volume': 30.0
})

result3 = engine.analyze(df_vstrong, 'R_100')

print(f"\n📊 Regime: {result3['hurst_signal']['regime']}")
print(f"   Hurst: {result3['hurst_signal']['hurst']:.3f}")
print(f"🎯 Signal: {result3['final_signal']}")
print(f"⏱️  Duration: {result3['duration']}s ({result3['duration']//60}min {result3['duration']%60}s)")
print(f"💡 Reasoning: {result3['reasoning']}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY: Dynamic Duration Ranges")
print("=" * 60)
print(f"Mean Reversion: {result['duration']}s")
print(f"Trending (moderate): {result2['duration']}s")
print(f"Trending (strong): {result3['duration']}s")
print("\nExpected Ranges:")
print("- MEAN_REVERSION: 60s - 3600s (based on O-U half-life)")
print("- TRENDING weak: 600s (10 min)")
print("- TRENDING moderate: 900s (15 min)")
print("- TRENDING strong: 1200s (20 min)")
print("- TRENDING very strong: 1800s (30 min)")
print("\n✅ Test complete!")
