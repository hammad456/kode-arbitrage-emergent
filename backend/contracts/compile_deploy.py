"""
FlashArbitrage Contract Compiler & Deployer
============================================
Cara pakai:
  cd backend
  source venv/bin/activate

  # 1. Compile saja (generate ABI + bytecode)
  python contracts/compile_deploy.py --compile

  # 2. Deploy ke Berachain mainnet
  python contracts/compile_deploy.py --deploy \
    --private-key 0xYOUR_PRIVATE_KEY \
    --rpc https://rpc.berachain.com

  # 3. Verifikasi contract sudah deployed
  python contracts/compile_deploy.py --verify \
    --contract 0xDEPLOYED_CONTRACT_ADDRESS \
    --rpc https://rpc.berachain.com
"""

import json
import sys
import os
import argparse
import time
from pathlib import Path

# Tambah parent ke path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def compile_contract():
    """Compile FlashArbitrage.sol menggunakan py-solc-x"""
    try:
        from solcx import compile_source, install_solc, get_installed_solc_versions

        SOLC_VERSION = "0.8.19"

        # Install solc jika belum ada
        installed = get_installed_solc_versions()
        if not any(str(v) == SOLC_VERSION for v in installed):
            print(f"[*] Installing solc {SOLC_VERSION}...")
            install_solc(SOLC_VERSION)
            print(f"[+] solc {SOLC_VERSION} installed")

        # Baca source code
        sol_path = Path(__file__).parent / "FlashArbitrage.sol"
        source_code = sol_path.read_text()

        print(f"[*] Compiling FlashArbitrage.sol...")

        compiled = compile_source(
            source_code,
            output_values=["abi", "bin", "bin-runtime"],
            solc_version=SOLC_VERSION,
            optimize=True,
            optimize_runs=200,
        )

        # Ambil output contract utama
        contract_key = "<stdin>:FlashArbitrage"
        contract_data = compiled[contract_key]

        abi      = contract_data["abi"]
        bytecode = contract_data["bin"]

        # Simpan ke file
        output = {
            "abi": abi,
            "bytecode": "0x" + bytecode,
            "compiler": f"solc-{SOLC_VERSION}",
            "optimize": True,
            "optimize_runs": 200,
            "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        out_path = Path(__file__).parent / "FlashArbitrage.json"
        out_path.write_text(json.dumps(output, indent=2))
        print(f"[+] Compiled! ABI + bytecode saved to: {out_path}")
        print(f"    ABI functions: {len([x for x in abi if x.get('type') == 'function'])}")
        print(f"    Bytecode size: {len(bytecode)//2} bytes")

        return abi, "0x" + bytecode

    except ImportError:
        print("[!] py-solc-x not installed. Run: pip install py-solc-x")
        sys.exit(1)
    except Exception as e:
        print(f"[!] Compilation failed: {e}")
        raise


def deploy_contract(private_key: str, rpc_url: str, gas_price_gwei: float = None):
    """Deploy FlashArbitrage contract ke Berachain"""
    from web3 import Web3
    from web3.middleware import geth_poa_middleware

    # Load compiled contract
    out_path = Path(__file__).parent / "FlashArbitrage.json"
    if not out_path.exists():
        print("[*] Contract not compiled yet, compiling first...")
        compile_contract()

    data = json.loads(out_path.read_text())
    abi      = data["abi"]
    bytecode = data["bytecode"]

    # Connect ke RPC
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        print(f"[!] Cannot connect to RPC: {rpc_url}")
        sys.exit(1)

    chain_id  = w3.eth.chain_id
    account   = w3.eth.account.from_key(private_key)
    deployer  = account.address

    print(f"[*] Connected to chain ID: {chain_id}")
    print(f"[*] Deployer: {deployer}")

    balance = w3.eth.get_balance(deployer)
    balance_bera = w3.from_wei(balance, "ether")
    print(f"[*] Balance: {balance_bera:.4f} BERA")

    if balance == 0:
        print("[!] Deployer has no BERA for gas!")
        sys.exit(1)

    # Gas price
    if gas_price_gwei:
        gas_price = w3.to_wei(gas_price_gwei, "gwei")
    else:
        gas_price = w3.eth.gas_price
        gas_price = int(gas_price * 1.2)  # 20% buffer

    print(f"[*] Gas price: {w3.from_wei(gas_price, 'gwei'):.2f} gwei")

    # Build deploy transaction
    FlashArbContract = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(deployer)

    # Estimate gas
    try:
        gas_estimate = FlashArbContract.constructor().estimate_gas({"from": deployer})
        gas_limit = int(gas_estimate * 1.3)  # 30% buffer
    except Exception as e:
        print(f"[!] Gas estimation failed: {e}")
        gas_limit = 2_000_000  # Fallback

    print(f"[*] Estimated gas: {gas_estimate:,} → using: {gas_limit:,}")

    deploy_cost_bera = w3.from_wei(gas_limit * gas_price, "ether")
    print(f"[*] Estimated deploy cost: {deploy_cost_bera:.6f} BERA")

    # Konfirmasi
    confirm = input("\n[?] Deploy contract? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("[*] Deployment cancelled")
        sys.exit(0)

    # Build dan sign transaction
    tx = FlashArbContract.constructor().build_transaction({
        "chainId": chain_id,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "nonce": nonce,
    })

    signed_tx = w3.eth.account.sign_transaction(tx, private_key)

    print(f"[*] Sending deployment transaction...")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"[*] TX Hash: {tx_hash.hex()}")
    print(f"[*] Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt["status"] == 1:
        contract_address = receipt["contractAddress"]
        gas_used = receipt["gasUsed"]
        actual_cost = w3.from_wei(gas_used * gas_price, "ether")

        print(f"\n[+] ✅ CONTRACT DEPLOYED SUCCESSFULLY!")
        print(f"    Address  : {contract_address}")
        print(f"    TX Hash  : {tx_hash.hex()}")
        print(f"    Gas Used : {gas_used:,}")
        print(f"    Cost     : {actual_cost:.6f} BERA")
        print(f"\n[!] SIMPAN ADDRESS INI DI .env:")
        print(f"    FLASH_ARB_CONTRACT={contract_address}")

        # Simpan ke file config
        config_path = Path(__file__).parent / "deployed_contracts.json"
        deployed = {}
        if config_path.exists():
            deployed = json.loads(config_path.read_text())

        deployed[str(chain_id)] = {
            "FlashArbitrage": contract_address,
            "deployer": deployer,
            "tx_hash": tx_hash.hex(),
            "block": receipt["blockNumber"],
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        config_path.write_text(json.dumps(deployed, indent=2))
        print(f"\n[+] Saved to: {config_path}")

        return contract_address
    else:
        print(f"[!] ❌ Deployment FAILED! TX: {tx_hash.hex()}")
        sys.exit(1)


def verify_contract(contract_address: str, rpc_url: str):
    """Verifikasi contract functions berjalan"""
    from web3 import Web3

    out_path = Path(__file__).parent / "FlashArbitrage.json"
    if not out_path.exists():
        print("[!] No compiled contract found. Run --compile first.")
        sys.exit(1)

    data = json.loads(out_path.read_text())
    abi  = data["abi"]

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"[!] Cannot connect to: {rpc_url}")
        sys.exit(1)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_address),
        abi=abi
    )

    print(f"[*] Verifying contract at: {contract_address}")

    # Test view functions
    try:
        owner = contract.functions.owner().call()
        print(f"[+] owner(): {owner}")
    except Exception as e:
        print(f"[!] owner() failed: {e}")

    try:
        paused = contract.functions.paused().call()
        print(f"[+] paused(): {paused}")
    except Exception as e:
        print(f"[!] paused() failed: {e}")

    try:
        min_bps = contract.functions.minProfitBps().call()
        print(f"[+] minProfitBps(): {min_bps}")
    except Exception as e:
        print(f"[!] minProfitBps() failed: {e}")

    try:
        kodiak_v2 = contract.functions.KODIAK_V2_FACTORY().call()
        print(f"[+] KODIAK_V2_FACTORY(): {kodiak_v2}")
    except Exception as e:
        print(f"[!] KODIAK_V2_FACTORY() failed: {e}")

    # Test repayment calc
    try:
        repay = contract.functions.calcFlashRepayment(1_000_000).call()
        print(f"[+] calcFlashRepayment(1M): {repay} (fee: {repay - 1_000_000})")
    except Exception as e:
        print(f"[!] calcFlashRepayment() failed: {e}")

    print(f"\n[+] ✅ Contract verification complete!")


