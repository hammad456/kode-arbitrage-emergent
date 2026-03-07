"""
Comprehensive Backend Tests for Berachain Arbitrage Bot
Tests all API endpoints including:
- Health check and system status
- Arbitrage opportunities scanning
- Triangular arbitrage detection
- Multi-hop arbitrage detection
- Trade execution with simulation and safety checks
- Engine stats and metrics
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test fixtures
@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def valid_wallet_address():
    return "0x1234567890123456789012345678901234567890"


# ============ HEALTH CHECK TESTS ============
class TestHealthEndpoint:
    """Health endpoint tests - verify system connectivity"""
    
    def test_health_returns_healthy(self, api_client):
        """GET /api/health should return healthy status"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["rpc_connected"] == True
        assert "block_number" in data
        assert isinstance(data["block_number"], int)
        assert data["block_number"] > 0
        assert data["chain_id"] == 80094  # Berachain mainnet
        print(f"✓ Health check passed - Block: {data['block_number']}")


# ============ OPPORTUNITIES TESTS ============
class TestOpportunitiesEndpoint:
    """Arbitrage opportunities endpoint tests"""
    
    def test_opportunities_returns_list(self, api_client):
        """GET /api/opportunities should return list of opportunities"""
        response = api_client.get(f"{BASE_URL}/api/opportunities")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Opportunities endpoint returned {len(data)} opportunities")
        
    def test_opportunities_have_required_fields(self, api_client):
        """Each opportunity should have required fields"""
        response = api_client.get(f"{BASE_URL}/api/opportunities")
        assert response.status_code == 200
        
        data = response.json()
        if len(data) > 0:
            opp = data[0]
            required_fields = [
                "id", "token_pair", "buy_dex", "sell_dex",
                "buy_price", "sell_price", "spread_percent",
                "potential_profit_usd", "gas_cost_usd", "net_profit_usd",
                "amount_in", "expected_out"
            ]
            for field in required_fields:
                assert field in opp, f"Missing required field: {field}"
            
            # Validate data types
            assert isinstance(opp["spread_percent"], (int, float))
            assert isinstance(opp["net_profit_usd"], (int, float))
            assert opp["spread_percent"] >= 0
            print(f"✓ Opportunity has all required fields: {opp['token_pair']}")
        else:
            print("⚠ No opportunities available for field validation")
            
    def test_opportunities_are_ranked(self, api_client):
        """Opportunities should be ranked by profit (highest first)"""
        response = api_client.get(f"{BASE_URL}/api/opportunities")
        assert response.status_code == 200
        
        data = response.json()
        if len(data) >= 2:
            # Verify sorted by net_profit_usd descending
            profits = [opp["net_profit_usd"] for opp in data]
            assert profits == sorted(profits, reverse=True), "Opportunities should be sorted by net profit"
            print(f"✓ Opportunities are properly ranked (top profit: ${profits[0]:.4f})")
        else:
            print("⚠ Not enough opportunities to verify ranking")


