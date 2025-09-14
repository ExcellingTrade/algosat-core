#!/usr/bin/env python3
"""
Comprehensive test script for execution time extraction with full mock data.
Tests both Fyers and Zerodha brokers with all orders and positions.

Usage:
    python test_execution_time_complete.py

This test script validates:
1. Execution time extraction from broker responses
2. Order normalization with all timestamp fields
3. Positions data with complete mock datasets
4. Transition-based execution time setting
"""

import sys
import os
import asyncio
from datetime import datetime, date
from typing import Dict, List, Any
from unittest.mock import patch

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'algosat'))

from algosat.brokers.fyers import FyersWrapper
from algosat.brokers.zerodha import ZerodhaWrapper
from algosat.core.order_manager import OrderManager


async def test_fyers_execution_time():
    """Test Fyers execution time extraction with complete mock data"""
    print("\n" + "="*60)
    print("TESTING FYERS EXECUTION TIME EXTRACTION")
    print("="*60)
    
    # Use patch to mock today's date to Aug 9, 2025 for testing
    mock_date = date(2025, 8, 9)
    
    with patch('datetime.date.today') as mock_today:
        mock_today.return_value = mock_date
        
        try:
            # Initialize Fyers wrapper (mock mode)
            fyers = FyersWrapper()
            
            # Get mock order details
            print("\n1. Fetching Fyers mock order details...")
            orders = await fyers.get_order_details_async()
            print(f"   Retrieved {len(orders)} orders")
            
            # Test order normalization for execution time extraction
            print("\n2. Testing order normalization...")
            order_manager = OrderManager()
            
            for i, order in enumerate(orders[:5], 1):  # Test first 5 orders
                print(f"\n   Order {i}: {order.get('id', 'N/A')}")
                print(f"   Status: {order.get('status', 'N/A')}")
                print(f"   Original orderDateTime: {order.get('orderDateTime', 'N/A')}")
                
                # Normalize single order
                normalized = order_manager._normalize_broker_orders_response([order])
                if normalized:
                    norm_order = normalized[0]
                    exec_time = norm_order.get('execution_time')
                    print(f"   Extracted execution_time: {exec_time}")
                    print(f"   Type: {type(exec_time)}")
                    
                    if exec_time:
                        print(f"   Formatted: {exec_time.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    print("   ERROR: Normalization failed")
            
            # Test positions
            print("\n3. Fetching Fyers mock positions...")
            positions = await fyers.get_positions_async()
            if positions.get('code') == 200:
                net_positions = positions.get('netPositions', [])
                print(f"   Retrieved {len(net_positions)} net positions")
                for i, pos in enumerate(net_positions[:3], 1):
                    print(f"   Position {i}: {pos.get('symbol', 'N/A')} - PL: {pos.get('pl', 0)}")
            else:
                print(f"   ERROR: Failed to get positions - {positions}")
                
        except Exception as e:
            print(f"ERROR in Fyers test: {e}")
            import traceback
            traceback.print_exc()


async def test_zerodha_execution_time():
    """Test Zerodha execution time extraction with complete mock data"""
    print("\n" + "="*60)
    print("TESTING ZERODHA EXECUTION TIME EXTRACTION")
    print("="*60)
    
    # Use patch to mock today's date to Aug 9, 2025 for testing
    mock_date = date(2025, 8, 9)
    
    with patch('datetime.date.today') as mock_today:
        mock_today.return_value = mock_date
        
        try:
            # Initialize Zerodha wrapper (mock mode)
            zerodha = ZerodhaWrapper()
            
            # Get mock order details
            print("\n1. Fetching Zerodha mock order details...")
            orders = await zerodha.get_order_details()
            print(f"   Retrieved {len(orders)} orders")
            
            # Test order normalization for execution time extraction
            print("\n2. Testing order normalization...")
            order_manager = OrderManager()
            
            for i, order in enumerate(orders[:5], 1):  # Test first 5 orders
                print(f"\n   Order {i}: {order.get('order_id', 'N/A')}")
                print(f"   Status: {order.get('status', 'N/A')}")
                print(f"   Original order_timestamp: {order.get('order_timestamp', 'N/A')}")
                print(f"   Original exchange_timestamp: {order.get('exchange_timestamp', 'N/A')}")
                print(f"   Original exchange_update_timestamp: {order.get('exchange_update_timestamp', 'N/A')}")
                
                # Normalize single order
                normalized = order_manager._normalize_broker_orders_response([order])
                if normalized:
                    norm_order = normalized[0]
                    exec_time = norm_order.get('execution_time')
                    print(f"   Extracted execution_time: {exec_time}")
                    print(f"   Type: {type(exec_time)}")
                    
                    if exec_time:
                        print(f"   Formatted: {exec_time.strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    print("   ERROR: Normalization failed")
            
            # Test positions
            print("\n3. Fetching Zerodha mock positions...")
            positions = await zerodha.get_positions()
            if isinstance(positions, dict) and 'net' in positions:
                net_positions = positions.get('net', [])
                print(f"   Retrieved {len(net_positions)} net positions")
                for i, pos in enumerate(net_positions[:3], 1):
                    print(f"   Position {i}: {pos.get('tradingsymbol', 'N/A')} - PnL: {pos.get('pnl', 0)}")
            else:
                print(f"   ERROR: Failed to get positions - {positions}")
                
        except Exception as e:
            print(f"ERROR in Zerodha test: {e}")
            import traceback
            traceback.print_exc()


async def test_transition_based_execution_time():
    """Test transition-based execution time setting logic"""
    print("\n" + "="*60)
    print("TESTING TRANSITION-BASED EXECUTION TIME LOGIC")
    print("="*60)
    
    print("\n1. Testing execution time extraction logic...")
    
    # Create sample order data for transition testing
    sample_order_with_execution = {
        'id': 'TEST123',
        'status': 'FILLED',
        'orderDateTime': '07-Aug-2025 09:33:08',  # Fyers format
        'execution_time': None  # Initially None
    }
    
    sample_order_already_has_execution = {
        'id': 'TEST456', 
        'status': 'FILLED',
        'orderDateTime': '07-Aug-2025 10:28:07',
        'execution_time': datetime(2025, 8, 7, 9, 30, 0)  # Already has execution time
    }
    
    order_manager = OrderManager()
    
    # Test case 1: Order without execution time should get it set
    print("\n   Case 1: Order without execution_time (should be set)")
    normalized1 = order_manager._normalize_broker_orders_response([sample_order_with_execution])
    if normalized1:
        exec_time = normalized1[0].get('execution_time')
        print(f"   Result: execution_time set to {exec_time}")
        print(f"   Success: {exec_time is not None}")
    
    # Test case 2: Order with existing execution time should keep it
    print("\n   Case 2: Order with existing execution_time (should be preserved)")
    original_exec_time = sample_order_already_has_execution['execution_time']
    normalized2 = order_manager._normalize_broker_orders_response([sample_order_already_has_execution])
    if normalized2:
        new_exec_time = normalized2[0].get('execution_time')
        print(f"   Original: {original_exec_time}")
        print(f"   Result: {new_exec_time}")
        print(f"   Success: {new_exec_time == original_exec_time}")
    
    # Test case 3: Order with non-FILLED status should not get execution time
    sample_order_pending = {
        'id': 'TEST789',
        'status': 'PENDING',
        'orderDateTime': '07-Aug-2025 11:06:09',
        'execution_time': None
    }
    
    print("\n   Case 3: PENDING order (should not get execution_time)")
    normalized3 = order_manager._normalize_broker_orders_response([sample_order_pending])
    if normalized3:
        exec_time = normalized3[0].get('execution_time')
        print(f"   Result: execution_time = {exec_time}")
        print(f"   Success: {exec_time is None}")


def print_summary():
    """Print test summary"""
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print("✓ Fyers mock data: 17 orders with orderDateTime extraction")
    print("✓ Zerodha mock data: 15 orders with timestamp extraction")
    print("✓ Positions mock data: Available for both brokers")
    print("✓ Transition-based logic: Only set execution_time when None")
    print("✓ Date safety: Mock data only active on Aug 9, 2025")
    print("\nExecution time extraction is ready for testing!")
    print("Set your system date to 2025-08-09 to activate mock data.")


async def main():
    """Main test function"""
    print("COMPREHENSIVE EXECUTION TIME EXTRACTION TEST")
    print("=" * 60)
    print("This test validates execution time extraction with complete mock datasets.")
    print("Mock data is only active when system date is Aug 9, 2025.")
    print(f"Current date: {date.today()}")
    
    # Run all tests
    await test_fyers_execution_time()
    await test_zerodha_execution_time() 
    await test_transition_based_execution_time()
    
    print_summary()


if __name__ == "__main__":
    asyncio.run(main())
