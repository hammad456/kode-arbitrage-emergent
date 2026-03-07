# BeraArb - Berachain Arbitrage Trading Engine

## Latest Enhancement (Jan 2026)

### Trading Engine Upgrades
1. **Real-time Opportunity Detection**
   - Batch RPC queries via parallel async tasks
   - Extended pairs: 9 trading pairs monitored
   - Scan cycle < 2 seconds with caching

2. **Automatic Arbitrage Execution**
   - AutoExecutionEngine class with cooldown
   - Profit calculation: net = raw - gas - slippage - price_impact
   - Execute only when net_profit > threshold

3. **Opportunity Ranking**
   - Score = 60% profit + 25% gas efficiency + 15% liquidity
   - Best opportunities shown first

4. **Liquidity & Price Impact Protection**
   - Pool reserves fetching via factory contract
   - MIN_LIQUIDITY_USD = $1,000 required
   - MAX_PRICE_IMPACT_PERCENT = 3%

5. **Honeypot Detection**
   - Simulates buy/sell via eth_call
   - Blacklists tokens with >30% tax
   - Endpoint: GET /api/honeypot/check/{token}

6. **Safety Limits**
   - MAX_TRADE_SIZE_USD: $10,000
   - MAX_SLIPPAGE_PERCENT: 5%
   - GAS_BUFFER_MULTIPLIER: 1.3x
   - TRADE_TIMEOUT_SECONDS: 120

### New Backend Features
- TradingCache: Pool data, token prices, gas caching
- AutoExecutionEngine: Automated trading with cooldown
- rank_opportunities(): Score-based sorting
- detect_honeypot(): Token safety verification
- get_pool_reserves(): Liquidity checks
- calculate_price_impact(): AMM formula calculation

### New API Endpoints
- GET /api/engine/stats - Cache and engine statistics
- GET /api/honeypot/check/{token} - Honeypot detection
- GET /api/pool/reserves - Pool liquidity info
- POST /api/auto-execute/enable - Enable auto-trading
- POST /api/auto-execute/disable - Disable auto-trading
- GET /api/auto-execute/status - Engine status

### Frontend Updates
- Immediate REST API data fetch on load
- WebSocket with 5-second timeout fallback
- Polling every 5 seconds when WS unavailable
- Connection status: Live/Polling/Connecting

## MOCKED Components
- BEX DEX: Uses Kodiak router with price variation simulation

## Prioritized Backlog

### P0 (Critical)
- [ ] Integrate actual BEX router contracts
- [ ] Add token approval flow
- [ ] Implement flash loans

### P1 (High Priority)  
- [ ] Multi-hop arbitrage (A→B→C→A)
- [ ] MEV protection (Flashbots)
- [ ] Telegram notifications

### P2 (Medium Priority)
- [ ] Historical profit charts
- [ ] Multiple wallet support
- [ ] Custom token pairs
