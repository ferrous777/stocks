// Manual test in browser console - copy and paste this
console.clear();
console.log('=== COMPREHENSIVE MUTUAL FUNDS DEBUG ===');

// 1. Check basic variables
console.log('1. Variables check:');
console.log('allSymbols exists:', typeof allSymbols !== 'undefined');
console.log('allDates exists:', typeof allDates !== 'undefined');
console.log('FUND_SYMBOLS exists:', typeof FUND_SYMBOLS !== 'undefined');

if (typeof allSymbols !== 'undefined') {
    console.log('allSymbols:', allSymbols);
}
if (typeof allDates !== 'undefined') {
    console.log('allDates:', allDates);
}
if (typeof FUND_SYMBOLS !== 'undefined') {
    console.log('FUND_SYMBOLS:', FUND_SYMBOLS);
}

// 2. Check DOM elements
console.log('\n2. DOM elements check:');
const mutualFundsSection = document.getElementById('mutualFundsSection');
const tableBody = document.getElementById('mutualFundsTableBody');
const loadingIndicator = document.getElementById('mutualFundsLoadingIndicator');
const noDataMessage = document.getElementById('mutualFundsNoDataMessage');

console.log('mutualFundsSection:', mutualFundsSection ? 'FOUND' : 'NOT FOUND');
console.log('tableBody:', tableBody ? 'FOUND' : 'NOT FOUND');
console.log('loadingIndicator:', loadingIndicator ? 'FOUND' : 'NOT FOUND');
console.log('noDataMessage:', noDataMessage ? 'FOUND' : 'NOT FOUND');

// 3. Check functions
console.log('\n3. Functions check:');
console.log('loadMutualFundsData exists:', typeof loadMutualFundsData === 'function');
console.log('loadFundSymbolData exists:', typeof loadFundSymbolData === 'function');
console.log('renderMutualFundsTable exists:', typeof renderMutualFundsTable === 'function');

// 4. Test API manually
console.log('\n4. Testing API manually:');
async function testAPI() {
    try {
        const response = await fetch('/api/recommendations/QQQ/20250524');
        console.log('QQQ API response status:', response.status);
        if (response.ok) {
            const data = await response.json();
            console.log('QQQ API data:', data);
        }
    } catch (error) {
        console.error('API test error:', error);
    }
}

// 5. Manual function call
console.log('\n5. Manually calling loadMutualFundsData:');
if (typeof loadMutualFundsData === 'function') {
    loadMutualFundsData();
} else {
    console.error('loadMutualFundsData function not found!');
}

// Run the API test
testAPI();
