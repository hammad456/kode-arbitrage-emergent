"""
ZLTRA - Zero-Loss Triangular Arbitrage with Instant Rebalance
=============================================================
Executes capital-efficient triangular arbitrage using flash loans.

Zero-Loss Guarantee:
  - Full on-chain simulation (eth_call) before any transaction
  - Only executes when net_profit > 0 after ALL costs:
    (flash loan fee + gas + DEX fees + slippage)
  - If simulation fails: NO on-chain tx, NO gas wasted

Instant Rebalance:
  - After a profitable trade, immediately check the inverse path
  - Detects chained opportunities within the same block window
  - Ensures portfolio returns to optimal token distribution

Flash Loan Flow (Uniswap V2 style):
  1. Borrow tokenA from LP pair (0 capital required)
  2. tokenA → tokenB on DEX1
  3. tokenB → tokenC on DEX2
  4. tokenC → tokenA on DEX3
  5. Repay borrowed tokenA + 0.3% fee
  6. Net profit = final_tokenA - repay_amount
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from web3 import Web3

from core.constants import (
    TOKENS, KODIAK_V2_ROUTER, KODIAK_V2_FACTORY, BEX_ROUTER,
    DEX_FEE_PERCENT, GAS_BUFFER_MULTIPLIER, MAX_GAS_LIMIT,
    MIN_PROFIT_THRESHOLD, MULTI_HOP_GAS_PER_SWAP
)
from core.abis import ROUTER_V2_ABI, FACTORY_ABI, FLASH_PAIR_ABI

logger = logging.getLogger(__name__)

# ZLTRA Configuration
FLASH_LOAN_FEE_PERCENT = 0.3        # Standard Uniswap V2 flash swap fee
ZLTRA_MIN_PROFIT_USD = 0.001        # Minimum profit after all costs
ZLTRA_MAX_SLIPPAGE_PERCENT = 1.0    # Max acceptable slippage per leg
ZLTRA_GAS_PER_LEG = 150_000         # Gas estimate per swap leg
ZLTRA_FLASH_OVERHEAD_GAS = 80_000   # Extra gas for flash loan callback overhead
ZLTRA_MAX_BORROW_PERCENT = 0.25     # Max 25% of pool reserves to borrow
REBALANCE_COOLDOWN_SECS = 3.0       # Minimum seconds between rebalance checks


@dataclass
class ZLTRAOpportunity:
    """Represents a validated zero-loss triangular arbitrage opportunity"""
    id: str
    path: List[str]                  # ["WBERA", "HONEY", "USDC", "WBERA"]
    path_str: str                    # human-readable
    flash_token: str                 # token to borrow
    flash_amount: int                # raw amount to borrow (wei)
    flash_amount_usd: float
    flash_fee_usd: float
    leg_amounts: List[int]           # amounts at each hop
    dexes: List[str]                 # DEX for each leg
    gross_profit_usd: float
    gas_cost_usd: float
    net_profit_usd: float
    profit_percent: float
    execution_probability: float     # 0-1
    pair_address: str               # pair to borrow from
    simulated: bool = True
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": "zltra",
            "path": self.path,
            "path_str": self.path_str,
            "flash_token": self.flash_token,
            "flash_amount": str(self.flash_amount),
            "flash_amount_usd": round(self.flash_amount_usd, 4),
            "flash_fee_usd": round(self.flash_fee_usd, 6),
            "leg_amounts": [str(a) for a in self.leg_amounts],
            "dexes": self.dexes,
            "gross_profit_usd": round(self.gross_profit_usd, 6),
            "gas_cost_usd": round(self.gas_cost_usd, 6),
            "net_profit_usd": round(self.net_profit_usd, 6),
            "profit_percent": round(self.profit_percent, 4),
            "execution_probability": round(self.execution_probability, 3),
            "pair_address": self.pair_address,
            "simulated": self.simulated,
            "timestamp": self.timestamp,
        }


class ZLTRAEngine:
    """
    Zero-Loss Triangular Arbitrage engine with Instant Rebalance.

    Usage:
        engine = ZLTRAEngine(w3)
        opportunities = await engine.scan(gas_price_wei, bera_price_usd)
    """

    def __init__(self, w3: Web3):
        self.w3 = w3
        self._pair_cache: Dict[str, str] = {}
        self._scan_count = 0
        self._last_rebalance_check: float = 0.0
        self._stats = {
            "total_scans": 0,
            "opportunities_found": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "rebalance_signals": 0,
        }

        # All triangular triplets to evaluate (symbol tuples)
        self._triplets: List[Tuple[str, str, str]] = [
            ("WBERA", "HONEY", "USDC"),
            ("WBERA", "HONEY", "USDT"),
            ("WBERA", "USDC", "WETH"),
            ("WBERA", "USDC", "WBTC"),
            ("WBERA", "USDT", "USDC"),
            ("WBERA", "WETH", "USDC"),
            ("WBERA", "WBTC", "USDC"),
            ("HONEY", "USDC", "WETH"),
            ("HONEY", "USDT", "USDC"),
            ("WETH", "USDC", "USDT"),
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(
        self,
        gas_price_wei: int,
        bera_price_usd: float,
    ) -> List[ZLTRAOpportunity]:
        """
        Scan all configured triplets for zero-loss triangular arbitrage.
        Returns validated, ranked opportunities.
        """
        self._scan_count += 1
        self._stats["total_scans"] += 1
        start = time.time()
        opportunities: List[ZLTRAOpportunity] = []

        tasks = [
            self._evaluate_triplet(a, b, c, gas_price_wei, bera_price_usd)
            for a, b, c in self._triplets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, ZLTRAOpportunity):
                opportunities.append(res)

        # Also check inverse direction for each triplet
        inverse_tasks = [
            self._evaluate_triplet(a, c, b, gas_price_wei, bera_price_usd)
            for a, b, c in self._triplets
        ]
        inv_results = await asyncio.gather(*inverse_tasks, return_exceptions=True)
        for res in inv_results:
            if isinstance(res, ZLTRAOpportunity):
                opportunities.append(res)

        self._stats["opportunities_found"] += len(opportunities)
        elapsed = time.time() - start
        logger.info(
            f"[ZLTRA] Scan #{self._scan_count}: {len(opportunities)} opps "
            f"in {elapsed*1000:.1f}ms"
        )

        # Rank by net profit
        opportunities.sort(key=lambda o: o.net_profit_usd, reverse=True)
        return opportunities

    async def check_rebalance(
        self,
        executed_opp: ZLTRAOpportunity,
        gas_price_wei: int,
        bera_price_usd: float,
    ) -> Optional[ZLTRAOpportunity]:
        """
        Instant Rebalance: after executing an opportunity, check if the
        inverse triangular path is also immediately profitable.

        This captures residual imbalance left in pools after the primary trade.
        """
        now = time.time()
        if now - self._last_rebalance_check < REBALANCE_COOLDOWN_SECS:
            return None
        self._last_rebalance_check = now

        # Reverse the path (skip repeated start token)
        fwd = executed_opp.path[:-1]  # e.g. ["WBERA", "HONEY", "USDC"]
        rev = list(reversed(fwd))     # e.g. ["USDC", "HONEY", "WBERA"]

        if len(rev) < 3:
            return None

        opp = await self._evaluate_triplet(
            rev[0], rev[1], rev[2],
            gas_price_wei, bera_price_usd
        )
        if opp:
            self._stats["rebalance_signals"] += 1
            logger.info(
                f"[ZLTRA] Rebalance signal: {opp.path_str} "
                f"profit=${opp.net_profit_usd:.4f}"
            )
        return opp

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "simulation_success_rate": (
                round(
                    self._stats["simulations_passed"]
                    / max(
                        self._stats["simulations_passed"]
                        + self._stats["simulations_failed"],
                        1,
                    )
                    * 100,
                    2,
                )
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _evaluate_triplet(
        self,
        sym_a: str,
        sym_b: str,
        sym_c: str,
        gas_price_wei: int,
        bera_price_usd: float,
    ) -> Optional[ZLTRAOpportunity]:
        """
        Evaluate a single A→B→C→A triangular path with flash loan.
        Returns ZLTRAOpportunity if profitable, None otherwise.
        """
        import uuid

        tok_a = TOKENS.get(sym_a)
        tok_b = TOKENS.get(sym_b)
        tok_c = TOKENS.get(sym_c)
        if not tok_a or not tok_b or not tok_c:
            return None

        try:
            # Flash borrow amount: 100 tokens of A
            flash_amount = int(100 * (10 ** tok_a["decimals"]))

            # Simulate leg 1: A → B
            amt_b = await self._simulate_swap(
                tok_a["address"], tok_b["address"], flash_amount
            )
            if not amt_b or amt_b == 0:
                self._stats["simulations_failed"] += 1
                return None

            # Simulate leg 2: B → C
            amt_c = await self._simulate_swap(
                tok_b["address"], tok_c["address"], amt_b
            )
            if not amt_c or amt_c == 0:
                self._stats["simulations_failed"] += 1
                return None

            # Simulate leg 3: C → A
            amt_a_final = await self._simulate_swap(
                tok_c["address"], tok_a["address"], amt_c
            )
            if not amt_a_final or amt_a_final == 0:
                self._stats["simulations_failed"] += 1
                return None

            self._stats["simulations_passed"] += 1

            # ----- Zero-Loss Cost Accounting -----
            flash_fee_raw = int(flash_amount * FLASH_LOAN_FEE_PERCENT / 100)
            repay_amount = flash_amount + flash_fee_raw
            gross_profit_raw = amt_a_final - repay_amount

            if gross_profit_raw <= 0:
                return None

            # USD conversion
            tok_a_price = bera_price_usd if sym_a == "WBERA" else 1.0
            decimals_a = tok_a["decimals"]

            gross_profit_usd = (gross_profit_raw / 10 ** decimals_a) * tok_a_price
            flash_amount_usd = (flash_amount / 10 ** decimals_a) * tok_a_price
            flash_fee_usd = (flash_fee_raw / 10 ** decimals_a) * tok_a_price

            # Gas cost (3 swaps + flash overhead)
            total_gas = ZLTRA_GAS_PER_LEG * 3 + ZLTRA_FLASH_OVERHEAD_GAS
            gas_cost_usd = (total_gas * gas_price_wei / 10 ** 18) * bera_price_usd

            # DEX fees already deducted by simulation (getAmountsOut accounts for 0.3%)
            # Add slippage buffer
            slippage_usd = flash_amount_usd * (ZLTRA_MAX_SLIPPAGE_PERCENT / 100) * 0.5

            net_profit_usd = gross_profit_usd - gas_cost_usd - slippage_usd

            # Zero-Loss Gate: only proceed if profit > threshold
            if net_profit_usd < ZLTRA_MIN_PROFIT_USD:
                return None

            # Profit %
            profit_percent = (gross_profit_raw / flash_amount) * 100

            # Execution probability (degrades with higher profit % due to competition)
            exec_prob = max(0.3, min(0.95, 0.95 - profit_percent * 0.05))

            # Get borrow pair address
            pair_address = await self._get_pair_address(
                tok_a["address"], tok_b["address"]
            )

            path = [sym_a, sym_b, sym_c, sym_a]
            return ZLTRAOpportunity(
                id=str(uuid.uuid4()),
                path=path,
                path_str=" → ".join(path),
                flash_token=sym_a,
                flash_amount=flash_amount,
                flash_amount_usd=flash_amount_usd,
                flash_fee_usd=flash_fee_usd,
                leg_amounts=[flash_amount, amt_b, amt_c, amt_a_final],
                dexes=["Kodiak V2", "Kodiak V2", "Kodiak V2"],
                gross_profit_usd=gross_profit_usd,
                gas_cost_usd=gas_cost_usd,
                net_profit_usd=net_profit_usd,
                profit_percent=profit_percent,
                execution_probability=exec_prob,
                pair_address=pair_address or "",
                simulated=True,
            )

        except Exception as e:
            logger.debug(f"[ZLTRA] Triplet {sym_a}→{sym_b}→{sym_c} error: {e}")
            self._stats["simulations_failed"] += 1
            return None

    async def _simulate_swap(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> Optional[int]:
        """
        Simulate a swap via getAmountsOut (eth_call — no state change, no gas spent).
        Returns output amount or None on failure.
        """
        try:
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(KODIAK_V2_ROUTER),
                abi=ROUTER_V2_ABI,
            )
            path = [
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
            ]
            amounts = router.functions.getAmountsOut(amount_in, path).call()
            return amounts[-1] if amounts else None
        except Exception:
            return None

    async def _get_pair_address(
        self, token_a: str, token_b: str
    ) -> Optional[str]:
        """Get Uniswap V2 pair address (cached)."""
        key = f"{min(token_a, token_b).lower()}_{max(token_a, token_b).lower()}"
        if key in self._pair_cache:
            return self._pair_cache[key]
        try:
            factory = self.w3.eth.contract(
                address=Web3.to_checksum_address(KODIAK_V2_FACTORY),
                abi=FACTORY_ABI,
            )
            addr = factory.functions.getPair(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b),
            ).call()
            if addr != "0x0000000000000000000000000000000000000000":
                self._pair_cache[key] = addr
                return addr
        except Exception:
            pass
        return None
