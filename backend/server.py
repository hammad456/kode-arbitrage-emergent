from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Berachain Configuration
BERACHAIN_RPC = os.environ.get('BERACHAIN_RPC', 'https://rpc.berachain.com')
CHAIN_ID = 80094

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(BERACHAIN_RPC))

# DEX Contract Addresses (Berachain Mainnet)
KODIAK_V3_ROUTER = "0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690"
KODIAK_V2_ROUTER = "0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022"
KODIAK_QUOTER = "0x644C8D6E501f7C994B74F5ceA96abe65d0BA662B"
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
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "active"

class TradeRequest(BaseModel):
    opportunity_id: str
    wallet_address: str
    slippage_tolerance: float = 0.5
    gas_price_gwei: Optional[float] = None

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

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# Price fetching functions
async def get_token_price_coingecko(token_id: str) -> float:
    """Fetch token price from CoinGecko API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={"ids": token_id, "vs_currencies": "usd"}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get(token_id, {}).get("usd", 0)
    except Exception as e:
        logger.error(f"CoinGecko price fetch error: {e}")
    return 0

async def get_dex_quote(router_address: str, token_in: str, token_out: str, amount_in: int, dex_name: str) -> Optional[PriceQuote]:
    """Get price quote from DEX router"""
    try:
        router = w3.eth.contract(address=Web3.to_checksum_address(router_address), abi=ROUTER_V2_ABI)
        path = [Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out)]
        
        amounts = router.functions.getAmountsOut(amount_in, path).call()
        amount_out = amounts[-1]
        
        # Calculate price
        token_in_info = next((t for t in TOKENS.values() if t["address"].lower() == token_in.lower()), None)
        token_out_info = next((t for t in TOKENS.values() if t["address"].lower() == token_out.lower()), None)
        
        if token_in_info and token_out_info:
            amount_in_decimal = amount_in / (10 ** token_in_info["decimals"])
            amount_out_decimal = amount_out / (10 ** token_out_info["decimals"])
            price = amount_out_decimal / amount_in_decimal if amount_in_decimal > 0 else 0
            
            # Estimate price impact (simplified)
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
        logger.error(f"DEX quote error ({dex_name}): {e}")
    return None

async def find_arbitrage_opportunities() -> List[ArbitrageOpportunity]:
    """Scan for arbitrage opportunities between DEXes"""
    opportunities = []
    
    # Token pairs to check
    pairs = [
        ("WBERA", "HONEY"),
        ("WBERA", "USDC"),
        ("HONEY", "USDC"),
        ("WETH", "WBERA"),
        ("WBTC", "WBERA"),
    ]
    
    # Get gas price for cost calculation
    try:
        gas_price = w3.eth.gas_price
    except Exception:
        gas_price = 50 * 10**9  # Default 50 gwei
    
    # Get BERA price for gas cost calculation
    bera_price = await get_token_price_coingecko("berachain-bera")
    if bera_price == 0:
        bera_price = 5.0  # Default estimate
    
    for token_a, token_b in pairs:
        token_a_info = TOKENS.get(token_a)
        token_b_info = TOKENS.get(token_b)
        
        if not token_a_info or not token_b_info:
            continue
        
        # Standard amount for comparison (1000 USD equivalent)
        amount_in = int(100 * (10 ** token_a_info["decimals"]))
        
        # Get quotes from both DEXes
        kodiak_v2_quote = await get_dex_quote(
            KODIAK_V2_ROUTER, 
            token_a_info["address"], 
            token_b_info["address"], 
            amount_in, 
            "Kodiak V2"
        )
        
        # Simulate BEX quote (in production, would call actual BEX contract)
        # For now, create slightly different price to demonstrate functionality
        bex_quote = None
        if kodiak_v2_quote:
            # Simulate BEX with slight price variation
            import random
            variation = random.uniform(-0.02, 0.02)
            bex_amount_out = int(int(kodiak_v2_quote.amount_out) * (1 + variation))
            bex_price = kodiak_v2_quote.price * (1 + variation)
            
            bex_quote = PriceQuote(
                dex="BEX",
                token_in=kodiak_v2_quote.token_in,
                token_out=kodiak_v2_quote.token_out,
                amount_in=kodiak_v2_quote.amount_in,
                amount_out=str(bex_amount_out),
                price=bex_price,
                price_impact=kodiak_v2_quote.price_impact * 0.9,
                gas_estimate=120000
            )
        
        if kodiak_v2_quote and bex_quote:
            # Determine arbitrage direction
            if kodiak_v2_quote.price > bex_quote.price:
                buy_quote, sell_quote = bex_quote, kodiak_v2_quote
            else:
                buy_quote, sell_quote = kodiak_v2_quote, bex_quote
            
            spread = ((sell_quote.price - buy_quote.price) / buy_quote.price) * 100
            
            if spread > 0.1:  # Minimum spread threshold
                # Calculate costs
                total_gas = buy_quote.gas_estimate + sell_quote.gas_estimate
                gas_cost_wei = total_gas * gas_price
                gas_cost_usd = (gas_cost_wei / 10**18) * bera_price
                
                # Calculate potential profit
                amount_out_buy = int(buy_quote.amount_out)
                amount_out_sell = int(sell_quote.amount_out)
                
                # Get token price for USD calculation
                token_price = await get_token_price_coingecko(token_b.lower())
                if token_price == 0:
                    token_price = 1.0
                
                profit_tokens = (amount_out_sell - amount_out_buy) / (10 ** token_b_info["decimals"])
                potential_profit_usd = profit_tokens * token_price
                net_profit_usd = potential_profit_usd - gas_cost_usd
                
                if net_profit_usd > 0:
                    opportunity = ArbitrageOpportunity(
                        token_pair=f"{token_a}/{token_b}",
                        buy_dex=buy_quote.dex,
                        sell_dex=sell_quote.dex,
                        buy_price=buy_quote.price,
                        sell_price=sell_quote.price,
                        spread_percent=spread,
                        potential_profit_usd=potential_profit_usd,
                        gas_cost_usd=gas_cost_usd,
                        net_profit_usd=net_profit_usd,
                        amount_in=str(amount_in),
                        expected_out=str(amount_out_sell)
                    )
                    opportunities.append(opportunity)
    
    return opportunities

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
    """Get list of supported tokens"""
    return [
        TokenInfo(address=t["address"], symbol=t["symbol"], decimals=t["decimals"])
        for t in TOKENS.values()
    ]

@api_router.get("/tokens/{address}/balance/{wallet}")
async def get_token_balance(address: str, wallet: str):
    """Get token balance for a wallet"""
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
    """Get all token balances for a wallet"""
    balances = []
    
    # Get native BERA balance
    try:
        native_balance = w3.eth.get_balance(Web3.to_checksum_address(address))
        balances.append({
            "symbol": "BERA",
            "address": "native",
            "balance_raw": str(native_balance),
            "balance_formatted": str(native_balance / 10**18),
            "decimals": 18,
            "usd_value": 0
        })
    except Exception as e:
        logger.error(f"Error getting native balance: {e}")
    
    # Get ERC20 balances
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
    """Get current arbitrage opportunities"""
    opportunities = await find_arbitrage_opportunities()
    
    # Store opportunities in DB
    for opp in opportunities:
        doc = opp.model_dump()
        await db.opportunities.update_one(
            {"id": opp.id},
            {"$set": doc},
            upsert=True
        )
    
    return opportunities

@api_router.get("/quote")
async def get_swap_quote(
    token_in: str,
    token_out: str,
    amount_in: str,
    dex: str = "kodiak"
):
    """Get swap quote from specified DEX"""
    router_address = KODIAK_V2_ROUTER if dex.lower() == "kodiak" else KODIAK_V2_ROUTER
    
    quote = await get_dex_quote(
        router_address,
        token_in,
        token_out,
        int(amount_in),
        dex.upper()
    )
    
    if not quote:
        raise HTTPException(status_code=400, detail="Failed to get quote")
    
    return quote

@api_router.post("/trade/build")
async def build_trade_transaction(request: TradeRequest):
    """Build transaction data for trade execution"""
    try:
        # Get opportunity from DB
        opp = await db.opportunities.find_one({"id": request.opportunity_id}, {"_id": 0})
        if not opp:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        
        # Get current gas price
        gas_price = w3.eth.gas_price
        if request.gas_price_gwei:
            gas_price = int(request.gas_price_gwei * 10**9)
        
        # Calculate deadline (20 minutes from now)
        deadline = int(datetime.now(timezone.utc).timestamp()) + 1200
        
        # Calculate minimum output with slippage
        slippage = request.slippage_tolerance / 100
        min_out = int(int(opp["expected_out"]) * (1 - slippage))
        
        # Build swap transaction for Kodiak V2
        pair_tokens = opp["token_pair"].split("/")
        token_in_info = TOKENS.get(pair_tokens[0])
        token_out_info = TOKENS.get(pair_tokens[1])
        
        if not token_in_info or not token_out_info:
            raise HTTPException(status_code=400, detail="Invalid token pair")
        
        router = w3.eth.contract(address=Web3.to_checksum_address(KODIAK_V2_ROUTER), abi=ROUTER_V2_ABI)
        
        # Build the transaction
        path = [
            Web3.to_checksum_address(token_in_info["address"]),
            Web3.to_checksum_address(token_out_info["address"])
        ]
        
        tx_data = router.functions.swapExactTokensForTokens(
            int(opp["amount_in"]),
            min_out,
            path,
            Web3.to_checksum_address(request.wallet_address),
            deadline
        ).build_transaction({
            'from': Web3.to_checksum_address(request.wallet_address),
            'gas': 250000,
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

@api_router.post("/trade/record")
async def record_trade(trade: TradeHistory):
    """Record completed trade in history"""
    doc = trade.model_dump()
    await db.trade_history.insert_one(doc)
    return {"status": "recorded", "trade_id": trade.id}

@api_router.get("/trades/{wallet_address}", response_model=List[TradeHistory])
async def get_trade_history(wallet_address: str, limit: int = 50):
    """Get trade history for a wallet"""
    trades = await db.trade_history.find(
        {"wallet_address": wallet_address.lower()},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    return trades

@api_router.get("/analytics/{wallet_address}")
async def get_analytics(wallet_address: str):
    """Get trading analytics for a wallet"""
    trades = await db.trade_history.find(
        {"wallet_address": wallet_address.lower()},
        {"_id": 0}
    ).to_list(1000)
    
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
    """Get current gas price"""
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
    """Get user settings"""
    settings = await db.settings.find_one(
        {"wallet_address": wallet_address.lower()},
        {"_id": 0}
    )
    
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
    """Update user settings"""
    doc = settings.model_dump()
    doc["wallet_address"] = wallet_address.lower()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.settings.update_one(
        {"wallet_address": wallet_address.lower()},
        {"$set": doc},
        upsert=True
    )
    
    return {"status": "updated", "settings": doc}

# WebSocket endpoint for real-time updates
@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Fetch and broadcast opportunities every 10 seconds
            opportunities = await find_arbitrage_opportunities()
            gas_data = await get_gas_price()
            
            await websocket.send_json({
                "type": "update",
                "opportunities": [o.model_dump() for o in opportunities],
                "gas": gas_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            await asyncio.sleep(10)
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
