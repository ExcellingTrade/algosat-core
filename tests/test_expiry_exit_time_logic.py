#!/usr/bin/env python3
"""
Test expiry exit time logic specifically
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.append('/opt/algosat')

def test_expiry_exit_time_specific():
    """Test the specific expiry exit time logic"""
    
    print("=== Testing Expiry Exit Time Logic ===\n")
    
    from algosat.common.swing_utils import get_atm_strike_symbol
    
    # Test with different scenarios
    test_scenarios = [
        {
            "name": "Morning (before expiry exit time)",
            "test_time": datetime(2025, 7, 24, 9, 0),  # 9:00 AM on Thursday
            "expiry_exit_time": "15:15",
            "expected_behavior": "Should use current Thursday"
        },
        {
            "name": "After expiry exit time",
            "test_time": datetime(2025, 7, 24, 16, 0),  # 4:00 PM on Thursday  
            "expiry_exit_time": "15:15",
            "expected_behavior": "Should use next Thursday"
        },
        {
            "name": "Exactly at expiry exit time",
            "test_time": datetime(2025, 7, 24, 15, 15),  # 3:15 PM on Thursday
            "expiry_exit_time": "15:15", 
            "expected_behavior": "Should use next Thursday (>= condition)"
        }
    ]
    
    for scenario in test_scenarios:
        print(f"Testing: {scenario['name']}")
        print(f"  Test time: {scenario['test_time']}")
        print(f"  Expiry exit time: {scenario['expiry_exit_time']}")
        
        mock_config = {
            "expiry_exit": {
                "enabled": True,
                "days_before_expiry": 0,
                "expiry_exit_time": scenario['expiry_exit_time']
            },
            "entry": {
                "atm_strike_offset_CE": 0,
                "step_ce": 50
            }
        }
        
        try:
            symbol_str, expiry_date = get_atm_strike_symbol(
                "NIFTY50", 23400, "CE", mock_config, scenario['test_time']
            )
            
            print(f"  Result: {expiry_date}")
            print(f"  Expected: {scenario['expected_behavior']}")
            
            # Check if the result matches expectation
            if scenario['test_time'].date() == expiry_date.date():
                result = "Using current Thursday"
            else:
                result = "Using next Thursday"
            
            print(f"  Actual: {result}")
            
            # Verify logic
            if "Should use current Thursday" in scenario['expected_behavior']:
                expected_current = True
            else:
                expected_current = False
                
            actual_current = (scenario['test_time'].date() == expiry_date.date())
            
            if expected_current == actual_current:
                print("  ✅ Test PASSED")
            else:
                print("  ❌ Test FAILED")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        print()
    
    print("=== Expiry Exit Time Logic Test Complete ===")

if __name__ == "__main__":
    test_expiry_exit_time_specific()
