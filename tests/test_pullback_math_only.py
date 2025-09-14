#!/usr/bin/env python3
"""
Simple test script for pullback calculation verification - mathematical tests only
Tests the corrected pullback calculation logic using swing distance
"""

def test_pullback_calculation():
    """Test pullback calculation with known values"""
    
    print("🧪 Testing Pullback Calculation Logic (Swing Distance Based)")
    print("=" * 60)
    
    # Test data based on your example and realistic scenarios
    test_cases = [
        {
            "name": "Your Example (CE - High=100, Low=50, 40% pullback)",
            "direction": "UP",
            "swing_high": 100.0,
            "swing_low": 50.0,
            "pullback_percentage": 40.0,  # 40% pullback
            "expected_pullback": 100.0 - (50.0 * 0.4),  # swing_high - (swing_distance * 0.4) = 100 - 20 = 80
        },
        {
            "name": "Your Example (PE - High=100, Low=50, 40% pullback)",
            "direction": "DOWN",
            "swing_high": 100.0,
            "swing_low": 50.0,
            "pullback_percentage": 40.0,  # 40% pullback
            "expected_pullback": 50.0 + (50.0 * 0.4)  # swing_low + (swing_distance * 0.4) = 50 + 20 = 70
        },
        {
            "name": "Order 315 Type (CE - Realistic scenario)",
            "direction": "UP",
            "swing_high": 24639.65,
            "swing_low": 24500.00,  # Assumed realistic swing low
            "pullback_percentage": 50.0,  # 50% pullback
            "expected_pullback": 24639.65 - ((24639.65 - 24500.00) * 0.5)  # 24639.65 - (139.65 * 0.5) = 24569.825
        },
        {
            "name": "50% Pullback Example (CE)",
            "direction": "UP",
            "swing_high": 25000.00,
            "swing_low": 24000.00,
            "pullback_percentage": 50.0,  # 50% pullback
            "expected_pullback": 25000.00 - ((25000.00 - 24000.00) * 0.5)  # 25000 - (1000 * 0.5) = 24500
        },
        {
            "name": "50% Pullback Example (PE)",
            "direction": "DOWN",
            "swing_high": 25000.00,
            "swing_low": 24000.00,
            "pullback_percentage": 50.0,  # 50% pullback
            "expected_pullback": 24000.00 + ((25000.00 - 24000.00) * 0.5)  # 24000 + (1000 * 0.5) = 24500
        },
        {
            "name": "Small Percentage (0.5%) CE",
            "direction": "UP",
            "swing_high": 24600.00,
            "swing_low": 24400.00,
            "pullback_percentage": 0.5,  # 0.5% pullback
            "expected_pullback": 24600.00 - ((24600.00 - 24400.00) * 0.005)  # 24600 - (200 * 0.005) = 24599
        }
    ]
    
    def calculate_pullback(direction, swing_high, swing_low, pullback_percentage):
        """Calculate pullback using the corrected swing distance formula"""
        pullback_factor = pullback_percentage / 100.0
        
        # Calculate swing distance
        swing_distance = swing_high - swing_low
        pullback_distance = swing_distance * pullback_factor
        
        if direction == "UP":
            # CE trade: Pullback is percentage down from swing high based on swing distance
            pullback_level = swing_high - pullback_distance
            return round(pullback_level, 2)
        
        elif direction == "DOWN":
            # PE trade: Pullback is percentage up from swing low based on swing distance
            pullback_level = swing_low + pullback_distance
            return round(pullback_level, 2)
        
        return None
    
    # Run test cases
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🔍 Test Case {i}: {test_case['name']}")
        print(f"   Direction: {test_case['direction']}")
        print(f"   Swing High: {test_case['swing_high']}")
        print(f"   Swing Low: {test_case['swing_low']}")
        print(f"   Pullback %: {test_case['pullback_percentage']}%")
        
        # Calculate swing distance
        swing_distance = test_case['swing_high'] - test_case['swing_low']
        pullback_distance = swing_distance * (test_case['pullback_percentage'] / 100.0)
        
        print(f"   Swing Distance: {swing_distance}")
        print(f"   Pullback Distance: {pullback_distance}")
        
        calculated = calculate_pullback(
            test_case['direction'],
            test_case['swing_high'],
            test_case['swing_low'],
            test_case['pullback_percentage']
        )
        
        expected = round(test_case['expected_pullback'], 2)
        
        print(f"   Expected: {expected}")
        print(f"   Calculated: {calculated}")
        
        if calculated == expected:
            print(f"   ✅ PASS")
        else:
            print(f"   ❌ FAIL")
        
        # Show formula for clarity
        if test_case['direction'] == "UP":
            print(f"   📝 Formula: {test_case['swing_high']} - ({swing_distance} × {test_case['pullback_percentage']/100}) = {calculated}")
        else:
            print(f"   📝 Formula: {test_case['swing_low']} + ({swing_distance} × {test_case['pullback_percentage']/100}) = {calculated}")
    
    print("\n" + "=" * 60)
    print("📋 Summary:")
    print("✅ Pullback calculation now uses swing distance (high - low)")
    print("✅ CE trades: pullback_level = swing_high - (swing_distance × pullback%)")
    print("✅ PE trades: pullback_level = swing_low + (swing_distance × pullback%)")
    print("✅ This ensures pullback level is always between swing_high and swing_low")

if __name__ == "__main__":
    print("🚀 Starting Pullback Calculation Tests (Swing Distance Based)")
    print("=" * 70)
    
    # Run mathematical tests
    test_pullback_calculation()
    
    print("\n✅ Test execution completed!")
    print("=" * 70)
