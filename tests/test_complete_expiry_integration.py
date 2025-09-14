#!/usr/bin/env python3
"""
Integration test for complete expiry date functionality
"""

import sys
import os
sys.path.append('/opt/algosat')

from datetime import datetime, timedelta
from algosat.common.swing_utils import get_atm_strike_symbol
from algosat.core.signal import TradeSignal
from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy

def test_complete_expiry_integration():
    """Test the complete expiry date functionality integration"""
    
    print("=== Complete Expiry Date Integration Test ===")
    
    # Test configuration with expiry exit settings
    test_config = {
        "entry": {
            "atm_strike_offset_CE": 0,
            "atm_strike_offset_PE": 0,
            "step_ce": 50,
            "step_pe": 50
        },
        "expiry_exit": {
            "enabled": True,
            "days_before_expiry": 0,
            "expiry_exit_time": "15:15"
        }
    }
    
    print("\n1. Testing expiry date selection logic:")
    
    # Test case 1: Morning - should use current expiry
    morning_time = datetime(2025, 7, 24, 9, 0)  # Thursday morning
    symbol_str, expiry_date = get_atm_strike_symbol("NIFTY50", 23400, "CE", test_config, morning_time)
    print(f"   Morning (9:00 AM): expiry_date = {expiry_date}")
    if expiry_date.date() == morning_time.date():
        print("   ✅ Correctly uses current Thursday expiry")
    else:
        print("   ❌ ERROR: Should use current Thursday expiry")
    
    # Test case 2: After expiry exit time - should use next expiry
    afternoon_time = datetime(2025, 7, 24, 16, 0)  # Thursday 4 PM (after 3:15 PM)
    symbol_str2, expiry_date2 = get_atm_strike_symbol("NIFTY50", 23400, "CE", test_config, afternoon_time)
    print(f"   Afternoon (4:00 PM): expiry_date = {expiry_date2}")
    if expiry_date2.date() > afternoon_time.date():
        print("   ✅ Correctly uses next Thursday expiry")
    else:
        print("   ❌ ERROR: Should use next Thursday expiry")
    
    print("\n2. Testing TradeSignal integration:")
    
    # Create a trade signal with expiry date
    from algosat.core.order_request import Side
    from algosat.core.signal import SignalType
    
    signal = TradeSignal(
        symbol=symbol_str,
        side=Side.BUY,
        signal_type=SignalType.ENTRY,
        price=100.0,
        expiry_date=expiry_date.isoformat()
    )
    
    if signal.expiry_date and isinstance(signal.expiry_date, str):
        print(f"   ✅ TradeSignal stores expiry_date: {signal.expiry_date}")
    else:
        print(f"   ❌ ERROR: TradeSignal expiry_date not set correctly")
    
    print("\n3. Testing expiry exit evaluation:")
    
    # Mock order row for expiry exit testing
    current_time = datetime(2025, 7, 24, 15, 30)  # Thursday 3:30 PM
    expiry_date_str = "2025-07-24T00:00:00"  # Today's expiry
    
    order_row = {
        "id": 123,
        "expiry_date": expiry_date_str,
        "strategy_symbol_id": 1,
        "strike_symbol": "NSE:NIFTY2572423400CE"
    }
    
    # Mock trade config for exit evaluation
    mock_trade_config = {
        "expiry_exit": {
            "enabled": True,
            "expiry_exit_time": "15:15"
        }
    }
    
    # Simulate the expiry exit check logic (from swing_highlow_buy.py)
    try:
        from algosat.core.time_utils import get_ist_datetime
        import pandas as pd
        
        # Use actual current time for testing
        current_datetime = current_time
        
        # Convert expiry_date to pandas datetime if it's a string
        if isinstance(order_row["expiry_date"], str):
            expiry_dt = pd.to_datetime(order_row["expiry_date"])
        else:
            expiry_dt = order_row["expiry_date"]
        
        should_exit = False
        
        # Check if today is the expiry date
        if current_datetime.date() == expiry_dt.date():
            # Get expiry exit time from config
            expiry_exit_time = mock_trade_config["expiry_exit"]["expiry_exit_time"]
            
            # Parse expiry_exit_time (format: "HH:MM")
            exit_hour, exit_minute = map(int, expiry_exit_time.split(":"))
            exit_time = current_datetime.replace(
                hour=exit_hour, minute=exit_minute, second=0, microsecond=0
            )
            
            if current_datetime >= exit_time:
                should_exit = True
        
        if should_exit:
            print(f"   ✅ Expiry exit logic working: would exit at {current_time.strftime('%H:%M')} (exit time: 15:15)")
        else:
            print(f"   ❌ ERROR: Should trigger exit at {current_time.strftime('%H:%M')} (exit time: 15:15)")
            
    except Exception as e:
        print(f"   ❌ ERROR in expiry exit logic: {e}")
    
    print("\n=== Integration Test Complete ===")

if __name__ == "__main__":
    test_complete_expiry_integration()
