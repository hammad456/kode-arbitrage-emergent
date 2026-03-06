# BeraArb - Berachain Arbitrage Trading Bot

## Original Problem Statement
Build a sophisticated arbitrage trading application for Berachain that is safe and intelligently profitable. The app should have a complete frontend and backend that works in real-time. The application must calculate slippage, price impact, and gas fees.

## Architecture Update (Jan 2026)

### Backend Enhancements
- Enhanced POST /api/execute-trade endpoint with real blockchain execution
- Comprehensive safety checks implemented
- WebSocket real-time price streaming
- REST API fallback for polling

### Trade Execution Flow
1. Validate inputs (pair, wallet, amount)
2. Re-fetch latest pool prices from both DEXes
3. Estimate gas cost with 30% buffer
4. Calculate: net_profit = raw_profit - gas_cost - slippage_cost
5. Execute only if net_profit > minimum_threshold
6. Build transactions for both legs (buy + sell)
7. Return transaction data for wallet signing

### Safety Checks
- MAX_TRADE_SIZE_USD: $10,000
- MAX_GAS_LIMIT: 500,000
- MAX_SLIPPAGE_PERCENT: 5%
- PRICE_CHANGE_TOLERANCE: 2%
- GAS_BUFFER_MULTIPLIER: 1.3x
- Abort if profit < gas cost
- Abort if spread becomes negative
- Abort if slippage exceeds tolerance

## What's Been Implemented

### Backend (server.py)
- [x] POST /api/execute-trade with full verification
- [x] On-chain price revalidation before execution
- [x] Gas estimation with buffer
- [x] Slippage cost calculation
- [x] Safety checks (trade size, gas, profit threshold)
- [x] Build both buy and sell transactions
- [x] POST /api/execute-trade/confirm for recording results
- [x] WebSocket /ws/prices for real-time updates (3 second interval)

### Frontend (Dashboard.js)
- [x] WebSocket connection for real-time data
- [x] REST API polling fallback when WebSocket unavailable
- [x] Connection status indicator (Live/Polling/Connecting)
- [x] Trade execution modal with verification display
- [x] Wallet connection with MetaMask
- [x] executeTrade() function for signing transactions

### API Endpoints
- GET /api/health - Health check
- GET /api/opportunities - Arbitrage opportunities
- GET /api/gas-price - Current gas pricing
- POST /api/execute-trade - Execute arbitrage with safety checks
- POST /api/execute-trade/confirm - Confirm and record execution

## MOCKED Components
- BEX Router uses same address as Kodiak V2 (actual BEX contracts not public)

## Prioritized Backlog

### P0 (Critical)
- [ ] Integrate actual BEX router when addresses available
- [ ] Add token approval flow before swaps
- [ ] Implement flash loan integration

### P1 (High Priority)
- [ ] Multi-hop arbitrage paths
- [ ] MEV protection (Flashbots)
- [ ] Price alerts via notifications

### P2 (Medium Priority)
- [ ] Historical profit tracking
- [ ] Multiple wallet support
- [ ] Telegram bot integration

## Next Tasks
1. Get actual BEX contract addresses from Berachain team
2. Add ERC20 approve() calls before swaps
3. Implement flash loan for capital efficiency
