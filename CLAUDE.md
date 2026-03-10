# CLAUDE.md — BeraArb: Berachain Production Arbitrage Engine

This file provides AI assistants with the context needed to work effectively in this codebase.

---

## Project Overview

**BeraArb** is a production-grade, institutional-quality arbitrage trading system for **Berachain mainnet** (chain ID: 80094). It detects and executes price discrepancies across multiple DEXes using real on-chain data, atomic execution, and optional flash loan support.

Key distinguishing features:
- Zero mock data — all prices fetched live from contracts via Multicall3 batching
- Atomic buy+sell execution with pre-trade `eth_call` simulation
- ERC20 approval management with MAX_UINT256 allowance
- MEV protection via optional private RPC submission
- CSV + MongoDB dual trade logging

---

## Repository Layout

```
kode-arbitrage-emergent/
├── backend/                         # Python FastAPI backend
│   ├── server.py                    # Main app (2608 lines) — all routes, MongoDB, Web3
│   ├── requirements.txt             # 143 pinned Python packages
│   ├── core/
│   │   ├── constants.py             # All chain config, DEX addresses, safety limits
│   │   └── abis.py                  # Smart contract ABIs (ERC20, UniV2, UniV3, Multicall3)
│   ├── scanner/
│   │   └── multicall_scanner.py     # RealPriceScanner — Multicall3 batch RPC calls (524 lines)
│   ├── execution/
│   │   ├── atomic_executor.py       # AtomicArbExecutor + TradeLogger (526 lines)
│   │   ├── token_approval.py        # TokenApprovalManager (200 lines)
│   │   └── flash_loan.py            # FlashLoanExecutor (326 lines)
│   ├── logs/
│   │   └── trade_history.csv        # Append-only trade log (production audit trail)
│   ├── tests/
│   │   └── test_berachain_arb.py    # pytest unit tests (445 lines)
│   └── api/                         # API utilities
│
├── frontend/                        # React 19 frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.js         # Main trading UI (811 lines) — WebSocket + REST
│   │   │   ├── Analytics.js         # Trade history & charts (387 lines)
│   │   │   └── Settings.js          # Config UI (382 lines)
│   │   ├── components/ui/           # 40+ shadcn/ui components (Radix UI primitives)
│   │   ├── context/
│   │   │   └── WalletContext.js     # MetaMask / ethers.js integration
│   │   ├── hooks/                   # Custom React hooks
│   │   ├── lib/                     # Shared utilities (cn helper, etc.)
│   │   ├── App.js                   # Router + layout
│   │   └── index.js                 # Entry point
│   ├── package.json                 # Frontend dependencies (Yarn 1.22.22)
│   ├── jsconfig.json                # Path alias: @/* → src/*
│   ├── components.json              # shadcn/ui config (New York style)
│   ├── tailwind.config.js           # Dark-mode Tailwind theme
│   ├── craco.config.js              # CRA + Webpack overrides
│   └── postcss.config.js            # tailwindcss + autoprefixer
│
├── backend_test.py                  # Full API integration test suite
├── test_result.md                   # Agent-to-agent testing communication file (YAML)
├── memory/PRD.md                    # Product requirements document
├── design_guidelines.json           # UI/UX design system spec
└── README.md                        # Production deployment reference
```

---

## Technology Stack

### Backend
| Layer | Technology |
|-------|-----------|
| Framework | FastAPI 0.110.1 + Uvicorn 0.25.0 |
| Database | MongoDB via `motor` 3.3.1 (async) |
| Blockchain | web3.py 7.14.1, eth-account, eth-abi |
| Async I/O | asyncio, aiohttp 3.13.3 |
| Validation | Pydantic models (FastAPI built-in) |
| Testing | pytest 9.0.2 |
| Linting | black 26.x, flake8 7.x, mypy |

### Frontend
| Layer | Technology |
|-------|-----------|
| Core | React 19.0.0, React DOM |
| Router | react-router-dom 7.x |
| UI Components | Radix UI + shadcn/ui (New York style) |
| Styling | Tailwind CSS 3.4.x + framer-motion |
| Web3 | ethers.js 5.7.2 |
| Charts | recharts 3.x |
| Forms | react-hook-form 7.x + zod 3.x |
| Build | Create React App + Craco |
| Package Mgr | Yarn 1.22.22 |

