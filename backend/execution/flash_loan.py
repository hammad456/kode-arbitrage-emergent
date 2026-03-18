"""
Flash Loan / Flash Swap Executor — Production Grade
=====================================================
Menggunakan FlashArbitrage.sol yang sudah dideploy di Berachain.

Flow:
  1. Bot scan peluang arbitrase (multicall_scanner.py)
  2. Pre-check profitability (simulate off-chain)
  3. Encode params → panggil executeFlashArbitrage() on contract
  4. Contract pinjam modal, eksekusi, kembalikan
  5. Profit otomatis tersimpan di contract
  6. Bot panggil withdrawToken() untuk ambil profit

Keamanan:
  - Jika profit < minProfit → TX revert (modal aman, hanya bayar gas)
  - onlyAuthorized pada semua fungsi eksekusi
  - nonReentrant pada semua state-changing functions
"""

import logging
import time
import json
import os
from typing import Dict, List, Optional, Any
from pathlib import Path
from web3 import Web3
from eth_abi import encode

from core.constants import (
    KODIAK_V2_FACTORY, KODIAK_V2_ROUTER, KODIAK_V3_ROUTER, BEX_ROUTER,
    DEX_FEE_PERCENT, GAS_BUFFER_MULTIPLIER, MAX_GAS_LIMIT,
    TOKENS, BEX_QUERY
)
from core.abis import FLASH_PAIR_ABI, FACTORY_ABI, ROUTER_V2_ABI

logger = logging.getLogger(__name__)

# ─── DEX Enum Values (harus match dengan Solidity DEX enum) ───────────────────
DEX_KODIAK_V2 = 0
DEX_KODIAK_V3 = 1
DEX_BEX       = 2

DEX_NAME_TO_INT = {
    "Kodiak V2": DEX_KODIAK_V2,
    "Kodiak V3": DEX_KODIAK_V3,
    "BEX":       DEX_BEX,
}

DEX_INT_TO_NAME = {v: k for k, v in DEX_NAME_TO_INT.items()}

# ─── Load ABI dari compiled contract ──────────────────────────────────────────
_ABI_PATH = Path(__file__).parent.parent / "contracts" / "FlashArbitrage.json"
_FLASH_ARB_ABI_CACHE = None

def get_flash_arb_abi() -> Optional[list]:
    """Load ABI FlashArbitrage dari compiled JSON"""
    global _FLASH_ARB_ABI_CACHE
    if _FLASH_ARB_ABI_CACHE is not None:
        return _FLASH_ARB_ABI_CACHE
    if _ABI_PATH.exists():
        data = json.loads(_ABI_PATH.read_text())
        _FLASH_ARB_ABI_CACHE = data.get("abi")
        return _FLASH_ARB_ABI_CACHE
    logger.warning(f"FlashArbitrage ABI not found at {_ABI_PATH}. Run compile_deploy.py --compile first.")
    return None

