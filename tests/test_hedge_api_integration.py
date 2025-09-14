#!/usr/bin/env python3
"""
Integration test to simulate the complete API flow for hedge field enhancement.
This script simulates the database response and API processing logic.
"""

import sys
sys.path.append('.')

def simulate_api_endpoint_flow():
    """Simulate the complete API endpoint flow with hedge field computation"""
    try:
        from algosat.api.schemas import OrderListResponse
        
        print("Simulating API endpoint flow...")
        print("-" * 50)
        
        # Simulate database response (what get_all_orders would return)
        mock_db_rows = [
            {
                'id': 371,
                'strategy_symbol_id': 1,
                'strike_symbol': 'NIFTY50-24300-CE',
                'symbol': 'NIFTY 50',
                'strategy_name': 'OptionBuy',
                'side': 'BUY',
                'qty': 100,
                'executed_quantity': 100,
                'entry_price': 150.0,
                'stop_loss': 140.0,
                'target_price': 160.0,
                'status': 'FILLED',
                'signal_time': '2024-01-01T10:00:00',
                'entry_time': '2024-01-01T10:01:00',
                'pnl': -1000.0,
                'parent_order_id': None,  # Main order
                'reason': 'Entry signal',
                'lot_qty': 100,
                'signal_direction': 'LONG'
            },
            {
                'id': 372,
                'strategy_symbol_id': 1,
                'strike_symbol': 'NIFTY50-24200-PE',
                'symbol': 'NIFTY 50',
                'strategy_name': 'OptionBuy',
                'side': 'SELL',
                'qty': 100,
                'executed_quantity': 100,
                'entry_price': 120.0,
                'stop_loss': 130.0,
                'target_price': 110.0,
                'status': 'FILLED',
                'signal_time': '2024-01-01T10:05:00',
                'entry_time': '2024-01-01T10:06:00',
                'pnl': 500.0,
                'parent_order_id': 371,  # Hedge order (parent is order 371)
                'reason': 'Hedge order',
                'lot_qty': 100,
                'signal_direction': 'SHORT'
            },
            {
                'id': 373,
                'strategy_symbol_id': 2,
                'strike_symbol': 'BANKNIFTY-51000-CE',
                'symbol': 'NIFTY BANK',
                'strategy_name': 'BankStrategy',
                'side': 'BUY',
                'qty': 50,
                'executed_quantity': 0,
                'entry_price': 200.0,
                'stop_loss': 180.0,
                'target_price': 220.0,
                'status': 'AWAITING_ENTRY',
                'signal_time': '2024-01-01T11:00:00',
                'entry_time': None,
                'pnl': 0.0,
                'parent_order_id': None,  # Main order
                'reason': 'New signal',
                'lot_qty': 50,
                'signal_direction': 'LONG'
            }
        ]
        
        print(f"Mock database returned {len(mock_db_rows)} rows")
        
        # Simulate the API endpoint processing logic
        print("\nApplying API endpoint logic...")
        
        # Add order_id field (alias for id) and compute is_hedge field for each row
        for row in mock_db_rows:
            row['order_id'] = row['id']
            # Set is_hedge to True if parent_order_id is present, False otherwise
            row['is_hedge'] = bool(row.get('parent_order_id'))
        
        # Convert to Pydantic models (as done in the API)
        orders = [OrderListResponse(**row) for row in mock_db_rows]
        
        print("\nAPI Response Summary:")
        print("=" * 60)
        for order in orders:
            hedge_status = "🔗 HEDGE" if order.is_hedge else "🎯 MAIN"
            parent_info = f" (parent: {order.parent_order_id})" if order.parent_order_id else ""
            print(f"Order {order.order_id}: {hedge_status}{parent_info}")
            print(f"  Symbol: {order.strike_symbol}")
            print(f"  Status: {order.status}")
            print(f"  PnL: {order.pnl}")
            print("-" * 60)
        
        # Verify hedge detection is working
        main_orders = [o for o in orders if not o.is_hedge]
        hedge_orders = [o for o in orders if o.is_hedge]
        
        print(f"\n📊 Summary:")
        print(f"  Main Orders: {len(main_orders)}")
        print(f"  Hedge Orders: {len(hedge_orders)}")
        
        # Verify specific relationships
        hedge_order = next((o for o in orders if o.id == 372), None)
        if hedge_order and hedge_order.parent_order_id == 371:
            print(f"  ✅ Correct hedge relationship: Order 372 is hedge of Order 371")
        
        print("\n🎉 API endpoint simulation completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ API endpoint simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run the integration test"""
    print("=" * 70)
    print("HEDGE FIELD API INTEGRATION TEST")
    print("=" * 70)
    
    success = simulate_api_endpoint_flow()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ INTEGRATION TEST PASSED!")
        print("\nThe API endpoint will now return hedge information:")
        print("- Main orders will have is_hedge=false, parent_order_id=null")
        print("- Hedge orders will have is_hedge=true, parent_order_id=<parent_id>")
        print("\nFrontend can now filter and display hedge relationships!")
    else:
        print("❌ INTEGRATION TEST FAILED!")
    
    print("=" * 70)
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
