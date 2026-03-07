"""
Flash Loan / Flash Swap Support for Capital-Efficient Arbitrage
Borrows liquidity, executes multi-hop arbitrage, and repays within single transaction
"""
import logging
from typing import Dict, List, Optional, Any
from web3 import Web3
from eth_abi import encode

from core.constants import (
    KODIAK_V2_FACTORY, KODIAK_V2_ROUTER, BEX_ROUTER,
    DEX_FEE_PERCENT, GAS_BUFFER_MULTIPLIER, MAX_GAS_LIMIT
)
from core.abis import FLASH_PAIR_ABI, FACTORY_ABI, ROUTER_V2_ABI

logger = logging.getLogger(__name__)


class FlashLoanExecutor:
    """
    Flash Loan/Swap Executor for capital-efficient arbitrage.
    
    Supports:
    1. Uniswap V2 style flash swaps (borrow from LP, repay with profit)
    2. Multi-hop arbitrage within single transaction
    3. Zero upfront capital requirement
    
    Note: Requires a deployed FlashArbitrage contract on Berachain.
    This class prepares the transaction data for such a contract.
    """
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.flash_arb_contract = None  # Set when deployed
    
    def calculate_flash_loan_repayment(
        self,
        borrow_amount: int,
        fee_percent: float = 0.3
    ) -> int:
        """
        Calculate amount needed to repay flash loan.
        Standard Uniswap V2 flash swap fee is 0.3%.
        """
        fee = int(borrow_amount * fee_percent / 100)
        return borrow_amount + fee
    
    async def get_pair_address(
        self,
        token_a: str,
        token_b: str,
        factory: str = KODIAK_V2_FACTORY
    ) -> Optional[str]:
        """Get pair address for flash swap"""
        try:
            factory_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(factory),
                abi=FACTORY_ABI
            )
            pair_address = factory_contract.functions.getPair(
                Web3.to_checksum_address(token_a),
                Web3.to_checksum_address(token_b)
            ).call()
            
            if pair_address == "0x0000000000000000000000000000000000000000":
                return None
            return pair_address
        except Exception as e:
            logger.error(f"Get pair error: {e}")
            return None
    
    async def prepare_flash_arbitrage_data(
        self,
        opportunity: Dict,
        wallet_address: str
    ) -> Optional[Dict]:
        """
        Prepare data for flash arbitrage execution.
        
        Flash Swap Flow:
        1. Borrow token_out from LP pair
        2. Swap token_out -> token_in on DEX B (sell)
        3. Repay borrowed token_out + fee with token_in profit
        
        Returns transaction data for FlashArbitrage contract.
        """
        try:
            from core.constants import TOKENS
            
            pair = opportunity.get("token_pair", "")
            tokens = pair.split("/") if "/" in pair else pair.split(" → ")[:2]
            
            if len(tokens) < 2:
                return None
            
            token_in_info = TOKENS.get(tokens[0])
            token_out_info = TOKENS.get(tokens[1])
            
            if not token_in_info or not token_out_info:
                return None
            
            amount_in = int(opportunity.get("amount_in", 0))
            buy_dex = opportunity.get("buy_dex", "Kodiak V2")
            sell_dex = opportunity.get("sell_dex", "BEX")
            
            # Get pair for flash swap
            pair_address = await self.get_pair_address(
                token_in_info["address"],
                token_out_info["address"]
            )
            
            if not pair_address:
                logger.warning("No pair found for flash swap")
                return None
            
            # Get routers
            buy_router = KODIAK_V2_ROUTER if "Kodiak" in buy_dex else BEX_ROUTER
            sell_router = KODIAK_V2_ROUTER if "Kodiak" in sell_dex else BEX_ROUTER
            
            # Calculate repayment amount (borrow + 0.3% fee)
            expected_borrow = int(opportunity.get("expected_out", 0))
            repay_amount = self.calculate_flash_loan_repayment(expected_borrow)
            
            # Encode callback data for flash swap
            # This data tells the callback what to do:
            # - Swap borrowed tokens on target DEX
            # - Calculate profit
            # - Repay original pair
            callback_data = encode(
                ['address', 'address', 'address', 'address', 'uint256', 'uint256'],
                [
                    Web3.to_checksum_address(token_in_info["address"]),
                    Web3.to_checksum_address(token_out_info["address"]),
                    Web3.to_checksum_address(sell_router),
                    Web3.to_checksum_address(wallet_address),
                    amount_in,
                    repay_amount
                ]
            )
            
            return {
                "pair_address": pair_address,
                "token_in": token_in_info["address"],
                "token_out": token_out_info["address"],
                "borrow_amount": expected_borrow,
                "repay_amount": repay_amount,
                "buy_router": buy_router,
                "sell_router": sell_router,
                "callback_data": callback_data.hex(),
                "estimated_profit": opportunity.get("net_profit_usd", 0),
                "flash_swap_fee_percent": DEX_FEE_PERCENT
            }
            
        except Exception as e:
            logger.error(f"Prepare flash arb error: {e}")
            return None
    
    async def simulate_flash_arbitrage(
        self,
        flash_data: Dict,
        gas_price_wei: int,
        bera_price_usd: float
    ) -> Dict:
        """
        Simulate flash arbitrage to verify profitability.
        
        Checks:
        1. Borrow is possible (sufficient liquidity)
        2. Sell gives enough to repay
        3. Net profit > gas cost
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
            # Get pair reserves to check liquidity
            pair_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(flash_data["pair_address"]),
                abi=FLASH_PAIR_ABI
            )
            
            reserves = pair_contract.functions.getReserves().call()
            token0 = pair_contract.functions.token0().call()
            
            # Determine which reserve is our borrow token
            if token0.lower() == flash_data["token_out"].lower():
                available_liquidity = reserves[0]
            else:
                available_liquidity = reserves[1]
            
            borrow_amount = flash_data["borrow_amount"]
            
            # Check if enough liquidity
            if borrow_amount > available_liquidity * 0.3:  # Max 30% of pool
                result["reason"] = "Insufficient liquidity for flash swap"
                return result
            
            # Simulate sell to get return amount
            sell_router = self.w3.eth.contract(
                address=Web3.to_checksum_address(flash_data["sell_router"]),
                abi=ROUTER_V2_ABI
            )
            
            sell_path = [
                Web3.to_checksum_address(flash_data["token_out"]),
                Web3.to_checksum_address(flash_data["token_in"])
            ]
            
            sell_amounts = sell_router.functions.getAmountsOut(
                borrow_amount, sell_path
            ).call()
            
            expected_return = sell_amounts[-1]
            result["expected_return"] = expected_return
            
            # Check if sell output covers repayment
            repay_amount = flash_data["repay_amount"]
            
            if expected_return < repay_amount:
                result["reason"] = f"Sell return {expected_return} < repay {repay_amount}"
                return result
            
            # Calculate profit
            profit_raw = expected_return - repay_amount
            
            # Estimate gas (flash swap is more complex)
            gas_estimate = 400000
            result["gas_estimate"] = gas_estimate
            
            gas_cost_usd = (gas_estimate * gas_price_wei / 10**18) * bera_price_usd
            
            # Assume token_in is BERA for simplicity
            profit_usd = (profit_raw / 10**18) * bera_price_usd - gas_cost_usd
            result["net_profit_usd"] = profit_usd
            
            if profit_usd <= 0:
                result["reason"] = f"Not profitable after gas: ${profit_usd:.4f}"
                return result
            
            result["profitable"] = True
            result["reason"] = "Flash arbitrage viable"
            return result
            
        except Exception as e:
            result["reason"] = f"Simulation error: {str(e)}"
            return result
    
    def get_flash_arbitrage_contract_bytecode(self) -> str:
        """
        Returns sample FlashArbitrage contract bytecode for deployment.
        
        Note: This is a placeholder. In production, you would deploy
        a custom FlashArbitrage contract that:
        1. Receives flash swap callback from Uniswap V2 pair
        2. Executes arbitrage swaps
        3. Repays flash loan with profit
        4. Sends remaining profit to owner
        """
        # Simplified contract structure (deploy separately)
        return """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.0;
        
        interface IUniswapV2Pair {
            function swap(uint amount0Out, uint amount1Out, address to, bytes calldata data) external;
            function token0() external view returns (address);
            function token1() external view returns (address);
        }
        
        interface IUniswapV2Router {
            function swapExactTokensForTokens(
                uint amountIn, uint amountOutMin, address[] calldata path,
                address to, uint deadline
            ) external returns (uint[] memory amounts);
        }
        
        interface IERC20 {
            function transfer(address to, uint value) external returns (bool);
            function balanceOf(address owner) external view returns (uint);
            function approve(address spender, uint value) external returns (bool);
        }
        
        contract FlashArbitrage {
            address public owner;
            
            constructor() {
                owner = msg.sender;
            }
            
            function executeFlashArbitrage(
                address pair,
                uint amount0Out,
                uint amount1Out,
                bytes calldata data
            ) external {
                require(msg.sender == owner, "Only owner");
                IUniswapV2Pair(pair).swap(amount0Out, amount1Out, address(this), data);
            }
            
            // Callback from Uniswap V2 pair
            function uniswapV2Call(
                address sender,
                uint amount0,
                uint amount1,
                bytes calldata data
            ) external {
                // Decode arbitrage parameters from data
                // Execute sell on target DEX
                // Repay flash loan
                // Send profit to owner
            }
            
            function withdraw(address token) external {
                require(msg.sender == owner, "Only owner");
                uint balance = IERC20(token).balanceOf(address(this));
                IERC20(token).transfer(owner, balance);
            }
        }
        """
