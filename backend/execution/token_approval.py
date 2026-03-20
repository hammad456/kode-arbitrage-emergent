"""
Token Approval Flow - ERC20 Approval Management
Checks allowance and approves MAX_UINT256 if needed before swaps
"""
import asyncio
import logging
from typing import Dict, Optional, Tuple
from web3 import Web3
from web3.exceptions import ContractLogicError

from core.constants import MAX_UINT256, MAX_RETRY_ATTEMPTS, RETRY_BASE_DELAY, GAS_INCREASE_PER_RETRY, GAS_BUFFER_MULTIPLIER
from core.abis import ERC20_ABI

logger = logging.getLogger(__name__)

class TokenApprovalManager:
    """Manages ERC20 token approvals for trading"""
    
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.approval_cache: Dict[str, int] = {}  # Cache: "token_spender_owner" -> allowance
        self.pending_approvals: Dict[str, str] = {}  # Pending tx hashes
    
    def _get_cache_key(self, token: str, spender: str, owner: str) -> str:
        return f"{token.lower()}_{spender.lower()}_{owner.lower()}"
    
    async def check_allowance(self, token_address: str, spender: str, owner: str) -> int:
        """Check current allowance for a token"""
        try:
            token_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            allowance = token_contract.functions.allowance(
                Web3.to_checksum_address(owner),
                Web3.to_checksum_address(spender)
            ).call()
            
            # Update cache
            cache_key = self._get_cache_key(token_address, spender, owner)
            self.approval_cache[cache_key] = allowance
            
            return allowance
        except Exception as e:
            logger.error(f"Allowance check failed: {e}")
            return 0
    
    async def approve_token(
        self,
        token_address: str,
        spender: str,
        owner: str,
        private_key: str,
        amount: int = MAX_UINT256,
        gas_price_wei: Optional[int] = None
    ) -> Dict:
        """
        Approve token for spending with retry logic.
        Returns: {success: bool, tx_hash: str, gas_used: int, error: str}
        """
        result = {
            "success": False,
            "tx_hash": None,
            "gas_used": 0,
            "error": None,
            "attempts": 0
        }
        
        for attempt in range(MAX_RETRY_ATTEMPTS):
            result["attempts"] = attempt + 1
            
            try:
                token_contract = self.w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=ERC20_ABI
                )
                
                # Get gas price with increase per retry
                if gas_price_wei is None:
                    gas_price = self.w3.eth.gas_price
                else:
                    gas_price = gas_price_wei
                
                # Increase gas by 20% per retry
                gas_price = int(gas_price * (1 + GAS_INCREASE_PER_RETRY * attempt))
                
                # Build approval transaction
                nonce = self.w3.eth.get_transaction_count(Web3.to_checksum_address(owner))
                
                # Estimate gas with buffer
                try:
                    gas_estimate = token_contract.functions.approve(
                        Web3.to_checksum_address(spender),
                        amount
                    ).estimate_gas({'from': Web3.to_checksum_address(owner)})
                    gas_limit = int(gas_estimate * GAS_BUFFER_MULTIPLIER)
                except Exception:
                    gas_limit = 100000  # Default for ERC20 approve
                
                tx = token_contract.functions.approve(
                    Web3.to_checksum_address(spender),
                    amount
                ).build_transaction({
                    'chainId': self.w3.eth.chain_id,
                    'gas': gas_limit,
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })
                
                # Sign and send
                signed_tx = self.w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                
                logger.info(f"Approval tx sent: {tx_hash.hex()} (attempt {attempt + 1})")
                
                # Wait for confirmation
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                
                if receipt['status'] == 1:
                    # Update cache
                    cache_key = self._get_cache_key(token_address, spender, owner)
                    self.approval_cache[cache_key] = amount
                    
                    result["success"] = True
                    result["tx_hash"] = tx_hash.hex()
                    result["gas_used"] = receipt['gasUsed']
                    logger.info(f"Approval successful: {tx_hash.hex()}")
                    return result
                else:
                    result["error"] = "Transaction reverted"
                    logger.warning(f"Approval reverted (attempt {attempt + 1})")
                    
            except Exception as e:
                result["error"] = str(e)
                logger.warning(f"Approval attempt {attempt + 1} failed: {e}")
            
            # Exponential backoff
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
        
        return result
    
    async def check_balance(self, token_address: str, owner: str) -> int:
        """Check ERC20 token balance for owner"""
        try:
            token_contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            return token_contract.functions.balanceOf(
                Web3.to_checksum_address(owner)
            ).call()
        except Exception as e:
            logger.error(f"Balance check failed: {e}")
            return 0

    async def ensure_approval(
        self,
        token_address: str,
        spender: str,
        owner: str,
        required_amount: int,
        private_key: str,
        gas_price_wei: Optional[int] = None
    ) -> Dict:
        """
        Check allowance and approve if insufficient.
        Pre-flight balance check ensures sufficient funds before approving.
        Returns approval result or success if already approved.
        """
        # Pre-flight: verify owner has sufficient balance
        current_balance = await self.check_balance(token_address, owner)
        if current_balance < required_amount:
            logger.warning(
                f"Insufficient balance: {current_balance} < {required_amount} for {token_address}"
            )
            return {
                "success": False,
                "already_approved": False,
                "error": f"Insufficient balance: have {current_balance}, need {required_amount}",
                "tx_hash": None,
                "gas_used": 0
            }

        current_allowance = await self.check_allowance(token_address, spender, owner)

        if current_allowance >= required_amount:
            logger.info(f"Token already approved: {current_allowance} >= {required_amount}")
            return {
                "success": True,
                "already_approved": True,
                "current_allowance": current_allowance,
                "tx_hash": None,
                "gas_used": 0
            }
        
        logger.info(f"Approval needed: {current_allowance} < {required_amount}")
        
        # Approve MAX_UINT256 to avoid repeated approvals
        approval_result = await self.approve_token(
            token_address,
            spender,
            owner,
            private_key,
            MAX_UINT256,
            gas_price_wei
        )
        
        approval_result["already_approved"] = False
        approval_result["previous_allowance"] = current_allowance
        
        return approval_result
    
    def invalidate_cache(self, token_address: str = None, owner: str = None):
        """Invalidate approval cache for token/owner"""
        if token_address is None and owner is None:
            self.approval_cache.clear()
            return
        
        keys_to_remove = []
        for key in self.approval_cache:
            if token_address and token_address.lower() in key:
                keys_to_remove.append(key)
            elif owner and owner.lower() in key:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.approval_cache[key]
