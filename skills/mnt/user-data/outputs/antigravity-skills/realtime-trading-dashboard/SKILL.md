---
name: realtime-trading-dashboard
description: "Real-time trading dashboard with Next.js 14, TradingView Lightweight Charts, Socket.IO, and shadcn/ui. Use when building live trading dashboards, embedding TradingView charts with custom overlays (order blocks, FVG, trade markers), displaying real-time P&L, building equity curves, or creating WebSocket-powered live data feeds for trading bots."
---

# Real-Time Trading Dashboard

## Overview

Production-grade trading dashboard built with Next.js 14 (App Router), TradingView Lightweight Charts for market data, Socket.IO for real-time updates, and shadcn/ui for components. Designed for monitoring an automated trading bot with live P&L, trade markers, and AI decision visualization.

## When to Use This Skill

- Building a real-time trading monitoring dashboard
- Embedding TradingView Lightweight Charts in Next.js
- Adding custom overlays to charts (markers, rectangles, lines)
- Streaming live data via Socket.IO to React components
- Building equity curves and performance analytics pages
- Dark-mode trading UI with professional aesthetics

## Stack

```json
{
  "framework": "Next.js 14+ (App Router)",
  "ui": "Tailwind CSS + shadcn/ui",
  "charts_market": "lightweight-charts (TradingView)",
  "charts_stats": "recharts",
  "realtime": "socket.io-client",
  "auth": "JWT (single admin user)",
  "theme": "Dark mode default"
}
```

## TradingView Lightweight Charts Integration

### Installation
```bash
npm install lightweight-charts
```

### React Component Pattern
```tsx
'use client';
import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi } from 'lightweight-charts';

interface CandleData {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
}

export function TradingChart({ symbol, timeframe }: { symbol: string; timeframe: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  
  useEffect(() => {
    if (!chartContainerRef.current) return;
    
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0f1118' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 500,
      crosshair: {
        mode: 0, // Normal crosshair
      },
      timeScale: {
        borderColor: '#374151',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#374151',
      },
    });
    
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    });
    
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    
    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);
    
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);
  
  return <div ref={chartContainerRef} className="w-full" />;
}
```

### Adding Custom Overlays

```tsx
// Trade markers (green triangles for wins, red for losses)
function addTradeMarkers(candleSeries: ISeriesApi<'Candlestick'>, trades: Trade[]) {
  const markers = trades.map(trade => ({
    time: trade.epoch as any,
    position: trade.direction === 'BUY' ? 'belowBar' : 'aboveBar',
    color: trade.result === 'won' ? '#22c55e' : '#ef4444',
    shape: trade.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
    text: `${trade.result === 'won' ? '+' : ''}$${trade.profit_loss.toFixed(2)}`,
  }));
  candleSeries.setMarkers(markers);
}

// EMA overlay lines
function addEMALine(chart: IChartApi, data: {time: number, value: number}[], color: string) {
  const series = chart.addLineSeries({
    color,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
  });
  series.setData(data);
  return series;
}

// Order Block rectangles (using box plugin or manual drawing)
// Note: lightweight-charts doesn't have native rectangles.
// Use price lines + background coloring or the drawings plugin.
function addOrderBlockZone(chart: IChartApi, top: number, bottom: number, color: string) {
  // Approach: Add two horizontal price lines with area between them
  const area = chart.addAreaSeries({
    topColor: color + '30',     // 30% opacity
    bottomColor: color + '10',  // 10% opacity
    lineColor: color,
    lineWidth: 1,
  });
  // Set data points spanning the visible range
  return area;
}
```

### Streaming Live Candles via Socket.IO

```tsx
'use client';
import { useEffect } from 'react';
import { io } from 'socket.io-client';

export function useLiveCandles(
  symbol: string,
  timeframe: string,
  onCandle: (candle: CandleData) => void,
  onTick: (tick: { price: number; time: number }) => void
) {
  useEffect(() => {
    const socket = io(process.env.NEXT_PUBLIC_WS_URL || 'http://localhost:8000', {
      transports: ['websocket'],
    });
    
    socket.emit('subscribe', { symbol, timeframe });
    
    socket.on('candle_update', (data) => {
      onCandle({
        time: data.epoch,
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
      });
    });
    
    socket.on('tick', (data) => {
      onTick({ price: data.quote, time: data.epoch });
    });
    
    return () => {
      socket.emit('unsubscribe', { symbol, timeframe });
      socket.disconnect();
    };
  }, [symbol, timeframe]);
}
```

## Dashboard Pages Structure

