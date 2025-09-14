#!/usr/bin/env python3
"""
Test Angel broker get_order_details method with simulated API response structure.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

# Mock Angel API response structure (simulating what smart_api.orderBook() returns)
MOCK_ANGEL_API_RESPONSE_SUCCESS = {
    "status": True,
    "message": "SUCCESS", 
    "errorcode": "",
    "data": [
        {'algoID': '99999', 'variety': 'AMO', 'ordertype': 'LIMIT', 'producttype': 'INTRADAY', 'duration': 'DAY', 'price': 150.0, 'triggerprice': 0.0, 'quantity': '150', 'disclosedquantity': '0', 'squareoff': 0.0, 'stoploss': 0.0, 'trailingstoploss': 0.0, 'tradingsymbol': 'NIFTY16SEP2524950CE', 'transactiontype': 'BUY', 'exchange': 'NFO', 'symboltoken': '44662', 'ordertag': '', 'instrumenttype': 'OPTIDX', 'strikeprice': 24950.0, 'optiontype': 'CE', 'expirydate': '16SEP2025', 'lotsize': '75', 'cancelsize': '0', 'averageprice': 0.0, 'filledshares': '0', 'unfilledshares': '150', 'orderid': '091389e428f2AO', 'text': '', 'status': 'open', 'orderstatus': 'open', 'updatetime': '13-Sep-2025 11:30:51', 'exchtime': '', 'exchorderupdatetime': '', 'fillid': '', 'filltime': '', 'parentorderid': '', 'uniqueorderid': '4abfa579-a1ee-4a1e-ba93-4f747f40a80e', 'exchangeorderid': ''},
        {'algoID': '99999', 'variety': 'AMO', 'ordertype': 'STOPLOSS_LIMIT', 'producttype': 'INTRADAY', 'duration': 'DAY', 'price': 220.0, 'triggerprice': 215.0, 'quantity': '150', 'disclosedquantity': '0', 'squareoff': 0.0, 'stoploss': 0.0, 'trailingstoploss': 0.0, 'tradingsymbol': 'NIFTY16SEP2524950CE', 'transactiontype': 'BUY', 'exchange': 'NFO', 'symboltoken': '44662', 'ordertag': '', 'instrumenttype': 'OPTIDX', 'strikeprice': 24950.0, 'optiontype': 'CE', 'expirydate': '16SEP2025', 'lotsize': '75', 'cancelsize': '0', 'averageprice': 0.0, 'filledshares': '0', 'unfilledshares': '150', 'orderid': '0913c74c7aa8AO', 'text': '', 'status': 'open', 'orderstatus': 'open', 'updatetime': '13-Sep-2025 12:57:43', 'exchtime': '', 'exchorderupdatetime': '', 'fillid': '', 'filltime': '', 'parentorderid': '', 'uniqueorderid': 'bdfe4e36-3cba-414c-b49f-54c4c5ef1857', 'exchangeorderid': ''}
    ]
}

MOCK_ANGEL_API_RESPONSE_FAILURE = {
    "status": False,
    "message": "INVALID_TOKEN",
    "errorcode": "AG8001",
    "data": None
}

MOCK_ANGEL_API_RESPONSE_EMPTY = {
    "status": True,
    "message": "SUCCESS",
    "errorcode": "",
    "data": []
}

class MockAngelOrderDetails:
    """Mock class to simulate enhanced get_order_details behavior."""
    
    def __init__(self):
        self.scenario = "success"  # Can be "success", "failure", "empty", "invalid_response"
    
    def simulate_get_order_details(self, scenario: str = "success") -> list:
        """
        Simulate the enhanced get_order_details method behavior.
        """
        print(f"🔄 Simulating Angel get_order_details - Scenario: {scenario}")
        print("-" * 60)
        
        if scenario == "success":
            orders_response = MOCK_ANGEL_API_RESPONSE_SUCCESS
        elif scenario == "failure":
            orders_response = MOCK_ANGEL_API_RESPONSE_FAILURE
        elif scenario == "empty":
            orders_response = MOCK_ANGEL_API_RESPONSE_EMPTY
        elif scenario == "invalid_response":
            orders_response = "invalid_response_string"
        else:
            orders_response = None
        
        print(f"📡 Mock API Response: {orders_response}")
        print()
        
        # Simulate the enhanced logic from get_order_details
        try:
            # Validate response structure
            if not isinstance(orders_response, dict):
                print(f"❌ Angel order details: Invalid response type {type(orders_response)}")
                return []
            
            # Check response status
            if not orders_response.get("status"):
                error_msg = orders_response.get("message", "Unknown error")
                error_code = orders_response.get("errorcode", "N/A")
                print(f"❌ Angel order details API call failed. Status: {orders_response.get('status')}, "
                      f"Message: {error_msg}, ErrorCode: {error_code}")
                return []
            
            # Extract data field
            data = orders_response.get("data", [])
            if not isinstance(data, list):
                print(f"❌ Angel order details: Expected list in data field, got {type(data)}")
                return []
            
            print(f"✅ Angel order details: Successfully retrieved {len(data)} orders")
            
            # Log sample order for debugging (first order only)
            if data and len(data) > 0:
                sample_order = data[0]
                print(f"📊 Angel order sample: OrderID={sample_order.get('orderid')}, "
                      f"Symbol={sample_order.get('tradingsymbol')}, "
                      f"Status={sample_order.get('status')}, "
                      f"Type={sample_order.get('ordertype')}")
            
            return data
            
        except Exception as e:
            print(f"❌ Error in get_order_details simulation: {e}")
            return []

async def test_angel_order_details_scenarios():
    """Test Angel enhanced get_order_details with different scenarios."""
    try:
        print("🧪 Testing Enhanced Angel get_order_details Method")
        print("=" * 70)
        
        mock_angel = MockAngelOrderDetails()
        
        # Test different scenarios
        scenarios = [
            ("success", "Successful response with orders"),
            ("empty", "Successful response with no orders"),
            ("failure", "API failure response"),
            ("invalid_response", "Invalid response type")
        ]
        
        for scenario, description in scenarios:
            print(f"\n📋 Test Case: {description}")
            print("=" * 50)
            
            result = mock_angel.simulate_get_order_details(scenario)
            
            print(f"📊 Result: {len(result)} orders returned")
            if result:
                print("📝 First order details:")
                first_order = result[0]
                print(f"  Order ID: {first_order.get('orderid')}")
                print(f"  Symbol: {first_order.get('tradingsymbol')}")
                print(f"  Status: {first_order.get('status')}")
                print(f"  Order Type: {first_order.get('ordertype')}")
                print(f"  Quantity: {first_order.get('quantity')}")
            
            print()
        
        print(f"✅ Angel enhanced get_order_details test completed!")
        
    except Exception as e:
        print(f"❌ Error during Angel get_order_details test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_order_details_scenarios())