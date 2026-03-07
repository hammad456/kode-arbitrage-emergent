# BeraArb - Berachain Production Arbitrage Engine

## Overview
Production-ready, institutional-grade arbitrage system for Berachain mainnet. Features real on-chain data integration, atomic execution, flash loan support, and MEV protection.

## Architecture

```
/app/backend/
├── server.py              # Main FastAPI application
├── core/
│   ├── constants.py       # Production constants & addresses
│   └── abis.py           # Contract ABIs
├── scanner/
│   └── multicall_scanner.py  # Real price scanner using Multicall3
├── execution/
│   ├── token_approval.py     # ERC20 approval management
│   ├── atomic_executor.py    # Atomic trade execution
│   └── flash_loan.py         # Flash swap/loan support
├── logs/
│   └── trade_history.csv     # Production trade logs
└── .env                   # Environment configuration
```

## Key Features

### 1. Real On-Chain Data
- **No mock data** - All prices fetched from actual DEX contracts
- **Multicall3 batching** - Efficient batch RPC calls (<1s latency)
- **Real-time reserves** - Live liquidity tracking from LP pairs

### 2. Token Approval Flow
- Automatic allowance checking before swaps
- `MAX_UINT256` approval to avoid repeated transactions
- Retry logic with exponential backoff

### 3. Atomic Execution
- Buy + Sell bundled as atomic operation
- Pre-trade simulation via `eth_call`
- Strict profit verification: `net_profit > gas + fees + slippage`

### 4. Flash Loan Support
- Capital-efficient arbitrage using borrowed liquidity
- Uniswap V2 style flash swaps
- Repay within single transaction

### 5. MEV Protection
- Private RPC submission (Flashbots-style)
- Front-running prevention
- Configurable via `PRIVATE_RPC_URL`

### 6. Reliability & Logging
- Max 3 retries with exponential backoff
- +20% gas price increase per retry
- CSV logging of all trade outcomes

## Safety Limits

| Parameter | Value |
|-----------|-------|
| MAX_TRADE_SIZE_USD | $10,000 |
| MAX_SLIPPAGE_PERCENT | 5% |
| MAX_PRICE_IMPACT_PERCENT | 3% |
| MIN_PROFIT_THRESHOLD | $0.0005 |
| DEX_FEE_PERCENT | 0.3% |
| MAX_RETRY_ATTEMPTS | 3 |
| GAS_INCREASE_PER_RETRY | 20% |

## DEX Integrations

| DEX | Router Address | Status |
|-----|----------------|--------|
| Kodiak V2 | `0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022` | ✅ Production |
| Kodiak V3 | `0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690` | ✅ Production |
| BEX | `0x21e2C0AFd058A89FCf7caf3aEA3cB84Ae977B73D` | ✅ Production |
| Honeypot | `0x1306D3c36eC7E38dd2c128fBe3097C2C2449af64` | ✅ Production |

## API Endpoints

### Scanning
- `GET /api/opportunities` - Standard arbitrage opportunities
- `GET /api/triangular-opportunities` - Triangular arbitrage routes
- `GET /api/multi-hop-opportunities` - Multi-hop routes (4+ tokens)
- `GET /api/production/scan-real` - Production scan with real data

### Execution
- `POST /api/execute-trade` - Build trade transactions
- `POST /api/production/execute-atomic` - Atomic execution with retries
- `POST /api/production/flash-arbitrage` - Flash loan execution

### Token Management
- `POST /api/production/approve-token` - Approve token spending
- `GET /api/production/check-allowance` - Check current allowance

### Statistics
- `GET /api/engine/stats` - Full engine statistics
- `GET /api/production/execution-stats` - Production execution stats
- `GET /api/production/trade-history` - Trade history from CSV

## Environment Configuration

```env
# Required
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
BERACHAIN_RPC="https://rpc.berachain.com"

# Optional - MEV Protection
PRIVATE_RPC_URL=""           # Flashbots-style private RPC
USE_PRIVATE_RPC="true"       # Enable private submission

# Production Mode
PRODUCTION_MODE="false"      # Set to "true" for mainnet
```

## Local Setup

1. Install dependencies:
```bash
cd /app/backend
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. Start the server:
```bash
uvicorn server:app --host 0.0.0.0 --port 8001
```

## Production Deployment

### Pre-deployment Checklist
- [ ] Set `PRODUCTION_MODE=true`
- [ ] Configure `PRIVATE_RPC_URL` for MEV protection
- [ ] Fund wallet with BERA for gas
- [ ] Test token approvals on testnet first
- [ ] Verify flash arbitrage contract deployment

### Execution Flow
1. Scanner detects arbitrage opportunity
2. Verify profit via `eth_call` simulation
3. Check token allowance, approve if needed
4. Execute buy on cheaper DEX
5. Execute sell on expensive DEX
6. Log trade outcome to CSV/MongoDB

### Profit Verification Formula
```
net_profit = expected_output - input_amount - gas_cost - dex_fees - slippage
```
- Execute only if `net_profit > 0`
- DEX fee: 0.3% per swap (configurable)
- Slippage: 0.5% default tolerance

## Flash Loan Deployment

The flash loan executor provides transaction data for a FlashArbitrage contract. To enable flash loans:

1. Deploy the `FlashArbitrage` contract (see `flash_loan.py` for bytecode)
2. Set the contract address in the executor
3. Use `/api/production/flash-arbitrage` endpoint

## Trade Logging

All trades are logged to `/app/backend/logs/trade_history.csv`:

| Field | Description |
|-------|-------------|
| timestamp | ISO timestamp |
| trade_id | Unique trade ID |
| pair | Token pair (e.g., WBERA/USDC) |
| type | direct/triangular/multi_hop |
| expected_profit_usd | Pre-trade profit estimate |
| actual_profit_usd | Post-trade actual profit |
| gas_used | Total gas consumed |
| status | success/failed |

## Monitoring

### Key Metrics
- Scan time (target: <1s)
- Success rate
- Total profit
- Gas efficiency

### Health Check
```bash
curl http://localhost:8001/api/health
```

## Security Notes

⚠️ **IMPORTANT**: 
- Never commit private keys to version control
- Use environment variables for sensitive data
- The `private_key` parameter in execution endpoints is for backend-only use
- Consider using a dedicated execution wallet with limited funds

## License

MIT License - See LICENSE file for details.
