#!/usr/bin/env python3
"""
Test the expiry date functionality implementation
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.append('/opt/algosat')

def test_expiry_date_functionality():
    """Test all the expiry date related changes"""
    
    print("=== Testing Expiry Date Functionality ===\n")
    
    # Test 1: Test get_atm_strike_symbol returns tuple
    print("1. Testing get_atm_strike_symbol method signature:")
    try:
        from algosat.common.swing_utils import get_atm_strike_symbol
        
        # Mock config
        mock_config = {
            "expiry_exit": {
                "enabled": True,
                "days_before_expiry": 0,
                "expiry_exit_time": "15:15"
            },
            "entry": {
                "atm_strike_offset_CE": 0,
                "step_ce": 50,
                "atm_strike_offset_PE": 0,
                "step_pe": 50
            }
        }
        
        # Test call
        result = get_atm_strike_symbol("NIFTY50", 23400, "CE", mock_config)
        
        # Check if it returns a tuple
        if isinstance(result, tuple) and len(result) == 2:
            symbol_str, expiry_date = result
            print(f"   ✅ Returns tuple: symbol='{symbol_str}', expiry_date='{expiry_date}'")
            print(f"   ✅ Symbol type: {type(symbol_str)}, Expiry type: {type(expiry_date)}")
        else:
            print(f"   ❌ Expected tuple of length 2, got: {type(result)} with value {result}")
            
    except Exception as e:
        print(f"   ❌ Error testing get_atm_strike_symbol: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Test expiry_exit_time logic
    print("\n2. Testing expiry exit time logic:")
    try:
        # Test with current time before expiry exit time
        today = datetime.now()
        before_expiry_config = {
            "expiry_exit": {
                "enabled": True,
                "days_before_expiry": 0,
                "expiry_exit_time": "16:00"  # Future time
            },
            "entry": {
                "atm_strike_offset_CE": 0,
                "step_ce": 50
            }
        }
        
        symbol_str, expiry_date = get_atm_strike_symbol("NIFTY50", 23400, "CE", before_expiry_config, today)
        print(f"   ✅ Before expiry exit time - expiry_date: {expiry_date}")
        
        # Test with current time after expiry exit time  
        after_expiry_config = {
            "expiry_exit": {
                "enabled": True,
                "days_before_expiry": 0,
                "expiry_exit_time": "09:00"  # Past time
            },
            "entry": {
                "atm_strike_offset_CE": 0,
                "step_ce": 50
            }
        }
        
        symbol_str2, expiry_date2 = get_atm_strike_symbol("NIFTY50", 23400, "CE", after_expiry_config, today)
        print(f"   ✅ After expiry exit time - expiry_date: {expiry_date2}")
        
        if expiry_date2 > expiry_date:
            print("   ✅ Expiry date correctly moved to next week when past expiry exit time")
        else:
            print("   ⚠️  Expiry date handling may need verification")
            
    except Exception as e:
        print(f"   ❌ Error testing expiry exit time logic: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Test TradeSignal with expiry_date
    print("\n3. Testing TradeSignal expiry_date field:")
    try:
        from algosat.core.signal import TradeSignal, SignalType
        
        # Create a TradeSignal with expiry_date
        signal = TradeSignal(
            symbol="NSE:NIFTY2572523400CE",
            side="BUY", 
            signal_type=SignalType.ENTRY,
            expiry_date="2025-07-24"
        )
        
        if hasattr(signal, 'expiry_date') and signal.expiry_date == "2025-07-24":
            print("   ✅ TradeSignal expiry_date field working correctly")
        else:
            print(f"   ❌ TradeSignal expiry_date issue: {getattr(signal, 'expiry_date', 'NOT_FOUND')}")
            
    except Exception as e:
        print(f"   ❌ Error testing TradeSignal: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 4: Test database schema (just verify imports work)
    print("\n4. Testing database schema imports:")
    try:
        from algosat.core.dbschema import orders
        
        # Check if expiry_date column exists in the table definition
        column_names = [col.name for col in orders.columns]
        if 'expiry_date' in column_names:
            print("   ✅ orders table has expiry_date column in schema")
        else:
            print(f"   ❌ expiry_date column not found in orders table. Columns: {column_names}")
            
    except Exception as e:
        print(f"   ❌ Error testing database schema: {e}")
    
    print("\n=== Expiry Date Functionality Test Complete ===")

if __name__ == "__main__":
    test_expiry_date_functionality()
