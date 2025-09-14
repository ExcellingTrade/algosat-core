#!/usr/bin/env python3
"""
Test script for pullback calculation verification
Tests the corrected pullback calculation logic for swing trading
"""

import sys
import os
import asyncio
import psycopg2
from decimal import Decimal

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

def test_pullback_calculation():
    """Test pullback calculation with known values"""
    
    print("🧪 Testing Pullback Calculation Logic")
    print("=" * 50)
    
    # Test data based on your example and order 315
    test_cases = [
        {
            "name": "Your Example (CE - High=100, Low=50, 40% pullback)",
            "direction": "UP",
            "swing_high": 100.0,
            "swing_low": 50.0,
            "pullback_percentage": 40.0,  # 40% pullback
            "expected_pullback": 100.0 - (50.0 * 0.4),  # swing_high - (swing_distance * 0.4) = 100 - 20 = 80
            "expected_pe_pullback": 50.0 + (50.0 * 0.4)  # For PE: swing_low + (swing_distance * 0.4) = 50 + 20 = 70
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
            "name": "Order 315 (CE - UP trend with corrected formula)",
            "direction": "UP",
            "swing_high": 24639.65,
            "swing_low": 24500.00,  # Assumed swing low
            "pullback_percentage": 0.5,  # 0.5% pullback
            "expected_pullback": 24639.65 - ((24639.65 - 24500.00) * 0.005)  # swing_high - (swing_distance * 0.005)
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
        
        # Show the special case for your example
        if "Your Example" in test_case['name'] and test_case['direction'] == "UP":
            pe_pullback = round(test_case['expected_pe_pullback'], 2)
            print(f"   📝 Note: For PE in same range, pullback would be: {pe_pullback}")
    
    print("\n" + "=" * 50)

def test_database_order_315():
    """Test against actual order 315 data from database"""
    
    print("\n🗄️  Testing Against Database Order 315")
    print("=" * 50)
    
    try:
        conn = psycopg2.connect(
            host='localhost',
            database='algosat_db',
            user='algosat_user',
            password='admin123'
        )
        cur = conn.cursor()
        
        # Get order 315 details
        cur.execute('''
            SELECT order_id, symbol, position_size, entry_price, 
                   entry_spot_swing_high, entry_spot_swing_low, 
                   direction, pullback_level
            FROM positions 
            WHERE order_id = 315
        ''')
        
        result = cur.fetchone()
        if result:
            order_id, symbol, position_size, entry_price, swing_high, swing_low, direction, current_pullback = result
            
            print(f"📊 Order {order_id} Details:")
            print(f"   Symbol: {symbol}")
            print(f"   Direction: {direction}")
            print(f"   Entry Price: {entry_price}")
            print(f"   Swing High: {swing_high}")
            print(f"   Swing Low: {swing_low}")
            print(f"   Current Pullback Level: {current_pullback}")
            
            # Test with different pullback percentages
            test_percentages = [0.5, 1.0, 2.0]
            
            for pullback_pct in test_percentages:
                pullback_factor = pullback_pct / 100.0
                
                if direction == "UP" and swing_high:
                    pullback_distance = float(swing_high) * pullback_factor
                    correct_pullback = float(swing_high) - pullback_distance
                    print(f"\n   📈 {pullback_pct}% Pullback Calculation:")
                    print(f"      Formula: {swing_high} - ({swing_high} × {pullback_factor}) = {round(correct_pullback, 2)}")
                
                elif direction == "DOWN" and swing_low:
                    pullback_distance = float(swing_low) * pullback_factor
                    correct_pullback = float(swing_low) + pullback_distance
                    print(f"\n   📉 {pullback_pct}% Pullback Calculation:")
                    print(f"      Formula: {swing_low} + ({swing_low} × {pullback_factor}) = {round(correct_pullback, 2)}")
        else:
            print("❌ Order 315 not found in database")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Database error: {e}")

def test_smart_level_configuration():
    """Test smart level configuration reading"""
    
    print("\n⚙️  Testing Smart Level Configuration")
    print("=" * 50)
    
    try:
        conn = psycopg2.connect(
            host='localhost',
            database='algosat_db',
            user='algosat_user',
            password='admin123'
        )
        cur = conn.cursor()
        
        # Get smart level configuration
        cur.execute('''
            SELECT symbol_name, pullback_percentage, is_enabled
            FROM algosat_symbol_smart_levels
            WHERE is_enabled = true
        ''')
        
        results = cur.fetchall()
        if results:
            print("📊 Active Smart Level Configurations:")
            for symbol_name, pullback_pct, is_enabled in results:
                print(f"   Symbol: {symbol_name}")
                print(f"   Pullback %: {pullback_pct}%")
                print(f"   Enabled: {is_enabled}")
                print(f"   ---")
        else:
            print("❌ No active smart level configurations found")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    print("🚀 Starting Pullback Calculation Tests")
    print("=" * 60)
    
    # Run all tests
    test_pullback_calculation()
    test_database_order_315()
    test_smart_level_configuration()
    
    print("\n✅ Test execution completed!")
    print("=" * 60)
