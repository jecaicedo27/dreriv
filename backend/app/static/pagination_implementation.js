// Pagination helper function
function changePage(direction) {
    const totalPages = Math.ceil(totalTrades / tradesPerPage);
    const newPage = currentPage + direction;

    if (newPage >= 1 && newPage <= totalPages) {
        currentPage = newPage;
        fetchRecentTrades();
    }
}

// Note: To implement pagination in dashboard.html:
// 1. Variables already added at line 367-369:
//    - let currentPage = 1;
//    - const tradesPerPage = 50;
//    - let totalTrades = 0;
//
// 2. Modify fetchRecentTrades() at line 801:
//    - Change limit=15 to limit=1000 to fetch all trades
//    - Add pagination slicing logic
//    - Add pagination UI controls (Previous/Next buttons)
//    - Display "Showing X-Y of Z trades"
//
// 3. Add changePage() function after fetchRecentTrades()

// Implementation: Replace line 803 with:
// const response = await fetch(`${API_BASE}/trades?limit=1000`);
// const allTrades = await response.json();
// totalTrades = allTrades.length;
// const totalPages = Math.ceil(totalTrades / tradesPerPage);
// const startIndex = (currentPage - 1) * tradesPerPage;
// const endIndex = startIndex + tradesPerPage;
// const trades = allTrades.slice(startIndex, endIndex);
