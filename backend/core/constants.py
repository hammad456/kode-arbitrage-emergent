"""
Berachain Production Constants - Real Mainnet Addresses
"""
import os
from decimal import Decimal

# Chain Configuration
CHAIN_ID = 80094
BERACHAIN_RPC = os.environ.get('BERACHAIN_RPC', 'https://rpc.berachain.com')
PRIVATE_RPC_URL = os.environ.get('PRIVATE_RPC_URL', '')  # Flashbots-style private submission

# DEX Contract Addresses (Berachain Mainnet - Official)
KODIAK_V3_ROUTER = "0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690"
KODIAK_V2_ROUTER = "0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022"
KODIAK_V2_FACTORY = "0x5C346464d33F90bABaf70dB6388507CC889C1070"
KODIAK_QUOTER = "0x644C8D6E501f7C994B74F5ceA96abe65d0BA662B"

# BEX (Berachain Exchange) - Official Addresses
BEX_ROUTER = "0x21e2C0AFd058A89FCf7caf3aEA3cB84Ae977B73D"  # BEX CrocSwap Router
BEX_QUERY = "0x8685CE9Db06D40CBa73e3d09e6868FE476B5dC89"   # BEX Query Contract

# Honeypot Router
HONEYPOT_ROUTER = "0x1306D3c36eC7E38dd2c128fBe3097C2C2449af64"

# System Contracts
WBERA = "0x6969696969696969696969696969696969696969"
MULTICALL3_ADDRESS = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Common tokens on Berachain
TOKENS = {
    "WBERA": {"address": "0x6969696969696969696969696969696969696969", "decimals": 18, "symbol": "WBERA"},
    "HONEY": {"address": "0xFCBD14DC51f0A4d49d5E53C2E0950e0bC26d0Dce", "decimals": 18, "symbol": "HONEY"},
    "USDC": {"address": "0x549943e04f40284185054145c6E4e9568C1D3241", "decimals": 6, "symbol": "USDC"},
    "USDT": {"address": "0x779Ded0c9e1022225f8E0630b35a9b54bE713736", "decimals": 6, "symbol": "USDT"},
    "WETH": {"address": "0x2F6F07CDcf3588944Bf4C42aC74ff24bF56e7590", "decimals": 18, "symbol": "WETH"},
    "WBTC": {"address": "0x0555E30da8f98308EdB960aa94C0Db47230d2B9c", "decimals": 8, "symbol": "WBTC"},
}

# Safety Limits - Production Ready
MAX_TRADE_SIZE_USD = 10000
MAX_GAS_LIMIT = 500000
TRADE_TIMEOUT_SECONDS = 120
MIN_PROFIT_THRESHOLD = 0.0005  # $0.0005 minimum for micro-arb
MIN_SPREAD_THRESHOLD = 0.05   # 0.05% spread threshold
MAX_SLIPPAGE_PERCENT = 5.0
PRICE_CHANGE_TOLERANCE = 2.0
GAS_BUFFER_MULTIPLIER = 1.3
MAX_PRICE_IMPACT_PERCENT = 3.0
MIN_LIQUIDITY_USD = 200
DEX_FEE_PERCENT = 0.3  # Default 0.3% DEX fee

# Multi-hop config
MAX_HOP_COUNT = 4
MULTI_HOP_GAS_PER_SWAP = 150000

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds
GAS_INCREASE_PER_RETRY = 0.20  # 20% increase per retry

# MAX_UINT256 for infinite approval
MAX_UINT256 = 2**256 - 1

# Flash Arbitrage Contract (set after deployment)
FLASH_ARB_CONTRACT = os.environ.get('FLASH_ARB_CONTRACT', '')

# BEX CrocSwap constants
BEX_POOL_IDX = 36000
BEX_MIN_SQRT_PRICE = 65536
BEX_MAX_UINT128 = (2**128) - 1
