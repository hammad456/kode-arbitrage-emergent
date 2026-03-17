from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import sys
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
import asyncio
import json
from web3 import Web3
from decimal import Decimal
import httpx
import time

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Add backend to path for module imports
sys.path.insert(0, str(ROOT_DIR))

# Import production modules
from core.constants import (
    PRIVATE_RPC_URL, DEX_FEE_PERCENT, MAX_RETRY_ATTEMPTS,
    RETRY_BASE_DELAY, GAS_INCREASE_PER_RETRY, MAX_UINT256
)
from execution.token_approval import TokenApprovalManager
from execution.atomic_executor import AtomicArbExecutor, TradeLogger
from execution.flash_loan import FlashLoanExecutor
from scanner.multicall_scanner import RealPriceScanner

# MongoDB connection - fallback to mongomock if real MongoDB unavailable
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'bearb_db')
try:
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=3000)
    db = client[db_name]
    logging.info(f"MongoDB connecting to: {mongo_url}")
except Exception as _mongo_err:
    logging.warning(f"MongoDB unavailable ({_mongo_err}), using in-memory mock")
    try:
        from mongomock_motor import AsyncMongoMockClient
        client = AsyncMongoMockClient()
        db = client[db_name]
        logging.info("Using mongomock-motor in-memory database")
    except ImportError:
        logging.error("mongomock-motor not installed; DB operations will fail")
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]

# Berachain Configuration
BERACHAIN_RPC = os.environ.get('BERACHAIN_RPC', 'https://rpc.berachain.com')
CHAIN_ID = 80094

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(BERACHAIN_RPC))

# Initialize Private RPC for MEV Protection (if configured)
private_rpc_url = os.environ.get('PRIVATE_RPC_URL', '')
private_w3 = Web3(Web3.HTTPProvider(private_rpc_url)) if private_rpc_url else None

# Initialize Production Execution Components
token_approval_manager = TokenApprovalManager(w3)
atomic_executor = AtomicArbExecutor(w3, private_w3)
flash_loan_executor = FlashLoanExecutor(w3)
real_price_scanner = RealPriceScanner(w3)
trade_logger = TradeLogger()

# Production Mode Flag
PRODUCTION_MODE = os.environ.get('PRODUCTION_MODE', 'false').lower() == 'true'
USE_PRIVATE_RPC = os.environ.get('USE_PRIVATE_RPC', 'true').lower() == 'true'

# Safety limits - Production ready (Micro-Arbitrage Optimized)
MAX_TRADE_SIZE_USD = 10000
MAX_GAS_LIMIT = 500000
TRADE_TIMEOUT_SECONDS = 120
MIN_PROFIT_THRESHOLD = 0.0005  # $0.0005 minimum for micro-arb
MIN_SPREAD_THRESHOLD = 0.05   # 0.05% spread threshold (micro-arbitrage)
MAX_SLIPPAGE_PERCENT = 5.0
PRICE_CHANGE_TOLERANCE = 2.0
GAS_BUFFER_MULTIPLIER = 1.3
MAX_PRICE_IMPACT_PERCENT = 3.0
MIN_LIQUIDITY_USD = 200  # Lower threshold for micro-arb
HONEYPOT_CHECK_ENABLED = True
AUTO_EXECUTE_ENABLED = False

# Multi-hop arbitrage config
MAX_HOP_COUNT = 4  # Max tokens in multi-hop route
MULTI_HOP_GAS_PER_SWAP = 150000

# Logging config
ARB_LOG_ENABLED = True

# DEX Contract Addresses (Berachain Mainnet - Production)
KODIAK_V3_ROUTER = "0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690"
KODIAK_V2_ROUTER = "0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022"
KODIAK_V2_FACTORY = "0x5C346464d33F90bABaf70dB6388507CC889C1070"
KODIAK_QUOTER = "0x644C8D6E501f7C994B74F5ceA96abe65d0BA662B"
# BEX (Berachain Exchange) - Official CrocSwap Router
BEX_ROUTER = "0x21e2C0AFd058A89FCf7caf3aEA3cB84Ae977B73D"
BEX_QUERY = "0x8685CE9Db06D40CBa73e3d09e6868FE476B5dC89"
# Honeypot Router
HONEYPOT_ROUTER = "0x1306D3c36eC7E38dd2c128fBe3097C2C2449af64"
WBERA = "0x6969696969696969696969696969696969696969"

# Common tokens on Berachain
TOKENS = {
    "WBERA": {"address": "0x6969696969696969696969696969696969696969", "decimals": 18, "symbol": "WBERA"},
    "HONEY": {"address": "0xFCBD14DC51f0A4d49d5E53C2E0950e0bC26d0Dce", "decimals": 18, "symbol": "HONEY"},
    "USDC": {"address": "0x549943e04f40284185054145c6E4e9568C1D3241", "decimals": 6, "symbol": "USDC"},
    "USDT": {"address": "0x779Ded0c9e1022225f8E0630b35a9b54bE713736", "decimals": 6, "symbol": "USDT"},
    "WETH": {"address": "0x2F6F07CDcf3588944Bf4C42aC74ff24bF56e7590", "decimals": 18, "symbol": "WETH"},
    "WBTC": {"address": "0x0555E30da8f98308EdB960aa94C0Db47230d2B9c", "decimals": 8, "symbol": "WBTC"},
}

# Uniswap V2 Router ABI (for Kodiak V2)
ROUTER_V2_ABI = json.loads('''[
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsIn","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"}
]''')

# ERC20 ABI
ERC20_ABI = json.loads('''[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
]''')

# Multicall ABI
MULTICALL_ABI = json.loads('''[
    {"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"struct Multicall3.Call[]","name":"calls","type":"tuple[]"}],"name":"aggregate","outputs":[{"internalType":"uint256","name":"blockNumber","type":"uint256"},{"internalType":"bytes[]","name":"returnData","type":"bytes[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"components":[{"internalType":"address","name":"target","type":"address"},{"internalType":"bool","name":"allowFailure","type":"bool"},{"internalType":"bytes","name":"callData","type":"bytes"}],"internalType":"struct Multicall3.Call3[]","name":"calls","type":"tuple[]"}],"name":"aggregate3","outputs":[{"components":[{"internalType":"bool","name":"success","type":"bool"},{"internalType":"bytes","name":"returnData","type":"bytes"}],"internalType":"struct Multicall3.Result[]","name":"returnData","type":"tuple[]"}],"stateMutability":"view","type":"function"}
]''')
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Pair ABI for reserves
PAIR_ABI = json.loads('''[
    {"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"_reserve0","type":"uint112"},{"name":"_reserve1","type":"uint112"},{"name":"_blockTimestampLast","type":"uint32"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"}
]''')

# Factory ABI
FACTORY_ABI = json.loads('''[
    {"constant":true,"inputs":[{"name":"tokenA","type":"address"},{"name":"tokenB","type":"address"}],"name":"getPair","outputs":[{"name":"pair","type":"address"}],"type":"function"}
]''')

# BEX CrocSwap Query ABI
BEX_QUERY_ABI = json.loads('''[
    {"inputs":[{"internalType":"address","name":"base","type":"address"},{"internalType":"address","name":"quote","type":"address"},{"internalType":"uint256","name":"poolIdx","type":"uint256"}],"name":"queryPrice","outputs":[{"internalType":"uint128","name":"","type":"uint128"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"address","name":"base","type":"address"},{"internalType":"address","name":"quote","type":"address"},{"internalType":"uint256","name":"poolIdx","type":"uint256"},{"internalType":"bool","name":"isBuy","type":"bool"},{"internalType":"bool","name":"inBaseQty","type":"bool"},{"internalType":"uint128","name":"qty","type":"uint128"},{"internalType":"uint16","name":"tip","type":"uint16"},{"internalType":"uint128","name":"limitPrice","type":"uint128"},{"internalType":"uint128","name":"minOut","type":"uint128"},{"internalType":"uint8","name":"reserveFlags","type":"uint8"}],"name":"previewSwap","outputs":[{"internalType":"int128","name":"baseFlow","type":"int128"},{"internalType":"int128","name":"quoteFlow","type":"int128"}],"stateMutability":"view","type":"function"}
]''')

# BEX CrocSwap constants
BEX_POOL_IDX = 36000
BEX_MIN_SQRT_PRICE = 65536
BEX_MAX_UINT128 = (2**128) - 1

app = FastAPI(title="Berachain Arbitrage Bot")
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pydantic Models
class TokenInfo(BaseModel):
    address: str
    symbol: str
    decimals: int
    balance: Optional[str] = "0"

class PriceQuote(BaseModel):
    dex: str
    token_in: str
    token_out: str
    amount_in: str
    amount_out: str
    price: float
    price_impact: float
    gas_estimate: int

class ArbitrageOpportunity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_pair: str
    buy_dex: str
    sell_dex: str
    buy_price: float
    sell_price: float
    spread_percent: float
    potential_profit_usd: float
    gas_cost_usd: float
    net_profit_usd: float
    amount_in: str
    expected_out: str
    token_in_address: str = ""
    token_out_address: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "active"

class TradeRequest(BaseModel):
    opportunity_id: str
    wallet_address: str
    slippage_tolerance: float = 0.5
    gas_price_gwei: Optional[float] = None

class ExecuteTradeRequest(BaseModel):
    pair: str
    buy_dex: str
    sell_dex: str
    amount: str
    slippage: float = 0.5
    wallet_address: str
    signed_tx: Optional[str] = None
    private_key: Optional[str] = None  # For backend execution (optional)
    
class TradeExecutionResult(BaseModel):
    success: bool
    tx_hash: Optional[str] = None
    gas_used: Optional[int] = None
    estimated_profit: Optional[float] = None
    actual_profit: Optional[float] = None
    error: Optional[str] = None
    buy_tx_hash: Optional[str] = None
    sell_tx_hash: Optional[str] = None

class TradeHistory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wallet_address: str
    token_pair: str
    buy_dex: str
    sell_dex: str
    amount_in: str
    amount_out: str
    profit_usd: float
    gas_used: int
    tx_hash: str
    status: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class SettingsUpdate(BaseModel):
    min_profit_threshold: float = 0.5
    max_slippage: float = 1.0
    gas_multiplier: float = 1.2
    auto_execute: bool = False

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# ============== ENHANCED ARB LOGGER ==============
class ArbLogger:
    """Comprehensive logging and metrics for arbitrage operations"""
    def __init__(self):
        self.opportunities_found = 0
        self.trades_skipped = 0
        self.trades_executed = 0
        self.trades_failed = 0
        self.total_profit = 0.0
        self.last_opportunities: List[Dict] = []
        self.skip_reasons: Dict[str, int] = {}
        self.profit_by_pair: Dict[str, float] = {}
        self.scans_count = 0
        self.scan_times: List[float] = []
        self.micro_arbs_found = 0  # 0.05%-0.2% spread
        self.triangular_found = 0
        self.multi_hop_found = 0
        self.simulations_passed = 0
        self.simulations_failed = 0
        self.last_scan_time = 0.0
        self.start_time = time.time()
    
    def log_opportunity(self, opp: Dict):
        if not ARB_LOG_ENABLED:
            return
        self.opportunities_found += 1
        spread = opp.get('spread_percent', 0)
        opp_type = opp.get('type', 'direct')
        
        # Track micro-arbitrage
        if 0.05 <= spread <= 0.2:
            self.micro_arbs_found += 1
        
        # Track by type
        if opp_type == 'triangular':
            self.triangular_found += 1
        elif opp_type == 'multi_hop':
            self.multi_hop_found += 1
        
        logger.info(f"[ARB] Found: {opp.get('token_pair')} | type={opp_type} | spread={spread:.3f}% | net=${opp.get('net_profit_usd', 0):.4f}")
    
    def log_skip(self, pair: str, reason: str):
        if not ARB_LOG_ENABLED:
            return
        self.trades_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1
        logger.debug(f"[ARB] Skip: {pair} | {reason}")
    
    def log_simulation(self, success: bool, reason: str = ""):
        if success:
            self.simulations_passed += 1
        else:
            self.simulations_failed += 1
            logger.debug(f"[ARB] Simulation failed: {reason}")
    
    def log_execution(self, opp: Dict, success: bool, tx_hash: str = None, actual_profit: float = 0):
        if not ARB_LOG_ENABLED:
            return
        
        pair = opp.get('token_pair', 'UNKNOWN')
        
        if success:
            self.trades_executed += 1
            profit = actual_profit if actual_profit else opp.get("net_profit_usd", 0)
            self.total_profit += profit
            self.profit_by_pair[pair] = self.profit_by_pair.get(pair, 0) + profit
            logger.info(f"[ARB] EXECUTED: {pair} | profit=${profit:.4f} | tx={tx_hash[:16] if tx_hash else 'N/A'}...")
        else:
            self.trades_failed += 1
            logger.warning(f"[ARB] FAILED: {pair}")
    
    def log_scan(self, scan_time: float, opps_count: int):
        self.scans_count += 1
        self.last_scan_time = scan_time
        self.scan_times.append(scan_time)
        # Keep only last 100 scan times
        if len(self.scan_times) > 100:
            self.scan_times = self.scan_times[-100:]
    
    def get_stats(self) -> Dict:
        uptime = time.time() - self.start_time
        avg_scan = sum(self.scan_times) / len(self.scan_times) if self.scan_times else 0
        
        return {
            "opportunities_found": self.opportunities_found,
            "micro_arbs_found": self.micro_arbs_found,
            "triangular_found": self.triangular_found,
            "multi_hop_found": self.multi_hop_found,
            "trades_skipped": self.trades_skipped,
            "trades_executed": self.trades_executed,
            "trades_failed": self.trades_failed,
            "total_profit": round(self.total_profit, 4),
            "profit_by_pair": self.profit_by_pair,
            "skip_reasons": dict(sorted(self.skip_reasons.items(), key=lambda x: x[1], reverse=True)[:10]),
            "simulations": {
                "passed": self.simulations_passed,
                "failed": self.simulations_failed,
                "success_rate": round(self.simulations_passed / (self.simulations_passed + self.simulations_failed) * 100, 2) if (self.simulations_passed + self.simulations_failed) > 0 else 0
            },
            "scanning": {
                "total_scans": self.scans_count,
                "last_scan_time_ms": round(self.last_scan_time * 1000, 2),
                "avg_scan_time_ms": round(avg_scan * 1000, 2),
                "uptime_hours": round(uptime / 3600, 2)
            }
        }

