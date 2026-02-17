#!/usr/bin/env python3
"""
Script to add pagination to the trades table in dashboard.html
Based on API documentation: /trades endpoint supports 'limit' parameter
"""

# Read the current dashboard.html
with open('/var/www/jhonk/dreriv/backend/app/static/dashboard.html', 'r') as f:
    content = f.read()

# Find and replace the fetchRecentTrades function
old_function = '''        async function fetchRecentTrades() {
            try {
                const response = await fetch(`${API_BASE}/trades?limit=15`);
                const trades = await response.json();

                const container = document.getElementById('tradesContent');

                if (trades.length === 0) {
                    container.innerHTML = '<div class="loading">No trades yet. Bot is accumulating data...</div>';
                    return;
                }

                const table = `
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Direction</th>
                                <th>Entry</th>
                                <th>Exit</th>
                                <th>Stake</th>
                                <th>Outcome</th>
                                <th>P&L</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${trades.map(trade => `
                                <tr>
                                    <td>${formatTime(trade.entry_time)}</td>
                                    <td><span class="direction-${trade.direction.toLowerCase()}">${trade.direction}</span></td>
                                    <td>${trade.entry_price.toFixed(2)}</td>
                                    <td>${trade.exit_price ? trade.exit_price.toFixed(2) : '-'}</td>
                                    <td>$${trade.stake.toFixed(2)}</td>
                                    <td><span class="outcome-${trade.outcome.toLowerCase()}">${trade.outcome}</span></td>
                                    <td class="${trade.pnl >= 0 ? 'positive' : 'negative'}">$${trade.pnl.toFixed(2)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;

                container.innerHTML = table;

            } catch (error) {
                console.error('Error fetching trades:', error);
                document.getElementById('tradesContent').innerHTML = '<div class="loading">Error loading trades</div>';
            }
        }'''

new_function = '''        async function fetchRecentTrades() {
            try {
                // Fetch more trades with pagination support
                const response = await fetch(`${API_BASE}/trades?limit=1000`);
                const allTrades = await response.json();
                
                totalTrades = allTrades.length;
                const totalPages = Math.ceil(totalTrades / tradesPerPage);
                
                // Calculate pagination slice
                const startIndex = (currentPage - 1) * tradesPerPage;
                const endIndex = startIndex + tradesPerPage;
                const trades = allTrades.slice(startIndex, endIndex);

                const container = document.getElementById('tradesContent');

                if (allTrades.length === 0) {
                    container.innerHTML = '<div class="loading">No trades yet. Bot is accumulating data...</div>';
                    return;
                }

                const table = `
                    <div style="margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="color: #9ca3af; font-size: 0.9rem;">
                            Showing ${startIndex + 1}-${Math.min(endIndex, totalTrades)} of ${totalTrades} trades
                        </div>
                        <div style="display: flex; gap: 10px;">
                            <button 
                           onclick="changePage(-1)" 
                                ${currentPage === 1 ? 'disabled' : ''}
                                style="padding: 8px 16px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; color: #fff; cursor: ${currentPage === 1 ? 'not-allowed' : 'pointer'}; opacity: ${currentPage === 1 ? '0.5' : '1'}; transition: all 0.3s; font-family: Inter, sans-serif;"
                            >
                                ← Previous
                            </button>
                            <span style="padding: 8px 16px; color: #fff; align-self: center; font-size: 0.9rem;">
                                Page ${currentPage} of ${totalPages}
                            </span>
                            <button 
                                onclick="changePage(1)" 
                                ${currentPage >= totalPages ? 'disabled' : ''}
                                style="padding: 8px 16px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; color: #fff; cursor: ${currentPage >= totalPages ? 'not-allowed' : 'pointer'}; opacity: ${currentPage >= totalPages ? '0.5' : '1'}; transition: all 0.3s; font-family: Inter, sans-serif;"
                            >
                                Next →
                            </button>
                        </div>
                    </div>
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Direction</th>
                                <th>Entry</th>
                                <th>Exit</th>
                                <th>Stake</th>
                                <th>Outcome</th>
                                <th>P&L</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${trades.map(trade => `
                                <tr>
                                    <td>${formatTime(trade.entry_time)}</td>
                                    <td><span class="direction-${trade.direction.toLowerCase()}">${trade.direction}</span></td>
                                    <td>${trade.entry_price.toFixed(2)}</td>
                                    <td>${trade.exit_price ? trade.exit_price.toFixed(2) : '-'}</td>
                                    <td>$${trade.stake.toFixed(2)}</td>
                                    <td><span class="outcome-${trade.outcome.toLowerCase()}">${trade.outcome}</span></td>
                                    <td class="${trade.pnl >= 0 ? 'positive' : 'negative'}">$${trade.pnl.toFixed(2)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;

                container.innerHTML = table;

            } catch (error) {
                console.error('Error fetching trades:', error);
                document.getElementById('tradesContent').innerHTML = '<div class="loading">Error loading trades</div>';
            }
        }
        
        function changePage(direction) {
            const totalPages = Math.ceil(totalTrades / tradesPerPage);
            const newPage = currentPage + direction;
            
            if (newPage >= 1 && newPage <= totalPages) {
                currentPage = newPage;
                fetchRecentTrades();
            }
        }'''

# Replace the function
if old_function in content:
    content = content.replace(old_function, new_function)
    print("✅ Successfully replaced fetchRecentTrades function")
else:
    print("❌ Could not find exact function match")
    print("Trying alternative approach...")
    # Save for manual review
    with open('/tmp/dashboard_new_function.txt', 'w') as f:
        f.write(new_function)
    print("Saved new function to /tmp/dashboard_new_function.txt for manual review")
    exit(1)

# Write back
with open('/var/www/jhonk/dreriv/backend/app/static/dashboard.html', 'w') as f:
    f.write(content)
    
print("✅ Dashboard updated with pagination support")
print("Pagination settings:")
print("  - Trades per page: 50")
print("  - API limit: 1000 trades")
print("  - Navigation: Previous/Next buttons")
