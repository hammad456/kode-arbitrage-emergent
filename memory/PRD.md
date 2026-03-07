# BeraArb - Berachain Arbitrage Trading Engine

## Latest Optimization (Jan 2026)

### Scanner Enhancements
1. **In-Memory Price Matrix**
   - PriceMatrix class tracks all token prices
   - Enables fast path discovery for triangular arb
   - Auto-updates on each scan cycle

2. **Optimized Direct Arbitrage**
   - 10 high-liquidity pairs monitored
   - Parallel async quotes for all pairs
   - Scan cycle: ~1-2 seconds

3. **Risk-Adjusted Ranking**
   - Score = profit (50%) + spread (15%) + gas_efficiency (15%) + liquidity (10%) + risk_adjusted (10%)
   - Risk factors: gas/profit ratio, price impact, liquidity
   - Opportunities sorted by highest score

4. **Triangular Arbitrage Detection**
   - find_triangular_arbitrage() function available
   - Detects A → B → C → A cycles
   - Endpoint: GET /api/triangular-opportunities
   - Disabled in main scan for performance (use dedicated endpoint)

5. **Safety Filters**
   - MIN_LIQUIDITY_USD: $1,000 minimum
   - MAX_PRICE_IMPACT_PERCENT: 3% maximum
   - Skips pools failing checks

### New Components
- **PriceMatrix**: In-memory token price tracking
- **rank_opportunities()**: Risk-adjusted sorting
- **find_triangular_arbitrage()**: Multi-hop detection
- **/api/triangular-opportunities**: Dedicated triangular endpoint

### Performance Metrics
- Scan time: ~1-2 seconds
- Pairs monitored: 10 high-liquidity
- Price updates: Real-time via price matrix

### Safety Limits
| Parameter | Value |
|-----------|-------|
| MAX_TRADE_SIZE_USD | $10,000 |
| MAX_SLIPPAGE_PERCENT | 5% |
| MAX_PRICE_IMPACT_PERCENT | 3% |
| MIN_PROFIT_THRESHOLD | $0.01 |
| MIN_LIQUIDITY_USD | $1,000 |

## MOCKED Components
- BEX DEX: Simulated with price variation from Kodiak

## Prioritized Backlog

### P0 (Critical)
- [ ] Integrate actual BEX router contracts
- [ ] Add token approval flow
- [ ] Background worker for triangular scanning

### P1 (High Priority)
- [ ] Flash loan integration
- [ ] MEV protection (Flashbots)
- [ ] Telegram notifications

### P2 (Medium Priority)
- [ ] Historical profit charts
- [ ] Multiple wallet support
- [ ] Custom token pairs