arb_logger = ArbLogger()

# ============== ADVANCED CACHING SYSTEM ==============
class TradingCache:
    """High-performance in-memory cache for maximum speed"""
    def __init__(self):
        self.pool_reserves: Dict[str, Dict] = {}
        self.token_prices: Dict[str, float] = {"bera": 5.0}
        self.gas_price: int = 50 * 10**9
        self.pair_addresses: Dict[str, str] = {}
        self.token_metadata: Dict[str, Dict] = {}
        self.honeypot_blacklist: set = set()
        self.last_update: Dict[str, float] = {}
        self.quotes_cache: Dict[str, Dict] = {}  # Cache recent quotes
        self.lock = asyncio.Lock()
    
    def is_stale(self, key: str, max_age: float = 5.0) -> bool:
        return time.time() - self.last_update.get(key, 0) > max_age
    
    async def update_gas_price(self):
        try:
            self.gas_price = w3.eth.gas_price
            self.last_update["gas"] = time.time()
        except Exception:
            pass
    
    async def update_token_price(self, token_id: str, price: float):
        async with self.lock:
            self.token_prices[token_id] = price
            self.last_update[f"price_{token_id}"] = time.time()
    
    def get_pair_key(self, token_a: str, token_b: str) -> str:
        return f"{min(token_a, token_b)}_{max(token_a, token_b)}"
    
    def cache_quote(self, pair_key: str, quote_data: Dict):
        self.quotes_cache[pair_key] = {**quote_data, "cached_at": time.time()}
        self.last_update[f"quote_{pair_key}"] = time.time()
    
    def get_cached_quote(self, pair_key: str, max_age: float = 2.0) -> Optional[Dict]:
        cached = self.quotes_cache.get(pair_key)
        if cached and time.time() - cached.get("cached_at", 0) < max_age:
            return cached
        return None

cache = TradingCache()

# ============== AUTO EXECUTION ENGINE ==============
class AutoExecutionEngine:
    """Automated arbitrage execution engine"""
    def __init__(self):
        self.enabled = False
        self.wallet_address: Optional[str] = None
        self.min_profit: float = 0.5
        self.max_slippage: float = 1.0
        self.running = False
        self.last_execution: float = 0
        self.cooldown: float = 10  # seconds between executions
        self.execution_count: int = 0
        self.total_profit: float = 0
    
    async def should_execute(self, opportunity: Dict) -> bool:
        if not self.enabled or not self.wallet_address:
            return False
        if time.time() - self.last_execution < self.cooldown:
            return False
        if opportunity.get("net_profit_usd", 0) < self.min_profit:
            return False
        return True

auto_engine = AutoExecutionEngine()

# Cache for prices
price_cache = {
    "bera_price": 5.0,
    "last_update": 0
}

async def get_token_price_coingecko(token_id: str) -> float:
    """Fetch token price from CoinGecko API with caching"""
    global price_cache
    current_time = time.time()
    
    if current_time - price_cache["last_update"] < 60:  # Cache for 60 seconds
        if token_id == "berachain-bera":
            return price_cache["bera_price"]
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": token_id, "vs_currencies": "usd"}
            )
            if response.status_code == 200:
                data = response.json()
                price = data.get(token_id, {}).get("usd", 0)
                if token_id == "berachain-bera" and price > 0:
                    price_cache["bera_price"] = price
                    price_cache["last_update"] = current_time
                return price
    except Exception as e:
        logger.error(f"CoinGecko price fetch error: {e}")
    
    return price_cache.get("bera_price", 5.0) if token_id == "berachain-bera" else 0

# ============== MULTICALL BATCH QUERIES ==============
async def multicall_batch_quotes(calls_data: List[Dict]) -> List[Optional[int]]:
    """Execute batch RPC calls using Multicall3 for efficiency"""
    if not calls_data:
        return []
    
    try:
        multicall = w3.eth.contract(address=Web3.to_checksum_address(MULTICALL3_ADDRESS), abi=MULTICALL_ABI)
        
        # Build calls array
        calls = []
        for call in calls_data:
            router = w3.eth.contract(address=Web3.to_checksum_address(call["router"]), abi=ROUTER_V2_ABI)
            calldata = router.encode_abi('getAmountsOut', args=[call["amount_in"], call["path"]])
            calls.append((call["router"], True, calldata))  # allowFailure=True
        
        # Execute multicall
        results = multicall.functions.aggregate3(calls).call()
        
        # Parse results
        parsed = []
        for i, result in enumerate(results):
            if result[0]:  # success
                try:
                    decoded = w3.codec.decode(['uint256[]'], result[1])
                    parsed.append(decoded[0][-1])  # Last amount (output)
                except Exception:
                    parsed.append(None)
            else:
                parsed.append(None)
        
        return parsed
    except Exception as e:
        logger.error(f"Multicall error: {e}")
        return [None] * len(calls_data)

# ============== POOL LIQUIDITY CHECK ==============
async def get_pool_reserves(token_a: str, token_b: str, factory: str = KODIAK_V2_FACTORY) -> Optional[Dict]:
    """Fetch pool reserves for liquidity check"""
    pair_key = cache.get_pair_key(token_a, token_b)
    
    # Check cache
    if pair_key in cache.pool_reserves and not cache.is_stale(f"reserves_{pair_key}", 10):
        return cache.pool_reserves[pair_key]
    
    try:
        # Get pair address
        if pair_key not in cache.pair_addresses:
            factory_contract = w3.eth.contract(address=Web3.to_checksum_address(factory), abi=FACTORY_ABI)
            pair_address = factory_contract.functions.getPair(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b)
            ).call()
            
            if pair_address == "0x0000000000000000000000000000000000000000":
                return None
            cache.pair_addresses[pair_key] = pair_address
        
        pair_address = cache.pair_addresses[pair_key]
        pair_contract = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)
        
        reserves = pair_contract.functions.getReserves().call()
        token0 = pair_contract.functions.token0().call()
        
        # Determine reserve order
        if token0.lower() == token_a.lower():
            reserve_a, reserve_b = reserves[0], reserves[1]
        else:
            reserve_a, reserve_b = reserves[1], reserves[0]
        
        result = {
            "pair_address": pair_address,
            "reserve_a": reserve_a,
            "reserve_b": reserve_b,
            "token_a": token_a,
            "token_b": token_b,
            "timestamp": time.time()
        }
        
        cache.pool_reserves[pair_key] = result
        cache.last_update[f"reserves_{pair_key}"] = time.time()
        
        return result
    except Exception as e:
        logger.debug(f"Get reserves error: {e}")
        return None

def check_liquidity_sufficient(reserves: Dict, amount_in: int, token_in: str, min_liquidity: int = 0) -> Dict:
    """Check if pool has sufficient liquidity for trade"""
    if not reserves:
        return {"sufficient": False, "reason": "No reserves data"}
    
    if token_in.lower() == reserves["token_a"].lower():
        reserve_out = reserves["reserve_b"]
    else:
        reserve_out = reserves["reserve_a"]
    
    if reserve_out < min_liquidity:
        return {"sufficient": False, "reason": f"Insufficient liquidity: {reserve_out}"}
    
    # Check if trade would take more than 10% of pool
    if amount_in > reserve_out * 0.1:
        return {"sufficient": False, "reason": "Trade too large for pool"}
    
    return {"sufficient": True, "reserve_out": reserve_out}

# ============== PRICE IMPACT CALCULATION ==============
def calculate_price_impact(amount_in: int, reserve_in: int, reserve_out: int) -> float:
    """Calculate actual price impact using constant product formula"""
    if reserve_in == 0 or reserve_out == 0:
        return 100.0
    
    # Constant product: x * y = k
    # After swap: (x + dx) * (y - dy) = k
    # dy = y * dx / (x + dx)
    amount_out = (reserve_out * amount_in) / (reserve_in + amount_in)
    
    # Spot price vs execution price
    spot_price = reserve_out / reserve_in
    exec_price = amount_out / amount_in if amount_in > 0 else 0
    
    price_impact = ((spot_price - exec_price) / spot_price) * 100 if spot_price > 0 else 100
    return max(0, price_impact)

# ============== HONEYPOT DETECTION ==============
async def detect_honeypot(token_address: str, router_address: str, test_amount: int = 10**18) -> Dict:
    """Detect honeypot tokens by simulating buy and sell"""
    if token_address.lower() in cache.honeypot_blacklist:
        return {"is_honeypot": True, "reason": "Blacklisted"}
    
    if not HONEYPOT_CHECK_ENABLED:
        return {"is_honeypot": False, "reason": "Check disabled"}
    
    try:
        router = w3.eth.contract(address=Web3.to_checksum_address(router_address), abi=ROUTER_V2_ABI)
        
        # Simulate buy: WBERA -> Token
        buy_path = [Web3.to_checksum_address(WBERA), Web3.to_checksum_address(token_address)]
        
        try:
            buy_result = router.functions.getAmountsOut(test_amount, buy_path).call()
            token_received = buy_result[-1]
        except Exception as e:
            return {"is_honeypot": True, "reason": f"Buy simulation failed: {e}"}
        
        if token_received == 0:
            cache.honeypot_blacklist.add(token_address.lower())
            return {"is_honeypot": True, "reason": "Zero output on buy"}
        
        # Simulate sell: Token -> WBERA
        sell_path = [Web3.to_checksum_address(token_address), Web3.to_checksum_address(WBERA)]
        
        try:
            sell_result = router.functions.getAmountsOut(token_received, sell_path).call()
            wbera_received = sell_result[-1]
        except Exception as e:
            cache.honeypot_blacklist.add(token_address.lower())
            return {"is_honeypot": True, "reason": f"Sell simulation failed: {e}"}
        
        if wbera_received == 0:
            cache.honeypot_blacklist.add(token_address.lower())
            return {"is_honeypot": True, "reason": "Zero output on sell"}
        
        # Check for excessive tax (> 30% loss is suspicious)
        loss_percent = ((test_amount - wbera_received) / test_amount) * 100
        if loss_percent > 30:
            cache.honeypot_blacklist.add(token_address.lower())
            return {"is_honeypot": True, "reason": f"Excessive tax: {loss_percent:.1f}%", "tax_percent": loss_percent}
        
        return {"is_honeypot": False, "tax_percent": loss_percent}
        
    except Exception as e:
        logger.error(f"Honeypot check error: {e}")
        return {"is_honeypot": False, "reason": f"Check failed: {e}"}