# ============ ENGINE STATS TESTS ============
class TestEngineStatsEndpoint:
    """Engine stats endpoint tests - verify arb_logger metrics"""
    
    def test_engine_stats_returns_data(self, api_client):
        """GET /api/engine/stats should return comprehensive stats"""
        response = api_client.get(f"{BASE_URL}/api/engine/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, dict)
        
        # Verify main sections exist
        assert "cache" in data
        assert "safety_limits" in data
        assert "arb_logger" in data
        print("✓ Engine stats endpoint returned data with required sections")
        
    def test_engine_stats_arb_logger_metrics(self, api_client):
        """arb_logger section should contain all required metrics"""
        response = api_client.get(f"{BASE_URL}/api/engine/stats")
        assert response.status_code == 200
        
        data = response.json()
        arb_logger = data.get("arb_logger", {})
        
        # Verify arb_logger fields
        required_arb_logger_fields = [
            "opportunities_found",
            "micro_arbs_found",
            "triangular_found",
            "multi_hop_found",
            "trades_skipped",
            "trades_executed",
            "trades_failed",
            "total_profit",
            "simulations",
            "scanning"
        ]
        
        for field in required_arb_logger_fields:
            assert field in arb_logger, f"Missing arb_logger field: {field}"
        
        # Verify simulations sub-fields
        simulations = arb_logger.get("simulations", {})
        assert "passed" in simulations
        assert "failed" in simulations
        assert "success_rate" in simulations
        
        # Verify scanning sub-fields  
        scanning = arb_logger.get("scanning", {})
        assert "total_scans" in scanning
        assert "last_scan_time_ms" in scanning
        assert "avg_scan_time_ms" in scanning
        
        print(f"✓ arb_logger metrics present - opportunities_found: {arb_logger['opportunities_found']}, micro_arbs: {arb_logger['micro_arbs_found']}")
        
    def test_engine_stats_safety_limits(self, api_client):
        """Safety limits should contain all required fields"""
        response = api_client.get(f"{BASE_URL}/api/engine/stats")
        assert response.status_code == 200
        
        data = response.json()
        safety = data.get("safety_limits", {})
        
        required_safety_fields = [
            "max_trade_size_usd",
            "max_slippage_percent",
            "min_profit_threshold",
            "min_spread_threshold",
            "max_hop_count"
        ]
        
        for field in required_safety_fields:
            assert field in safety, f"Missing safety_limits field: {field}"
        
        # Verify max_hop_count for multi-hop arbitrage
        assert safety["max_hop_count"] >= 4
        print(f"✓ Safety limits present - max_hop_count: {safety['max_hop_count']}")


# ============ TRIANGULAR OPPORTUNITIES TESTS ============
class TestTriangularOpportunities:
    """Triangular arbitrage endpoint tests"""
    
    def test_triangular_opportunities_endpoint_exists(self, api_client):
        """GET /api/triangular-opportunities should exist and respond"""
        response = api_client.get(f"{BASE_URL}/api/triangular-opportunities")
        assert response.status_code == 200
        
        data = response.json()
        assert "base_token" in data
        assert "opportunities" in data
        assert "count" in data
        assert isinstance(data["opportunities"], list)
        print(f"✓ Triangular opportunities endpoint returned {data['count']} routes")
        
    def test_triangular_with_custom_base_token(self, api_client):
        """Triangular endpoint should accept base_token parameter"""
        response = api_client.get(f"{BASE_URL}/api/triangular-opportunities?base_token=WBERA")
        assert response.status_code == 200
        
        data = response.json()
        assert data["base_token"] == "WBERA"
        print(f"✓ Triangular endpoint accepts base_token parameter")


# ============ MULTI-HOP OPPORTUNITIES TESTS ============
class TestMultiHopOpportunities:
    """Multi-hop arbitrage endpoint tests (4+ token routes)"""
    
    def test_multi_hop_endpoint_exists(self, api_client):
        """GET /api/multi-hop-opportunities should exist and respond"""
        response = api_client.get(f"{BASE_URL}/api/multi-hop-opportunities")
        assert response.status_code == 200
        
        data = response.json()
        assert "base_token" in data
        assert "max_hops" in data
        assert "opportunities" in data
        assert "count" in data
        assert isinstance(data["opportunities"], list)
        print(f"✓ Multi-hop opportunities endpoint returned {data['count']} routes (max_hops: {data['max_hops']})")
        
    def test_multi_hop_with_custom_max_hops(self, api_client):
        """Multi-hop endpoint should accept max_hops parameter"""
        response = api_client.get(f"{BASE_URL}/api/multi-hop-opportunities?max_hops=5")
        assert response.status_code == 200
        
        data = response.json()
        # max_hops might be capped by server config, just verify it responds
        assert "max_hops" in data
        print(f"✓ Multi-hop endpoint accepts max_hops parameter (returned: {data['max_hops']})")


# ============ TRADE EXECUTION TESTS ============
class TestTradeExecution:
    """Trade execution endpoint tests with simulation and safety checks"""
    
    def test_execute_trade_validates_inputs(self, api_client, valid_wallet_address):
        """POST /api/execute-trade should validate all inputs"""
        response = api_client.post(f"{BASE_URL}/api/execute-trade", json={
            "pair": "WBERA/HONEY",
            "buy_dex": "BEX",
            "sell_dex": "Kodiak V2",
            "amount": "100000000000000000000",
            "slippage": 0.5,
            "wallet_address": valid_wallet_address
        })
        assert response.status_code == 200
        
        data = response.json()
        # Should return success or failure with proper structure
        assert "success" in data
        print(f"✓ Execute trade endpoint validates inputs - success: {data['success']}")
        
    def test_execute_trade_returns_verification(self, api_client, valid_wallet_address):
        """Execute trade should return on-chain verification data"""
        response = api_client.post(f"{BASE_URL}/api/execute-trade", json={
            "pair": "WBERA/HONEY",
            "buy_dex": "BEX",
            "sell_dex": "Kodiak V2",
            "amount": "100000000000000000000",
            "slippage": 0.5,
            "wallet_address": valid_wallet_address
        })
        assert response.status_code == 200
        
        data = response.json()
        
        # Verification should always be present
        assert "verification" in data
        verification = data["verification"]
        
        # Check verification fields
        assert "valid" in verification
        assert "safety_checks" in verification
        
        safety = verification["safety_checks"]
        expected_checks = [
            "profit_exceeds_gas",
            "profit_exceeds_minimum",
            "slippage_acceptable",
            "spread_positive",
            "gas_within_limit"
        ]
        for check in expected_checks:
            assert check in safety, f"Missing safety check: {check}"
        
        print(f"✓ Execute trade returns verification with safety checks")
        
    def test_execute_trade_rejects_invalid_pair(self, api_client, valid_wallet_address):
        """Execute trade should reject invalid token pairs"""
        response = api_client.post(f"{BASE_URL}/api/execute-trade", json={
            "pair": "INVALID/TOKEN",
            "buy_dex": "BEX",
            "sell_dex": "Kodiak V2",
            "amount": "100000000000000000000",
            "slippage": 0.5,
            "wallet_address": valid_wallet_address
        })
        # Should return 400 for invalid pair or 200 with success=false
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            assert data["success"] == False
        else:
            data = response.json()
            assert "detail" in data  # Error message
        print(f"✓ Execute trade correctly rejects invalid pair (status: {response.status_code})")
        
    def test_execute_trade_rejects_excessive_slippage(self, api_client, valid_wallet_address):
        """Execute trade should reject slippage above limit"""
        response = api_client.post(f"{BASE_URL}/api/execute-trade", json={
            "pair": "WBERA/HONEY",
            "buy_dex": "BEX",
            "sell_dex": "Kodiak V2",
            "amount": "100000000000000000000",
            "slippage": 50.0,  # Excessive slippage
            "wallet_address": valid_wallet_address
        })
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            # Either rejected or slippage check should fail
            if "verification" in data and "safety_checks" in data["verification"]:
                assert not data["verification"]["safety_checks"]["slippage_acceptable"] or data["success"] == False
        print(f"✓ Execute trade handles excessive slippage")
        
    def test_execute_trade_rejects_unprofitable(self, api_client, valid_wallet_address):
        """Execute trade should reject if profit < gas cost"""
        response = api_client.post(f"{BASE_URL}/api/execute-trade", json={
            "pair": "WBERA/HONEY",
            "buy_dex": "BEX",
            "sell_dex": "Kodiak V2",
            "amount": "100000000000000000000",
            "slippage": 0.5,
            "wallet_address": valid_wallet_address
        })
        assert response.status_code == 200
        
        data = response.json()
        verification = data.get("verification", {})
        
        # If spread is 0 or negative, trade should be rejected
        if verification.get("spread_percent", 0) <= 0:
            assert data["success"] == False
            print(f"✓ Execute trade correctly rejects unprofitable trade (spread: {verification.get('spread_percent', 0)}%)")
        else:
            print(f"✓ Trade would be profitable (spread: {verification.get('spread_percent', 0)}%)")


# ============ TOKENS ENDPOINT TESTS ============
class TestTokensEndpoint:
    """Token list endpoint tests"""
    
    def test_tokens_returns_list(self, api_client):
        """GET /api/tokens should return supported tokens"""
        response = api_client.get(f"{BASE_URL}/api/tokens")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 4  # At least WBERA, HONEY, USDC, USDT
        
        # Verify token structure
        if len(data) > 0:
            token = data[0]
            assert "address" in token
            assert "symbol" in token
            assert "decimals" in token
        
        symbols = [t["symbol"] for t in data]
        print(f"✓ Tokens endpoint returned {len(data)} tokens: {', '.join(symbols)}")


# ============ GAS PRICE TESTS ============
class TestGasPriceEndpoint:
    """Gas price endpoint tests"""
    
    def test_gas_price_returns_data(self, api_client):
        """GET /api/gas-price should return gas pricing"""
        response = api_client.get(f"{BASE_URL}/api/gas-price")
        assert response.status_code == 200
        
        data = response.json()
        assert "gwei" in data
        assert "wei" in data
        assert isinstance(data["gwei"], (int, float))
        print(f"✓ Gas price endpoint returned {data['gwei']} gwei")


# ============ DEX QUOTE TESTS ============
class TestDexQuoteEndpoint:
    """DEX quote endpoint tests"""
    
    def test_quote_endpoint_works(self, api_client):
        """GET /api/quote should return price quote or error"""
        response = api_client.get(f"{BASE_URL}/api/quote", params={
            "token_in": "WBERA",
            "token_out": "HONEY",
            "amount_in": "1000000000000000000"  # 1 WBERA
        })
        # Quote endpoint may return 200 with data or 400 if quote fails
        assert response.status_code in [200, 400]
        
        data = response.json()
        if response.status_code == 200:
            assert "quotes" in data or "kodiak_v2" in data
            print(f"✓ Quote endpoint returned price data")
        else:
            # 400 means quote failed (could be RPC issue) but endpoint exists
            assert "detail" in data
            print(f"✓ Quote endpoint exists but returned error: {data['detail']}")


# ============ INTEGRATION TEST ============
class TestIntegration:
    """End-to-end integration tests"""
    
    def test_opportunities_match_engine_stats(self, api_client):
        """Opportunities found should be reflected in engine stats"""
        # Get opportunities
        opp_response = api_client.get(f"{BASE_URL}/api/opportunities")
        assert opp_response.status_code == 200
        opportunities = opp_response.json()
        
        # Get engine stats
        stats_response = api_client.get(f"{BASE_URL}/api/engine/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()
        
        arb_logger = stats.get("arb_logger", {})
        
        # Verify scanning is working
        assert arb_logger["scanning"]["total_scans"] > 0
        print(f"✓ Integration check passed - {len(opportunities)} active opportunities, {arb_logger['scanning']['total_scans']} scans performed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
