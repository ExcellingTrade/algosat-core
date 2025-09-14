#!/usr/bin/env python3
"""
Verify the fix addresses the specific "Could not find matching order in broker response" error.
"""

def simulate_order_matching_scenario():
    """
    Simulate the scenario from the logs where the order matching was failing.
    """
    print("Simulating the order matching scenario from the logs...")
    print()
    
    # From the logs: Database has broker_order_id without suffix
    db_broker_order_id = "25080800223154"
    
    # From the logs: Fyers live response has order with -BO-1 suffix  
    live_broker_orders = {
        "fyers": [
            {
                "id": "25080800223154-BO-1",
                "status": 2,  # FILLED in Fyers
                "productType": "MARGIN",
                "symbol": "NSE:NIFTY50-25JUN25-23400-CE",
                "qty": 50,
                "filledQty": 50,
                "tradedPrice": 156.75
            }
        ]
    }
    
    # Simulate the old logic (would fail)
    print("❌ OLD LOGIC (before fix):")
    old_cache_lookup_id = db_broker_order_id  # Just returned as-is
    print(f"  DB broker_order_id: {db_broker_order_id}")
    print(f"  Cache lookup ID (old): {old_cache_lookup_id}")
    print(f"  Live order ID from Fyers: {live_broker_orders['fyers'][0]['id']}")
    old_match = old_cache_lookup_id == live_broker_orders['fyers'][0]['id']
    print(f"  Match found: {old_match}")
    print(f"  Result: {'✓ SUCCESS' if old_match else '✗ FAILED - Could not find matching order in broker response'}")
    print()
    
    # Simulate the new logic (should succeed)
    print("✅ NEW LOGIC (after fix):")
    
    # Import the fixed function
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'algosat'))
    from algosat.core.order_manager import OrderManager
    
    new_cache_lookup_id = OrderManager._get_cache_lookup_order_id(
        db_broker_order_id, 
        "fyers", 
        "MARGIN"
    )
    print(f"  DB broker_order_id: {db_broker_order_id}")
    print(f"  Cache lookup ID (new): {new_cache_lookup_id}")
    print(f"  Live order ID from Fyers: {live_broker_orders['fyers'][0]['id']}")
    new_match = new_cache_lookup_id == live_broker_orders['fyers'][0]['id']
    print(f"  Match found: {new_match}")
    print(f"  Result: {'✓ SUCCESS - Order found and matched!' if new_match else '✗ STILL FAILING'}")
    print()
    
    return new_match

if __name__ == "__main__":
    success = simulate_order_matching_scenario()
    
    if success:
        print("🎉 SUCCESS! The fix resolves the 'Could not find matching order in broker response' error.")
    else:
        print("❌ The fix did not resolve the issue. Further investigation needed.")