# ============== OPPORTUNITY RANKING ==============
def rank_opportunities(opportunities: List[Dict]) -> List[Dict]:
    """
    Advanced risk-adjusted ranking for opportunities.
    Optimized for micro-arbitrage (0.05-0.2% spreads).
    
    Scoring weights:
    - Net profit (35%): Higher is better
    - Risk score (25%): Lower is better (gas/profit ratio, price impact)
    - Liquidity (20%): Higher is better
    - Spread quality (10%): Optimal range 0.1-1%
    - Execution probability (10%): Based on pool stability
    """
    if not opportunities:
        return []
    
    # Get max values for normalization
    max_profit = max(o.get("net_profit_usd", 0) for o in opportunities) or 0.001
    max_liquidity = max(o.get("liquidity_usd", 1) for o in opportunities) or 1
    
    for opp in opportunities:
        net_profit = opp.get("net_profit_usd", 0)
        liquidity = opp.get("liquidity_usd", 1)
        price_impact = opp.get("price_impact", 5)
        spread = opp.get("spread_percent", 0)
        gas_cost = opp.get("gas_cost_usd", 0.01)
        opp_type = opp.get("type", "direct")
        
        # 1. Profit score (normalized 0-1)
        profit_norm = min(net_profit / max_profit, 1) if max_profit > 0 else 0
        
        # 2. Risk score (lower is better, so invert for ranking)
        gas_risk = min(gas_cost / (net_profit + 0.0001), 1)  # Gas as % of profit
        impact_risk = min(price_impact / MAX_PRICE_IMPACT_PERCENT, 1)
        type_risk = 0.1 if opp_type == "direct" else 0.3 if opp_type == "triangular" else 0.5
        risk_score = (gas_risk * 0.4) + (impact_risk * 0.4) + (type_risk * 0.2)
        risk_norm = 1 - risk_score  # Invert: lower risk = higher score
        
        # 3. Liquidity score (normalized 0-1)
        liquidity_norm = min(liquidity / max_liquidity, 1)
        
        # 4. Spread quality score (optimal: 0.1-1%, penalize extremes)
        if 0.1 <= spread <= 1.0:
            spread_score = 1.0
        elif spread < 0.1:
            spread_score = spread / 0.1  # Linear ramp up
        else:
            spread_score = max(0, 1 - (spread - 1) / 5)  # Penalize high spreads
        
        # 5. Execution probability (simple heuristic)
        exec_prob = 0.9 if opp_type == "direct" else 0.7 if opp_type == "triangular" else 0.5
        
        # Final ranking score (weighted sum)
        opp["rank_score"] = (
            (profit_norm * 0.35) +
            (risk_norm * 0.25) +
            (liquidity_norm * 0.20) +
            (spread_score * 0.10) +
            (exec_prob * 0.10)
        )
        
        # Store individual metrics for display
        opp["risk_score"] = round(risk_score, 4)
        opp["risk_adjusted_profit"] = round(net_profit * (1 - risk_score), 4)
        opp["execution_probability"] = round(exec_prob * 100, 1)
    
    return sorted(opportunities, key=lambda x: x.get("rank_score", 0), reverse=True)

# ============== IN-MEMORY PRICE MATRIX ==============
class PriceMatrix:
    """In-memory price matrix for fast arbitrage detection"""
    def __init__(self):
        self.prices: Dict[str, Dict[str, float]] = {}  # prices[tokenA][tokenB] = rate
        self.amounts: Dict[str, Dict[str, int]] = {}   # amounts[tokenA][tokenB] = amount_out
        self.last_update: float = 0
        self.lock = asyncio.Lock()
    
    async def update(self, token_a: str, token_b: str, price: float, amount_out: int):
        async with self.lock:
            if token_a not in self.prices:
                self.prices[token_a] = {}
                self.amounts[token_a] = {}
            self.prices[token_a][token_b] = price
            self.amounts[token_a][token_b] = amount_out
            self.last_update = time.time()
    
    def get_price(self, token_a: str, token_b: str) -> Optional[float]:
        return self.prices.get(token_a, {}).get(token_b)
    
    def get_all_tokens(self) -> List[str]:
        return list(self.prices.keys())
    
    def find_triangular_paths(self, start_token: str) -> List[List[str]]:
        """Find all triangular arbitrage paths starting from a token"""
        paths = []
        tokens = self.get_all_tokens()
        
        for mid_token in tokens:
            if mid_token == start_token:
                continue
            if start_token not in self.prices or mid_token not in self.prices.get(start_token, {}):
                continue
            
            for end_token in tokens:
                if end_token == start_token or end_token == mid_token:
                    continue
                
                # Check if full path exists: start -> mid -> end -> start
                if (mid_token in self.prices and 
                    end_token in self.prices.get(mid_token, {}) and
                    start_token in self.prices.get(end_token, {})):
                    paths.append([start_token, mid_token, end_token, start_token])
        
        return paths
    
    def find_multi_hop_paths(self, start_token: str, max_hops: int = 4) -> List[List[str]]:
        """
        Find multi-hop arbitrage paths (4+ tokens) using DFS.
        Path: start -> A -> B -> C -> ... -> start
        """
        paths = []
        tokens = self.get_all_tokens()
        
        def dfs(current: str, path: List[str], visited: set):
            if len(path) > max_hops:
                return
            
            # Check if we can return to start
            if len(path) >= 3 and start_token in self.prices.get(current, {}):
                paths.append(path + [start_token])
            
            # Continue exploring
            for next_token in tokens:
                if next_token in visited or next_token == start_token:
                    continue
                if next_token in self.prices.get(current, {}):
                    dfs(next_token, path + [next_token], visited | {next_token})
        
        # Start DFS from each neighbor of start_token
        for first_hop in tokens:
            if first_hop != start_token and first_hop in self.prices.get(start_token, {}):
                dfs(first_hop, [start_token, first_hop], {first_hop})
        
        return paths
    
    def calculate_path_profit(self, path: List[str]) -> Optional[float]:
        """Calculate theoretical profit for a given path using cached prices"""
        if len(path) < 3:
            return None
        
        # Start with 1 unit, multiply through path
        current_value = 1.0
        for i in range(len(path) - 1):
            price = self.get_price(path[i], path[i + 1])
            if price is None or price == 0:
                return None
            current_value *= price
        
        # Profit percentage: (final - initial) / initial * 100
        return (current_value - 1) * 100

price_matrix = PriceMatrix()

# ============== ON-CHAIN SIMULATION ==============
async def simulate_swap_onchain(router: str, amount_in: int, path: List[str]) -> Optional[int]:
    """
    Simulate swap using eth_call to verify profit exists before execution.
    Returns expected output amount or None if simulation fails.
    """
    try:
        router_contract = w3.eth.contract(address=Web3.to_checksum_address(router), abi=ROUTER_V2_ABI)
        checksummed_path = [Web3.to_checksum_address(addr) for addr in path]
        
        # Use call() which simulates without state change
        result = router_contract.functions.getAmountsOut(amount_in, checksummed_path).call()
        return result[-1] if result else None
    except Exception as e:
        logger.debug(f"Simulation failed: {e}")
        return None

async def verify_profit_onchain(opp: Dict) -> Dict:
    """
    Verify arbitrage profit still exists using on-chain simulation.
    Returns verification result with updated amounts.
    """
    try:
        pair = opp.get("token_pair", "")
        tokens = pair.split("/") if "/" in pair else pair.split(" → ")[:2]
        
        if len(tokens) < 2:
            return {"valid": False, "reason": "Invalid pair format"}
        
        token_in = TOKENS.get(tokens[0])
        token_out = TOKENS.get(tokens[1])
        
        if not token_in or not token_out:
            return {"valid": False, "reason": "Unknown tokens"}
        
        amount_in = int(opp.get("amount_in", 0))
        if amount_in == 0:
            return {"valid": False, "reason": "Invalid amount"}
        
        # Simulate buy
        buy_path = [token_in["address"], token_out["address"]]
        buy_output = await simulate_swap_onchain(KODIAK_V2_ROUTER, amount_in, buy_path)
        
        if not buy_output:
            return {"valid": False, "reason": "Buy simulation failed"}
        
        # Simulate sell
        sell_path = [token_out["address"], token_in["address"]]
        sell_output = await simulate_swap_onchain(KODIAK_V2_ROUTER, buy_output, sell_path)
        
        if not sell_output:
            return {"valid": False, "reason": "Sell simulation failed"}
        
        # Calculate actual profit
        raw_profit = sell_output - amount_in
        raw_profit_decimal = raw_profit / (10 ** token_in["decimals"])
        
        # Get current gas cost
        gas_price = cache.gas_price
        bera_price = cache.token_prices.get("bera", 5.0)
        gas_cost_usd = (300000 * gas_price / 10**18) * bera_price
        
        token_price = bera_price if tokens[0] == "WBERA" else 1.0
        net_profit_usd = (raw_profit_decimal * token_price) - gas_cost_usd
        
        # Safety: reject if final profit <= 0
        if net_profit_usd <= 0:
            arb_logger.log_skip(pair, f"Simulation shows loss: ${net_profit_usd:.4f}")
            return {"valid": False, "reason": f"Profit <= 0 after simulation: ${net_profit_usd:.4f}"}
        
        return {
            "valid": True,
            "simulated_buy_output": buy_output,
            "simulated_sell_output": sell_output,
            "simulated_profit_usd": net_profit_usd,
            "gas_cost_usd": gas_cost_usd
        }
    except Exception as e:
        return {"valid": False, "reason": str(e)}

# ============== TRIANGULAR ARBITRAGE DETECTION ==============
async def find_triangular_arbitrage(base_token: str = "WBERA", amount_in: int = None) -> List[Dict]:
    """
    Detect triangular arbitrage opportunities: A -> B -> C -> A
    Returns profitable cycles with net profit calculation
    """
    opportunities = []
    base_info = TOKENS.get(base_token)
    if not base_info:
        return []
    
    if amount_in is None:
        amount_in = int(100 * (10 ** base_info["decimals"]))
    
    gas_price = cache.gas_price
    bera_price = cache.token_prices.get("bera", 5.0)
    
    # Get all triangular paths from price matrix
    paths = price_matrix.find_triangular_paths(base_token)
    
    for path in paths:
        try:
            # Simulate the full cycle
            current_amount = amount_in
            total_gas = 0
            leg_details = []
            
            for i in range(len(path) - 1):
                token_from = path[i]
                token_to = path[i + 1]
                
                from_info = TOKENS.get(token_from)
                to_info = TOKENS.get(token_to)
                
                if not from_info or not to_info:
                    break
                
                # Get quote for this leg
                quote = await get_dex_quote_fast(
                    KODIAK_V2_ROUTER,
                    from_info["address"],
                    to_info["address"],
                    current_amount,
                    "Kodiak V2"
                )
                
                if not quote:
                    break
                
                leg_details.append({
                    "from": token_from,
                    "to": token_to,
                    "amount_in": current_amount,
                    "amount_out": int(quote.amount_out),
                    "price": quote.price
                })
                
                current_amount = int(quote.amount_out)
                total_gas += quote.gas_estimate
            
            if len(leg_details) != 3:
                continue
            
            # Calculate profit
            final_amount = current_amount
            raw_profit = final_amount - amount_in
            raw_profit_decimal = raw_profit / (10 ** base_info["decimals"])
            
            # Convert to USD
            token_price = bera_price if base_token == "WBERA" else 1.0
            raw_profit_usd = raw_profit_decimal * token_price
            
            # Calculate costs
            gas_cost_usd = (total_gas * gas_price / 10**18) * bera_price
            slippage_cost_usd = (amount_in / (10 ** base_info["decimals"])) * token_price * 0.015  # 1.5% for 3 swaps
            
            net_profit_usd = raw_profit_usd - gas_cost_usd - slippage_cost_usd
            
            if net_profit_usd > MIN_PROFIT_THRESHOLD:
                profit_percent = (raw_profit / amount_in) * 100 if amount_in > 0 else 0
                
                opportunities.append({
                    "type": "triangular",
                    "path": path,
                    "path_str": " → ".join(path),
                    "amount_in": str(amount_in),
                    "amount_out": str(final_amount),
                    "raw_profit_usd": raw_profit_usd,
                    "gas_cost_usd": gas_cost_usd,
                    "slippage_cost_usd": slippage_cost_usd,
                    "net_profit_usd": net_profit_usd,
                    "profit_percent": profit_percent,
                    "total_gas": total_gas,
                    "legs": leg_details,
                    "risk_score": 0.5  # Higher risk for triangular
                })
        except Exception as e:
            logger.debug(f"Triangular arb error for path {path}: {e}")
            continue
    
    return sorted(opportunities, key=lambda x: x.get("net_profit_usd", 0), reverse=True)