def load_abi():
    """Load ABI dari file compiled"""
    out_path = Path(__file__).parent / "FlashArbitrage.json"
    if not out_path.exists():
        return None
    data = json.loads(out_path.read_text())
    return data.get("abi")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FlashArbitrage Contract Tool")
    parser.add_argument("--compile",  action="store_true", help="Compile contract")
    parser.add_argument("--deploy",   action="store_true", help="Deploy contract")
    parser.add_argument("--verify",   action="store_true", help="Verify deployed contract")
    parser.add_argument("--private-key", type=str, help="Private key for deployment")
    parser.add_argument("--rpc",      type=str, default="https://rpc.berachain.com",
                        help="RPC URL")
    parser.add_argument("--contract", type=str, help="Contract address for verification")
    parser.add_argument("--gas-gwei", type=float, help="Gas price in gwei (optional)")

    args = parser.parse_args()

    if args.compile:
        compile_contract()

    elif args.deploy:
        if not args.private_key:
            print("[!] --private-key required for deploy")
            sys.exit(1)
        # Compile dulu jika belum
        out_path = Path(__file__).parent / "FlashArbitrage.json"
        if not out_path.exists():
            compile_contract()
        deploy_contract(args.private_key, args.rpc, args.gas_gwei)

    elif args.verify:
        if not args.contract:
            print("[!] --contract required for verify")
            sys.exit(1)
        verify_contract(args.contract, args.rpc)

    else:
        parser.print_help()
