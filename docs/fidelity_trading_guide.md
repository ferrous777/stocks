# Using Trading Recommendations in Fidelity

This guide explains how to implement the trading recommendations from our analysis tool in Fidelity's trading platform.

## Understanding the Recommendations Table

Each row contains:
- **Symbol**: The stock ticker symbol
- **Action**: BUY, SELL, or EXIT
- **Type**: LONG, SHORT, or CLOSE position
- **Confidence**: How strong the signal is (higher is better)
- **Entry Price**: The target price to enter the trade
- **Stop Loss**: The price at which to cut losses (1.5-2% from entry)
- **Take Profit**: The target price to take profits (4.5-12% from entry)
- **Position Size**: Recommended number of shares (based on 2% account risk)
- **Order Type**: How to place the order (typically LIMIT)
- **Risk/Reward**: Ratio of potential profit to potential loss (typically 3.0-6.0)

## Understanding Trade Types

### BUY (LONG) Trades
- **When**: The system predicts the stock price will rise
- **Entry**: Buy shares at the Entry Price
- **Profit**: Made when stock rises above Entry Price
- **Loss**: Taken if stock falls to Stop Loss
- **Exit**: Either at Take Profit or Stop Loss level
- **Example**: Buy 100 shares at $100, stop at $98, target $106

### SELL (SHORT) Trades
- **When**: The system predicts the stock price will fall
- **Entry**: Sell/short shares at the Entry Price
- **Profit**: Made when stock falls below Entry Price
- **Loss**: Taken if stock rises to Stop Loss
- **Exit**: Either at Take Profit or Stop Loss level
- **Note**: Requires margin account and borrowable shares
- **Example**: Short 100 shares at $100, stop at $102, target $94

### EXIT (CLOSE) Trades
- **When**: The system suggests closing existing positions
- **Why**: Could indicate:
  * Trend reversal
  * Technical resistance/support reached
  * Risk level increased
  * Better opportunities elsewhere
- **Action**: Close any existing position (long or short)
- **Timing**: Use limit orders near current price for best execution
- **Note**: Consider partial exits at 50% of target profit

### Trade Type Selection
The system selects trade types based on:
1. Trend direction and strength
2. Support and resistance levels
3. Volume patterns
4. Technical indicator signals
5. Overall market conditions

### Risk Considerations by Type
- **LONG**: Maximum risk is Entry Price - Stop Loss
- **SHORT**: Theoretical unlimited risk, practically limited by stop loss
- **EXIT**: Risk of missing further moves, balanced against protecting profits

Remember:
- Always use the recommended Position Size
- Place stops immediately after entry
- Consider scaling out of profitable trades
- Don't force trades - wait for clear signals

## Trade Parameters

### Risk Management
- Stop Loss: 1.5-2% from entry price
- Take Profit: 4.5-12% from entry price (varies with trend strength)
- Position Size: Calculated to risk 2% of account per trade
- Risk/Reward: Minimum 3:1, can reach 6:1 in strong trends

### Entry Rules
1. Only take trades with confidence > 80%
2. Use limit orders at the specified Entry Price
3. Always place stop loss orders immediately after entry
4. Set take profit orders as limit orders

## Placing Orders in Fidelity

### For BUY (LONG) Recommendations:
1. Log into Fidelity and click "Trade"
2. Enter the Symbol
3. Select "Buy"
4. For Order Type, select "Limit"
5. Enter the Position Size from the recommendations
6. Set the Limit Price to the Entry Price
7. Under "Time in Force", select "Day + Extended Hours"
8. Review and submit the order

### For SELL (SHORT) Recommendations:
1. Follow the same steps as above but select "Sell" instead of "Buy"
2. If you don't own the shares, select "Short Sale" (requires margin approval)

### For EXIT (CLOSE) Recommendations:
1. If you have an existing position, close it using a limit order
2. Set the limit price near the current market price to ensure execution

## Setting Up Stop Loss Orders

After your entry order fills:
1. Click "Trade"
2. Select "Conditional"
3. Choose "Stop Loss"
4. Enter the Stop Loss price from the recommendations
5. Set this as "GTC" (Good Till Canceled)

## Setting Up Take Profit Orders

Similarly for profit targets:
1. Click "Trade"
2. Select "Conditional"
3. Choose "Limit"
4. Enter the Take Profit price from the recommendations
5. Set this as "GTC"

## Best Practices