async def find_multi_hop_arbitrage(base_token: str = "WBERA", amount_in: int = None, max_hops: int = 4) -> List[Dict]:
    """
    Detect multi-hop arbitrage opportunities: A -> B -> C -> D -> A
    Returns profitable routes with 4+ tokens
    """
    opportunities = []
    base_info = TOKENS.get(base_token)
    if not base_info:
        return []
    
    if amount_in is None:
        amount_in = int(50 * (10 ** base_info["decimals"]))  # Smaller amount for multi-hop
    
    gas_price = cache.gas_price
    bera_price = cache.token_prices.get("bera", 5.0)
    
    # Get multi-hop paths from price matrix (limit to avoid performance issues)
    paths = price_matrix.find_multi_hop_paths(base_token, max_hops)[:20]
    
    for path in paths:
        if len(path) <= 3:  # Skip triangular (handled separately)
            continue
        
        try:
            # Quick profit estimate using cached prices first
            cached_profit = price_matrix.calculate_path_profit(path)
            if cached_profit is None or cached_profit < MIN_SPREAD_THRESHOLD:
                continue
            
            # Simulate the full cycle with actual quotes
            current_amount = amount_in
            total_gas = 0
            leg_details = []
            valid_path = True
            
            for i in range(len(path) - 1):
                token_from = path[i]
                token_to = path[i + 1]
                
                from_info = TOKENS.get(token_from)
                to_info = TOKENS.get(token_to)
                
                if not from_info or not to_info:
                    valid_path = False
                    break
                
                # Get quote for this leg
                quote = await get_dex_quote_fast(
                    KODIAK_V2_ROUTER,
                    from_info["address"],
                    to_info["address"],
                    current_amount,
                    "Kodiak V2"
                )
                
                if not quote:
                    valid_path = False
                    break
                
                leg_details.append({
                    "from": token_from,
                    "to": token_to,
                    "amount_in": current_amount,
                    "amount_out": int(quote.amount_out),
                    "price": quote.price
                })
                
                current_amount = int(quote.amount_out)
                total_gas += MULTI_HOP_GAS_PER_SWAP
            
            if not valid_path or len(leg_details) != len(path) - 1:
                continue
            
            # Calculate profit
            final_amount = current_amount
            raw_profit = final_amount - amount_in
            raw_profit_decimal = raw_profit / (10 ** base_info["decimals"])
            
            # Convert to USD
            token_price = bera_price if base_token == "WBERA" else 1.0
            raw_profit_usd = raw_profit_decimal * token_price
            
            # Calculate costs (higher for multi-hop)
            gas_cost_usd = (total_gas * gas_price / 10**18) * bera_price
            slippage_per_hop = 0.005  # 0.5% per hop
            slippage_cost_usd = (amount_in / (10 ** base_info["decimals"])) * token_price * slippage_per_hop * (len(path) - 1)
            
            net_profit_usd = raw_profit_usd - gas_cost_usd - slippage_cost_usd
            
            if net_profit_usd > MIN_PROFIT_THRESHOLD:
                profit_percent = (raw_profit / amount_in) * 100 if amount_in > 0 else 0
                
                opportunities.append({
                    "id": str(uuid.uuid4()),
                    "type": "multi_hop",
                    "path": path,
                    "token_pair": " → ".join(path),
                    "path_str": " → ".join(path),
                    "buy_dex": "Kodiak V2",
                    "sell_dex": "Kodiak V2",
                    "buy_price": leg_details[0]["price"],
                    "sell_price": leg_details[-1]["price"],
                    "amount_in": str(amount_in),
                    "amount_out": str(final_amount),
                    "raw_profit_usd": raw_profit_usd,
                    "spread_percent": profit_percent,
                    "potential_profit_usd": raw_profit_usd,
                    "gas_cost_usd": gas_cost_usd,
                    "slippage_cost_usd": slippage_cost_usd,
                    "net_profit_usd": net_profit_usd,
                    "profit_percent": profit_percent,
                    "total_gas": total_gas,
                    "legs": leg_details,
                    "hop_count": len(path) - 1,
                    "risk_score": 0.6,  # Higher risk for multi-hop
                    "liquidity_usd": 3000,
                    "price_impact": 2.5,
                    "token_in_address": base_info["address"],
                    "token_out_address": base_info["address"]
                })
                arb_logger.log_opportunity(opportunities[-1])
        except Exception as e:
            logger.debug(f"Multi-hop arb error for path {path}: {e}")
            continue
    
    return sorted(opportunities, key=lambda x: x.get("net_profit_usd", 0), reverse=True)

async def get_dex_quote_fast(router_address: str, token_in: str, token_out: str, amount_in: int, dex_name: str) -> Optional[PriceQuote]:
    """Get price quote from DEX router - optimized"""
    try:
        router = w3.eth.contract(address=Web3.to_checksum_address(router_address), abi=ROUTER_V2_ABI)
        path = [Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out)]
        
        amounts = router.functions.getAmountsOut(amount_in, path).call()
        amount_out = amounts[-1]
        
        token_in_info = next((t for t in TOKENS.values() if t["address"].lower() == token_in.lower()), None)
        token_out_info = next((t for t in TOKENS.values() if t["address"].lower() == token_out.lower()), None)
        
        if token_in_info and token_out_info:
            amount_in_decimal = amount_in / (10 ** token_in_info["decimals"])
            amount_out_decimal = amount_out / (10 ** token_out_info["decimals"])
            price = amount_out_decimal / amount_in_decimal if amount_in_decimal > 0 else 0
            price_impact = min(0.1 + (amount_in_decimal * 0.001), 5.0)
            
            return PriceQuote(
                dex=dex_name,
                token_in=token_in_info["symbol"],
                token_out=token_out_info["symbol"],
                amount_in=str(amount_in),
                amount_out=str(amount_out),
                price=price,
                price_impact=price_impact,
                gas_estimate=150000
            )
    except Exception as e:
        logger.debug(f"DEX quote error ({dex_name}): {e}")
    return None

async def get_bex_quote_fast(token_in: str, token_out: str, amount_in: int) -> Optional[PriceQuote]:
    """Get price quote from BEX (CrocSwap) using previewSwap - proper interface"""
    try:
        bex_query_contract = w3.eth.contract(
            address=Web3.to_checksum_address(BEX_QUERY),
            abi=BEX_QUERY_ABI
        )
        token_in_cs = Web3.to_checksum_address(token_in)
        token_out_cs = Web3.to_checksum_address(token_out)

        # CrocSwap: base is the lower address token
        if int(token_in_cs, 16) < int(token_out_cs, 16):
            base, quote_addr = token_in_cs, token_out_cs
            is_buy = False      # Selling base
            in_base_qty = True
            limit_price = BEX_MIN_SQRT_PRICE
        else:
            base, quote_addr = token_out_cs, token_in_cs
            is_buy = True       # Buying base with quote
            in_base_qty = False
            limit_price = BEX_MAX_UINT128

        base_flow, quote_flow = bex_query_contract.functions.previewSwap(
            base, quote_addr, BEX_POOL_IDX,
            is_buy, in_base_qty, amount_in,
            0, limit_price, 0, 0
        ).call()

        # We receive the token with negative flow (outflow from pool)
        amount_out = abs(base_flow) if is_buy else abs(quote_flow)
        if not (is_buy and base_flow < 0) and not (not is_buy and quote_flow < 0):
            return None

        token_in_info = next((t for t in TOKENS.values() if t["address"].lower() == token_in.lower()), None)
        token_out_info = next((t for t in TOKENS.values() if t["address"].lower() == token_out.lower()), None)

        if token_in_info and token_out_info:
            amount_in_decimal = amount_in / (10 ** token_in_info["decimals"])
            amount_out_decimal = amount_out / (10 ** token_out_info["decimals"])
            price = amount_out_decimal / amount_in_decimal if amount_in_decimal > 0 else 0
            return PriceQuote(
                dex="BEX",
                token_in=token_in_info["symbol"],
                token_out=token_out_info["symbol"],
                amount_in=str(amount_in),
                amount_out=str(amount_out),
                price=price,
                price_impact=min(0.1 + (amount_in_decimal * 0.001), 5.0),
                gas_estimate=180000
            )
    except Exception as e:
        logger.debug(f"BEX quote error: {e}")
    return None

async def get_multicall_quotes(pairs: List[tuple], amount_in_map: Dict[str, int]) -> Dict[str, PriceQuote]:
    """Fetch multiple quotes using multicall for speed"""
    results = {}
    
    # Parallel fetch for Kodiak
    tasks = []
    for token_a, token_b in pairs:
        token_a_info = TOKENS.get(token_a)
        token_b_info = TOKENS.get(token_b)
        if not token_a_info or not token_b_info:
            continue
        amount_in = amount_in_map.get(token_a, int(100 * (10 ** token_a_info["decimals"])))
        tasks.append(get_dex_quote_fast(KODIAK_V2_ROUTER, token_a_info["address"], token_b_info["address"], amount_in, "Kodiak V2"))
    
    quotes = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, quote in enumerate(quotes):
        if isinstance(quote, PriceQuote):
            pair_key = f"{pairs[i][0]}/{pairs[i][1]}"
            results[f"kodiak_{pair_key}"] = quote
    
    return results

