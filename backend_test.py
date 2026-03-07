#!/usr/bin/env python3
"""
Backend API Testing for Berachain Production Arbitrage Engine
Tests all production endpoints with real on-chain data integration
"""

import asyncio
import aiohttp
import json
import sys
import time
import os
from typing import Dict, List, Any

# Get backend URL from frontend env
def get_backend_url():
    """Get backend URL from frontend .env file"""
    try:
        with open('/app/frontend/.env', 'r') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL'):
                    url = line.split('=')[1].strip()
                    return f"{url}/api"
        return "http://localhost:8001/api"
    except Exception:
        return "http://localhost:8001/api"

BASE_URL = get_backend_url()

class BerachainArbEngineTest:
    def __init__(self):
        self.base_url = BASE_URL
        self.session = None
        self.results = []
        
    async def __aenter__(self):
        """Async context manager entry"""
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make HTTP request with error handling"""
        url = f"{self.base_url}{endpoint}"
        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.content_type == 'application/json':
                    data = await response.json()
                else:
                    text = await response.text()
                    data = {"raw_response": text}
                
                return {
                    "status_code": response.status,
                    "data": data,
                    "headers": dict(response.headers),
                    "url": url
                }
        except Exception as e:
            return {
                "status_code": 0,
                "error": str(e),
                "url": url
            }
    
    def log_test(self, test_name: str, success: bool, details: Dict = None, error: str = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "timestamp": time.time()
        }
        if details:
            result["details"] = details
        if error:
            result["error"] = error
        
        self.results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
        if error:
            print(f"   Error: {error}")
        if details and not success:
            print(f"   Details: {details}")
        print()
    
    async def test_health_endpoint(self):
        """Test GET /api/health - Verify RPC connection status"""
        print("Testing Health Endpoint...")
        
        resp = await self.make_request("GET", "/health")
        
        if resp["status_code"] != 200:
            self.log_test("Health Check", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check required fields
        required_fields = ["status", "rpc_connected", "block_number", "chain_id"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Health Check", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Check RPC connection
        if not data["rpc_connected"]:
            self.log_test("Health Check", False, data, "RPC not connected")
            return
        
        # Check chain ID (should be Berachain: 80094)
        if data["chain_id"] != 80094:
            self.log_test("Health Check", False, data, f"Unexpected chain_id: {data['chain_id']}")
            return
        
        # Check block number is positive
        if data["block_number"] <= 0:
            self.log_test("Health Check", False, data, f"Invalid block_number: {data['block_number']}")
            return
        
        self.log_test("Health Check", True, {
            "status": data["status"],
            "rpc_connected": data["rpc_connected"],
            "block_number": data["block_number"],
            "chain_id": data["chain_id"]
        })
    
    async def test_engine_stats_endpoint(self):
        """Test GET /api/engine/stats - Verify production metrics are included"""
        print("Testing Engine Stats Endpoint...")
        
        resp = await self.make_request("GET", "/engine/stats")
        
        if resp["status_code"] != 200:
            self.log_test("Engine Stats", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check for production-specific sections
        required_sections = ["production", "safety_limits", "arb_logger"]
        missing_sections = [s for s in required_sections if s not in data]
        
        if missing_sections:
            self.log_test("Engine Stats", False, data, f"Missing sections: {missing_sections}")
            return
        
        # Verify production section
        production = data["production"]
        required_prod_fields = ["mode", "atomic_executor_stats", "scanner_metrics"]
        missing_prod_fields = [f for f in required_prod_fields if f not in production]
        
        if missing_prod_fields:
            self.log_test("Engine Stats", False, production, f"Missing production fields: {missing_prod_fields}")
            return
        
        # Verify atomic executor stats
        executor_stats = production["atomic_executor_stats"]
        required_executor_fields = ["total_executions", "successful", "failed"]
        missing_executor_fields = [f for f in required_executor_fields if f not in executor_stats]
        
        if missing_executor_fields:
            self.log_test("Engine Stats", False, executor_stats, f"Missing executor fields: {missing_executor_fields}")
            return
        
        # Verify scanner metrics  
        scanner_metrics = production["scanner_metrics"]
        required_scanner_fields = ["total_scans", "scan_errors", "last_scan_time_ms"]
        missing_scanner_fields = [f for f in required_scanner_fields if f not in scanner_metrics]
        
        if missing_scanner_fields:
            self.log_test("Engine Stats", False, scanner_metrics, f"Missing scanner fields: {missing_scanner_fields}")
            return
        
        self.log_test("Engine Stats", True, {
            "production_mode": production["mode"],
            "total_executions": executor_stats["total_executions"],
            "total_scans": scanner_metrics["total_scans"],
            "error_rate": scanner_metrics.get("error_rate", 0)
        })
    
    async def test_production_scan_endpoint(self):
        """Test GET /api/production/scan-real - Test multicall-based scanner with real on-chain data"""
        print("Testing Production Scan Endpoint...")
        
        resp = await self.make_request("GET", "/production/scan-real")
        
        if resp["status_code"] != 200:
            self.log_test("Production Scan", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check for required fields
        required_fields = ["opportunities", "count", "scan_metrics"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Production Scan", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Verify scan metrics
        scan_metrics = data["scan_metrics"]
        required_metrics = ["total_scans", "last_scan_time_ms", "error_rate"]
        missing_metrics = [m for m in required_metrics if m not in scan_metrics]
        
        if missing_metrics:
            self.log_test("Production Scan", False, scan_metrics, f"Missing metrics: {missing_metrics}")
            return
        
        # Verify scan time is reasonable (< 5 seconds)
        scan_time_ms = scan_metrics["last_scan_time_ms"]
        if scan_time_ms > 5000:
            self.log_test("Production Scan", False, scan_metrics, f"Scan too slow: {scan_time_ms}ms")
            return
        
        # Check that opportunities is a list
        if not isinstance(data["opportunities"], list):
            self.log_test("Production Scan", False, data, "Opportunities should be a list")
            return
        
        # Verify count matches opportunities length
        if data["count"] != len(data["opportunities"]):
            self.log_test("Production Scan", False, data, "Count doesn't match opportunities length")
            return
        
        self.log_test("Production Scan", True, {
            "opportunities_found": data["count"],
            "scan_time_ms": scan_time_ms,
            "total_scans": scan_metrics["total_scans"],
            "error_rate": scan_metrics["error_rate"]
        })
    
    async def test_production_execution_stats_endpoint(self):
        """Test GET /api/production/execution-stats - Verify executor and scanner stats"""
        print("Testing Production Execution Stats Endpoint...")
        
        resp = await self.make_request("GET", "/production/execution-stats")
        
        if resp["status_code"] != 200:
            self.log_test("Production Execution Stats", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check for required fields
        required_fields = ["atomic_executor", "scanner", "production_mode"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Production Execution Stats", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Verify atomic executor stats
        executor_stats = data["atomic_executor"]
        required_executor_fields = ["total_executions", "successful", "failed"]
        missing_executor_fields = [f for f in required_executor_fields if f not in executor_stats]
        
        if missing_executor_fields:
            self.log_test("Production Execution Stats", False, executor_stats, f"Missing executor fields: {missing_executor_fields}")
            return
        
        # Verify scanner stats
        scanner_stats = data["scanner"]
        required_scanner_fields = ["total_scans", "scan_errors"]
        missing_scanner_fields = [f for f in required_scanner_fields if f not in scanner_stats]
        
        if missing_scanner_fields:
            self.log_test("Production Execution Stats", False, scanner_stats, f"Missing scanner fields: {missing_scanner_fields}")
            return
        
        self.log_test("Production Execution Stats", True, {
            "total_executions": executor_stats["total_executions"],
            "success_rate": f"{executor_stats['successful']}/{executor_stats['total_executions']}",
            "total_scans": scanner_stats["total_scans"],
            "production_mode": data["production_mode"]
        })
    
    async def test_check_allowance_endpoint(self):
        """Test GET /api/production/check-allowance - Test allowance checking"""
        print("Testing Check Allowance Endpoint...")
        
        # Test with HONEY token, Kodiak V2 router, and a test address
        token_address = "0xFCBD14DC51f0A4d49d5E53C2E0950e0bC26d0Dce"  # HONEY
        spender_address = "0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022"  # Kodiak V2 Router
        owner_address = "0x0000000000000000000000000000000000000001"  # Test address
        
        params = {
            "token_address": token_address,
            "spender_address": spender_address,
            "owner_address": owner_address
        }
        
        resp = await self.make_request("GET", "/production/check-allowance", params=params)
        
        if resp["status_code"] != 200:
            self.log_test("Check Allowance", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check for required fields
        required_fields = ["allowance_raw", "allowance_formatted", "is_unlimited", "token_address", "spender", "owner"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Check Allowance", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Verify allowance is a valid number string
        try:
            int(data["allowance_raw"])
        except ValueError:
            self.log_test("Check Allowance", False, data, "Invalid allowance_raw format")
            return
        
        # Verify boolean field
        if not isinstance(data["is_unlimited"], bool):
            self.log_test("Check Allowance", False, data, "is_unlimited should be boolean")
            return
        
        self.log_test("Check Allowance", True, {
            "allowance_raw": data["allowance_raw"],
            "allowance_formatted": data["allowance_formatted"],
            "is_unlimited": data["is_unlimited"]
        })
    
    async def test_opportunities_endpoint(self):
        """Test GET /api/opportunities - Test standard arbitrage scanning"""
        print("Testing Standard Opportunities Endpoint...")
        
        resp = await self.make_request("GET", "/opportunities")
        
        if resp["status_code"] != 200:
            self.log_test("Standard Opportunities", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Should be a list
        if not isinstance(data, list):
            self.log_test("Standard Opportunities", False, data, "Response should be a list")
            return
        
        # If opportunities exist, verify structure
        if data:
            opp = data[0]
            required_fields = ["id", "token_pair", "buy_dex", "sell_dex", "spread_percent", "net_profit_usd"]
            missing_fields = [f for f in required_fields if f not in opp]
            
            if missing_fields:
                self.log_test("Standard Opportunities", False, opp, f"Missing opportunity fields: {missing_fields}")
                return
            
            # Verify numeric fields
            try:
                float(opp["spread_percent"])
                float(opp["net_profit_usd"])
            except (ValueError, TypeError):
                self.log_test("Standard Opportunities", False, opp, "Invalid numeric fields")
                return
        
        self.log_test("Standard Opportunities", True, {
            "opportunities_count": len(data),
            "has_opportunities": len(data) > 0
        })
    
    async def test_triangular_opportunities_endpoint(self):
        """Test GET /api/triangular-opportunities - Test triangular arbitrage detection"""
        print("Testing Triangular Opportunities Endpoint...")
        
        resp = await self.make_request("GET", "/triangular-opportunities")
        
        if resp["status_code"] != 200:
            self.log_test("Triangular Opportunities", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check required fields
        required_fields = ["base_token", "opportunities", "count"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Triangular Opportunities", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Verify count matches opportunities length
        if data["count"] != len(data["opportunities"]):
            self.log_test("Triangular Opportunities", False, data, "Count doesn't match opportunities length")
            return
        
        # If opportunities exist, verify structure
        opportunities = data["opportunities"]
        if opportunities:
            opp = opportunities[0]
            required_opp_fields = ["type", "path", "net_profit_usd", "legs"]
            missing_opp_fields = [f for f in required_opp_fields if f not in opp]
            
            if missing_opp_fields:
                self.log_test("Triangular Opportunities", False, opp, f"Missing opportunity fields: {missing_opp_fields}")
                return
            
            # Verify it's actually triangular
            if opp["type"] != "triangular":
                self.log_test("Triangular Opportunities", False, opp, f"Expected triangular type, got {opp['type']}")
                return
        
        self.log_test("Triangular Opportunities", True, {
            "base_token": data["base_token"],
            "opportunities_count": data["count"],
            "has_opportunities": data["count"] > 0
        })
    
    async def test_gas_price_endpoint(self):
        """Test GET /api/gas-price - Verify gas price endpoint"""
        print("Testing Gas Price Endpoint...")
        
        resp = await self.make_request("GET", "/gas-price")
        
        if resp["status_code"] != 200:
            self.log_test("Gas Price", False, resp, "Non-200 status code")
            return
        
        data = resp["data"]
        
        # Check required fields
        required_fields = ["wei", "gwei", "recommended"]
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            self.log_test("Gas Price", False, data, f"Missing fields: {missing_fields}")
            return
        
        # Verify recommended structure
        recommended = data["recommended"]
        required_rec_fields = ["slow", "standard", "fast", "instant"]
        missing_rec_fields = [f for f in required_rec_fields if f not in recommended]
        
        if missing_rec_fields:
            self.log_test("Gas Price", False, recommended, f"Missing recommended fields: {missing_rec_fields}")
            return
        
        # Verify numeric values
        try:
            float(data["gwei"])
            for tier in required_rec_fields:
                float(recommended[tier])
        except (ValueError, TypeError):
            self.log_test("Gas Price", False, data, "Invalid numeric values")
            return
        
        self.log_test("Gas Price", True, {
            "gwei": data["gwei"],
            "recommended_fast": recommended["fast"],
            "has_error": "error" in data
        })
    
    async def run_all_tests(self):
        """Run all production endpoint tests"""
        print("🚀 Starting Berachain Production Arbitrage Engine Backend Tests")
        print(f"Backend URL: {self.base_url}")
        print("=" * 80)
        
        start_time = time.time()
        
        # Test all production endpoints as specified in the review request
        test_functions = [
            self.test_health_endpoint,
            self.test_engine_stats_endpoint,
            self.test_production_scan_endpoint,
            self.test_production_execution_stats_endpoint,
            self.test_check_allowance_endpoint,
            self.test_opportunities_endpoint,
            self.test_triangular_opportunities_endpoint,
            self.test_gas_price_endpoint
        ]
        
        for test_func in test_functions:
            try:
                await test_func()
            except Exception as e:
                test_name = test_func.__name__.replace("test_", "").replace("_endpoint", "").title()
                self.log_test(test_name, False, error=f"Test exception: {str(e)}")
        
        # Print summary
        total_time = time.time() - start_time
        passed = sum(1 for r in self.results if r["success"])
        failed = len(self.results) - passed
        
        print("=" * 80)
        print("🏁 TEST SUMMARY")
        print("=" * 80)
        print(f"✅ PASSED: {passed}")
        print(f"❌ FAILED: {failed}")
        print(f"⏱️  TOTAL TIME: {total_time:.2f}s")
        print(f"📊 SUCCESS RATE: {(passed/len(self.results)*100):.1f}%")
        print()
        
        # Print failed tests details
        if failed > 0:
            print("🔍 FAILED TESTS DETAILS:")
            print("-" * 40)
            for result in self.results:
                if not result["success"]:
                    print(f"❌ {result['test']}")
                    if "error" in result:
                        print(f"   Error: {result['error']}")
                    print()
        
        # Return summary for test_result.md update
        return {
            "total": len(self.results),
            "passed": passed,
            "failed": failed,
            "success_rate": passed/len(self.results)*100,
            "duration": total_time,
            "results": self.results
        }

async def main():
    """Main test runner"""
    async with BerachainArbEngineTest() as tester:
        summary = await tester.run_all_tests()
        return summary

if __name__ == "__main__":
    # Run tests
    try:
        summary = asyncio.run(main())
        
        # Exit with non-zero code if any tests failed for CI/CD
        if summary["failed"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test runner error: {e}")
        sys.exit(1)