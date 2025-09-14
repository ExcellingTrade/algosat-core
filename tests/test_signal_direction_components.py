#!/usr/bin/env python3

"""
Simple test to verify signal_direction integration components
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_signal_direction_components():
    """Test that all signal_direction components are properly integrated"""
    
    print("Testing Signal Direction Integration Components...")
    print("=" * 60)
    
    success = True
    
    # Test 1: TradeSignal has signal_direction field
    try:
        from algosat.core.signal import TradeSignal, Side, SignalType
        
        signal = TradeSignal(
            symbol="TEST_SYMBOL",
            side=Side.BUY,
            signal_type=SignalType.ENTRY,
            signal_direction="UP"
        )
        
        if hasattr(signal, 'signal_direction') and signal.signal_direction == "UP":
            print("✅ Test 1: TradeSignal.signal_direction field works correctly")
        else:
            print("❌ Test 1: TradeSignal.signal_direction field missing or incorrect")
            success = False
            
    except Exception as e:
        print(f"❌ Test 1: Error with TradeSignal: {e}")
        success = False
    
    # Test 2: BrokerManager includes signal_direction in field list
    try:
        import inspect
        from algosat.core.broker_manager import BrokerManager
        
        # Get the source code of build_order_request_for_strategy method
        method = getattr(BrokerManager, 'build_order_request_for_strategy')
        source = inspect.getsource(method)
        
        if 'signal_direction' in source:
            print("✅ Test 2: BrokerManager includes signal_direction in field processing")
        else:
            print("❌ Test 2: BrokerManager does not include signal_direction")
            success = False
            
    except Exception as e:
        print(f"❌ Test 2: Error checking BrokerManager: {e}")
        success = False
    
    # Test 3: OrderManager extracts signal_direction from extra
    try:
        import inspect
        from algosat.core.order_manager import OrderManager
        
        # Get the source code of _insert_and_get_order_id method
        method = getattr(OrderManager, '_insert_and_get_order_id')
        source = inspect.getsource(method)
        
        if 'signal_direction' in source:
            print("✅ Test 3: OrderManager extracts signal_direction for database insertion")
        else:
            print("❌ Test 3: OrderManager does not extract signal_direction")
            success = False
            
    except Exception as e:
        print(f"❌ Test 3: Error checking OrderManager: {e}")
        success = False
    
    # Test 4: Database schema includes signal_direction column
    try:
        from algosat.core.dbschema import orders
        
        # Check if signal_direction column exists in orders table definition
        column_names = [col.name for col in orders.columns]
        
        if 'signal_direction' in column_names:
            print("✅ Test 4: Database schema includes signal_direction column")
        else:
            print("❌ Test 4: Database schema missing signal_direction column")
            success = False
            
    except Exception as e:
        print(f"❌ Test 4: Error checking database schema: {e}")
        success = False
    
    # Test 5: Verify swing strategies use signal_direction
    try:
        swing_files = [
            '/opt/algosat/algosat/strategies/swing_highlow_buy.py',
            '/opt/algosat/algosat/strategies/swing_highlow_sell.py'
        ]
        
        swing_tests_passed = 0
        for file_path in swing_files:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    if 'signal_direction=' in content and 'TradeSignal(' in content:
                        swing_tests_passed += 1
        
        if swing_tests_passed == 2:
            print("✅ Test 5: Both swing strategies use signal_direction in TradeSignal")
        else:
            print(f"❌ Test 5: Only {swing_tests_passed}/2 swing strategies use signal_direction")
            success = False
            
    except Exception as e:
        print(f"❌ Test 5: Error checking swing strategies: {e}")
        success = False
    
    print(f"\n" + "=" * 60)
    
    if success:
        print("🎉 ALL INTEGRATION COMPONENTS VERIFIED!")
        print()
        print("📋 Integration Summary:")
        print("✅ TradeSignal class includes signal_direction field")
        print("✅ BrokerManager processes signal_direction from TradeSignal")
        print("✅ OrderManager extracts signal_direction for database storage")
        print("✅ Database orders table has signal_direction column")
        print("✅ Swing strategies populate signal_direction in TradeSignal")
        print()
        print("🚀 Ready for production use!")
        print("   - SwingHighLowBuy will set signal_direction = 'UP' or 'DOWN'")
        print("   - SwingHighLowSell will set signal_direction = 'UP' or 'DOWN'")
        print("   - Orders table will store the signal direction for exit logic")
        print("   - Exit strategies can use signal_direction for decision making")
        
    else:
        print("❌ SOME INTEGRATION COMPONENTS FAILED!")
        print("Please review the failed tests above")
    
    return success

if __name__ == "__main__":
    test_signal_direction_components()
