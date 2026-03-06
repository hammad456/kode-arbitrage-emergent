# BeraArb - Berachain Arbitrage Trading Bot

## Original Problem Statement
Build a sophisticated arbitrage trading application for Berachain that is safe and intelligently profitable. The app should have a complete frontend and backend that works in real-time. The application must calculate slippage, price impact, and gas fees.

## User Choices
- DEX: BEX and Kodiak Finance
- Wallet: MetaMask integration
- Data Source: Combination (DEX contracts + third-party API)
- Execution Mode: Semi-auto (user sets parameters, system executes)
- RPC: Public Berachain RPC

## User Personas
1. **DeFi Traders** - Users looking for arbitrage opportunities on Berachain
2. **Crypto Investors** - Users who want automated profit detection
3. **Institutional Traders** - Professional traders requiring detailed analytics

## Core Requirements (Static)
- Real-time arbitrage opportunity detection
- MetaMask wallet integration
- Slippage and price impact calculation
- Gas fee estimation and optimization
- Trade execution with confirmation
- Portfolio balance tracking
- Trade history and analytics

## Architecture
- **Frontend**: React 19 + Tailwind CSS + Shadcn/UI + Framer Motion + Recharts
- **Backend**: FastAPI + Web3.py + MongoDB + Motor
- **Blockchain**: Berachain Mainnet (Chain ID: 80094)
- **DEX Integrations**: Kodiak Finance (V2/V3 routers), BEX (simulated)

## What's Been Implemented (Jan 2026)

### Backend (server.py)
- [x] Web3 connection to Berachain mainnet RPC
- [x] Kodiak DEX router integration (V2: 0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022)
- [x] Real-time price fetching from DEX contracts
- [x] Arbitrage opportunity detection algorithm
- [x] Gas price fetching and estimation
- [x] CoinGecko API integration for USD prices
- [x] Trade transaction building endpoint
- [x] Wallet balances endpoint (native + ERC20)
- [x] Trade history and analytics endpoints
- [x] User settings persistence (MongoDB)
- [x] WebSocket endpoint for real-time updates

### Frontend
- [x] Dashboard with live arbitrage opportunities
- [x] MetaMask wallet connection (Berachain auto-switch)
- [x] Portfolio balances display
- [x] Gas price recommendations panel
- [x] Trade execution modal with slippage settings
- [x] Settings page (trading config, risk management, notifications)
- [x] Analytics page with charts and trade history
- [x] Dark theme "Orbital Command" design
- [x] Responsive design for mobile

### API Endpoints
- GET /api/health - Health check with RPC status
- GET /api/tokens - List of supported tokens
- GET /api/opportunities - Arbitrage opportunities
- GET /api/gas-price - Current gas price
- GET /api/wallet/{address}/balances - Wallet balances
- POST /api/trade/build - Build trade transaction
- POST /api/trade/record - Record trade history
- GET /api/trades/{wallet} - Trade history
- GET /api/analytics/{wallet} - Trading analytics
- GET/POST /api/settings/{wallet} - User settings

## MOCKED/Simulated Components
- **BEX DEX Quotes**: BEX contract addresses not publicly documented, so quotes are simulated with price variation from Kodiak

## Prioritized Backlog

### P0 (Critical)
- [ ] Implement actual BEX smart contract integration when addresses are available
- [ ] Add actual transaction signing via MetaMask
- [ ] Implement WebSocket real-time updates on frontend

### P1 (High Priority)
- [ ] Add multi-hop arbitrage paths (A→B→C→A)
- [ ] Implement flash loan integration for capital efficiency
- [ ] Add token approval flow before swaps
- [ ] Price alerts and notifications

### P2 (Medium Priority)
- [ ] Historical arbitrage opportunity charts
- [ ] Profit/loss reporting with export
- [ ] Multiple wallet support
- [ ] MEV protection integration

### P3 (Nice to Have)
- [ ] Telegram/Discord bot notifications
- [ ] Custom token pair configuration
- [ ] Portfolio performance benchmarking

## Next Tasks
1. Get actual BEX contract addresses and integrate
2. Implement MetaMask transaction signing flow
3. Add token approval checking and flow
4. Enable WebSocket for live dashboard updates
5. Add profit tracking after successful trades
