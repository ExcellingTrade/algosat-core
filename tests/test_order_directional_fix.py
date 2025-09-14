#!/usr/bin/env python3
"""
Test script to verify the directional logic fix for BO/CO order calculations
"""

# Test the directional logic
def test_directional_logic():
    # Test BUY side calculations
    print("=== BUY Side Test ===")
    limit_price = 100.0
    stop_loss_raw = 95.0  # Stop loss level (absolute price)
    take_profit_raw = 110.0  # Take profit level (absolute price)
    
    # BUY: stop is below entry, target is above entry
    stop_loss_raw_value = abs(limit_price - stop_loss_raw)  # abs(100 - 95) = 5
    take_profit_raw_value = abs(take_profit_raw - limit_price)  # abs(110 - 100) = 10
    
    print(f"BUY - Limit: {limit_price}, Stop: {stop_loss_raw}, Target: {take_profit_raw}")
    print(f"BUY - Stop Loss Diff: {stop_loss_raw_value}, Take Profit Diff: {take_profit_raw_value}")
    
    # Test SELL side calculations
    print("\n=== SELL Side Test ===")
    limit_price = 100.0
    stop_loss_raw = 105.0  # Stop loss level (absolute price)
    take_profit_raw = 90.0  # Take profit level (absolute price)
    
    # SELL: stop is above entry, target is below entry
    stop_loss_raw_value = abs(stop_loss_raw - limit_price)  # abs(105 - 100) = 5
    take_profit_raw_value = abs(limit_price - take_profit_raw)  # abs(100 - 90) = 10
    
    print(f"SELL - Limit: {limit_price}, Stop: {stop_loss_raw}, Target: {take_profit_raw}")
    print(f"SELL - Stop Loss Diff: {stop_loss_raw_value}, Take Profit Diff: {take_profit_raw_value}")
    
    # Test 0.05 rounding
    print("\n=== Rounding Test ===")
    test_values = [5.025, 5.075, 10.445, 10.309]
    for val in test_values:
        rounded = round(round(val / 0.05) * 0.05, 2)
        print(f"{val} -> {rounded}")

if __name__ == "__main__":
    test_directional_logic()
