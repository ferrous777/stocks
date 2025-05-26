// Test the mutual funds loading directly in browser console
// Copy and paste this into browser console to debug

console.log('=== Mutual Funds Debug Test ===');
console.log('Available symbols:', allSymbols);
console.log('Available dates:', allDates);
console.log('Fund symbols constant:', FUND_SYMBOLS);

// Find which fund symbols are available
const availableFundSymbols = FUND_SYMBOLS.filter(symbol => allSymbols.includes(symbol));
console.log('Available fund symbols:', availableFundSymbols);

// Test loading one symbol
async function testLoadSymbol() {
    const testSymbol = 'QQQ';
    const testDate = allDates[0] || '20250524';
    console.log(`Testing ${testSymbol} for date ${testDate}`);
    
    try {
        const response = await fetch(`/api/recommendations/${testSymbol}/${testDate}`);
        console.log('Response status:', response.status);
        if (response.ok) {
            const data = await response.json();
            console.log('Response data:', data);
        } else {
            console.log('Response not ok');
        }
    } catch (error) {
        console.error('Fetch error:', error);
    }
}

// Test the mutual funds elements
console.log('Mutual funds section element:', document.getElementById('mutualFundsSection'));
console.log('Mutual funds table body:', document.getElementById('mutualFundsTableBody'));
console.log('Mutual funds loading indicator:', document.getElementById('mutualFundsLoadingIndicator'));

// Call the test
testLoadSymbol();
