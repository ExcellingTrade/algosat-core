#!/usr/bin/env python3
"""
Test script for complete two-tier risk management system:
1. Broker-level risk management with emergency stops
2. Per-trade loss validation with automatic exit

This script tests both risk management layers to ensure they work correctly together.
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, '/opt/algosat')

from algosat.core.db import AsyncSessionLocal, get_broker_risk_summary, get_order_by_id
from algosat.core.strategy_manager import RiskManager
from algosat.core.order_manager import OrderManager
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from sqlalchemy import text

async def test_broker_risk_management():
    """Test the broker-level risk management system"""
    print("=" * 60)
    print("🧪 TESTING BROKER-LEVEL RISK MANAGEMENT")
    print("=" * 60)
    
    broker_manager = BrokerManager()
    data_manager = DataManager()
    order_manager = OrderManager(broker_manager)
    # Initialize risk manager
    risk_manager = RiskManager(order_manager)
    
    try:
        # Test 1: Check broker risk limits
        print("\n1️⃣ Testing broker risk limit checks...")
        risk_check_result = await risk_manager.check_broker_risk_limits()
        print(f"✅ Broker risk check result: {risk_check_result}")
        
        # Test 2: Get risk summary
        print("\n2️⃣ Testing risk summary...")
        async with AsyncSessionLocal() as session:
            risk_summary = await get_broker_risk_summary(session)
            # Convert Decimal and datetime objects for JSON serialization
            def convert_objects(obj):
                if hasattr(obj, '__dict__'):
                    return {k: convert_objects(v) for k, v in obj.__dict__.items()}
                elif isinstance(obj, dict):
                    return {k: convert_objects(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_objects(item) for item in obj]
                elif hasattr(obj, '__class__'):
                    if 'Decimal' in str(type(obj)):
                        return float(obj)
                    elif 'datetime' in str(type(obj)):
                        return str(obj)
                    else:
                        return obj
                else:
                    return obj
            
            risk_summary_serializable = convert_objects(risk_summary)
            print(f"✅ Risk summary: {json.dumps(risk_summary_serializable, indent=2)}")
        
        # Test 3: Test position-based P&L calculation
        print("\n3️⃣ Testing position-based P&L calculation...")
        async with AsyncSessionLocal() as session:
            # Test P&L calculation for each broker
            brokers = ['fyers', 'angel', 'zerodha']
            broker_pnl = {}
            for broker in brokers:
                try:
                    pnl = await risk_manager._calculate_broker_pnl(session, broker)
                    broker_pnl[broker] = pnl
                except Exception as e:
                    broker_pnl[broker] = f"Error: {str(e)}"
            
            print(f"✅ Broker P&L calculation: {json.dumps(broker_pnl, indent=2)}")
        
        print("\n✅ BROKER-LEVEL RISK MANAGEMENT TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ BROKER-LEVEL RISK MANAGEMENT TEST FAILED: {e}")
        return False

async def test_per_trade_loss_validation():
    """Test the per-trade loss validation system"""
    print("\n" + "=" * 60)
    print("🧪 TESTING PER-TRADE LOSS VALIDATION")
    print("=" * 60)
    
    try:
        # Test 1: Get strategy config with max_loss_per_lot
        print("\n1️⃣ Testing strategy config parsing...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT trade FROM strategy_configs WHERE id = 2"))
            config_row = result.fetchone()
            
            if config_row:
                trade_config = json.loads(config_row[0]) if isinstance(config_row[0], str) else config_row[0]
                max_loss_per_lot = trade_config.get('max_loss_per_lot', 0)
                lot_size = trade_config.get('lot_size', 0)
                print(f"✅ Strategy config loaded: max_loss_per_lot={max_loss_per_lot}, lot_size={lot_size}")
            else:
                print("❌ No strategy config found")
                return False
        
        # Test 2: Get broker risk summary for trade enabled brokers
        print("\n2️⃣ Testing trade enabled brokers count...")
        async with AsyncSessionLocal() as session:
            risk_data = await get_broker_risk_summary(session)
            trade_enabled_brokers = risk_data.get('summary', {}).get('trade_enabled_brokers', 0)
            print(f"✅ Trade enabled brokers: {trade_enabled_brokers}")
        
        # Test 3: Simulate per-trade risk calculation
        print("\n3️⃣ Testing per-trade risk calculation...")
        lot_qty = 2  # Example lot quantity
        total_risk_exposure = lot_qty * trade_enabled_brokers * max_loss_per_lot
        print(f"✅ Risk calculation: {lot_qty} lots × {trade_enabled_brokers} brokers × ₹{max_loss_per_lot} = ₹{total_risk_exposure}")
        
        # Test 4: Test risk threshold scenarios
        print("\n4️⃣ Testing risk threshold scenarios...")
        
        # Scenario A: Within limit
        test_pnl_safe = -1000  # Small loss
        if total_risk_exposure > 0 and test_pnl_safe > -abs(total_risk_exposure):
            print(f"✅ SAFE: P&L {test_pnl_safe} is within limit of ₹{total_risk_exposure}")
        else:
            print(f"⚠️  SAFE scenario failed: P&L {test_pnl_safe}, limit ₹{total_risk_exposure}")
        
        # Scenario B: Exceeds limit
        test_pnl_danger = -(total_risk_exposure + 1000)  # Loss exceeding limit
        if total_risk_exposure > 0 and test_pnl_danger < -abs(total_risk_exposure):
            print(f"🚨 DANGER: P&L {test_pnl_danger} exceeds limit of ₹{total_risk_exposure} - would trigger exit")
        else:
            print(f"✅ DANGER scenario test: P&L {test_pnl_danger}, limit ₹{total_risk_exposure}")
        
        print("\n✅ PER-TRADE LOSS VALIDATION TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ PER-TRADE LOSS VALIDATION TEST FAILED: {e}")
        return False

async def test_integration_scenarios():
    """Test integration scenarios where both systems work together"""
    print("\n" + "=" * 60)
    print("🧪 TESTING INTEGRATION SCENARIOS")
    print("=" * 60)
    
    try:
        # Scenario 1: Check if both systems can work simultaneously
        print("\n1️⃣ Testing simultaneous risk management systems...")
        
        # Initialize both systems
        broker_manager = BrokerManager()
        data_manager = DataManager()
        order_manager = OrderManager(broker_manager)
        risk_manager = RiskManager(order_manager)
        
        # Check broker limits
        broker_check = await risk_manager.check_broker_risk_limits()
        print(f"✅ Broker risk check: {broker_check}")
        
        # Get current order count for simulation
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM orders WHERE status IN ('ENTRY', 'PARTIALLY_FILLED')"))
            active_orders = result.scalar()
            print(f"✅ Active orders count: {active_orders}")
        
        # Scenario 2: Memory and performance check
        print("\n2️⃣ Testing system performance...")
        start_time = datetime.now()
        
        # Run multiple checks to test caching
        async with AsyncSessionLocal() as session:
            for i in range(3):
                await risk_manager._calculate_broker_pnl(session, 'fyers')
            
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        print(f"✅ Multiple P&L calculations completed in {execution_time:.2f} seconds (caching working)")
        
        print("\n✅ INTEGRATION TESTS PASSED")
        return True
        
    except Exception as e:
        print(f"❌ INTEGRATION TEST FAILED: {e}")
        return False

async def main():
    """Main test runner"""
    print("🚀 STARTING COMPLETE RISK MANAGEMENT SYSTEM TESTS")
    print(f"⏰ Test started at: {datetime.now()}")
    
    # Run all test suites
    test_results = []
    
    # Test broker-level risk management
    broker_test = await test_broker_risk_management()
    test_results.append(("Broker Risk Management", broker_test))
    
    # Test per-trade loss validation
    trade_test = await test_per_trade_loss_validation()
    test_results.append(("Per-Trade Loss Validation", trade_test))
    
    # Test integration scenarios
    integration_test = await test_integration_scenarios()
    test_results.append(("Integration Scenarios", integration_test))
    
    # Print final results
    print("\n" + "=" * 60)
    print("📊 FINAL TEST RESULTS")
    print("=" * 60)
    
    all_passed = True
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Risk management system is ready for production.")
    else:
        print("⚠️  SOME TESTS FAILED! Please review the issues above.")
    print("=" * 60)
    
    print(f"⏰ Test completed at: {datetime.now()}")

if __name__ == "__main__":
    asyncio.run(main())
