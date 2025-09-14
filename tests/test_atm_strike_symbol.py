#!/usr/bin/env python3
"""
Test script for get_atm_strike_symbol method from swing_utils.py
Test date: July 29th, 2025
"""

import sys
import os
from datetime import datetime

# Add the project root to Python path
sys.path.append('/opt/algosat')

from algosat.common.swing_utils import get_atm_strike_symbol

def test_get_atm_strike_symbol():
    """Test the get_atm_strike_symbol method with various scenarios"""
    
    # Test date: July 29th, 2025
    test_date = datetime(2025, 7, 29, 10, 30)  # 10:30 AM
    
    print("=" * 80)
    print(f"Testing get_atm_strike_symbol for date: {test_date.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    # Test configurations
    test_configs = [
        {
            "name": "Basic NIFTY weekly config",
            "config": {
                "expiry_exit": {
                    "enabled": True,
                    "days_before_expiry": 3,
                    "expiry_exit_time": "11:15"
                },
                "entry": {
                    "atm_strike_offset_CE": 0,
                    "atm_strike_offset_PE": 0,
                    "step_ce": 50,
                    "step_pe": 50
                }
            }
        },
        {
            "name": "BANKNIFTY with offset config",
            "config": {
                "expiry_exit": {
                    "enabled": True,
                    "days_before_expiry": 1,
                    "expiry_exit_time": "11:15"
                },
                "entry": {
                    "atm_strike_offset_CE": 100,
                    "atm_strike_offset_PE": -100,
                    "step_ce": 100,
                    "step_pe": 100
                }
            }
        },
        {
            "name": "SENSEX monthly config",
            "config": {
                "expiry_exit": {
                    "enabled": True,
                    "days_before_expiry": 0,
                    "expiry_exit_time": "11:15"
                },
                "entry": {
                    "atm_strike_offset_CE": 0,
                    "atm_strike_offset_PE": 0,
                    "step_ce": 100,
                    "step_pe": 100
                }
            }
        }
    ]
    
    # Test symbols and their spot prices
    test_cases = [
        {"symbol": "NIFTY", "spot_price": 24850.75},
        {"symbol": "NSE:NIFTY50-INDEX", "spot_price": 24850.75},
        {"symbol": "BANKNIFTY", "spot_price": 51200.30},
        {"symbol": "NSE:NIFTYBANK-INDEX", "spot_price": 51200.30},
        {"symbol": "SENSEX", "spot_price": 81500.45},
    ]
    
    option_types = ["CE", "PE"]
    
    for config_info in test_configs:
        print(f"\n{'-' * 60}")
        print(f"Config: {config_info['name']}")
        print(f"{'-' * 60}")
        
        config = config_info['config']
        
        for test_case in test_cases:
            symbol = test_case['symbol']
            spot_price = test_case['spot_price']
            
            print(f"\nSymbol: {symbol} | Spot Price: {spot_price}")
            print("-" * 40)
            
            for option_type in option_types:
                try:
                    strike_symbol, expiry_date = get_atm_strike_symbol(
                        symbol=symbol,
                        spot_price=spot_price,
                        option_type=option_type,
                        config=config,
                        today=test_date
                    )
                    
                    print(f"  {option_type}: {strike_symbol}")
                    print(f"      Expiry: {expiry_date.strftime('%Y-%m-%d (%A)')}")
                    
                except Exception as e:
                    print(f"  {option_type}: ERROR - {str(e)}")
            
            print()

def test_edge_cases():
    """Test edge cases and special scenarios"""
    
    print("\n" + "=" * 80)
    print("TESTING EDGE CASES")
    print("=" * 80)
    
    # Test near market close on expiry day
    expiry_day = datetime(2025, 7, 31, 15, 20)  # Thursday 15:20 (past expiry exit time)
    
    config = {
        "expiry_exit": {
            "enabled": True,
            "days_before_expiry": 0,
            "expiry_exit_time": "11:15"
        },
        "entry": {
            "atm_strike_offset_CE": 0,
            "atm_strike_offset_PE": 0,
            "step_ce": 50,
            "step_pe": 50
        }
    }
    
    print(f"\nTest: Expiry day scenario (past expiry exit time)")
    print(f"Date: {expiry_day.strftime('%Y-%m-%d %H:%M (%A)')}")
    print("-" * 50)
    
    try:
        strike_symbol, expiry_date = get_atm_strike_symbol(
            symbol="NIFTY",
            spot_price=24800.00,
            option_type="CE",
            config=config,
            today=expiry_day
        )
        
        print(f"Strike Symbol: {strike_symbol}")
        print(f"Expiry Date: {expiry_date.strftime('%Y-%m-%d (%A)')}")
        print("✓ Should roll to next expiry since past expiry exit time")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
    
    # Test with days_before_expiry
    print(f"\nTest: With days_before_expiry = 2")
    print("-" * 50)
    
    config_early = {
        "expiry_exit": {
            "enabled": True,
            "days_before_expiry": 2,
            "expiry_exit_time": "11:15"
        },
        "entry": {
            "atm_strike_offset_CE": 0,
            "atm_strike_offset_PE": 0,
            "step_ce": 50,
            "step_pe": 50
        }
    }
    
    try:
        strike_symbol, expiry_date = get_atm_strike_symbol(
            symbol="NIFTY",
            spot_price=24800.00,
            option_type="CE",
            config=config_early,
            today=expiry_day
        )
        
        print(f"Strike Symbol: {strike_symbol}")
        print(f"Expiry Date: {expiry_date.strftime('%Y-%m-%d (%A)')}")
        print("✓ Should be 2 days before actual expiry")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")

def test_step_and_offset_calculations():
    """Test strike price calculations with different steps and offsets"""
    
    print("\n" + "=" * 80)
    print("TESTING STEP AND OFFSET CALCULATIONS")
    print("=" * 80)
    
    # Test date for calculations
    test_date = datetime(2025, 7, 29, 10, 30)
    
    spot_price = 24873.45  # Awkward spot price to test rounding
    
    test_scenarios = [
        {
            "name": "No offset, 50 step",
            "config": {"entry": {"atm_strike_offset_CE": 0, "step_ce": 50}},
            "expected_strike": 24850  # Should round to nearest 50
        },
        {
            "name": "100 offset, 50 step", 
            "config": {"entry": {"atm_strike_offset_CE": 100, "step_ce": 50}},
            "expected_strike": 24950  # (24873.45 + 100) / 50 = 499.469, round = 499, * 50 = 24950
        },
        {
            "name": "-50 offset, 100 step",
            "config": {"entry": {"atm_strike_offset_CE": -50, "step_ce": 100}},
            "expected_strike": 24800  # (24873.45 - 50) / 100 = 248.23, round = 248, * 100 = 24800
        }
    ]
    
    base_config = {
        "expiry_exit": {"enabled": True, "days_before_expiry": 0, "expiry_exit_time": "11:15"},
        "entry": {}
    }
    
    print(f"Spot Price: {spot_price}")
    print("-" * 40)
    
    for scenario in test_scenarios:
        config = base_config.copy()
        config["entry"].update(scenario["config"]["entry"])
        
        try:
            strike_symbol, expiry_date = get_atm_strike_symbol(
                symbol="NIFTY",
                spot_price=spot_price,
                option_type="CE",
                config=config,
                today=test_date
            )
            
            # Extract strike from symbol (e.g., NSE:NIFTY2580524850CE -> 24850)
            import re
            # Pattern: NSE:{SYMBOL}{YY}{MMDD}{STRIKE}{TYPE}
            # For NIFTY: NSE:NIFTY2580524850CE -> strike is 24850
            # For monthly: NSE:SENSEX25JUL81500CE -> strike is 81500
            if 'NIFTY' in strike_symbol:
                # NIFTY format: NSE:NIFTY{YY}{MMDD}{STRIKE}{TYPE}
                strike_match = re.search(r'NIFTY\d{5}(\d+)(?:CE|PE)$', strike_symbol)
            else:
                # Monthly format: NSE:{SYMBOL}{YY}{MMM}{STRIKE}{TYPE}
                strike_match = re.search(r'[A-Z]{3}(\d+)(?:CE|PE)$', strike_symbol)
            actual_strike = int(strike_match.group(1)) if strike_match else "Unknown"
            
            print(f"{scenario['name']}:")
            print(f"  Expected Strike: {scenario['expected_strike']}")
            print(f"  Actual Strike: {actual_strike}")
            print(f"  Symbol: {strike_symbol}")
            print(f"  Match: {'✓' if actual_strike == scenario['expected_strike'] else '✗'}")
            print()
            
        except Exception as e:
            print(f"{scenario['name']}: ERROR - {str(e)}")
            print()

# --- Custom test for current day and spot price 24540 ---
def test_today_spot():
    from datetime import datetime
    from algosat.common.swing_utils import get_atm_strike_symbol
    today = datetime.now()
    symbol = "NIFTY"
    spot_price = 24540
    option_type = "CE"
    config = {
        "expiry_exit": {"enabled": True, "days_before_expiry": 3},
        "entry": {"atm_strike_offset_CE": 0, "step_ce": 50, "atm_strike_offset_PE": 0, "step_pe": 50}
    }
    strike_symbol, expiry_date = get_atm_strike_symbol(symbol, spot_price, option_type, config, today=today)
    print("\n--- Test: get_atm_strike_symbol for today ---")
    print(f"Today: {today.strftime('%Y-%m-%d %H:%M')}")
    print(f"Spot Price: {spot_price}")
    print(f"Strike Symbol: {strike_symbol}")
    print(f"Expiry Date: {expiry_date}")

# --- Custom test for days_before_expiry = 3 ---
def test_days_before_expiry_3():
    from datetime import datetime
    from algosat.common.swing_utils import get_atm_strike_symbol
    today = datetime.now()
    symbol = "NIFTY"
    spot_price = 24540
    option_type = "CE"
    config = {
        "expiry_exit": {"enabled": True, "days_before_expiry": 4},
        "entry": {"atm_strike_offset_CE": 0, "step_ce": 50, "atm_strike_offset_PE": 0, "step_pe": 50}
    }
    strike_symbol, expiry_date = get_atm_strike_symbol(symbol, spot_price, option_type, config, today=today)
    print("\n--- Test: get_atm_strike_symbol with days_before_expiry=3 ---")
    print(f"Today: {today.strftime('%Y-%m-%d %H:%M')}")
    print(f"Spot Price: {spot_price}")
    print(f"Strike Symbol: {strike_symbol}")
    print(f"Expiry Date: {expiry_date}")

if __name__ == "__main__":
    print("Testing get_atm_strike_symbol method")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python path includes: {'/opt/algosat' in sys.path}")
    
    try:
        # Run all tests
        test_get_atm_strike_symbol()
        test_edge_cases()
        test_step_and_offset_calculations()
        test_today_spot()  # Run the custom test for today's date
        test_days_before_expiry_3()  # Test for days_before_expiry = 3
        
        print("\n" + "=" * 80)
        print("ALL TESTS COMPLETED")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nFATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
