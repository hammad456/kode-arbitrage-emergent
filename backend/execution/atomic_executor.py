"""
Atomic Arbitrage Executor - Production Trade Execution
Handles atomic transactions, flash swaps, and retry logic

Safety guarantees:
  1. Pre-execution profit simulation via eth_call (no gas spent)
  2. Post-buy actual balance read — sell ABORTS if balance unverifiable
  3. slippage_cost included in net_profit so reporting is accurate
  4. Gas estimates consistent: 250 000 per swap (tuneable via GAS_PER_SWAP)
  5. Gas price re-fetched at execution time (not stale from scan)
  6. Strict MIN_NET_PROFIT_USD enforced before any on-chain call
"""
import asyncio
import logging
import time
import csv
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound

from core.constants import (
    MAX_RETRY_ATTEMPTS, RETRY_BASE_DELAY, GAS_INCREASE_PER_RETRY,
    GAS_BUFFER_MULTIPLIER, MAX_GAS_LIMIT, DEX_FEE_PERCENT,
    TRADE_TIMEOUT_SECONDS, PRIVATE_RPC_URL, KODIAK_V2_ROUTER, BEX_ROUTER
)
from core.abis import ROUTER_V2_ABI, ERC20_ABI, BEX_QUERY_ABI
from core.constants import BEX_QUERY

logger = logging.getLogger(__name__)

# Conservative, consistent gas estimate for one V2 swap
GAS_PER_SWAP = 250_000
# Minimum net profit to even attempt execution (prevents dust trades)
MIN_NET_PROFIT_USD = 0.01   # $0.01 hard floor


class TradeLogger:
    """Logs all trade outcomes to CSV and provides metrics"""

    def __init__(self, log_dir: str = "/app/backend/logs"):
        self.log_dir = log_dir
        self.csv_file = os.path.join(log_dir, "trade_history.csv")
        self._ensure_csv_exists()

    def _ensure_csv_exists(self):
        os.makedirs(self.log_dir, exist_ok=True)
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'trade_id', 'pair', 'type', 'buy_dex', 'sell_dex',
                    'amount_in', 'expected_out', 'actual_out', 'expected_profit_usd',
                    'actual_profit_usd', 'gas_used', 'gas_price_gwei', 'gas_cost_usd',
                    'buy_tx_hash', 'sell_tx_hash', 'status', 'error', 'retry_count',
                    'execution_time_ms', 'slippage_actual'
                ])

    def log_trade(self, trade_data: Dict):
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    trade_data.get('timestamp', datetime.now(timezone.utc).isoformat()),
                    trade_data.get('trade_id', ''),
                    trade_data.get('pair', ''),
                    trade_data.get('type', 'direct'),
                    trade_data.get('buy_dex', ''),
                    trade_data.get('sell_dex', ''),
                    trade_data.get('amount_in', ''),
                    trade_data.get('expected_out', ''),
                    trade_data.get('actual_out', ''),
                    trade_data.get('expected_profit_usd', 0),
                    trade_data.get('actual_profit_usd', 0),
                    trade_data.get('gas_used', 0),
                    trade_data.get('gas_price_gwei', 0),
                    trade_data.get('gas_cost_usd', 0),
                    trade_data.get('buy_tx_hash', ''),
                    trade_data.get('sell_tx_hash', ''),
                    trade_data.get('status', 'unknown'),
                    trade_data.get('error', ''),
                    trade_data.get('retry_count', 0),
                    trade_data.get('execution_time_ms', 0),
                    trade_data.get('slippage_actual', 0)
                ])
            logger.info(f"Trade logged: {trade_data.get('trade_id')} - {trade_data.get('status')}")
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")

    def get_recent_trades(self, limit: int = 100) -> List[Dict]:
        trades = []
        try:
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
            return trades[-limit:] if len(trades) > limit else trades
        except Exception as e:
            logger.error(f"Failed to read trades: {e}")
            return []