# Minimal ABI hardcoded sebagai fallback jika belum dikompilasi
FLASH_ARB_ABI_MINIMAL = [
    # executeFlashArbitrage
    {
        "inputs": [
            {"name": "flashPair",     "type": "address"},
            {"name": "tokenBorrow",   "type": "address"},
            {"name": "borrowAmount",  "type": "uint256"},
            {"name": "sellDex",       "type": "uint8"},
            {"name": "buyDex",        "type": "uint8"},
            {"name": "minProfit",     "type": "uint256"},
        ],
        "name": "executeFlashArbitrage",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # executeDirectArbitrage
    {
        "inputs": [
            {"components": [
                {"name": "tokenIn",      "type": "address"},
                {"name": "tokenOut",     "type": "address"},
                {"name": "amountIn",     "type": "uint256"},
                {"name": "buyDex",       "type": "uint8"},
                {"name": "sellDex",      "type": "uint8"},
                {"name": "minProfitAmt", "type": "uint256"},
            ], "name": "params", "type": "tuple"}
        ],
        "name": "executeDirectArbitrage",
        "outputs": [{"name": "profit", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # checkArbitrageProfitability
    {
        "inputs": [
            {"name": "tokenIn",  "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "buyDex",   "type": "uint8"},
            {"name": "sellDex",  "type": "uint8"},
        ],
        "name": "checkArbitrageProfitability",
        "outputs": [
            {"name": "profitable",      "type": "bool"},
            {"name": "expectedProfit",  "type": "uint256"},
            {"name": "buyOutput",       "type": "uint256"},
            {"name": "sellOutput",      "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function"
    },
    # withdrawToken
    {
        "inputs": [{"name": "token", "type": "address"}],
        "name": "withdrawToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # withdrawTokens (batch)
    {
        "inputs": [{"name": "tokens", "type": "address[]"}],
        "name": "withdrawTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # depositToken
    {
        "inputs": [
            {"name": "token",  "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "depositToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # getTokenBalance
    {
        "inputs": [{"name": "token", "type": "address"}],
        "name": "getTokenBalance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    # calcFlashRepayment
    {
        "inputs": [{"name": "borrowAmount", "type": "uint256"}],
        "name": "calcFlashRepayment",
        "outputs": [{"name": "repayAmount", "type": "uint256"}],
        "stateMutability": "pure",
        "type": "function"
    },
    # owner
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    # paused
    {
        "inputs": [],
        "name": "paused",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    # minProfitBps
    {
        "inputs": [],
        "name": "minProfitBps",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    # setMinProfitBps
    {
        "inputs": [{"name": "bps", "type": "uint256"}],
        "name": "setMinProfitBps",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # setBot
    {
        "inputs": [
            {"name": "bot",        "type": "address"},
            {"name": "authorized", "type": "bool"}
        ],
        "name": "setBot",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # setPaused
    {
        "inputs": [{"name": "state", "type": "bool"}],
        "name": "setPaused",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    # Events
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "tokenBorrow", "type": "address"},
            {"indexed": True,  "name": "tokenOther",  "type": "address"},
            {"indexed": False, "name": "borrowAmount","type": "uint256"},
            {"indexed": False, "name": "profit",      "type": "uint256"},
            {"indexed": False, "name": "sellDex",     "type": "uint8"},
            {"indexed": False, "name": "buyDex",      "type": "uint8"},
            {"indexed": False, "name": "blockNumber", "type": "uint256"},
        ],
        "name": "FlashArbExecuted",
        "type": "event"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "tokenIn",    "type": "address"},
            {"indexed": True,  "name": "tokenOut",   "type": "address"},
            {"indexed": False, "name": "amountIn",   "type": "uint256"},
            {"indexed": False, "name": "profit",     "type": "uint256"},
            {"indexed": False, "name": "buyDex",     "type": "uint8"},
            {"indexed": False, "name": "sellDex",    "type": "uint8"},
            {"indexed": False, "name": "blockNumber","type": "uint256"},
        ],
        "name": "DirectArbExecuted",
        "type": "event"
    },
]


class FlashLoanExecutor:
    """
    Production Flash Loan Executor menggunakan FlashArbitrage.sol

    Lifecycle:
      1. set_contract_address(addr)  — setelah deploy
      2. simulate_flash_arbitrage()  — pre-check off-chain
      3. execute_flash_arbitrage()   — eksekusi on-chain
      4. withdraw_profits()          — tarik profit ke wallet
    """

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.contract_address: Optional[str] = os.environ.get("FLASH_ARB_CONTRACT", "")
        self._contract = None

        # Load contract address dari deployed_contracts.json jika ada
        deployed_path = Path(__file__).parent.parent / "contracts" / "deployed_contracts.json"
        if not self.contract_address and deployed_path.exists():
            try:
                deployed = json.loads(deployed_path.read_text())
                chain_id = str(w3.eth.chain_id)
                if chain_id in deployed:
                    self.contract_address = deployed[chain_id].get("FlashArbitrage", "")
                    if self.contract_address:
                        logger.info(f"Loaded FlashArbitrage address from deployed_contracts.json: {self.contract_address}")
            except Exception as e:
                logger.warning(f"Could not load deployed_contracts.json: {e}")

        if self.contract_address:
            self._init_contract()

    def _init_contract(self):
        """Initialize contract instance"""
        try:
            abi = get_flash_arb_abi() or FLASH_ARB_ABI_MINIMAL
            self._contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.contract_address),
                abi=abi
            )
            logger.info(f"FlashArbitrage contract initialized: {self.contract_address}")
        except Exception as e:
            logger.error(f"Failed to init FlashArbitrage contract: {e}")
            self._contract = None

    def set_contract_address(self, address: str):
        """Set deployed contract address"""
        self.contract_address = address
        self._init_contract()

    def is_ready(self) -> bool:
        """Cek apakah contract sudah dikonfigurasi"""
        return self._contract is not None and bool(self.contract_address)

    # ─── SIMULASI OFF-CHAIN ────────────────────────────────────────────────────

    async def simulate_flash_arbitrage(
        self,
        flash_data: Dict,
        gas_price_wei: int,
        bera_price_usd: float
    ) -> Dict:
        """
        Simulasi lengkap flash arbitrase.
        Panggil ini SEBELUM eksekusi untuk verifikasi profitabilitas.

        Returns:
          profitable     : bool
          reason         : str
          borrow_amount  : int
          repay_amount   : int
          expected_return: int
          net_profit_usd : float
          gas_estimate   : int
        """
        result = {
            "profitable": False,
            "reason": None,
            "borrow_amount": flash_data.get("borrow_amount", 0),
            "repay_amount": flash_data.get("repay_amount", 0),
            "expected_return": 0,
            "net_profit_usd": 0,
            "gas_estimate": 0
        }

        try:
            pair_addr = flash_data.get("pair_address", "")
            token_in  = flash_data.get("token_in", "")
            token_out = flash_data.get("token_out", "")
            borrow    = flash_data.get("borrow_amount", 0)

            if not all([pair_addr, token_in, token_out, borrow]):
                result["reason"] = "Missing flash_data fields"
                return result

            # ─ Check 1: Likuiditas pair mencukupi ─────────────────────────────
            pair_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(pair_addr),
                abi=FLASH_PAIR_ABI
            )
            reserves = pair_contract.functions.getReserves().call()
            token0   = pair_contract.functions.token0().call()

            avail = reserves[0] if token0.lower() == token_in.lower() else reserves[1]

            # Flash swap max 30% pool
            if borrow > avail * 0.3:
                result["reason"] = f"Insufficient liquidity: need {borrow}, have {avail * 0.3:.0f} (30% of pool)"
                return result

            # ─ Check 2: Simulasi sell di sell_router ──────────────────────────
            sell_router = flash_data.get("sell_router", KODIAK_V2_ROUTER)
            sell_on_bex = flash_data.get("sell_on_bex", False)

            if not sell_on_bex:
                router_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(sell_router),
                    abi=ROUTER_V2_ABI
                )
                sell_path = [
                    Web3.to_checksum_address(token_in),
                    Web3.to_checksum_address(token_out)
                ]
                sell_amounts = router_contract.functions.getAmountsOut(
                    borrow, sell_path
                ).call()
                token_other_received = sell_amounts[-1]
            else:
                # BEX previewSwap (async, import dari scanner)
                from scanner.multicall_scanner import RealPriceScanner
                scanner = RealPriceScanner(self.w3)
                token_other_received = await scanner.get_bex_quote(
                    token_in, token_out, borrow
                ) or 0

            if token_other_received == 0:
                result["reason"] = "Sell step simulation failed"
                return result

            # ─ Check 3: Simulasi buy kembali di buy_router ────────────────────
            buy_router = flash_data.get("buy_router", KODIAK_V2_ROUTER)
            buy_on_bex = flash_data.get("buy_on_bex", False)

            repay_amount = (borrow * 1003) // 1000 + 1
            result["repay_amount"] = repay_amount

            if not buy_on_bex:
                router_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(buy_router),
                    abi=ROUTER_V2_ABI
                )
                buy_path = [
                    Web3.to_checksum_address(token_out),
                    Web3.to_checksum_address(token_in)
                ]
                buy_amounts = router_contract.functions.getAmountsOut(
                    token_other_received, buy_path
                ).call()
                token_in_returned = buy_amounts[-1]
            else:
                from scanner.multicall_scanner import RealPriceScanner
                scanner = RealPriceScanner(self.w3)
                token_in_returned = await scanner.get_bex_quote(
                    token_out, token_in, token_other_received
                ) or 0

            result["expected_return"] = token_in_returned

            # ─ Check 4: Verifikasi profit ─────────────────────────────────────
            if token_in_returned < repay_amount:
                result["reason"] = (
                    f"Cannot repay: returned {token_in_returned} < "
                    f"repay {repay_amount}"
                )
                return result

            profit_raw = token_in_returned - repay_amount

            # Gas estimate untuk flash swap (~400k)
            gas_estimate = 400_000
            result["gas_estimate"] = gas_estimate

            gas_cost_usd = (gas_estimate * gas_price_wei / 10**18) * bera_price_usd

            # Konversi profit ke USD
            token_in_info = next(
                (t for t in TOKENS.values() if t["address"].lower() == token_in.lower()),
                None
            )
            token_decimals = token_in_info["decimals"] if token_in_info else 18
            # Assume stablecoin profit = USD 1:1 jika bukan WBERA
            is_wbera = token_in.lower() == "0x6969696969696969696969696969696969696969"
            token_price = bera_price_usd if is_wbera else 1.0

            profit_usd = (profit_raw / 10**token_decimals) * token_price - gas_cost_usd
            result["net_profit_usd"] = profit_usd

            if profit_usd <= 0:
                result["reason"] = f"Not profitable after gas: ${profit_usd:.4f}"
                return result

            result["profitable"] = True
            result["reason"] = (
                f"Flash arb viable: borrow {borrow}, "
                f"profit ${profit_usd:.4f} USD"
            )
            return result

        except Exception as e:
            result["reason"] = f"Simulation error: {str(e)}"
            logger.error(f"Flash arb simulation error: {e}")
            return result

    # ─── EKSEKUSI ON-CHAIN ─────────────────────────────────────────────────────

    async def execute_flash_arbitrage(
        self,
        opportunity: Dict,
        wallet_address: str,
        private_key: str,
        gas_price_wei: Optional[int] = None,
        bera_price_usd: float = 5.0
    ) -> Dict:
        """
        Eksekusi flash arbitrage via FlashArbitrage.sol contract.

        Args:
          opportunity    : Dict dari scanner (buy_dex, sell_dex, token_pair, dll)
          wallet_address : Address wallet bot
          private_key    : Private key untuk sign TX
          gas_price_wei  : Override gas price (opsional)
          bera_price_usd : Harga BERA untuk kalkulasi biaya

        Returns:
          Dict dengan status, tx_hash, profit, gas_used
        """
        result = {
            "success": False,
            "tx_hash": None,
            "profit_usd": 0,
            "gas_used": 0,
            "error": None,
        }

        if not self.is_ready():
            result["error"] = (
                "FlashArbitrage contract not configured. "
                "Deploy contract dan set FLASH_ARB_CONTRACT di .env"
            )
            return result

        try:
            # ─ Parse opportunity ──────────────────────────────────────────────
            pair      = opportunity.get("token_pair", "")
            tokens    = pair.split("/") if "/" in pair else []
            if len(tokens) < 2:
                result["error"] = f"Invalid pair format: {pair}"
                return result

            symbol_in   = tokens[0]
            symbol_out  = tokens[1]
            token_in    = TOKENS.get(symbol_in)
            token_out   = TOKENS.get(symbol_out)

            if not token_in or not token_out:
                result["error"] = f"Unknown tokens: {symbol_in}/{symbol_out}"
                return result

            amount_in   = int(opportunity.get("amount_in", 0))
            buy_dex_name  = opportunity.get("buy_dex", "Kodiak V2")
            sell_dex_name = opportunity.get("sell_dex", "Kodiak V2")

            buy_dex_int  = DEX_NAME_TO_INT.get(buy_dex_name,  DEX_KODIAK_V2)
            sell_dex_int = DEX_NAME_TO_INT.get(sell_dex_name, DEX_KODIAK_V2)

            # ─ Cari pair address untuk flash swap ─────────────────────────────
            factory = self.w3.eth.contract(
                address=Web3.to_checksum_address(KODIAK_V2_FACTORY),
                abi=FACTORY_ABI
            )
            pair_address = factory.functions.getPair(
                Web3.to_checksum_address(token_in["address"]),
                Web3.to_checksum_address(token_out["address"])
            ).call()

            if pair_address == "0x0000000000000000000000000000000000000000":
                result["error"] = f"No Kodiak V2 pair found for {pair}"
                return result

            # ─ Set minimum profit ─────────────────────────────────────────────
            # Minimal 0.1% dari amount_in sebagai profit floor
            min_profit = (amount_in * 10) // 10000  # 0.1%

            # ─ Get gas price ──────────────────────────────────────────────────
            if gas_price_wei is None:
                gas_price_wei = self.w3.eth.gas_price
            gas_price = int(gas_price_wei * 1.2)  # 20% buffer

            # ─ Estimate gas ───────────────────────────────────────────────────
            try:
                gas_estimate = self._contract.functions.executeFlashArbitrage(
                    Web3.to_checksum_address(pair_address),
                    Web3.to_checksum_address(token_in["address"]),
                    amount_in,
                    sell_dex_int,
                    buy_dex_int,
                    min_profit
                ).estimate_gas({"from": Web3.to_checksum_address(wallet_address)})
                gas_limit = min(int(gas_estimate * 1.3), MAX_GAS_LIMIT)
            except Exception as e:
                logger.warning(f"Gas estimation failed: {e}, using 500k")
                gas_limit = 500_000

            # ─ Build Transaction ──────────────────────────────────────────────
            nonce = self.w3.eth.get_transaction_count(
                Web3.to_checksum_address(wallet_address)
            )

            tx = self._contract.functions.executeFlashArbitrage(
                Web3.to_checksum_address(pair_address),
                Web3.to_checksum_address(token_in["address"]),
                amount_in,
                sell_dex_int,
                buy_dex_int,
                min_profit
            ).build_transaction({
                "chainId":  self.w3.eth.chain_id,
                "gas":      gas_limit,
                "gasPrice": gas_price,
                "nonce":    nonce,
            })

            # ─ Sign & Send ────────────────────────────────────────────────────
            signed = self.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

            logger.info(f"Flash arb TX sent: {tx_hash.hex()}")

            # ─ Wait for receipt ───────────────────────────────────────────────
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                gas_used = receipt["gasUsed"]
                gas_cost = (gas_used * gas_price / 10**18) * bera_price_usd

                # Parse FlashArbExecuted event untuk profit aktual
                profit_raw = 0
                try:
                    events = self._contract.events.FlashArbExecuted().process_receipt(receipt)
                    if events:
                        profit_raw = events[0]["args"]["profit"]
                        decimals   = token_in.get("decimals", 18)
                        is_wbera   = token_in["address"].lower() == "0x6969696969696969696969696969696969696969"
                        t_price    = bera_price_usd if is_wbera else 1.0
                        profit_usd = (profit_raw / 10**decimals) * t_price - gas_cost
                        result["profit_usd"] = profit_usd
                        result["profit_raw"] = profit_raw
                except Exception as ev_err:
                    logger.warning(f"Could not parse profit event: {ev_err}")

                result.update({
                    "success":  True,
                    "tx_hash":  tx_hash.hex(),
                    "gas_used": gas_used,
                    "block":    receipt["blockNumber"],
                })
                logger.info(f"Flash arb SUCCESS! Profit: ${result['profit_usd']:.4f}")
            else:
                result["error"] = f"TX reverted: {tx_hash.hex()}"
                logger.warning(f"Flash arb reverted: {tx_hash.hex()}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Flash arb execution error: {e}")

        return result

    # ─── DIRECT ARBITRAGE ─────────────────────────────────────────────────────

    async def execute_direct_arbitrage(
        self,
        opportunity: Dict,
        wallet_address: str,
        private_key: str,
        gas_price_wei: Optional[int] = None,
        bera_price_usd: float = 5.0
    ) -> Dict:
        """Execute direct arbitrage menggunakan modal yang ada di contract"""
        result = {
            "success": False,
            "tx_hash": None,
            "profit_usd": 0,
            "gas_used": 0,
            "error": None,
        }

        if not self.is_ready():
            result["error"] = "FlashArbitrage contract not configured"
            return result

        try:
            pair = opportunity.get("token_pair", "")
            tokens = pair.split("/") if "/" in pair else []
            if len(tokens) < 2:
                result["error"] = f"Invalid pair: {pair}"
                return result

            token_in   = TOKENS.get(tokens[0])
            token_out  = TOKENS.get(tokens[1])
            if not token_in or not token_out:
                result["error"] = "Unknown tokens"
                return result

            amount_in    = int(opportunity.get("amount_in", 0))
            buy_dex_int  = DEX_NAME_TO_INT.get(opportunity.get("buy_dex",  "Kodiak V2"), DEX_KODIAK_V2)
            sell_dex_int = DEX_NAME_TO_INT.get(opportunity.get("sell_dex", "Kodiak V2"), DEX_KODIAK_V2)
            min_profit   = int(amount_in * 0.001)  # 0.1% minimum

            # Check contract balance
            contract_balance = self._contract.functions.getTokenBalance(
                Web3.to_checksum_address(token_in["address"])
            ).call()

            if contract_balance < amount_in:
                result["error"] = (
                    f"Contract balance insufficient: "
                    f"have {contract_balance}, need {amount_in}"
                )
                return result

            if gas_price_wei is None:
                gas_price_wei = self.w3.eth.gas_price
            gas_price = int(gas_price_wei * 1.2)

            params_tuple = (
                Web3.to_checksum_address(token_in["address"]),
                Web3.to_checksum_address(token_out["address"]),
                amount_in,
                buy_dex_int,
                sell_dex_int,
                min_profit,
            )

            nonce = self.w3.eth.get_transaction_count(
                Web3.to_checksum_address(wallet_address)
            )

            try:
                gas_estimate = self._contract.functions.executeDirectArbitrage(
                    params_tuple
                ).estimate_gas({"from": Web3.to_checksum_address(wallet_address)})
                gas_limit = min(int(gas_estimate * 1.3), MAX_GAS_LIMIT)
            except Exception:
                gas_limit = 400_000

            tx = self._contract.functions.executeDirectArbitrage(
                params_tuple
            ).build_transaction({
                "chainId":  self.w3.eth.chain_id,
                "gas":      gas_limit,
                "gasPrice": gas_price,
                "nonce":    nonce,
            })

            signed  = self.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                gas_used  = receipt["gasUsed"]
                gas_cost  = (gas_used * gas_price / 10**18) * bera_price_usd

                try:
                    events = self._contract.events.DirectArbExecuted().process_receipt(receipt)
                    if events:
                        profit_raw = events[0]["args"]["profit"]
                        t_price    = bera_price_usd if tokens[0] == "WBERA" else 1.0
                        profit_usd = (profit_raw / 10**token_in["decimals"]) * t_price - gas_cost
                        result["profit_usd"] = profit_usd
                except Exception:
                    pass

                result.update({
                    "success": True,
                    "tx_hash": tx_hash.hex(),
                    "gas_used": gas_used,
                })
            else:
                result["error"] = f"TX reverted: {tx_hash.hex()}"

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Direct arb error: {e}")

        return result

    # ─── PROFIT WITHDRAWAL ────────────────────────────────────────────────────

    async def withdraw_all_profits(
        self,
        wallet_address: str,
        private_key: str,
        gas_price_wei: Optional[int] = None
    ) -> Dict:
        """Tarik semua profit dari contract ke wallet"""
        if not self.is_ready():
            return {"success": False, "error": "Contract not configured"}

        token_addresses = [t["address"] for t in TOKENS.values()]

        if gas_price_wei is None:
            gas_price_wei = self.w3.eth.gas_price

        nonce = self.w3.eth.get_transaction_count(
            Web3.to_checksum_address(wallet_address)
        )

        tx = self._contract.functions.withdrawTokens(
            [Web3.to_checksum_address(a) for a in token_addresses]
        ).build_transaction({
            "chainId":  self.w3.eth.chain_id,
            "gas":      200_000,
            "gasPrice": gas_price_wei,
            "nonce":    nonce,
        })

        signed  = self.w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        return {
            "success":  receipt["status"] == 1,
            "tx_hash":  tx_hash.hex(),
            "gas_used": receipt["gasUsed"],
        }

    # ─── UTILITY ──────────────────────────────────────────────────────────────

    def get_contract_balances(self) -> Dict[str, float]:
        """Cek saldo semua token di contract"""
        if not self.is_ready():
            return {}

        balances = {}
        for symbol, token in TOKENS.items():
            try:
                raw = self._contract.functions.getTokenBalance(
                    Web3.to_checksum_address(token["address"])
                ).call()
                balances[symbol] = raw / 10**token["decimals"]
            except Exception:
                balances[symbol] = 0.0

        return balances

    def get_contract_info(self) -> Dict:
        """Get informasi contract"""
        if not self.is_ready():
            return {"deployed": False, "address": None}

        try:
            owner      = self._contract.functions.owner().call()
            paused     = self._contract.functions.paused().call()
            min_bps    = self._contract.functions.minProfitBps().call()
            balances   = self.get_contract_balances()

            return {
                "deployed":     True,
                "address":      self.contract_address,
                "owner":        owner,
                "paused":       paused,
                "min_profit_bps": min_bps,
                "min_profit_pct": min_bps / 100,
                "balances":     balances,
            }
        except Exception as e:
            return {"deployed": True, "address": self.contract_address, "error": str(e)}

    # ─── LEGACY: Prepare flash data (untuk kompatibilitas) ────────────────────

    async def prepare_flash_arbitrage_data(
        self,
        opportunity: Dict,
        wallet_address: str
    ) -> Optional[Dict]:
        """Legacy helper untuk prepare flash arbitrage data"""
        try:
            pair = opportunity.get("token_pair", "")
            tokens = pair.split("/") if "/" in pair else []
            if len(tokens) < 2:
                return None

            token_in_info  = TOKENS.get(tokens[0])
            token_out_info = TOKENS.get(tokens[1])
            if not token_in_info or not token_out_info:
                return None

            amount_in  = int(opportunity.get("amount_in", 0))
            buy_dex    = opportunity.get("buy_dex",  "Kodiak V2")
            sell_dex   = opportunity.get("sell_dex", "Kodiak V2")

            factory = self.w3.eth.contract(
                address=Web3.to_checksum_address(KODIAK_V2_FACTORY),
                abi=FACTORY_ABI
            )
            pair_address = factory.functions.getPair(
                Web3.to_checksum_address(token_in_info["address"]),
                Web3.to_checksum_address(token_out_info["address"])
            ).call()

            if pair_address == "0x0000000000000000000000000000000000000000":
                return None

            repay_amount  = (amount_in * 1003) // 1000 + 1
            buy_router    = KODIAK_V2_ROUTER if "Kodiak" in buy_dex  else BEX_ROUTER
            sell_router   = KODIAK_V2_ROUTER if "Kodiak" in sell_dex else BEX_ROUTER

            return {
                "pair_address":   pair_address,
                "token_in":       token_in_info["address"],
                "token_out":      token_out_info["address"],
                "borrow_amount":  amount_in,
                "repay_amount":   repay_amount,
                "buy_router":     buy_router,
                "sell_router":    sell_router,
                "buy_on_bex":     buy_dex == "BEX",
                "sell_on_bex":    sell_dex == "BEX",
                "estimated_profit": opportunity.get("net_profit_usd", 0),
                "contract_address": self.contract_address or "NOT_DEPLOYED",
            }
        except Exception as e:
            logger.error(f"prepare_flash_arbitrage_data error: {e}")
            return None

    def get_flash_arbitrage_contract_bytecode(self) -> str:
        """Return path ke contract source untuk deployment"""
        sol_path = Path(__file__).parent.parent / "contracts" / "FlashArbitrage.sol"
        if sol_path.exists():
            return f"# Contract source: {sol_path}\n# Compile dengan: python contracts/compile_deploy.py --compile"
        return "# FlashArbitrage.sol not found"
