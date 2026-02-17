import csv
import json

CSV_PATH = "/var/www/jhonk/dreriv/backend/candles_feb12.csv"
HTML_PATH = "/var/www/jhonk/dreriv/backend/view_chart.html"

try:
    with open(CSV_PATH, 'r') as f:
        csv_content = f.read()
        
    # Escape newlines for JS string
    csv_string = csv_content.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')
    
    with open(HTML_PATH, 'r') as f:
        html_content = f.read()
        
    # Inject call to loadData
    injection = f"""
    <script>
        const csvData = `{csv_string}`;
        // Wait for chart to init
        setTimeout(() => {{
            window.loadData(csvData);
        }}, 500);
    </script>
    </body>
    """
    
    new_html = html_content.replace('</body>', injection)
    
    with open(HTML_PATH, 'w') as f:
        f.write(new_html)
        
    print("Successfully injected CSV data into HTML.")
    
except Exception as e:
    print(f"Error: {e}")