async def find_arbitrage_opportunities_fast() -> List[ArbitrageOpportunity]:
    """
    Optimized arbitrage scanning with in-memory price matrix.
    Detects both direct and triangular arbitrage opportunities.
    
    Features:
    - Focused pair scanning for speed
    - Direct arbitrage (DEX A vs DEX B)
    - Triangular arbitrage (A → B → C → A)
    - Risk-adjusted profit ranking
    """
    start_time = time.time()
    opportunities = []
    
    # Core high-liquidity pairs for fast scanning
    pairs = [
        ("WBERA", "HONEY"),
        ("WBERA", "USDC"),
        ("WBERA", "USDT"),
        ("WBERA", "WETH"),
        ("WBERA", "WBTC"),
        ("HONEY", "USDC"),
        ("HONEY", "USDT"),
        ("WETH", "USDC"),
        ("WBTC", "USDC"),
        ("USDC", "USDT"),
    ]
    
    # Update cache once
    await cache.update_gas_price()
    gas_price = cache.gas_price
    
    bera_price = await get_token_price_coingecko("berachain-bera")
    await cache.update_token_price("bera", bera_price)
    
    # Build all quote tasks at once
    quote_tasks = []
    pair_meta = []
    
    for token_a, token_b in pairs:
        token_a_info = TOKENS.get(token_a)
        token_b_info = TOKENS.get(token_b)
        if not token_a_info or not token_b_info:
            continue
        
        amount_in = int(100 * (10 ** token_a_info["decimals"]))
        quote_tasks.append(get_dex_quote_fast(
            KODIAK_V2_ROUTER,
            token_a_info["address"],
            token_b_info["address"],
            amount_in,
            "Kodiak V2"
        ))
        pair_meta.append({
            "token_a": token_a,
            "token_b": token_b,
            "amount_in": amount_in,
            "token_a_info": token_a_info,
            "token_b_info": token_b_info
        })
    
    # Execute all quotes in parallel
    quotes = await asyncio.gather(*quote_tasks, return_exceptions=True)
    
    # Process quotes and update price matrix
    for i, quote in enumerate(quotes):
        if not isinstance(quote, PriceQuote):
            continue
        
        meta = pair_meta[i]
        token_a, token_b = meta["token_a"], meta["token_b"]
        token_a_info, token_b_info = meta["token_a_info"], meta["token_b_info"]
        amount_in = meta["amount_in"]
        pair_key = f"{token_a}/{token_b}"
        
        # Update price matrix for triangular detection
        await price_matrix.update(token_a, token_b, quote.price, int(quote.amount_out))
        
        # Estimate liquidity and price impact (use cached or defaults)
        liquidity_usd = 10000  # Default
        price_impact = quote.price_impact
        
        # Check cache for reserves
        pair_cache_key = cache.get_pair_key(token_a_info["address"], token_b_info["address"])
        if pair_cache_key in cache.pool_reserves:
            reserves = cache.pool_reserves[pair_cache_key]
            reserve_a = reserves["reserve_a"] / (10 ** token_a_info["decimals"])
            reserve_b = reserves["reserve_b"] / (10 ** token_b_info["decimals"])
            
            if token_a == "WBERA":
                liquidity_usd = reserve_a * bera_price * 2
            elif token_b == "WBERA":
                liquidity_usd = reserve_b * bera_price * 2
            else:
                liquidity_usd = max(reserve_a, reserve_b) * 2
            
            # Skip low liquidity
            if liquidity_usd < MIN_LIQUIDITY_USD:
                continue
        
        # Skip high price impact
        if price_impact > MAX_PRICE_IMPACT_PERCENT:
            continue
        
        # Get quotes from both Kodiak V3 and BEX in parallel
        v3_task = get_dex_quote_fast(
            KODIAK_V3_ROUTER,
            token_a_info["address"],
            token_b_info["address"],
            amount_in,
            "Kodiak V3"
        )
        bex_task = get_bex_quote_fast(
            token_a_info["address"],
            token_b_info["address"],
            amount_in
        )
        v3_result, bex_result = await asyncio.gather(v3_task, bex_task, return_exceptions=True)

        # Collect all valid second-dex quotes and pick best arbitrage
        second_dex_candidates = []
        if isinstance(v3_result, PriceQuote):
            second_dex_candidates.append(v3_result)
        if isinstance(bex_result, PriceQuote):
            second_dex_candidates.append(bex_result)

        second_dex_quote = None
        best_spread = 0.0
        for candidate in second_dex_candidates:
            candidate_spread = abs(quote.price - candidate.price) / max(quote.price, candidate.price, 1e-18) * 100
            if candidate_spread > best_spread:
                best_spread = candidate_spread
                second_dex_quote = candidate
        
        # If no second DEX quote available, skip this pair
        if not second_dex_quote:
            arb_logger.log_skip(pair_key, "No second DEX quote available")
            continue
        
        # Determine arbitrage direction based on REAL prices
        if quote.price > second_dex_quote.price:
            buy_quote, sell_quote = second_dex_quote, quote
        else:
            buy_quote, sell_quote = quote, second_dex_quote
        
        spread = ((sell_quote.price - buy_quote.price) / buy_quote.price) * 100
        
        if spread > 0.05:
            total_gas = buy_quote.gas_estimate + sell_quote.gas_estimate
            gas_cost_usd = (total_gas * gas_price / 10**18) * bera_price
            
            amount_out_buy = int(buy_quote.amount_out)
            amount_out_sell = int(sell_quote.amount_out)
            
            # Calculate profits
            token_price = bera_price if token_b == "WBERA" else 1.0
            raw_profit = (amount_out_sell - amount_out_buy) / (10 ** token_b_info["decimals"]) * token_price
            slippage_cost = abs(amount_out_buy) / (10 ** token_b_info["decimals"]) * token_price * 0.005
            impact_cost = abs(amount_out_buy) / (10 ** token_b_info["decimals"]) * token_price * (price_impact / 100)
            
            net_profit = raw_profit - gas_cost_usd - slippage_cost - impact_cost
            
            if net_profit > MIN_PROFIT_THRESHOLD:
                opp_data = {
                    "id": str(uuid.uuid4()),
                    "type": "direct",
                    "token_pair": pair_key,
                    "buy_dex": buy_quote.dex,
                    "sell_dex": sell_quote.dex,
                    "buy_price": buy_quote.price,
                    "sell_price": sell_quote.price,
                    "spread_percent": spread,
                    "potential_profit_usd": raw_profit,
                    "gas_cost_usd": gas_cost_usd,
                    "net_profit_usd": net_profit,
                    "amount_in": str(amount_in),
                    "expected_out": str(amount_out_sell),
                    "token_in_address": token_a_info["address"],
                    "token_out_address": token_b_info["address"],
                    "liquidity_usd": liquidity_usd,
                    "price_impact": price_impact,
                    "slippage_cost_usd": slippage_cost,
                    "price_impact_cost_usd": impact_cost
                }
                opportunities.append(opp_data)
                arb_logger.log_opportunity(opp_data)
            else:
                arb_logger.log_skip(pair_key, f"net_profit ${net_profit:.4f} < threshold")
    
    # Lightweight triangular detection using cached prices
    # Only check if we have enough price data in matrix
    if len(price_matrix.prices) >= 4:
        tri_paths = price_matrix.find_triangular_paths("WBERA")
        for path in tri_paths[:5]:  # Check top 5 paths only
            try:
                # Quick profit estimate using cached prices
                p1 = price_matrix.get_price(path[0], path[1])
                p2 = price_matrix.get_price(path[1], path[2])
                p3 = price_matrix.get_price(path[2], path[3])
                
                if p1 and p2 and p3:
                    # Rough cycle profit: start with 1, multiply through
                    cycle_return = p1 * p2 * p3
                    cycle_profit_pct = (cycle_return - 1) * 100
                    
                    if cycle_profit_pct > MIN_SPREAD_THRESHOLD:
                        # Estimate costs
                        gas_cost_usd = (450000 * gas_price / 10**18) * bera_price
                        net_estimate = (cycle_profit_pct / 100) * 100 * bera_price - gas_cost_usd
                        
                        if net_estimate > MIN_PROFIT_THRESHOLD:
                            opportunities.append({
                                "id": str(uuid.uuid4()),
                                "type": "triangular",
                                "token_pair": " → ".join(path),
                                "buy_dex": "Kodiak V2",
                                "sell_dex": "Kodiak V2",
                                "buy_price": p1,
                                "sell_price": p3,
                                "spread_percent": cycle_profit_pct,
                                "potential_profit_usd": net_estimate + gas_cost_usd,
                                "gas_cost_usd": gas_cost_usd,
                                "net_profit_usd": net_estimate,
                                "amount_in": str(int(100 * 10**18)),
                                "expected_out": str(int(100 * cycle_return * 10**18)),
                                "token_in_address": TOKENS.get("WBERA", {}).get("address", ""),
                                "token_out_address": TOKENS.get("WBERA", {}).get("address", ""),
                                "liquidity_usd": 5000,
                                "price_impact": 2.0,
                                "slippage_cost_usd": 0.015 * net_estimate,
                                "price_impact_cost_usd": 0.02 * net_estimate,
                                "path": path
                            })
            except Exception:
                continue
    
    # Rank by risk-adjusted profit
    ranked = rank_opportunities(opportunities)
    
    # Convert to ArbitrageOpportunity objects
    result = []
    for opp in ranked:
        result.append(ArbitrageOpportunity(
            id=opp.get("id", str(uuid.uuid4())),
            token_pair=opp["token_pair"],
            buy_dex=opp["buy_dex"],
            sell_dex=opp["sell_dex"],
            buy_price=opp["buy_price"],
            sell_price=opp["sell_price"],
            spread_percent=opp["spread_percent"],
            potential_profit_usd=opp["potential_profit_usd"],
            gas_cost_usd=opp["gas_cost_usd"],
            net_profit_usd=opp["net_profit_usd"],
            amount_in=opp["amount_in"],
            expected_out=opp["expected_out"],
            token_in_address=opp.get("token_in_address", ""),
            token_out_address=opp.get("token_out_address", "")
        ))
    
    scan_time = time.time() - start_time
    direct_count = len([o for o in ranked if o.get("type") == "direct"])
    tri_count = len([o for o in ranked if o.get("type") == "triangular"])
    multi_count = len([o for o in ranked if o.get("type") == "multi_hop"])
    
    # Log scan metrics
    arb_logger.log_scan(scan_time, len(result))
    logger.info(f"Scan: {scan_time:.2f}s, {len(result)} opps (direct:{direct_count}, tri:{tri_count}, multi:{multi_count})")
    
    return result

async def verify_opportunity_onchain(pair: str, buy_dex: str, sell_dex: str, amount: int, slippage: float = 0.5) -> Dict[str, Any]:
    """Re-verify prices on-chain before execution with comprehensive safety checks"""
    tokens = pair.split("/")
    if len(tokens) != 2:
        return {"valid": False, "error": "Invalid pair format"}
    
    token_in = TOKENS.get(tokens[0])
    token_out = TOKENS.get(tokens[1])
    
    if not token_in or not token_out:
        return {"valid": False, "error": "Unknown tokens"}
    
    # Get fresh quotes from both DEXes
    buy_router = KODIAK_V2_ROUTER if buy_dex == "Kodiak V2" else BEX_ROUTER
    sell_router = KODIAK_V2_ROUTER if sell_dex == "Kodiak V2" else BEX_ROUTER
    
    buy_quote = await get_dex_quote_fast(buy_router, token_in["address"], token_out["address"], amount, buy_dex)
    sell_quote = await get_dex_quote_fast(sell_router, token_in["address"], token_out["address"], amount, sell_dex)
    
    if not buy_quote or not sell_quote:
        return {"valid": False, "error": "Failed to get fresh quotes"}
    
    # Calculate current spread
    spread = ((sell_quote.price - buy_quote.price) / buy_quote.price) * 100
    
    # Get gas cost with buffer
    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = 50 * 10**9
    
    bera_price = await get_token_price_coingecko("berachain-bera")
    
    # Calculate gas for both legs with buffer
    buy_gas = int(buy_quote.gas_estimate * GAS_BUFFER_MULTIPLIER)
    sell_gas = int(sell_quote.gas_estimate * GAS_BUFFER_MULTIPLIER)
    total_gas = buy_gas + sell_gas
    gas_cost_wei = total_gas * gas_price
    gas_cost_usd = (gas_cost_wei / 10**18) * bera_price
    
    # Calculate raw profit (sell - buy)
    buy_amount_out = int(buy_quote.amount_out)
    sell_amount_out = int(sell_quote.amount_out)
    raw_profit_tokens = (sell_amount_out - buy_amount_out) / (10 ** token_out["decimals"])
    
    # Get token price for USD conversion
    token_price = 1.0  # Default for stablecoins
    if tokens[1] == "WBERA":
        token_price = bera_price
    
    raw_profit_usd = raw_profit_tokens * token_price
    
    # Calculate slippage cost
    slippage_factor = slippage / 100
    slippage_cost_usd = abs(buy_amount_out) / (10 ** token_out["decimals"]) * token_price * slippage_factor
    
    # Net profit = raw_profit - gas_cost - slippage_cost
    net_profit_usd = raw_profit_usd - gas_cost_usd - slippage_cost_usd
    
    # Safety validations
    safety_checks = {
        "profit_exceeds_gas": net_profit_usd > gas_cost_usd,
        "profit_exceeds_minimum": net_profit_usd > MIN_PROFIT_THRESHOLD,
        "slippage_acceptable": slippage <= MAX_SLIPPAGE_PERCENT,
        "spread_positive": spread > 0,
        "gas_within_limit": total_gas <= MAX_GAS_LIMIT
    }
    
    all_checks_passed = all(safety_checks.values())
    
    error_message = None
    if not all_checks_passed:
        failed_checks = [k for k, v in safety_checks.items() if not v]
        error_message = f"Safety checks failed: {', '.join(failed_checks)}"
    
    return {
        "valid": all_checks_passed,
        "buy_quote": buy_quote.model_dump() if buy_quote else None,
        "sell_quote": sell_quote.model_dump() if sell_quote else None,
        "spread_percent": spread,
        "raw_profit_usd": raw_profit_usd,
        "gas_cost_usd": gas_cost_usd,
        "slippage_cost_usd": slippage_cost_usd,
        "net_profit_usd": net_profit_usd,
        "total_gas_estimate": total_gas,
        "gas_price_gwei": gas_price / 10**9,
        "safety_checks": safety_checks,
        "error": error_message,
        "token_in_address": token_in["address"],
        "token_out_address": token_out["address"],
        "buy_router": buy_router,
        "sell_router": sell_router
    }

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Berachain Arbitrage Bot API", "chain_id": CHAIN_ID}