1. **Risk Management**:
   - Never risk more than 2% of your account on any single trade
   - Use the Position Size as a maximum, not a requirement
   - Always set stop losses to protect your capital

2. **Order Execution**:
   - Use limit orders to ensure you get your desired entry price
   - Consider breaking larger orders into smaller lots
   - Be patient with entry prices - don't chase the stock

3. **Position Monitoring**:
   - Set price alerts in Fidelity for your stops and targets
   - Monitor high-confidence trades more closely
   - Consider scaling out of profitable positions at 50% of target

4. **Documentation**:
   - Keep a trading journal with your entries and exits
   - Note which strategies generated the signals
   - Track your success rate with different confidence levels

## Important Notes

1. **Market Orders**: Avoid using market orders - always use limit orders to control your entry and exit prices.

2. **Confidence Levels**: Consider only taking trades with confidence levels above 80%.

3. **Price Validity**: Recommendations are based on recent prices - verify current market prices before trading.

4. **Risk Warning**: These are algorithmic recommendations. Always:
   - Do your own research
   - Follow your trading plan
   - Never trade with money you can't afford to lose
   - Consider consulting with a financial advisor

## Example Trade

For a BUY recommendation like GOOGL:

Symbol: GOOGL
Action: BUY
Type: LONG
Confidence: 100.0%
Entry Price: $204.02
Stop Loss: $197.78 (-3.1%)
Take Profit: $222.38 (+9.0%)
Position Size: 320 shares
Order Type: LIMIT
Risk/Reward: 2.9

### Step-by-Step Implementation:

1. **Place Entry Order**:
   - Open Fidelity trading platform
   - Select GOOGL
   - Click "Buy"
   - Order Type: LIMIT
   - Quantity: 320 shares
   - Limit Price: $204.02
   - Time in Force: Day + Extended Hours
   - Total Position Value: $65,286.40

2. **Place Stop Loss Order** (after entry fills):
   - Order Type: Stop Loss
   - Quantity: 320 shares
   - Stop Price: $197.78
   - Risk per Share: $6.24
   - Total Risk: $1,996.80 (about 2% of $100k account)

3. **Place Take Profit Order**:
   - Order Type: Limit
   - Quantity: 320 shares
   - Limit Price: $222.38
   - Profit per Share: $18.36
   - Total Potential Profit: $5,875.20

4. **Optional Scale-Out Orders**:
   - First Target (50%):
     * Quantity: 160 shares
     * Limit Price: $213.20 (halfway to target)
   - Second Target (50%):
     * Quantity: 160 shares
     * Limit Price: $222.38 (full target)

5. **Position Monitoring**:
   - Set price alerts at:
     * Stop Loss: $197.78
     * First Target: $213.20
     * Final Target: $222.38
   - Monitor support levels below entry
   - Watch for increasing volume on moves up

6. **Trade Management**:
   - High confidence signal (100%)
   - Strong risk/reward ratio (2.9)
   - Consider trailing stop after 5% profit
   - Maximum loss limited to 2% of account

Remember to always verify current market conditions before placing any trades.

## Understanding Risk/Reward

The Risk/Reward ratio is a critical metric that compares potential profit to potential loss:

### Calculation
- **Risk** = Entry Price - Stop Loss (for longs)
- **Risk** = Stop Loss - Entry Price (for shorts)
- **Reward** = Take Profit - Entry Price (for longs)
- **Reward** = Entry Price - Take Profit (for shorts)
- **Risk/Reward Ratio** = Potential Reward / Potential Risk

### Example Calculations
For a LONG trade (GOOGL):
- Entry: $204.02
- Stop: $197.78
- Target: $222.38
- Risk = $204.02 - $197.78 = $6.24
- Reward = $222.38 - $204.02 = $18.36
- R/R Ratio = $18.36 / $6.24 = 2.9

For a SHORT trade (MSFT):
- Entry: $415.06
- Stop: $427.76
- Target: $377.70
- Risk = $427.76 - $415.06 = $12.70
- Reward = $415.06 - $377.70 = $37.36
- R/R Ratio = $37.36 / $12.70 = 2.9

### Interpretation
- Ratio > 3.0: Excellent trade setup
- Ratio 2.0-3.0: Good trade setup
- Ratio < 2.0: Consider skipping trade

### Key Points
- Higher ratios provide better profit potential for the risk taken
- System targets ratios between 3.0-6.0 for optimal trades
- Actual results may vary due to market conditions
- Consider scaling out to lock in profits at predetermined levels
- Ratios adjust based on trend strength and volatility 