---

## Environment Variables

### Backend (`backend/.env`)
```env
# Required
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
BERACHAIN_RPC="https://rpc.berachain.com"

# Optional — MEV protection
PRIVATE_RPC_URL=""          # Flashbots-style private RPC endpoint
USE_PRIVATE_RPC="true"      # Enable private submission

# Production gate
PRODUCTION_MODE="false"     # Set "true" for mainnet execution
```

### Frontend (`frontend/.env`)
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

**Never commit `.env` files, private keys, or credential files.**

---

## Key Configuration (`backend/core/constants.py`)

### Berachain Mainnet
- **Chain ID:** 80094
- **RPC:** `https://rpc.berachain.com`

### DEX Routers
| DEX | Address |
|-----|---------|
| Kodiak V2 | `0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022` |
| Kodiak V3 | `0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690` |
| BEX | `0x21e2C0AFd058A89FCf7caf3aEA3cB84Ae977B73D` |
| Honeypot | `0x1306D3c36eC7E38dd2c128fBe3097C2C2449af64` |

### Token Addresses
| Token | Address |
|-------|---------|
| WBERA | `0x6969696969696969696969696969696969696969` |
| HONEY | `0xFCBD14DC51f0A4d49d5E53C2E0950e0bC26d0Dce` |
| USDC | `0x549943e04f40284185054145c6E4e9568C1D3241` |

### Safety Limits
| Parameter | Value |
|-----------|-------|
| MAX_TRADE_SIZE_USD | $10,000 |
| MAX_SLIPPAGE_PERCENT | 5% |
| MAX_PRICE_IMPACT_PERCENT | 3% |
| MIN_PROFIT_THRESHOLD | $0.0005 |
| DEX_FEE_PERCENT | 0.3% |
| MAX_RETRY_ATTEMPTS | 3 |
| GAS_INCREASE_PER_RETRY | 20% |

---

## API Endpoints

### Scanning
- `GET /api/health` — RPC connectivity check
- `GET /api/opportunities` — Standard direct arbitrage
- `GET /api/triangular-opportunities` — Triangular routes
- `GET /api/multi-hop-opportunities` — Multi-hop (4+ tokens)
- `GET /api/production/scan-real` — Real on-chain scan via Multicall3

### Execution
- `POST /api/execute-trade` — Build trade transaction data
- `POST /api/production/execute-atomic` — Atomic execution with retries
- `POST /api/production/flash-arbitrage` — Flash loan execution

### Token Management
- `POST /api/production/approve-token` — ERC20 spending approval
- `GET /api/production/check-allowance` — Read current allowance

### Statistics
- `GET /api/engine/stats` — Full system statistics
- `GET /api/production/execution-stats` — Execution-specific stats
- `GET /api/production/trade-history` — CSV trade log query

---

## Development Workflows

### Running the Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env       # populate with real values
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Running the Frontend
```bash
cd frontend
yarn install
yarn start                 # dev server on :3000
yarn build                 # production build
```

### Running Backend Tests
```bash
cd backend
pytest tests/test_berachain_arb.py -v
```

### Running Integration Tests
```bash
python backend_test.py     # full API integration suite
```

---

## Code Conventions

### Python (Backend)
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants
- **Private methods:** prefixed with `_` (e.g., `_fetch_reserves`)
- **Type hints:** used throughout; run `mypy` to validate
- **Async:** all I/O is `async/await` — do not introduce blocking calls
- **Error handling:** `try/except` with structured logging; never silently swallow exceptions in execution paths
- **Retry pattern:** exponential backoff with gas price escalation — see `atomic_executor.py` for the canonical pattern
- **Pydantic models:** define request/response contracts in `server.py` at the top of the file

### JavaScript/React (Frontend)
- **Naming:** `camelCase` for variables/functions, `PascalCase` for components
- **Imports:** use `@/` path alias (maps to `src/`) — e.g., `import { Button } from "@/components/ui/button"`
- **State:** React hooks only (`useState`, `useEffect`, `useCallback`, `useMemo`)
- **Global state:** React Context API (`WalletContext`) — do not introduce Redux or Zustand without discussion
- **UI components:** always prefer components from `src/components/ui/` (shadcn/ui) before writing raw HTML
- **Styling:** Tailwind CSS utility classes; custom design tokens are defined in `tailwind.config.js`
- **Web3:** use `ethers.js` 5.x API — note this is v5 not v6 (different import style)
- **API calls:** use `axios` with `REACT_APP_BACKEND_URL` as base; fallback to REST when WebSocket is unavailable

