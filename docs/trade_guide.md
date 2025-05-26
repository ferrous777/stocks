# Trade Guide: Example Implementation

## GOOGL Long Trade Example

### Trade Details
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

### Step-by-Step Implementation

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

### Key Points to Remember
- Always verify current market prices before placing orders
- Use limit orders to ensure good entry prices
- Place stop loss immediately after entry fills
- Consider scaling out at predetermined levels
- Monitor the position and adjust stops as needed 