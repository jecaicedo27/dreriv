import pandas as pd
import numpy as np
import json
import os

CSV_PATH = "/var/www/jhonk/dreriv/backend/candles_feb12.csv"
OUTPUT_HTML = "/var/www/jhonk/dreriv/backend/app/static/replay_feb12.html"

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def generate_html():
    print(f"Reading {CSV_PATH}...")
    try:
        df = pd.read_csv(CSV_PATH)
        df['time'] = pd.to_datetime(df['time'])
        
        # Calculate Indicators
        df['ema21'] = calculate_ema(df['close'], 21)
        df['ema50'] = calculate_ema(df['close'], 50)
        
        # Prepare data for Lightweight Charts
        # Candles: { time, open, high, low, close }
        # Lines: { time, value }
        # Time must be UNIX timestamp (seconds)
        
        candles_data = []
        ema21_data = []
        ema50_data = []
        hurst_data = [] # Mock dataset for the dashboard look
        
        for _, row in df.iterrows():
            ts = int(row['time'].timestamp())
            
            candles_data.append({
                "time": ts,
                "open": row['open'],
                "high": row['high'],
                "low": row['low'],
                "close": row['close']
            })
            
            ema21_data.append({"time": ts, "value": row['ema21']})
            ema50_data.append({"time": ts, "value": row['ema50']})
            
            # Mock Hurst/Trend Strength for visualization
            spread = abs(row['ema21'] - row['ema50'])
            hurst_data.append({"time": ts, "value": spread * 1000}) # Scale up for visibility
            
        # HTML Template
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Historia Interactiva: 12 Feb</title>
    <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ background-color: #121212; color: #e0e0e0; font-family: sans-serif; margin: 0; padding: 20px; }}
        h1 {{ color: #00ffaa; }}
        .chart-container {{ height: 600px; width: 100%; border: 1px solid #333; }}
        .legend {{ position: absolute; top: 80px; left: 30px; z-index: 10; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>🕰️ Replay: 12 Febrero (Simulación)</h1>
    <p>Estos son los datos exactos que usó el bot. Puedes hacer zoom y scroll.</p>
    <div id="chart" class="chart-container"></div>
    <div class="legend">
        <span style="color: #00ffaa">EMA 21</span> | <span style="color: #ff4500">EMA 50</span>
    </div>

    <script>
        const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
            layout: {{ background: {{ color: '#121212' }}, textColor: '#DDD' }},
            grid: {{ vertLines: {{ color: '#222' }}, horzLines: {{ color: '#222' }} }},
            timeScale: {{ timeVisible: true, secondsVisible: false }},
            rightPriceScale: {{ borderColor: '#333' }},
        }});

        // Candle Series
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#00ffaa', downColor: '#ff4500', borderVisible: false,
            wickUpColor: '#00ffaa', wickDownColor: '#ff4500'
        }});
        candleSeries.setData({json.dumps(candles_data)});

        // EMA 21 (Green)
        const ema21Series = chart.addLineSeries({{ color: '#00ffaa', lineWidth: 2 }});
        ema21Series.setData({json.dumps(ema21_data)});

        // EMA 50 (Red)
        const ema50Series = chart.addLineSeries({{ color: '#ff4500', lineWidth: 2 }});
        ema50Series.setData({json.dumps(ema50_data)});

        // Fit Content
        chart.timeScale().fitContent();
    </script>
</body>
</html>
        """
        
        with open(OUTPUT_HTML, 'w') as f:
            f.write(html)
            
        print(f"Generated {OUTPUT_HTML}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    generate_html()