### Design System
The project uses a Bloomberg Terminal + Cyberpunk aesthetic ("E1: The Anti-AI Designer"):
- **Typography:** Space Grotesk (headings), Inter (body), JetBrains Mono (data/numbers)
- **Colors:** Dark background, orange `#FF9F1C` (primary), cyan `#00F0FF` (accent)
- **Layout:** Bento Grid with 1px visible borders
- **Components:** Glassmorphism effects, no generic "SaaS blue"

---

## Testing Protocol

This project uses a dual-agent testing pattern documented in `test_result.md`:

1. **main_agent** implements features and updates `test_result.md` with YAML task status
2. **testing_agent** reads `test_result.md`, runs tests, and writes results back

### `test_result.md` Structure
```yaml
user_problem_statement: "..."
backend:
  - task: "Task name"
    implemented: true
    working: true
    file: "path/to/file.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "..."
frontend:
  - task: "..."
    ...
metadata:
  created_by: "main_agent"
  version: "1.0"
  test_sequence: 0
test_plan:
  current_focus: []
  stuck_tasks: []
agent_communication:
  - agent: "main"
    message: "..."
```

**Rules:**
- Always update `test_result.md` before calling the testing agent
- Set `needs_retesting: true` on tasks you modified
- Increment `stuck_count` when the same issue recurs
- Do NOT edit the protocol header section at the top of `test_result.md`

---

## Architecture Notes

### Execution Flow
```
Scanner (Multicall3 batch) → Opportunity detected
  → Pre-trade simulation (eth_call) → Profit verified
  → Token allowance check → Approve if needed
  → Execute buy on cheap DEX
  → Execute sell on expensive DEX
  → Log to CSV + MongoDB
```

### Price Scanner (`multicall_scanner.py`)
- Uses Multicall3 contract to batch multiple `getReserves` calls in a single RPC request
- Achieves <1s scan latency
- Caches pair addresses to avoid redundant lookups
- Fetches real-time reserves from LP pairs for accurate pricing

### Trade Logger (`atomic_executor.py`)
- All trades appended to `backend/logs/trade_history.csv`
- Fields: `timestamp`, `trade_id`, `pair`, `type`, `expected_profit_usd`, `actual_profit_usd`, `gas_used`, `status`
- MongoDB stores full structured records for dashboard queries

### Profit Verification
```
net_profit = expected_output - input_amount - gas_cost - dex_fees - slippage
```
Only execute if `net_profit > 0`. DEX fee default: 0.3% per swap.

---

## Security Requirements

- **Never commit private keys** — use `PRIVATE_KEY` env var only; it is backend-only
- **Never log private keys** — scrub before any log statement
- Validate all user inputs at API boundaries with Pydantic
- `PRODUCTION_MODE=false` is the safe default — require explicit opt-in for mainnet
- The execution wallet should hold minimal funds (just enough for gas + trade capital)
- Flash loan contract address must be verified on-chain before enabling flash arbitrage

---

## Common Pitfalls

1. **web3.py `encode_abi` compatibility** — use the pattern in `multicall_scanner.py` (known issue fixed in test iteration 2); avoid calling `encode_abi` directly on `ContractFunction` objects
2. **ethers.js v5 vs v6** — this project uses v5; imports are `ethers.utils.*`, `ethers.providers.*`, not the v6 flat namespace
3. **React 19** — concurrent features are available; be careful with `useEffect` cleanup for WebSocket connections (see `Dashboard.js`)
4. **Async MongoDB** — always use `await` with `motor`; never mix sync `pymongo` calls
5. **Craco + CRA** — webpack config is in `craco.config.js`, not `webpack.config.js`
6. **Path aliases** — `@/` only works in the frontend; do not use in backend Python code

---

## Git & Branch Conventions

- Default development branch: `master`
- Feature branches: `claude/<session-id>` (used by AI agents)
- Commit messages: descriptive imperative form, e.g. `Add multicall batching to price scanner`
- Git user configured as `emergent-agent-e1 <github@emergent.sh>` in `.gitconfig`