@api_router.get("/health")
async def health_check():
    try:
        is_connected = w3.is_connected()
        block_number = w3.eth.block_number if is_connected else 0
        return {
            "status": "healthy",
            "rpc_connected": is_connected,
            "block_number": block_number,
            "chain_id": CHAIN_ID
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@api_router.get("/tokens", response_model=List[TokenInfo])
async def get_tokens():
    return [TokenInfo(address=t["address"], symbol=t["symbol"], decimals=t["decimals"]) for t in TOKENS.values()]

@api_router.get("/tokens/{address}/balance/{wallet}")
async def get_token_balance(address: str, wallet: str):
    try:
        token = w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)
        balance = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        decimals = token.functions.decimals().call()
        symbol = token.functions.symbol().call()
        return {
            "address": address,
            "symbol": symbol,
            "balance_raw": str(balance),
            "balance_formatted": str(balance / (10 ** decimals)),
            "decimals": decimals
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@api_router.get("/wallet/{address}/balances")
async def get_wallet_balances(address: str):
    balances = []
    try:
        native_balance = w3.eth.get_balance(Web3.to_checksum_address(address))
        bera_price = await get_token_price_coingecko("berachain-bera")
        balances.append({
            "symbol": "BERA",
            "address": "native",
            "balance_raw": str(native_balance),
            "balance_formatted": str(native_balance / 10**18),
            "decimals": 18,
            "usd_value": (native_balance / 10**18) * bera_price
        })
    except Exception as e:
        logger.error(f"Error getting native balance: {e}")
    
    for symbol, token_info in TOKENS.items():
        try:
            token = w3.eth.contract(address=Web3.to_checksum_address(token_info["address"]), abi=ERC20_ABI)
            balance = token.functions.balanceOf(Web3.to_checksum_address(address)).call()
            balances.append({
                "symbol": symbol,
                "address": token_info["address"],
                "balance_raw": str(balance),
                "balance_formatted": str(balance / (10 ** token_info["decimals"])),
                "decimals": token_info["decimals"],
                "usd_value": 0
            })
        except Exception as e:
            logger.error(f"Error getting {symbol} balance: {e}")
    
    return {"address": address, "balances": balances}

@api_router.get("/opportunities", response_model=List[ArbitrageOpportunity])
async def get_arbitrage_opportunities():
    opportunities = await find_arbitrage_opportunities_fast()
    for opp in opportunities:
        doc = opp.model_dump()
        await db.opportunities.update_one({"id": opp.id}, {"$set": doc}, upsert=True)
    return opportunities

@api_router.get("/quote")
async def get_swap_quote(token_in: str, token_out: str, amount_in: str, dex: str = "kodiak"):
    router_address = KODIAK_V2_ROUTER if dex.lower() == "kodiak" else BEX_ROUTER
    quote = await get_dex_quote_fast(router_address, token_in, token_out, int(amount_in), dex.upper())
    if not quote:
        raise HTTPException(status_code=400, detail="Failed to get quote")
    return quote

@api_router.post("/trade/build")
async def build_trade_transaction(request: TradeRequest):
    try:
        opp = await db.opportunities.find_one({"id": request.opportunity_id}, {"_id": 0})
        if not opp:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        
        gas_price = w3.eth.gas_price
        if request.gas_price_gwei:
            gas_price = int(request.gas_price_gwei * 10**9)
        
        deadline = int(datetime.now(timezone.utc).timestamp()) + TRADE_TIMEOUT_SECONDS
        slippage = request.slippage_tolerance / 100
        min_out = int(int(opp["expected_out"]) * (1 - slippage))
        
        pair_tokens = opp["token_pair"].split("/")
        token_in_info = TOKENS.get(pair_tokens[0])
        token_out_info = TOKENS.get(pair_tokens[1])
        
        if not token_in_info or not token_out_info:
            raise HTTPException(status_code=400, detail="Invalid token pair")
        
        router = w3.eth.contract(address=Web3.to_checksum_address(KODIAK_V2_ROUTER), abi=ROUTER_V2_ABI)
        path = [Web3.to_checksum_address(token_in_info["address"]), Web3.to_checksum_address(token_out_info["address"])]
        
        tx_data = router.functions.swapExactTokensForTokens(
            int(opp["amount_in"]),
            min_out,
            path,
            Web3.to_checksum_address(request.wallet_address),
            deadline
        ).build_transaction({
            'from': Web3.to_checksum_address(request.wallet_address),
            'gas': min(250000, MAX_GAS_LIMIT),
            'gasPrice': gas_price,
            'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(request.wallet_address)),
            'chainId': CHAIN_ID
        })
        
        return {
            "to": KODIAK_V2_ROUTER,
            "data": tx_data["data"],
            "value": "0x0",
            "gas": hex(tx_data["gas"]),
            "gasPrice": hex(tx_data["gasPrice"]),
            "chainId": hex(CHAIN_ID),
            "nonce": tx_data["nonce"],
            "opportunity": opp
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/execute-trade")
async def execute_trade(request: ExecuteTradeRequest):
    """
    Execute arbitrage trade with comprehensive safety checks.
    
    Flow:
    1. Validate inputs and trade size
    2. Re-fetch latest pool prices from both DEXes
    3. Estimate gas cost and calculate slippage
    4. Calculate: net_profit = raw_profit - gas_cost - slippage_cost
    5. Execute only if net_profit > minimum_threshold
    6. Build and return transactions for wallet signing
    
    Safety checks:
    - Abort if price changed significantly
    - Abort if gas > expected profit
    - Abort if slippage exceeds tolerance
    - Enforce trade size limits
    """
    execution_id = str(uuid.uuid4())
    logger.info(f"[{execution_id}] Starting trade execution for {request.pair}")
    
    try:
        # 1. VALIDATE INPUTS
        amount = int(request.amount)
        tokens = request.pair.split("/")
        
        if len(tokens) != 2:
            raise HTTPException(status_code=400, detail="Invalid pair format. Expected: TOKEN_A/TOKEN_B")
        
        token_in = TOKENS.get(tokens[0])
        token_out = TOKENS.get(tokens[1])
        
        if not token_in or not token_out:
            raise HTTPException(status_code=400, detail=f"Unknown tokens in pair {request.pair}")
        
        # Validate wallet address
        try:
            wallet = Web3.to_checksum_address(request.wallet_address)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid wallet address")
        
        # 2. SAFETY CHECK: Trade size limit
        bera_price = await get_token_price_coingecko("berachain-bera")
        token_price = bera_price if tokens[0] == "WBERA" else 1.0
        amount_usd = (amount / (10 ** token_in["decimals"])) * token_price
        
        if amount_usd > MAX_TRADE_SIZE_USD:
            logger.warning(f"[{execution_id}] Trade size ${amount_usd:.2f} exceeds limit ${MAX_TRADE_SIZE_USD}")
            return {
                "success": False,
                "error": f"Trade size ${amount_usd:.2f} exceeds maximum ${MAX_TRADE_SIZE_USD} USD",
                "execution_id": execution_id
            }
        
        # 3. SAFETY CHECK: Slippage tolerance
        if request.slippage > MAX_SLIPPAGE_PERCENT:
            return {
                "success": False,
                "error": f"Slippage {request.slippage}% exceeds maximum {MAX_SLIPPAGE_PERCENT}%",
                "execution_id": execution_id
            }
        
        # 4. RE-VERIFY OPPORTUNITY ON-CHAIN
        logger.info(f"[{execution_id}] Verifying opportunity on-chain...")
        verification = await verify_opportunity_onchain(
            request.pair,
            request.buy_dex,
            request.sell_dex,
            amount,
            request.slippage
        )
        
        if not verification["valid"]:
            logger.warning(f"[{execution_id}] Verification failed: {verification.get('error')}")
            arb_logger.log_skip(request.pair, verification.get("error", "Verification failed"))
            return {
                "success": False,
                "error": verification.get("error", "Opportunity no longer profitable"),
                "verification": verification,
                "execution_id": execution_id
            }
        
        # 4.5 ON-CHAIN SIMULATION - Verify profit exists
        logger.info(f"[{execution_id}] Running on-chain simulation...")
        simulation = await verify_profit_onchain({
            "token_pair": request.pair,
            "amount_in": str(amount)
        })
        
        # Log simulation result
        arb_logger.log_simulation(simulation["valid"], simulation.get("reason", ""))
        
        if not simulation["valid"]:
            logger.warning(f"[{execution_id}] Simulation failed: {simulation.get('reason')}")
            arb_logger.log_skip(request.pair, f"Simulation: {simulation.get('reason')}")
            return {
                "success": False,
                "error": f"On-chain simulation failed: {simulation.get('reason')}",
                "simulation": simulation,
                "execution_id": execution_id
            }
        
        # Use simulated profit if available
        if simulation.get("simulated_profit_usd"):
            verification["net_profit_usd"] = simulation["simulated_profit_usd"]
        
        # 5. SAFETY CHECK: Profit must exceed gas cost (strict: revert if <= 0)
        if verification["net_profit_usd"] <= verification["gas_cost_usd"]:
            logger.warning(f"[{execution_id}] Profit ${verification['net_profit_usd']:.4f} <= gas ${verification['gas_cost_usd']:.4f}")
            return {
                "success": False,
                "error": f"Net profit ${verification['net_profit_usd']:.4f} does not exceed gas cost ${verification['gas_cost_usd']:.4f}",
                "verification": verification,
                "execution_id": execution_id
            }
        
        # 6. SAFETY CHECK: Minimum profit threshold
        if verification["net_profit_usd"] < MIN_PROFIT_THRESHOLD:
            return {
                "success": False,
                "error": f"Net profit ${verification['net_profit_usd']:.4f} below minimum threshold ${MIN_PROFIT_THRESHOLD}",
                "verification": verification,
                "execution_id": execution_id
            }
        
        # 7. GET CURRENT GAS PRICE
        try:
            gas_price = w3.eth.gas_price
        except Exception:
            gas_price = 50 * 10**9
        
        # Apply gas buffer
        gas_price_with_buffer = int(gas_price * GAS_BUFFER_MULTIPLIER)
        
        # 8. CALCULATE MINIMUM OUTPUT WITH SLIPPAGE PROTECTION
        slippage_factor = request.slippage / 100
        buy_expected_out = int(verification["buy_quote"]["amount_out"])
        min_out_buy = int(buy_expected_out * (1 - slippage_factor))
        
        # 9. BUILD BUY TRANSACTION (First leg: Buy on cheaper DEX)
        buy_router_address = verification["buy_router"]
        buy_router = w3.eth.contract(address=Web3.to_checksum_address(buy_router_address), abi=ROUTER_V2_ABI)
        buy_path = [
            Web3.to_checksum_address(token_in["address"]), 
            Web3.to_checksum_address(token_out["address"])
        ]
        
        deadline = int(datetime.now(timezone.utc).timestamp()) + TRADE_TIMEOUT_SECONDS
        
        try:
            nonce = w3.eth.get_transaction_count(wallet)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get nonce: {e}")
        
        buy_gas_limit = min(int(verification["buy_quote"]["gas_estimate"] * GAS_BUFFER_MULTIPLIER), MAX_GAS_LIMIT)
        
        buy_tx_data = buy_router.functions.swapExactTokensForTokens(
            amount,
            min_out_buy,
            buy_path,
            wallet,
            deadline
        ).build_transaction({
            'from': wallet,
            'gas': buy_gas_limit,
            'gasPrice': gas_price_with_buffer,
            'nonce': nonce,
            'chainId': CHAIN_ID
        })
        
        # 10. BUILD SELL TRANSACTION (Second leg: Sell on expensive DEX)
        sell_router_address = verification["sell_router"]
        sell_expected_out = int(verification["sell_quote"]["amount_out"])
        min_out_sell = int(sell_expected_out * (1 - slippage_factor))
        
        sell_router = w3.eth.contract(address=Web3.to_checksum_address(sell_router_address), abi=ROUTER_V2_ABI)
        sell_path = [
            Web3.to_checksum_address(token_out["address"]), 
            Web3.to_checksum_address(token_in["address"])
        ]
        
        sell_gas_limit = min(int(verification["sell_quote"]["gas_estimate"] * GAS_BUFFER_MULTIPLIER), MAX_GAS_LIMIT)
        
        sell_tx_data = sell_router.functions.swapExactTokensForTokens(
            buy_expected_out,  # Use expected output from buy as input for sell
            min_out_sell,
            sell_path,
            wallet,
            deadline
        ).build_transaction({
            'from': wallet,
            'gas': sell_gas_limit,
            'gasPrice': gas_price_with_buffer,
            'nonce': nonce + 1,  # Next nonce for second transaction
            'chainId': CHAIN_ID
        })
        
        logger.info(f"[{execution_id}] Trade verification passed. Net profit: ${verification['net_profit_usd']:.4f}")
        
        # 11. RETURN TRANSACTIONS FOR FRONTEND SIGNING
        return {
            "success": True,
            "execution_id": execution_id,
            "tx_hash": None,  # Filled after user signs
            "estimated_profit": verification["net_profit_usd"],
            "raw_profit": verification["raw_profit_usd"],
            "gas_cost_usd": verification["gas_cost_usd"],
            "slippage_cost_usd": verification["slippage_cost_usd"],
            "spread_percent": verification["spread_percent"],
            "gas_price_gwei": gas_price_with_buffer / 10**9,
            
            # Buy transaction (first leg)
            "buy_transaction": {
                "to": buy_router_address,
                "data": buy_tx_data["data"],
                "value": "0x0",
                "gas": hex(buy_tx_data["gas"]),
                "gasPrice": hex(buy_tx_data["gasPrice"]),
                "chainId": hex(CHAIN_ID),
                "nonce": buy_tx_data["nonce"],
                "description": f"Buy {tokens[1]} on {request.buy_dex}"
            },
            
            # Sell transaction (second leg)
            "sell_transaction": {
                "to": sell_router_address,
                "data": sell_tx_data["data"],
                "value": "0x0",
                "gas": hex(sell_tx_data["gas"]),
                "gasPrice": hex(sell_tx_data["gasPrice"]),
                "chainId": hex(CHAIN_ID),
                "nonce": sell_tx_data["nonce"],
                "description": f"Sell {tokens[1]} on {request.sell_dex}"
            },
            
            # Legacy single transaction format for backward compatibility
            "transaction": {
                "to": buy_router_address,
                "data": buy_tx_data["data"],
                "value": "0x0",
                "gas": hex(buy_tx_data["gas"]),
                "gasPrice": hex(buy_tx_data["gasPrice"]),
                "chainId": hex(CHAIN_ID),
                "nonce": buy_tx_data["nonce"]
            },
            
            "verification": verification,
            "safety_summary": {
                "trade_size_usd": amount_usd,
                "max_trade_size": MAX_TRADE_SIZE_USD,
                "slippage_percent": request.slippage,
                "max_slippage": MAX_SLIPPAGE_PERCENT,
                "profit_exceeds_gas": verification["net_profit_usd"] > verification["gas_cost_usd"],
                "total_gas_estimate": verification["total_gas_estimate"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{execution_id}] Execute trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/execute-trade/confirm")
async def confirm_trade_execution(
    execution_id: str,
    buy_tx_hash: str,
    sell_tx_hash: Optional[str] = None,
    wallet_address: str = ""
):
    """
    Confirm trade execution after user signs transactions.
    Records the trade result in database.
    """
    try:
        # Wait for buy transaction confirmation
        buy_receipt = w3.eth.wait_for_transaction_receipt(buy_tx_hash, timeout=TRADE_TIMEOUT_SECONDS)
        
        result = {
            "execution_id": execution_id,
            "buy_tx_hash": buy_tx_hash,
            "buy_status": "success" if buy_receipt.status == 1 else "failed",
            "buy_gas_used": buy_receipt.gasUsed,
            "buy_block": buy_receipt.blockNumber
        }
        
        # If sell transaction provided, wait for it too
        if sell_tx_hash:
            sell_receipt = w3.eth.wait_for_transaction_receipt(sell_tx_hash, timeout=TRADE_TIMEOUT_SECONDS)
            result.update({
                "sell_tx_hash": sell_tx_hash,
                "sell_status": "success" if sell_receipt.status == 1 else "failed",
                "sell_gas_used": sell_receipt.gasUsed,
                "sell_block": sell_receipt.blockNumber,
                "total_gas_used": buy_receipt.gasUsed + sell_receipt.gasUsed
            })
        
        # Record in database
        if wallet_address:
            trade_record = {
                "id": execution_id,
                "wallet_address": wallet_address.lower(),
                "buy_tx_hash": buy_tx_hash,
                "sell_tx_hash": sell_tx_hash,
                "status": "success" if buy_receipt.status == 1 else "failed",
                "gas_used": result.get("total_gas_used", buy_receipt.gasUsed),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await db.trade_executions.insert_one(trade_record)
        
        return result
        
    except Exception as e:
        logger.error(f"Confirm trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/trade/record")
async def record_trade(trade: TradeHistory):
    doc = trade.model_dump()
    await db.trade_history.insert_one(doc)
    return {"status": "recorded", "trade_id": trade.id}

@api_router.get("/trades/{wallet_address}", response_model=List[TradeHistory])
async def get_trade_history(wallet_address: str, limit: int = 50):
    trades = await db.trade_history.find(
        {"wallet_address": wallet_address.lower()},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    return trades

@api_router.get("/analytics/{wallet_address}")
async def get_analytics(wallet_address: str):
    trades = await db.trade_history.find({"wallet_address": wallet_address.lower()}, {"_id": 0}).to_list(1000)
    total_trades = len(trades)
    total_profit = sum(t.get("profit_usd", 0) for t in trades)
    total_gas = sum(t.get("gas_used", 0) for t in trades)
    successful = len([t for t in trades if t.get("status") == "success"])
    
    return {
        "wallet_address": wallet_address,
        "total_trades": total_trades,
        "successful_trades": successful,
        "success_rate": (successful / total_trades * 100) if total_trades > 0 else 0,
        "total_profit_usd": total_profit,
        "total_gas_used": total_gas,
        "average_profit_per_trade": total_profit / total_trades if total_trades > 0 else 0
    }

@api_router.get("/gas-price")
async def get_gas_price():
    try:
        gas_price = w3.eth.gas_price
        return {
            "wei": str(gas_price),
            "gwei": gas_price / 10**9,
            "recommended": {
                "slow": gas_price * 0.9 / 10**9,
                "standard": gas_price / 10**9,
                "fast": gas_price * 1.2 / 10**9,
                "instant": gas_price * 1.5 / 10**9
            }
        }
    except Exception as e:
        return {
            "wei": "50000000000",
            "gwei": 50,
            "recommended": {"slow": 40, "standard": 50, "fast": 60, "instant": 75},
            "error": str(e)
        }

@api_router.get("/settings/{wallet_address}")
async def get_settings(wallet_address: str):
    settings = await db.settings.find_one({"wallet_address": wallet_address.lower()}, {"_id": 0})
    if not settings:
        settings = {
            "wallet_address": wallet_address.lower(),
            "min_profit_threshold": 0.5,
            "max_slippage": 1.0,
            "gas_multiplier": 1.2,
            "auto_execute": False,
            "notifications": True
        }
    return settings

@api_router.post("/settings/{wallet_address}")
async def update_settings(wallet_address: str, settings: SettingsUpdate):
    doc = settings.model_dump()
    doc["wallet_address"] = wallet_address.lower()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.settings.update_one({"wallet_address": wallet_address.lower()}, {"$set": doc}, upsert=True)
    
    # Update auto-execution engine
    if settings.auto_execute:
        auto_engine.enabled = True
        auto_engine.wallet_address = wallet_address.lower()
        auto_engine.min_profit = settings.min_profit_threshold
        auto_engine.max_slippage = settings.max_slippage
    else:
        auto_engine.enabled = False
    
    return {"status": "updated", "settings": doc}

# ============== AUTO EXECUTION ENDPOINTS ==============
@api_router.post("/auto-execute/enable")
async def enable_auto_execution(wallet_address: str, min_profit: float = 0.5, max_slippage: float = 1.0):
    """Enable automatic trade execution"""
    auto_engine.enabled = True
    auto_engine.wallet_address = wallet_address.lower()
    auto_engine.min_profit = min_profit
    auto_engine.max_slippage = max_slippage
    
    return {
        "status": "enabled",
        "wallet_address": wallet_address,
        "min_profit": min_profit,
        "max_slippage": max_slippage
    }

@api_router.post("/auto-execute/disable")
async def disable_auto_execution():
    """Disable automatic trade execution"""
    auto_engine.enabled = False
    return {"status": "disabled"}

@api_router.get("/auto-execute/status")
async def get_auto_execution_status():
    """Get auto-execution engine status"""
    return {
        "enabled": auto_engine.enabled,
        "wallet_address": auto_engine.wallet_address,
        "min_profit": auto_engine.min_profit,
        "max_slippage": auto_engine.max_slippage,
        "execution_count": auto_engine.execution_count,
        "total_profit": auto_engine.total_profit,
        "last_execution": auto_engine.last_execution
    }

@api_router.get("/honeypot/check/{token_address}")
async def check_honeypot(token_address: str):
    """Check if a token is a honeypot"""
    result = await detect_honeypot(token_address, KODIAK_V2_ROUTER)
    return result

@api_router.get("/pool/reserves")
async def get_pool_reserves_endpoint(token_a: str, token_b: str):
    """Get pool reserves and liquidity info"""
    # Try to get token addresses from symbols if provided
    token_a_addr = token_a
    token_b_addr = token_b
    
    # Check if input is a symbol instead of address
    if len(token_a) < 20:
        token_info = TOKENS.get(token_a.upper())
        if token_info:
            token_a_addr = token_info["address"]
    
    if len(token_b) < 20:
        token_info = TOKENS.get(token_b.upper())
        if token_info:
            token_b_addr = token_info["address"]
    
    reserves = await get_pool_reserves(token_a_addr, token_b_addr)
    if not reserves:
        return {
            "found": False,
            "message": "Pool not found or reserves unavailable",
            "token_a": token_a_addr,
            "token_b": token_b_addr
        }
    
    # Get token info
    token_a_info = next((t for t in TOKENS.values() if t["address"].lower() == token_a_addr.lower()), None)
    token_b_info = next((t for t in TOKENS.values() if t["address"].lower() == token_b_addr.lower()), None)
    
    response = {
        "found": True,
        "pair_address": reserves["pair_address"],
        "reserve_a": str(reserves["reserve_a"]),
        "reserve_b": str(reserves["reserve_b"]),
        "token_a": reserves["token_a"],
        "token_b": reserves["token_b"]
    }
    
    if token_a_info and token_b_info:
        response["reserve_a_formatted"] = reserves["reserve_a"] / (10 ** token_a_info["decimals"])
        response["reserve_b_formatted"] = reserves["reserve_b"] / (10 ** token_b_info["decimals"])
    
    return response

@api_router.get("/engine/stats")
async def get_engine_stats():
    """Get comprehensive trading engine statistics"""
    return {
        "cache": {
            "pools_cached": len(cache.pool_reserves),
            "pairs_cached": len(cache.pair_addresses),
            "honeypot_blacklist_size": len(cache.honeypot_blacklist),
            "gas_price_gwei": cache.gas_price / 10**9,
            "bera_price_usd": cache.token_prices.get("bera", 0)
        },
        "price_matrix": {
            "tokens_tracked": len(price_matrix.prices),
            "last_update": price_matrix.last_update,
            "pairs_in_matrix": sum(len(v) for v in price_matrix.prices.values())
        },
        "auto_engine": {
            "enabled": auto_engine.enabled,
            "execution_count": auto_engine.execution_count,
            "total_profit": auto_engine.total_profit
        },
        "production": {
            "mode": PRODUCTION_MODE,
            "private_rpc_configured": bool(private_rpc_url),
            "use_private_rpc": USE_PRIVATE_RPC,
            "atomic_executor_stats": atomic_executor.get_execution_stats(),
            "scanner_metrics": real_price_scanner.get_scan_metrics(),
            "approvals_cached": len(token_approval_manager.approval_cache)
        },
        "safety_limits": {
            "max_trade_size_usd": MAX_TRADE_SIZE_USD,
            "max_slippage_percent": MAX_SLIPPAGE_PERCENT,
            "max_price_impact_percent": MAX_PRICE_IMPACT_PERCENT,
            "min_profit_threshold": MIN_PROFIT_THRESHOLD,
            "min_liquidity_usd": MIN_LIQUIDITY_USD,
            "min_spread_threshold": MIN_SPREAD_THRESHOLD,
            "max_hop_count": MAX_HOP_COUNT,
            "dex_fee_percent": DEX_FEE_PERCENT,
            "max_retry_attempts": MAX_RETRY_ATTEMPTS,
            "gas_increase_per_retry": f"{GAS_INCREASE_PER_RETRY * 100}%"
        },
        "arb_logger": arb_logger.get_stats()
    }

@api_router.get("/multi-hop-opportunities")
async def get_multi_hop_opportunities(base_token: str = "WBERA", max_hops: int = 4):
    """Get multi-hop arbitrage opportunities (4+ tokens)"""
    try:
        opps = await find_multi_hop_arbitrage(base_token, max_hops=min(max_hops, MAX_HOP_COUNT))
        return {
            "base_token": base_token,
            "max_hops": max_hops,
            "opportunities": opps,
            "count": len(opps)
        }
    except Exception as e:
        return {"error": str(e), "opportunities": [], "count": 0}

@api_router.get("/triangular-opportunities")
async def get_triangular_opportunities(base_token: str = "WBERA"):
    """Get triangular arbitrage opportunities"""
    try:
        opps = await find_triangular_arbitrage(base_token)
        return {
            "base_token": base_token,
            "opportunities": opps,
            "count": len(opps)
        }
    except Exception as e:
        return {"error": str(e), "opportunities": [], "count": 0}

# ============== PRODUCTION EXECUTION ENDPOINTS ==============

class AtomicExecutionRequest(BaseModel):
    """Request for atomic arbitrage execution"""
    opportunity_id: str
    wallet_address: str
    private_key: str  # WARNING: Only for backend execution, never log
    slippage_tolerance: float = 0.5
    use_private_rpc: bool = True
    use_flash_loan: bool = False

class TokenApprovalRequest(BaseModel):
    """Request for token approval"""
    token_address: str
    spender_address: str
    wallet_address: str
    private_key: str  # WARNING: Only for backend execution
    amount: Optional[str] = None  # If None, approves MAX_UINT256

@api_router.post("/production/execute-atomic")
async def execute_atomic_arbitrage(request: AtomicExecutionRequest):
    """
    Production atomic arbitrage execution with:
    - Pre-trade simulation via eth_call
    - Token approval flow
    - Retry logic with gas escalation
    - Private RPC for MEV protection
    - Comprehensive logging
    """
    try:
        # Get the opportunity from recent scan
        opportunities = await find_arbitrage_opportunities_fast()
        opportunity = None
        for opp in opportunities:
            if opp.id == request.opportunity_id:
                opportunity = opp.model_dump()
                break
        
        if not opportunity:
            return {
                "success": False,
                "error": "Opportunity not found or expired. Scan again.",
                "opportunities_available": len(opportunities)
            }
        
        # Get current BERA price
        bera_price = await get_token_price_coingecko("berachain-bera")
        
        # Check and approve tokens if needed
        tokens = opportunity["token_pair"].split("/")
        token_in = TOKENS.get(tokens[0])
        
        if token_in:
            # Determine which router needs approval
            buy_dex = opportunity.get("buy_dex", "Kodiak V2")
            buy_router = KODIAK_V2_ROUTER if "Kodiak" in buy_dex else BEX_ROUTER
            
            approval_result = await token_approval_manager.ensure_approval(
                token_address=token_in["address"],
                spender=buy_router,
                owner=request.wallet_address,
                required_amount=int(opportunity["amount_in"]),
                private_key=request.private_key
            )
            
            if not approval_result["success"]:
                return {
                    "success": False,
                    "error": f"Token approval failed: {approval_result.get('error')}",
                    "approval_result": approval_result
                }
        
        # Execute atomic arbitrage
        result = await atomic_executor.execute_arbitrage(
            opportunity=opportunity,
            wallet_address=request.wallet_address,
            private_key=request.private_key,
            slippage_tolerance=request.slippage_tolerance,
            use_private_rpc=request.use_private_rpc,
            bera_price_usd=bera_price
        )
        
        # Store in database
        if result["success"]:
            trade_doc = {
                "id": result["trade_id"],
                "wallet_address": request.wallet_address.lower(),
                "token_pair": opportunity["token_pair"],
                "buy_dex": opportunity["buy_dex"],
                "sell_dex": opportunity["sell_dex"],
                "amount_in": opportunity["amount_in"],
                "expected_profit_usd": opportunity["net_profit_usd"],
                "actual_profit_usd": result["actual_profit_usd"],
                "gas_used": result["total_gas_used"],
                "buy_tx_hash": result["buy_result"]["tx_hash"] if result["buy_result"] else None,
                "sell_tx_hash": result["sell_result"]["tx_hash"] if result["sell_result"] else None,
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await db.trades.insert_one(trade_doc)
        
        return result
        
    except Exception as e:
        logger.error(f"Atomic execution error: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@api_router.post("/production/approve-token")
async def approve_token(request: TokenApprovalRequest):
    """
    Approve token for DEX trading with retry logic.
    Approves MAX_UINT256 by default to avoid repeated approvals.
    """
    try:
        amount = int(request.amount) if request.amount else MAX_UINT256
        
        result = await token_approval_manager.approve_token(
            token_address=request.token_address,
            spender=request.spender_address,
            owner=request.wallet_address,
            private_key=request.private_key,
            amount=amount
        )
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@api_router.get("/production/check-allowance")
async def check_token_allowance(
    token_address: str,
    spender_address: str,
    owner_address: str
):
    """Check current token allowance"""
    try:
        allowance = await token_approval_manager.check_allowance(
            token_address=token_address,
            spender=spender_address,
            owner=owner_address
        )
        
        # Get token decimals for formatted display
        token_info = next(
            (t for t in TOKENS.values() if t["address"].lower() == token_address.lower()),
            None
        )
        
        decimals = token_info["decimals"] if token_info else 18
        
        return {
            "allowance_raw": str(allowance),
            "allowance_formatted": allowance / (10 ** decimals),
            "is_unlimited": allowance >= MAX_UINT256 // 2,
            "token_address": token_address,
            "spender": spender_address,
            "owner": owner_address
        }
        
    except Exception as e:
        return {"error": str(e)}

@api_router.post("/production/flash-arbitrage")
async def execute_flash_arbitrage(request: AtomicExecutionRequest):
    """
    Execute flash loan arbitrage for capital efficiency.
    Borrows liquidity, executes arbitrage, repays within single transaction.
    
    Note: Requires deployed FlashArbitrage contract on Berachain.
    """
    try:
        # Get the opportunity
        opportunities = await find_arbitrage_opportunities_fast()
        opportunity = None
        for opp in opportunities:
            if opp.id == request.opportunity_id:
                opportunity = opp.model_dump()
                break
        
        if not opportunity:
            return {
                "success": False,
                "error": "Opportunity not found or expired"
            }
        
        # Prepare flash arbitrage data
        flash_data = await flash_loan_executor.prepare_flash_arbitrage_data(
            opportunity=opportunity,
            wallet_address=request.wallet_address
        )
        
        if not flash_data:
            return {
                "success": False,
                "error": "Failed to prepare flash arbitrage data"
            }
        
        # Get current prices
        bera_price = await get_token_price_coingecko("berachain-bera")
        gas_price = w3.eth.gas_price
        
        # Simulate to verify profitability
        simulation = await flash_loan_executor.simulate_flash_arbitrage(
            flash_data=flash_data,
            gas_price_wei=gas_price,
            bera_price_usd=bera_price
        )
        
        if not simulation["profitable"]:
            return {
                "success": False,
                "error": f"Flash arbitrage not profitable: {simulation['reason']}",
                "simulation": simulation
            }
        
        # Return flash arbitrage transaction data
        # Note: Actual execution requires deployed FlashArbitrage contract
        return {
            "success": True,
            "flash_data": flash_data,
            "simulation": simulation,
            "message": "Flash arbitrage prepared. Deploy FlashArbitrage contract to execute.",
            "contract_bytecode_hint": "See flash_loan_executor.get_flash_arbitrage_contract_bytecode()"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@api_router.get("/production/scan-real")
async def scan_real_opportunities():
    """
    Production scan using real on-chain data via Multicall.
    No mock data - all prices fetched from actual DEX contracts.
    """
    # Fetch gas price with fallback
    try:
        gas_price = w3.eth.gas_price
    except Exception as e:
        logger.warning(f"Gas price fetch failed, using fallback: {e}")
        gas_price = int(1e9)  # 1 gwei fallback

    # Fetch BERA price with fallback
    try:
        bera_price = await get_token_price_coingecko("berachain-bera")
        if bera_price <= 0:
            raise ValueError("Invalid price returned")
    except Exception as e:
        logger.warning(f"BERA price fetch failed, using cached fallback: {e}")
        bera_price = price_cache.get("bera_price", 5.0)

    try:
        # Use real price scanner
        opportunities = await real_price_scanner.scan_arbitrage_opportunities(
            gas_price_wei=gas_price,
            bera_price_usd=bera_price
        )

        # Get scanner metrics
        metrics = real_price_scanner.get_scan_metrics()

        return {
            "opportunities": opportunities,
            "count": len(opportunities),
            "scan_metrics": metrics,
            "gas_price_gwei": gas_price / 10**9,
            "bera_price_usd": bera_price
        }

    except Exception as e:
        logger.error(f"Scan-real error: {e}")
        return {
            "error": str(e),
            "opportunities": [],
            "count": 0,
            "gas_price_gwei": gas_price / 10**9,
            "bera_price_usd": bera_price
        }

@api_router.get("/production/execution-stats")
async def get_production_execution_stats():
    """Get production execution statistics"""
    return {
        "atomic_executor": atomic_executor.get_execution_stats(),
        "scanner": real_price_scanner.get_scan_metrics(),
        "approvals_cached": len(token_approval_manager.approval_cache),
        "production_mode": PRODUCTION_MODE,
        "private_rpc_configured": bool(private_rpc_url),
        "use_private_rpc": USE_PRIVATE_RPC
    }

@api_router.get("/production/trade-history")
async def get_production_trade_history(limit: int = 100):
    """Get recent trades from CSV log"""
    trades = trade_logger.get_recent_trades(limit)
    return {
        "trades": trades,
        "count": len(trades)
    }


# WebSocket endpoint for real-time updates
@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            scan_start = time.time()
            
            # Fast scan - target < 1 second
            opportunities = await find_arbitrage_opportunities_fast()
            
            scan_time = time.time() - scan_start
            
            # Get gas price from cache
            gas_price = cache.gas_price
            gas_data = {
                "wei": str(gas_price),
                "gwei": gas_price / 10**9,
                "recommended": {
                    "slow": gas_price * 0.9 / 10**9,
                    "standard": gas_price / 10**9,
                    "fast": gas_price * 1.2 / 10**9,
                    "instant": gas_price * 1.5 / 10**9
                }
            }
            
            # Get best opportunity for auto-execution
            best_opp = opportunities[0] if opportunities else None
            
            await websocket.send_json({
                "type": "update",
                "opportunities": [o.model_dump() for o in opportunities],
                "gas": gas_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scan_time_ms": int(scan_time * 1000),
                "pools_scanned": len(cache.pool_reserves),
                "auto_engine": {
                    "enabled": auto_engine.enabled,
                    "execution_count": auto_engine.execution_count,
                    "total_profit": auto_engine.total_profit
                },
                "best_opportunity": best_opp.model_dump() if best_opp else None
            })
            
            # Update every 2 seconds for faster detection
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Include router
app.include_router(api_router)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