```
app/
├── layout.tsx          # Dark theme, sidebar nav
├── page.tsx            # Dashboard home
├── trades/
│   └── page.tsx        # Trade history + active trades
├── analysis/
│   └── page.tsx        # Market analysis, patterns, Crash/Boom
├── performance/
│   └── page.tsx        # Equity curve, analytics, A/B testing
└── settings/
    └── page.tsx        # Bot config, risk params, API keys
```

## Key Dashboard Components

### Metric Card
```tsx
function MetricCard({ title, value, change, positive }: {
  title: string; value: string; change?: string; positive?: boolean;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-sm text-gray-400">{title}</p>
      <p className="text-2xl font-bold text-white mt-1">{value}</p>
      {change && (
        <p className={`text-sm mt-1 ${positive ? 'text-green-400' : 'text-red-400'}`}>
          {positive ? '▲' : '▼'} {change}
        </p>
      )}
    </div>
  );
}
```

### Groq Decision Card
```tsx
function GroqDecisionCard({ decision }: { decision: GroqDecision }) {
  const colors = {
    BUY: 'border-green-500 bg-green-500/10',
    SELL: 'border-red-500 bg-red-500/10',
    WAIT: 'border-gray-500 bg-gray-500/10',
  };
  
  return (
    <div className={`border rounded-lg p-4 ${colors[decision.decision]}`}>
      <div className="flex justify-between items-center">
        <span className="text-xl font-bold">{decision.decision}</span>
        <ConfidenceBar value={decision.confidence} />
      </div>
      
      {/* Layer agreement indicator */}
      <div className="flex gap-1 mt-2">
        <LayerDot label="Mech" active={decision.layer1_agrees} />
        <LayerDot label="pgvec" active={decision.layer2_agrees} />
        <LayerDot label="Groq" active={decision.layer3_agrees} />
      </div>
      
      {/* Expandable reasoning */}
      <details className="mt-3">
        <summary className="text-sm text-gray-400 cursor-pointer">Reasoning</summary>
        <pre className="text-xs text-gray-300 mt-2 whitespace-pre-wrap">
          {decision.reasoning}
        </pre>
      </details>
      
      {/* Counter arguments (devil's advocate) */}
      {decision.counter_arguments?.length > 0 && (
        <div className="mt-2 text-xs text-yellow-400">
          ⚠️ {decision.counter_arguments.join(' | ')}
        </div>
      )}
    </div>
  );
}
```

### Equity Curve with Recharts
```tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area } from 'recharts';

function EquityCurve({ data }: { data: {date: string, balance: number, drawdown: number}[] }) {
  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={data}>
        <XAxis dataKey="date" stroke="#6b7280" />
        <YAxis stroke="#6b7280" />
        <Tooltip 
          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
          labelStyle={{ color: '#9ca3af' }}
        />
        <Line type="monotone" dataKey="balance" stroke="#22c55e" strokeWidth={2} dot={false} />
        <Area type="monotone" dataKey="drawdown" fill="#ef4444" fillOpacity={0.1} stroke="#ef4444" strokeWidth={1} />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

## Backend Socket.IO Server (FastAPI)

```python
import socketio
from fastapi import FastAPI

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

@sio.on('subscribe')
async def handle_subscribe(sid, data):
    symbol = data['symbol']
    timeframe = data['timeframe']
    await sio.enter_room(sid, f"{symbol}_{timeframe}")

@sio.on('unsubscribe')  
async def handle_unsubscribe(sid, data):
    await sio.leave_room(sid, f"{data['symbol']}_{data['timeframe']}")

# Call this when new candle data arrives
async def broadcast_candle(symbol: str, timeframe: str, candle: dict):
    await sio.emit('candle_update', candle, room=f"{symbol}_{timeframe}")

async def broadcast_tick(symbol: str, tick: dict):
    await sio.emit('tick', tick, room=f"{symbol}_ticks")

async def broadcast_trade(trade: dict):
    await sio.emit('trade_update', trade)  # Broadcast to all connected clients

async def broadcast_groq_decision(decision: dict):
    await sio.emit('groq_decision', decision)
```

## Design Guidelines

- **Color palette:** Dark background (#0f1118), cards (#111827), borders (#1f2937)
- **Green:** #22c55e (profits, wins, buy signals)
- **Red:** #ef4444 (losses, sell signals)
- **Yellow:** #eab308 (warnings, caution)
- **Blue:** #3b82f6 (neutral info, order blocks)
- **Font:** Use mono font for prices and numbers (`font-mono`)
- **Animations:** Minimal — flash green/red on new trade events, smooth chart updates
- **Responsive:** Desktop-first, minimum 1280px width for full experience
