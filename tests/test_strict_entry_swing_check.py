#!/usr/bin/env python3
"""
Test script for strict entry vs swing check validation in SwingHighLowBuyStrategy.
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from unittest.mock import Mock, AsyncMock
from algosat.strategies.swing_highlow_buy import SwingHighLowBuyStrategy


class MockConfig:
    def __init__(self):
        self.symbol = "NSE:NIFTY50"
        self.exchange = "NSE"
        self.instrument = "NIFTY50"
        self.enable_smart_levels = True
        self.symbol_id = 1
        self.strategy_id = 1
        self.trade = {
            "entry": {"timeframe": "5m", "swing_left_bars": 3, "swing_right_bars": 3, "entry_buffer": 0},
            "stoploss": {"percentage": 0.05, "timeframe": "5m"},
            "confirmation": {"timeframe": "1m", "candles": 1},
            "ce_lot_qty": 2,
            "pe_lot_qty": 2,
            "lot_size": 75
        }
        self.indicators = {"rsi_period": 14, "rsi_timeframe": "5m"}


async def test_strict_entry_swing_check():
    """Test the strict entry vs swing check functionality."""
    
    print("🔍 Testing Strict Entry vs Swing Check Validation")
    print("=" * 60)
    
    # Create mock strategy
    config = MockConfig()
    data_manager = Mock()
    execution_manager = Mock()
    
    # Create strategy instance
    strategy = SwingHighLowBuyStrategy(config, data_manager, execution_manager)
    
    # Mock smart level with strict_entry_vs_swing_check enabled
    strategy._smart_level = {
        'id': 1,
        'name': 'Test Level',
        'strategy_symbol_id': 1,
        'is_active': True,
        'entry_level': 23000.0,
        'bullish_target': 23500.0,
        'bearish_target': 22500.0,
        'initial_lot_ce': 2,
        'initial_lot_pe': 2,
        'remaining_lot_ce': 2,
        'remaining_lot_pe': 2,
        'ce_buy_enabled': True,
        'ce_sell_enabled': False,
        'pe_buy_enabled': True,
        'pe_sell_enabled': False,
        'max_trades': 5,
        'max_loss_trades': 2,
        'pullback_percentage': 50.0,
        'strict_entry_vs_swing_check': True,  # ENABLED
        'notes': 'Test level',
        'created_at': None,
        'updated_at': None
    }
    
    # Test scenarios
    test_cases = [
        {
            'name': 'UP Trend - Swing High ABOVE Entry Level (PASS)',
            'breakout_type': 'CE',
            'spot_price': 23050.0,
            'direction': 'UP',
            'swing_high': {'price': 23100.0},  # Above entry_level (23000)
            'swing_low': {'price': 22900.0},
            'expected_result': True
        },
        {
            'name': 'UP Trend - Swing High BELOW Entry Level (FAIL)',
            'breakout_type': 'CE',
            'spot_price': 23050.0,
            'direction': 'UP',
            'swing_high': {'price': 22950.0},  # Below entry_level (23000)
            'swing_low': {'price': 22900.0},
            'expected_result': False
        },
        {
            'name': 'DOWN Trend - Swing Low BELOW Entry Level (PASS)',
            'breakout_type': 'PE',
            'spot_price': 22950.0,
            'direction': 'DOWN',
            'swing_high': {'price': 23100.0},
            'swing_low': {'price': 22900.0},  # Below entry_level (23000)
            'expected_result': True
        },
        {
            'name': 'DOWN Trend - Swing Low ABOVE Entry Level (FAIL)',
            'breakout_type': 'PE',
            'spot_price': 22950.0,
            'direction': 'DOWN',
            'swing_high': {'price': 23100.0},
            'swing_low': {'price': 23050.0},  # Above entry_level (23000)
            'expected_result': False
        }
    ]
    
    print(f"Entry Level: {strategy._smart_level['entry_level']}")
    print(f"Strict Check Enabled: {strategy._smart_level['strict_entry_vs_swing_check']}")
    print()
    
    # Run test cases
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        print(f"  Breakout Type: {test_case['breakout_type']}")
        print(f"  Spot Price: {test_case['spot_price']}")
        print(f"  Direction: {test_case['direction']}")
        print(f"  Swing High: {test_case['swing_high']['price']}")
        print(f"  Swing Low: {test_case['swing_low']['price']}")
        print(f"  Expected: {'PASS' if test_case['expected_result'] else 'FAIL'}")
        
        try:
            is_valid, smart_level_data, smart_lot_qty = await strategy.validate_smart_level_entry(
                test_case['breakout_type'],
                test_case['spot_price'],
                test_case['direction'],
                swing_high=test_case['swing_high'],
                swing_low=test_case['swing_low']
            )
            
            result_str = "PASS" if is_valid else "FAIL"
            status = "✅ CORRECT" if is_valid == test_case['expected_result'] else "❌ INCORRECT"
            
            print(f"  Result: {result_str} - {status}")
            if is_valid:
                print(f"  Smart Lot Qty: {smart_lot_qty}")
                
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
        
        print()
    
    # Test with strict check disabled
    print("Testing with Strict Entry vs Swing Check DISABLED")
    print("-" * 50)
    
    strategy._smart_level['strict_entry_vs_swing_check'] = False
    
    test_case_disabled = {
        'name': 'UP Trend - Swing High BELOW Entry Level with Strict Check DISABLED (should PASS)',
        'breakout_type': 'CE',
        'spot_price': 23050.0,
        'direction': 'UP',
        'swing_high': {'price': 22950.0},  # Below entry_level (23000) but strict check disabled
        'swing_low': {'price': 22900.0},
        'expected_result': True
    }
    
    print(f"Test: {test_case_disabled['name']}")
    
    try:
        is_valid, smart_level_data, smart_lot_qty = await strategy.validate_smart_level_entry(
            test_case_disabled['breakout_type'],
            test_case_disabled['spot_price'],
            test_case_disabled['direction'],
            swing_high=test_case_disabled['swing_high'],
            swing_low=test_case_disabled['swing_low']
        )
        
        result_str = "PASS" if is_valid else "FAIL"
        status = "✅ CORRECT" if is_valid == test_case_disabled['expected_result'] else "❌ INCORRECT" 
        
        print(f"Result: {result_str} - {status}")
        if is_valid:
            print(f"Smart Lot Qty: {smart_lot_qty}")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
    
    print("\n🎉 Testing completed!")


if __name__ == "__main__":
    asyncio.run(test_strict_entry_swing_check())
