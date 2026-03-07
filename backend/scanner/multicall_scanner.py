"""
Production Multicall Scanner - Real On-Chain Data
Replaces mock/random price data with actual blockchain queries
Uses Multicall3 for efficient batch RPC calls (<1s latency)
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from web3 import Web3
from eth_abi import decode

from core.constants import (
    TOKENS, KODIAK_V2_ROUTER, KODIAK_V2_FACTORY, KODIAK_V3_ROUTER, BEX_ROUTER, BEX_QUERY,
    MULTICALL3_ADDRESS, MIN_SPREAD_THRESHOLD, MIN_PROFIT_THRESHOLD,
    MIN_LIQUIDITY_USD, MAX_PRICE_IMPACT_PERCENT, DEX_FEE_PERCENT,
    GAS_BUFFER_MULTIPLIER
)
from core.abis import (
    ROUTER_V2_ABI, MULTICALL_ABI, PAIR_ABI, FACTORY_ABI, BEX_QUERY_ABI
)

logger = logging.getLogger(__name__)


class RealPriceScanner:
    """
    Production scanner using real on-chain data.
    Features:
    - Multicall batch queries for speed
    - Real reserves from LP pairs
    - Real quotes from routers
    - No mock/random data
    """
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.multicall = w3.eth.contract(
            address=Web3.to_checksum_address(MULTICALL3_ADDRESS),
            abi=MULTICALL_ABI
        )
        self.kodiak_router = w3.eth.contract(
            address=Web3.to_checksum_address(KODIAK_V2_ROUTER),
            abi=ROUTER_V2_ABI
        )
        self.kodiak_factory = w3.eth.contract(
            address=Web3.to_checksum_address(KODIAK_V2_FACTORY),
            abi=FACTORY_ABI
        )
        
        # Cache for pair addresses
        self.pair_cache: Dict[str, str] = {}
        self.reserves_cache: Dict[str, Dict] = {}
        self.cache_timestamp: Dict[str, float] = {}
        
        # Scan metrics
        self.last_scan_time = 0.0
        self.total_scans = 0
        self.scan_errors = 0
    
    def _get_pair_key(self, token_a: str, token_b: str) -> str:
        """Generate consistent pair key"""
        return f"{min(token_a, token_b).lower()}_{max(token_a, token_b).lower()}"
    
    async def get_pair_address(self, token_a: str, token_b: str) -> Optional[str]:
        """Get pair address from factory (cached)"""
        pair_key = self._get_pair_key(token_a, token_b)
        
        if pair_key in self.pair_cache:
            return self.pair_cache[pair_key]
        
        try:
            pair_address = self.kodiak_factory.functions.getPair(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b)
            ).call()
            
            if pair_address != "0x0000000000000000000000000000000000000000":
                self.pair_cache[pair_key] = pair_address
                return pair_address
        except Exception as e:
            logger.debug(f"Get pair error: {e}")
        
        return None
    
    async def batch_get_pair_addresses(self, pairs: List[Tuple[str, str]]) -> Dict[str, str]:
        """Get multiple pair addresses using multicall"""
        if not pairs:
            return {}
        
        try:
            calls = []
            pair_keys = []
            
            for token_a, token_b in pairs:
                pair_key = self._get_pair_key(token_a, token_b)
                pair_keys.append(pair_key)
                
                # Skip if cached
                if pair_key in self.pair_cache:
                    continue
                
                calldata = self.kodiak_factory.encode_abi(
                    'getPair',
                    args=[
                        Web3.to_checksum_address(token_a),
                        Web3.to_checksum_address(token_b)
                    ]
                )
                calls.append((KODIAK_V2_FACTORY, True, calldata))
            
            if not calls:
                # All cached
                return {pk: self.pair_cache.get(pk, "") for pk in pair_keys}
            
            # Execute multicall
            results = self.multicall.functions.aggregate3(calls).call()
            
            call_idx = 0
            for i, pair_key in enumerate(pair_keys):
                if pair_key in self.pair_cache:
                    continue
                
                if results[call_idx][0]:  # success
                    try:
                        pair_address = decode(['address'], results[call_idx][1])[0]
                        if pair_address != "0x0000000000000000000000000000000000000000":
                            self.pair_cache[pair_key] = pair_address
                    except Exception:
                        pass
                call_idx += 1
            
            return {pk: self.pair_cache.get(pk, "") for pk in pair_keys}
            
        except Exception as e:
            logger.error(f"Batch get pairs error: {e}")
            return {}
    
    async def batch_get_reserves(self, pair_addresses: List[str]) -> Dict[str, Dict]:
        """Get reserves for multiple pairs using multicall"""
        if not pair_addresses:
            return {}
        
        try:
            calls = []
            valid_pairs = []
            
            for pair_addr in pair_addresses:
                if not pair_addr or pair_addr == "0x0000000000000000000000000000000000000000":
                    continue
                
                valid_pairs.append(pair_addr)
                
                # getReserves call
                pair_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(pair_addr),
                    abi=PAIR_ABI
                )
                calldata = pair_contract.encode_abi('getReserves')
                calls.append((pair_addr, True, calldata))
            
            if not calls:
                return {}
            
            # Execute multicall
            results = self.multicall.functions.aggregate3(calls).call()
            
            reserves_map = {}
            for i, pair_addr in enumerate(valid_pairs):
                if results[i][0]:  # success
                    try:
                        decoded = decode(['uint112', 'uint112', 'uint32'], results[i][1])
                        reserves_map[pair_addr] = {
                            "reserve0": decoded[0],
                            "reserve1": decoded[1],
                            "timestamp": decoded[2]
                        }
                        self.reserves_cache[pair_addr] = reserves_map[pair_addr]
                        self.cache_timestamp[pair_addr] = time.time()
                    except Exception:
                        pass
            
            return reserves_map
            
        except Exception as e:
            logger.error(f"Batch get reserves error: {e}")
            return {}
    
    async def batch_get_quotes(
        self,
        quote_requests: List[Dict]
    ) -> List[Optional[Dict]]:
        """
        Get multiple quotes using multicall for speed.
        
        quote_requests: List of {
            "router": str,
            "token_in": str,
            "token_out": str,
            "amount_in": int
        }
        
        Returns list of quote results (or None if failed)
        """
        if not quote_requests:
            return []
        
        try:
            calls = []
            
            for req in quote_requests:
                router_addr = req["router"]
                path = [
                    Web3.to_checksum_address(req["token_in"]),
                    Web3.to_checksum_address(req["token_out"])
                ]
                
                router = self.w3.eth.contract(
                    address=Web3.to_checksum_address(router_addr),
                    abi=ROUTER_V2_ABI
                )
                calldata = router.encode_abi(
                    'getAmountsOut',
                    args=[req["amount_in"], path]
                )
                calls.append((router_addr, True, calldata))
            
            # Execute multicall
            results = self.multicall.functions.aggregate3(calls).call()
            
            quotes = []
            for i, result in enumerate(results):
                if result[0]:  # success
                    try:
                        amounts = decode(['uint256[]'], result[1])[0]
                        quotes.append({
                            "amount_in": quote_requests[i]["amount_in"],
                            "amount_out": amounts[-1],
                            "router": quote_requests[i]["router"],
                            "success": True
                        })
                    except Exception:
                        quotes.append(None)
                else:
                    quotes.append(None)
            
            return quotes
            
        except Exception as e:
            logger.error(f"Batch get quotes error: {e}")
            return [None] * len(quote_requests)
    
    async def scan_arbitrage_opportunities(
        self,
        gas_price_wei: int,
        bera_price_usd: float
    ) -> List[Dict]:
        """
        Production arbitrage scan using real on-chain data.
        Target: <1 second scan time using multicall batching.
        
        Returns ranked list of arbitrage opportunities.
        """
        start_time = time.time()
        opportunities = []
        
        # High-liquidity trading pairs
        pairs_to_scan = [
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
        
        try:
            # Step 1: Batch get all pair addresses
            token_pairs = []
            for symbol_a, symbol_b in pairs_to_scan:
                token_a = TOKENS.get(symbol_a)
                token_b = TOKENS.get(symbol_b)
                if token_a and token_b:
                    token_pairs.append((token_a["address"], token_b["address"]))
            
            pair_addresses = await self.batch_get_pair_addresses(token_pairs)
            
            # Step 2: Batch get reserves for all pairs
            valid_pairs = [addr for addr in pair_addresses.values() if addr]
            reserves_map = await self.batch_get_reserves(valid_pairs)
            
            # Step 3: Batch get quotes from multiple DEXes
            quote_requests = []
            quote_metadata = []
            
            for i, (symbol_a, symbol_b) in enumerate(pairs_to_scan):
                token_a = TOKENS.get(symbol_a)
                token_b = TOKENS.get(symbol_b)
                if not token_a or not token_b:
                    continue
                
                amount_in = int(100 * (10 ** token_a["decimals"]))
                
                # Kodiak V2 quote
                quote_requests.append({
                    "router": KODIAK_V2_ROUTER,
                    "token_in": token_a["address"],
                    "token_out": token_b["address"],
                    "amount_in": amount_in
                })
                quote_metadata.append({
                    "symbol_a": symbol_a,
                    "symbol_b": symbol_b,
                    "token_a": token_a,
                    "token_b": token_b,
                    "dex": "Kodiak V2"
                })
                
                # Kodiak V3 quote (different prices may exist)
                quote_requests.append({
                    "router": KODIAK_V3_ROUTER,
                    "token_in": token_a["address"],
                    "token_out": token_b["address"],
                    "amount_in": amount_in
                })
                quote_metadata.append({
                    "symbol_a": symbol_a,
                    "symbol_b": symbol_b,
                    "token_a": token_a,
                    "token_b": token_b,
                    "dex": "Kodiak V3"
                })
                
                # BEX quote (may fail if interface differs)
                quote_requests.append({
                    "router": BEX_ROUTER,
                    "token_in": token_a["address"],
                    "token_out": token_b["address"],
                    "amount_in": amount_in
                })
                quote_metadata.append({
                    "symbol_a": symbol_a,
                    "symbol_b": symbol_b,
                    "token_a": token_a,
                    "token_b": token_b,
                    "dex": "BEX"
                })
            
            quotes = await self.batch_get_quotes(quote_requests)
            
            # Step 4: Analyze quotes for arbitrage
            # Group quotes by pair
            pair_quotes: Dict[str, Dict[str, Dict]] = {}
            
            for i, quote in enumerate(quotes):
                if not quote or not quote.get("success"):
                    continue
                
                meta = quote_metadata[i]
                pair_key = f"{meta['symbol_a']}/{meta['symbol_b']}"
                dex = meta["dex"]
                
                if pair_key not in pair_quotes:
                    pair_quotes[pair_key] = {}
                
                pair_quotes[pair_key][dex] = {
                    "quote": quote,
                    "meta": meta
                }
            
            # Step 5: Find arbitrage between DEXes
            for pair_key, dex_quotes in pair_quotes.items():
                if len(dex_quotes) < 2:
                    continue
                
                # Get available quotes for this pair
                kodiak_v2_data = dex_quotes.get("Kodiak V2")
                kodiak_v3_data = dex_quotes.get("Kodiak V3")
                bex_data = dex_quotes.get("BEX")
                
                # Compare all available pairs of DEXes
                dex_pairs_to_compare = []
                
                if kodiak_v2_data and kodiak_v3_data:
                    dex_pairs_to_compare.append((kodiak_v2_data, kodiak_v3_data, "Kodiak V2", "Kodiak V3"))
                if kodiak_v2_data and bex_data:
                    dex_pairs_to_compare.append((kodiak_v2_data, bex_data, "Kodiak V2", "BEX"))
                if kodiak_v3_data and bex_data:
                    dex_pairs_to_compare.append((kodiak_v3_data, bex_data, "Kodiak V3", "BEX"))
                
                for dex_a_data, dex_b_data, dex_a_name, dex_b_name in dex_pairs_to_compare:
                    dex_a_quote = dex_a_data["quote"]
                    dex_b_quote = dex_b_data["quote"]
                    meta = dex_a_data["meta"]
                    
                    token_a = meta["token_a"]
                    token_b = meta["token_b"]
                    
                    # Calculate prices
                    amount_in = dex_a_quote["amount_in"]
                    dex_a_out = dex_a_quote["amount_out"]
                    dex_b_out = dex_b_quote["amount_out"]
                    
                    amount_in_decimal = amount_in / (10 ** token_a["decimals"])
                    dex_a_out_decimal = dex_a_out / (10 ** token_b["decimals"])
                    dex_b_out_decimal = dex_b_out / (10 ** token_b["decimals"])
                    
                    dex_a_price = dex_a_out_decimal / amount_in_decimal if amount_in_decimal > 0 else 0
                    dex_b_price = dex_b_out_decimal / amount_in_decimal if amount_in_decimal > 0 else 0
                    
                    if dex_a_price == 0 or dex_b_price == 0:
                        continue
                    
                    # Determine arbitrage direction
                    if dex_a_price > dex_b_price:
                        buy_dex, sell_dex = dex_b_name, dex_a_name
                        buy_price, sell_price = dex_b_price, dex_a_price
                        buy_out, sell_out = dex_b_out, dex_a_out
                    else:
                        buy_dex, sell_dex = dex_a_name, dex_b_name
                        buy_price, sell_price = dex_a_price, dex_b_price
                        buy_out, sell_out = dex_a_out, dex_b_out
                
                    # Calculate spread
                    spread_percent = ((sell_price - buy_price) / buy_price) * 100
                    
                    if spread_percent < MIN_SPREAD_THRESHOLD:
                        continue
                    
                    # Calculate profits with real costs
                    total_gas = 300000 * 2  # Two swaps
                    gas_cost_usd = (total_gas * gas_price_wei / 10**18) * bera_price_usd
                    
                    # Token price for USD conversion
                    token_price = bera_price_usd if meta["symbol_a"] == "WBERA" else 1.0
                    
                    # Gross profit
                    profit_tokens = (sell_out - buy_out) / (10 ** token_b["decimals"])
                    token_out_price = bera_price_usd if meta["symbol_b"] == "WBERA" else 1.0
                    raw_profit_usd = profit_tokens * token_out_price
                    
                    # DEX fees (0.3% * 2 swaps)
                    dex_fees_usd = amount_in_decimal * token_price * (DEX_FEE_PERCENT / 100) * 2
                    
                    # Slippage estimate
                    slippage_cost_usd = amount_in_decimal * token_price * 0.005
                    
                    # Net profit
                    net_profit_usd = raw_profit_usd - gas_cost_usd - dex_fees_usd - slippage_cost_usd
                    
                    if net_profit_usd <= MIN_PROFIT_THRESHOLD:
                        continue
                    
                    # Get liquidity from reserves
                    pair_key_lookup = self._get_pair_key(token_a["address"], token_b["address"])
                    pair_addr = self.pair_cache.get(pair_key_lookup, "")
                    reserves = reserves_map.get(pair_addr, {})
                    
                    liquidity_usd = 0
                    if reserves:
                        if meta["symbol_a"] == "WBERA":
                            liquidity_usd = (reserves.get("reserve0", 0) / 10**18) * bera_price_usd * 2
                        else:
                            liquidity_usd = (reserves.get("reserve0", 0) / (10 ** token_a["decimals"])) * 2
                    
                    if liquidity_usd < MIN_LIQUIDITY_USD:
                        continue
                    
                    # Create opportunity
                    import uuid
                    opp = {
                        "id": str(uuid.uuid4()),
                        "type": "direct",
                        "token_pair": pair_key,
                        "buy_dex": buy_dex,
                        "sell_dex": sell_dex,
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "spread_percent": spread_percent,
                        "potential_profit_usd": raw_profit_usd,
                        "gas_cost_usd": gas_cost_usd,
                        "dex_fees_usd": dex_fees_usd,
                        "slippage_cost_usd": slippage_cost_usd,
                        "net_profit_usd": net_profit_usd,
                        "amount_in": str(amount_in),
                        "expected_out": str(sell_out),
                        "token_in_address": token_a["address"],
                        "token_out_address": token_b["address"],
                        "liquidity_usd": liquidity_usd,
                        "price_impact": min(amount_in_decimal / 1000, MAX_PRICE_IMPACT_PERCENT),
                        "timestamp": time.time()
                    }
                    
                    opportunities.append(opp)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            self.scan_errors += 1
        
        finally:
            self.last_scan_time = time.time() - start_time
            self.total_scans += 1
        
        # Sort by net profit
        opportunities.sort(key=lambda x: x.get("net_profit_usd", 0), reverse=True)
        
        logger.info(f"Scan complete: {len(opportunities)} opportunities in {self.last_scan_time:.3f}s")
        
        return opportunities
    
    def get_scan_metrics(self) -> Dict:
        """Get scanner performance metrics"""
        return {
            "total_scans": self.total_scans,
            "scan_errors": self.scan_errors,
            "last_scan_time_ms": round(self.last_scan_time * 1000, 2),
            "pairs_cached": len(self.pair_cache),
            "reserves_cached": len(self.reserves_cache),
            "error_rate": round(self.scan_errors / max(self.total_scans, 1) * 100, 2)
        }