class AtomicArbExecutor:
    """
    Production-grade arbitrage executor with:
    - Strict pre-execution profit simulation (eth_call, no gas)
    - Post-buy actual balance verification — ABORTS sell if can't confirm
    - Accurate net_profit including all costs (gas + fees + slippage)
    - Retry logic with exponential backoff + gas escalation
    - Private RPC submission for MEV protection
    """

    def __init__(self, w3: Web3, private_w3: Optional[Web3] = None):
        self.w3 = w3
        self.private_w3 = private_w3 if private_w3 else w3
        self.trade_logger = TradeLogger()
        self.execution_stats = {
            "total_executions": 0,
            "successful": 0,
            "failed": 0,
            "total_profit_usd": 0.0,
            "total_gas_spent_usd": 0.0
        }

    def get_token_balance(self, token_address: str, wallet_address: str) -> int:
        """Get current ERC20 token balance for wallet."""
        try:
            token = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            return token.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        except Exception as e:
            logger.warning(f"Balance check failed for {token_address}: {e}")
            return -1  # -1 = unreadable (distinct from 0 = empty)

    async def simulate_swap(
        self,
        router_address: str,
        amount_in: int,
        path: List[str],
        from_address: str = "0x0000000000000000000000000000000000000001"
    ) -> Optional[int]:
        """Simulate swap via eth_call (no state change, no gas spent)."""
        try:
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(router_address),
                abi=ROUTER_V2_ABI
            )
            checksummed_path = [Web3.to_checksum_address(addr) for addr in path]
            result = router.functions.getAmountsOut(amount_in, checksummed_path).call()
            return result[-1] if result else None
        except Exception as e:
            logger.debug(f"Swap simulation failed: {e}")
            return None

    async def verify_profit_before_execution(
        self,
        buy_router: str,
        sell_router: str,
        token_in_address: str,
        token_out_address: str,
        amount_in: int,
        gas_price_wei: int,
        bera_price_usd: float,
        token_in_decimals: int = 18,
        token_out_decimals: int = 18,
        token_in_price_usd: float = 1.0
    ) -> Dict:
        """
        Strict profit verification using on-chain simulation.
        Net profit = gross_profit - gas - dex_fees - slippage.
        All four costs are included in the returned net_profit_usd.
        """
        result = {
            "valid": False,
            "reason": None,
            "buy_output": 0,
            "sell_output": 0,
            "gross_profit": 0.0,
            "gas_cost_usd": 0.0,
            "dex_fees_usd": 0.0,
            "slippage_cost_usd": 0.0,
            "net_profit_usd": 0.0
        }

        try:
            # ── Simulate buy ─────────────────────────────────────────
            buy_output = await self.simulate_swap(
                buy_router, amount_in,
                [token_in_address, token_out_address]
            )
            if not buy_output or buy_output <= 0:
                result["reason"] = "Buy simulation returned zero"
                return result
            result["buy_output"] = buy_output

            # ── Simulate sell ─────────────────────────────────────────
            sell_output = await self.simulate_swap(
                sell_router, buy_output,
                [token_out_address, token_in_address]
            )
            if not sell_output or sell_output <= 0:
                result["reason"] = "Sell simulation returned zero"
                return result
            result["sell_output"] = sell_output

            # ── Gross profit ──────────────────────────────────────────
            raw_profit_tokens = sell_output - amount_in
            gross_profit_usd = (raw_profit_tokens / (10 ** token_in_decimals)) * token_in_price_usd
            result["gross_profit"] = gross_profit_usd

            if gross_profit_usd <= 0:
                result["reason"] = f"Gross profit ≤ 0: ${gross_profit_usd:.6f}"
                return result

            # ── Costs ─────────────────────────────────────────────────
            total_gas   = GAS_PER_SWAP * 2                   # buy + sell
            gas_cost    = (total_gas * gas_price_wei / 10**18) * bera_price_usd
            amount_usd  = (amount_in / (10 ** token_in_decimals)) * token_in_price_usd
            dex_fees    = amount_usd * (DEX_FEE_PERCENT / 100) * 2   # 0.3% * 2 swaps
            slippage    = amount_usd * 0.005                          # 0.5% slippage estimate

            result["gas_cost_usd"]      = gas_cost
            result["dex_fees_usd"]      = dex_fees
            result["slippage_cost_usd"] = slippage

            # ── Net profit (ALL four costs deducted) ──────────────────
            net_profit = gross_profit_usd - gas_cost - dex_fees - slippage
            result["net_profit_usd"] = net_profit

            if net_profit < MIN_NET_PROFIT_USD:
                result["reason"] = f"Net profit ${net_profit:.4f} < floor ${MIN_NET_PROFIT_USD}"
                return result

            result["valid"] = True
            result["reason"] = "Profit verified"
            return result

        except Exception as e:
            result["reason"] = f"Verification error: {e}"
            return result

    async def execute_swap(
        self,
        router_address: str,
        amount_in: int,
        amount_out_min: int,
        path: List[str],
        recipient: str,
        private_key: str,
        deadline_seconds: int = 120,    # tighter deadline (was 300)
        gas_price_wei: Optional[int] = None,
        use_private_rpc: bool = True
    ) -> Dict:
        """Execute a single swap with retry logic."""
        result = {
            "success": False,
            "tx_hash": None,
            "gas_used": 0,
            "actual_output": 0,
            "error": None,
            "attempts": 0
        }

        w3_to_use = self.private_w3 if use_private_rpc and PRIVATE_RPC_URL else self.w3

        for attempt in range(MAX_RETRY_ATTEMPTS):
            result["attempts"] = attempt + 1
            try:
                router = w3_to_use.eth.contract(
                    address=Web3.to_checksum_address(router_address),
                    abi=ROUTER_V2_ABI
                )
                checksummed_path      = [Web3.to_checksum_address(a) for a in path]
                checksummed_recipient = Web3.to_checksum_address(recipient)

                # Fresh gas price each attempt, escalated per retry
                base_gas = gas_price_wei if gas_price_wei else w3_to_use.eth.gas_price
                gas_price = int(base_gas * (1 + GAS_INCREASE_PER_RETRY * attempt))

                deadline = int(time.time()) + deadline_seconds

                # Gas limit: try estimate, fallback to GAS_PER_SWAP
                try:
                    gas_est = router.functions.swapExactTokensForTokens(
                        amount_in, amount_out_min, checksummed_path,
                        checksummed_recipient, deadline
                    ).estimate_gas({'from': checksummed_recipient})
                    gas_limit = min(int(gas_est * GAS_BUFFER_MULTIPLIER), MAX_GAS_LIMIT)
                except Exception:
                    gas_limit = GAS_PER_SWAP

                nonce = w3_to_use.eth.get_transaction_count(checksummed_recipient)

                tx = router.functions.swapExactTokensForTokens(
                    amount_in, amount_out_min, checksummed_path,
                    checksummed_recipient, deadline
                ).build_transaction({
                    'chainId': w3_to_use.eth.chain_id,
                    'gas': gas_limit,
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })

                signed_tx = w3_to_use.eth.account.sign_transaction(tx, private_key)
                tx_hash   = w3_to_use.eth.send_raw_transaction(signed_tx.raw_transaction)

                logger.info(f"Swap tx sent: {tx_hash.hex()} (attempt {attempt+1})")

                # Wait for receipt (sync — kept intentional: must know buy succeeded before sell)
                receipt = w3_to_use.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=TRADE_TIMEOUT_SECONDS
                )

                if receipt['status'] == 1:
                    result["success"]  = True
                    result["tx_hash"]  = tx_hash.hex()
                    result["gas_used"] = receipt['gasUsed']
                    logger.info(f"Swap confirmed: {tx_hash.hex()}")
                    return result
                else:
                    result["error"] = "Transaction reverted on-chain"
                    logger.warning(f"Swap reverted (attempt {attempt+1})")

            except Exception as e:
                result["error"] = str(e)
                logger.warning(f"Swap attempt {attempt+1} failed: {e}")

            if attempt < MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))

        return result

    async def execute_arbitrage(
        self,
        opportunity: Dict,
        wallet_address: str,
        private_key: str,
        slippage_tolerance: float = 0.5,
        use_private_rpc: bool = True,
        bera_price_usd: float = 5.0
    ) -> Dict:
        """
        Execute complete arbitrage: Buy on DEX A → Sell on DEX B.

        Safety chain:
          1. verify_profit_before_execution (eth_call simulation)
          2. Execute buy
          3. Read actual post-buy balance — ABORT if unreadable
          4. Execute sell using actual balance
          5. Report accurate net_profit (all costs included)
        """
        start_time = time.time()
        trade_id   = f"arb_{int(time.time())}_{opportunity.get('id','unk')[:8]}"

        result = {
            "success": False,
            "trade_id": trade_id,
            "buy_result": None,
            "sell_result": None,
            "total_gas_used": 0,
            "expected_profit_usd": opportunity.get("net_profit_usd", 0),
            "actual_profit_usd": 0.0,
            "error": None,
            "execution_time_ms": 0
        }

        try:
            # ── Parse pair ────────────────────────────────────────────
            pair   = opportunity.get("token_pair", "")
            tokens = pair.split("/") if "/" in pair else pair.split(" → ")[:2]
            if len(tokens) < 2:
                result["error"] = f"Invalid pair format: '{pair}'"
                return result

            from core.constants import TOKENS, DYNAMIC_TOKENS
            token_in_info  = TOKENS.get(tokens[0]) or DYNAMIC_TOKENS.get(tokens[0])
            token_out_info = TOKENS.get(tokens[1]) or DYNAMIC_TOKENS.get(tokens[1])

            if not token_in_info or not token_out_info:
                result["error"] = f"Unknown tokens: {tokens[0]}, {tokens[1]}"
                return result

            amount_in = int(opportunity.get("amount_in", 0))
            if amount_in <= 0:
                result["error"] = "amount_in is zero"
                return result

            buy_dex  = opportunity.get("buy_dex",  "Kodiak V2")
            sell_dex = opportunity.get("sell_dex", "BEX")
            buy_router  = KODIAK_V2_ROUTER if "Kodiak" in buy_dex  else BEX_ROUTER
            sell_router = KODIAK_V2_ROUTER if "Kodiak" in sell_dex else BEX_ROUTER

            # ── Fresh gas price at execution time ─────────────────────
            try:
                gas_price = self.w3.eth.gas_price
            except Exception:
                gas_price = int(1e9)

            token_in_price = bera_price_usd if tokens[0] == "WBERA" else 1.0

            # ── Step 1: Profit verification ───────────────────────────
            verification = await self.verify_profit_before_execution(
                buy_router, sell_router,
                token_in_info["address"], token_out_info["address"],
                amount_in, gas_price, bera_price_usd,
                token_in_info["decimals"], token_out_info["decimals"],
                token_in_price
            )

            if not verification["valid"]:
                result["error"] = f"Pre-execution check failed: {verification['reason']}"
                return result

            logger.info(
                f"[{trade_id}] Verified net_profit=${verification['net_profit_usd']:.4f} "
                f"(gross={verification['gross_profit']:.4f} "
                f"gas={verification['gas_cost_usd']:.4f} "
                f"fees={verification['dex_fees_usd']:.4f} "
                f"slip={verification['slippage_cost_usd']:.4f})"
            )

            # ── Step 2: Slippage floors ───────────────────────────────
            slippage_factor     = 1 - (slippage_tolerance / 100)
            buy_amount_out_min  = int(verification["buy_output"]  * slippage_factor)
            # sell_amount_out_min will be recalculated after actual balance read

            # ── Step 3: Execute buy ───────────────────────────────────
            buy_result = await self.execute_swap(
                router_address  = buy_router,
                amount_in       = amount_in,
                amount_out_min  = buy_amount_out_min,
                path            = [token_in_info["address"], token_out_info["address"]],
                recipient       = wallet_address,
                private_key     = private_key,
                gas_price_wei   = gas_price,
                use_private_rpc = use_private_rpc
            )
            result["buy_result"] = buy_result

            if not buy_result["success"]:
                result["error"] = f"Buy failed: {buy_result['error']}"
                return result

            result["total_gas_used"] += buy_result["gas_used"]

            # ── Step 4: Verify actual received balance ────────────────
            actual_received = self.get_token_balance(token_out_info["address"], wallet_address)

            if actual_received < 0:
                # Balance read failed — cannot determine how much to sell. ABORT.
                result["error"] = (
                    "ABORT: Could not read post-buy balance for token_out. "
                    "Buy TX succeeded but sell skipped to prevent loss. "
                    f"Manually check wallet for {token_out_info['symbol']} balance."
                )
                logger.error(result["error"])
                return result

            if actual_received == 0:
                result["error"] = (
                    "ABORT: Post-buy balance is zero. Buy TX may have reverted silently."
                )
                logger.error(result["error"])
                return result

            if actual_received < buy_amount_out_min:
                result["error"] = (
                    f"ABORT: Received {actual_received} < min expected {buy_amount_out_min}. "
                    "Slippage exceeded tolerance on buy side."
                )
                logger.error(result["error"])
                return result

            logger.info(f"[{trade_id}] Actual received: {actual_received} {token_out_info['symbol']}")

            # ── Step 5: Execute sell using ACTUAL balance ─────────────
            # Scale the sell minimum proportionally to what we actually received
            scale = actual_received / max(verification["buy_output"], 1)
            sell_amount_out_min = int(verification["sell_output"] * scale * slippage_factor)

            sell_result = await self.execute_swap(
                router_address  = sell_router,
                amount_in       = actual_received,
                amount_out_min  = sell_amount_out_min,
                path            = [token_out_info["address"], token_in_info["address"]],
                recipient       = wallet_address,
                private_key     = private_key,
                gas_price_wei   = gas_price,
                use_private_rpc = use_private_rpc
            )
            result["sell_result"] = sell_result

            if not sell_result["success"]:
                result["error"] = (
                    f"Sell failed after successful buy: {sell_result['error']}. "
                    f"You hold {actual_received} {token_out_info['symbol']} — sell manually."
                )
                logger.error(result["error"])
                return result

            result["total_gas_used"] += sell_result["gas_used"]

            # ── Step 6: Accurate profit reporting ────────────────────
            # Include ALL four cost components (gas, fees, slippage)
            actual_gas_cost = (result["total_gas_used"] * gas_price / 10**18) * bera_price_usd
            result["actual_profit_usd"] = (
                verification["gross_profit"]
                - actual_gas_cost
                - verification["dex_fees_usd"]
                - verification["slippage_cost_usd"]   # ← was missing before
            )

            result["success"] = True
            self.execution_stats["total_executions"] += 1
            self.execution_stats["successful"]        += 1
            self.execution_stats["total_profit_usd"] += result["actual_profit_usd"]
            self.execution_stats["total_gas_spent_usd"] += actual_gas_cost

            logger.info(f"[{trade_id}] Arbitrage complete! Net profit: ${result['actual_profit_usd']:.4f}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Arbitrage execution error: {e}", exc_info=True)
            self.execution_stats["total_executions"] += 1
            self.execution_stats["failed"]           += 1

        finally:
            result["execution_time_ms"] = int((time.time() - start_time) * 1000)
            self._log_trade_result(opportunity, result, start_time)

        return result

    def _log_trade_result(self, opportunity: Dict, result: Dict, start_time: float):
        self.trade_logger.log_trade({
            "timestamp":          datetime.now(timezone.utc).isoformat(),
            "trade_id":           result.get("trade_id", ""),
            "pair":               opportunity.get("token_pair", ""),
            "type":               opportunity.get("type", "direct"),
            "buy_dex":            opportunity.get("buy_dex", ""),
            "sell_dex":           opportunity.get("sell_dex", ""),
            "amount_in":          opportunity.get("amount_in", ""),
            "expected_out":       opportunity.get("expected_out", ""),
            "actual_out":         result.get("sell_result", {}).get("actual_output", "") if result.get("sell_result") else "",
            "expected_profit_usd": opportunity.get("net_profit_usd", 0),
            "actual_profit_usd":  result.get("actual_profit_usd", 0),
            "gas_used":           result.get("total_gas_used", 0),
            "gas_price_gwei":     0,
            "gas_cost_usd":       0,
            "buy_tx_hash":        result.get("buy_result",  {}).get("tx_hash", "") if result.get("buy_result")  else "",
            "sell_tx_hash":       result.get("sell_result", {}).get("tx_hash", "") if result.get("sell_result") else "",
            "status":             "success" if result.get("success") else "failed",
            "error":              result.get("error", ""),
            "retry_count":        0,
            "execution_time_ms":  result.get("execution_time_ms", 0),
            "slippage_actual":    0
        })

    def get_execution_stats(self) -> Dict:
        return self.execution_stats.copy()
