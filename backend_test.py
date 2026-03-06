import requests
import sys
from datetime import datetime
import json

class BerachainArbBotAPITester:
    def __init__(self, base_url="https://smart-arb-bot-1.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.mock_wallet = "0x742d35Cc6634C0532925a3b8D4c78c9f35717361"

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        if headers is None:
            headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=30)

            print(f"   Status: {response.status_code}")
            
            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ PASSED - Status: {response.status_code}")
                return True, response.json() if response.content else {}
            else:
                print(f"❌ FAILED - Expected {expected_status}, got {response.status_code}")
                if response.content:
                    try:
                        error_data = response.json()
                        print(f"   Error details: {error_data}")
                    except:
                        print(f"   Response text: {response.text[:200]}")
                        
                self.failed_tests.append({
                    "name": name,
                    "endpoint": endpoint,
                    "expected": expected_status,
                    "actual": response.status_code,
                    "error": response.text[:200] if response.content else "No response"
                })
                return False, {}

        except requests.exceptions.RequestException as e:
            print(f"❌ FAILED - Network Error: {str(e)}")
            self.failed_tests.append({
                "name": name,
                "endpoint": endpoint,
                "expected": expected_status,
                "actual": "Network Error",
                "error": str(e)
            })
            return False, {}

    def test_health_endpoint(self):
        """Test health check and RPC connection"""
        success, response = self.run_test(
            "Health Check",
            "GET",
            "api/health",
            200
        )
        
        if success:
            rpc_connected = response.get('rpc_connected', False)
            if rpc_connected:
                print(f"   RPC Status: Connected ✅")
                print(f"   Block Number: {response.get('block_number', 'N/A')}")
                print(f"   Chain ID: {response.get('chain_id', 'N/A')}")
            else:
                print(f"   ⚠️ WARNING: RPC not connected")
        
        return success

    def test_opportunities_endpoint(self):
        """Test arbitrage opportunities endpoint"""
        success, response = self.run_test(
            "Arbitrage Opportunities", 
            "GET",
            "api/opportunities",
            200
        )
        
        if success:
            if isinstance(response, list):
                print(f"   Found {len(response)} opportunities")
                for i, opp in enumerate(response[:3]):  # Show first 3
                    print(f"   Opp {i+1}: {opp.get('token_pair', 'N/A')} - "
                          f"Spread: {opp.get('spread_percent', 0):.3f}% - "
                          f"Net Profit: ${opp.get('net_profit_usd', 0):.2f}")
            else:
                print(f"   ⚠️ WARNING: Expected list, got {type(response)}")
        
        return success

    def test_gas_price_endpoint(self):
        """Test gas price endpoint"""
        success, response = self.run_test(
            "Gas Price Information",
            "GET", 
            "api/gas-price",
            200
        )
        
        if success:
            gas_gwei = response.get('gwei', 0)
            print(f"   Current Gas: {gas_gwei} gwei")
            
            recommended = response.get('recommended', {})
            if recommended:
                print(f"   Recommended: {recommended}")
        
        return success

    def test_tokens_endpoint(self):
        """Test supported tokens endpoint"""
        success, response = self.run_test(
            "Supported Tokens List",
            "GET",
            "api/tokens", 
            200
        )
        
        if success:
            if isinstance(response, list):
                print(f"   Found {len(response)} supported tokens")
                for token in response[:5]:  # Show first 5
                    print(f"   - {token.get('symbol', 'N/A')}: {token.get('address', 'N/A')[:10]}...")
            else:
                print(f"   ⚠️ WARNING: Expected list, got {type(response)}")
        
        return success

    def test_wallet_balances_endpoint(self):
        """Test wallet balances endpoint"""
        success, response = self.run_test(
            "Wallet Balances",
            "GET",
            f"api/wallet/{self.mock_wallet}/balances",
            200
        )
        
        if success:
            balances = response.get('balances', [])
            print(f"   Found {len(balances)} token balances")
            for balance in balances[:3]:  # Show first 3
                symbol = balance.get('symbol', 'N/A')
                formatted = balance.get('balance_formatted', '0')
                print(f"   - {symbol}: {formatted}")
        
        return success

    def test_settings_endpoints(self):
        """Test settings get/post endpoints"""
        # Test GET settings
        get_success, get_response = self.run_test(
            "Get User Settings",
            "GET",
            f"api/settings/{self.mock_wallet}",
            200
        )
        
        if get_success:
            print(f"   Min Profit Threshold: ${get_response.get('min_profit_threshold', 0)}")
            print(f"   Max Slippage: {get_response.get('max_slippage', 0)}%")
            print(f"   Auto Execute: {get_response.get('auto_execute', False)}")
        
        # Test POST settings
        test_settings = {
            "min_profit_threshold": 1.0,
            "max_slippage": 0.8,
            "gas_multiplier": 1.3,
            "auto_execute": False
        }
        
        post_success, post_response = self.run_test(
            "Update User Settings",
            "POST",
            f"api/settings/{self.mock_wallet}",
            200,
            data=test_settings
        )
        
        return get_success and post_success

    def test_analytics_endpoint(self):
        """Test analytics endpoint"""
        success, response = self.run_test(
            "Trading Analytics",
            "GET",
            f"api/analytics/{self.mock_wallet}",
            200
        )
        
        if success:
            print(f"   Total Trades: {response.get('total_trades', 0)}")
            print(f"   Total Profit: ${response.get('total_profit_usd', 0):.2f}")
            print(f"   Success Rate: {response.get('success_rate', 0):.1f}%")
        
        return success

    def test_root_endpoint(self):
        """Test root API endpoint"""
        success, response = self.run_test(
            "Root API Endpoint",
            "GET",
            "api/",
            200
        )
        
        if success:
            print(f"   Message: {response.get('message', 'N/A')}")
            print(f"   Chain ID: {response.get('chain_id', 'N/A')}")
        
        return success

def main():
    print("🚀 Starting BeraArb API Testing...")
    print("=" * 60)
    
    tester = BerachainArbBotAPITester()
    
    # List of core API tests to run
    api_tests = [
        tester.test_root_endpoint,
        tester.test_health_endpoint,
        tester.test_opportunities_endpoint,
        tester.test_gas_price_endpoint,
        tester.test_tokens_endpoint,
        tester.test_wallet_balances_endpoint,
        tester.test_analytics_endpoint,
        tester.test_settings_endpoints,
    ]
    
    # Run all tests
    for test_func in api_tests:
        try:
            test_func()
        except Exception as e:
            print(f"❌ FAILED - Exception: {str(e)}")
            tester.failed_tests.append({
                "name": test_func.__name__,
                "endpoint": "N/A",
                "expected": "No Exception", 
                "actual": "Exception",
                "error": str(e)
            })
    
    # Print final results
    print("\n" + "=" * 60)
    print(f"📊 TEST SUMMARY")
    print(f"Tests Run: {tester.tests_run}")
    print(f"Tests Passed: {tester.tests_passed}")
    print(f"Tests Failed: {len(tester.failed_tests)}")
    print(f"Success Rate: {(tester.tests_passed/tester.tests_run*100):.1f}%" if tester.tests_run > 0 else "N/A")
    
    if tester.failed_tests:
        print("\n❌ FAILED TESTS:")
        for i, failure in enumerate(tester.failed_tests, 1):
            print(f"{i}. {failure['name']}")
            print(f"   Endpoint: {failure['endpoint']}")
            print(f"   Expected: {failure['expected']}, Got: {failure['actual']}")
            print(f"   Error: {failure['error']}")
    
    return 0 if len(tester.failed_tests) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())