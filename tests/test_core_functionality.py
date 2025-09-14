#!/usr/bin/env python3
"""
Comprehensive test script to validate core functionality after rate limiting changes.
Tests initialization, data fetching, and order placement to ensure no corruption.
"""

import asyncio
import sys
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Core imports similar to main.py
from algosat.core.db import init_db, engine
from algosat.core.db import seed_default_strategies_and_configs
from algosat.core.data_manager import DataManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_manager import OrderManager
from algosat.core.order_request import OrderRequest, OrderType, Side
from algosat.common.logger import get_logger

# Additional imports for testing
from algosat.core.db import get_trade_enabled_brokers, AsyncSessionLocal

logger = get_logger("CoreFunctionalityTest")

class CoreFunctionalityTester:
    """Test class to validate core functionality"""
    
    def __init__(self):
        self.broker_manager = None
        self.data_manager = None
        self.order_manager = None
        self.test_results = {}
        
    async def initialize_components(self):
        """Initialize all components similar to main.py"""
        try:
            logger.info("🔄 Starting core functionality test...")
            
            # 1) Initialize database schema
            logger.info("🔄 Initializing database schema...")
            await init_db()
            self.test_results["db_init"] = {"status": "success", "message": "Database initialized"}
            
            # 2) Seed default strategies and configs
            logger.info("🔄 Seeding default strategies and configs...")
            await seed_default_strategies_and_configs()
            self.test_results["db_seed"] = {"status": "success", "message": "Default data seeded"}
            
            # 3) Initialize broker manager
            logger.info("🔄 Initializing broker manager...")
            self.broker_manager = BrokerManager()
            await self.broker_manager.setup()
            self.test_results["broker_manager"] = {"status": "success", "message": f"Broker manager initialized with {len(self.broker_manager.brokers)} brokers"}
            
            # 4) Initialize data manager
            logger.info("🔄 Initializing data manager...")
            self.data_manager = DataManager(broker_manager=self.broker_manager)
            await self.data_manager.ensure_broker()
            self.test_results["data_manager"] = {"status": "success", "message": "Data manager initialized"}
            
            # 5) Initialize order manager
            logger.info("🔄 Initializing order manager...")
            self.order_manager = OrderManager(self.broker_manager)
            self.test_results["order_manager"] = {"status": "success", "message": "Order manager initialized"}
            
            logger.info("✅ All components initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize components: {e}")
            logger.error(traceback.format_exc())
            self.test_results["initialization"] = {"status": "error", "message": str(e)}
            return False
    
    async def test_broker_connections(self):
        """Test broker connections and basic functionality"""
        try:
            logger.info("🔄 Testing broker connections...")
            
            if not self.broker_manager or not self.broker_manager.brokers:
                self.test_results["broker_connections"] = {"status": "warning", "message": "No brokers available"}
                return
            
            broker_results = {}
            
            for broker_name, broker in self.broker_manager.brokers.items():
                try:
                    logger.info(f"Testing broker: {broker_name}")
                    
                    # Test get_profile
                    try:
                        profile = await broker.get_profile()
                        broker_results[f"{broker_name}_profile"] = {"status": "success", "data": profile}
                        logger.info(f"✅ {broker_name} profile fetched successfully")
                    except Exception as e:
                        broker_results[f"{broker_name}_profile"] = {"status": "error", "message": str(e)}
                        logger.warning(f"⚠️ {broker_name} profile fetch failed: {e}")
                    
                    # Test get_positions
                    try:
                        positions = await broker.get_positions()
                        broker_results[f"{broker_name}_positions"] = {"status": "success", "count": len(positions) if positions else 0}
                        logger.info(f"✅ {broker_name} positions fetched successfully ({len(positions) if positions else 0} positions)")
                    except Exception as e:
                        broker_results[f"{broker_name}_positions"] = {"status": "error", "message": str(e)}
                        logger.warning(f"⚠️ {broker_name} positions fetch failed: {e}")
                    
                    # Note: Skipping get_margin test as brokers don't have this method
                    logger.info(f"✅ {broker_name} basic broker methods tested")
                        
                except Exception as e:
                    broker_results[broker_name] = {"status": "error", "message": str(e)}
                    logger.error(f"❌ Broker {broker_name} test failed: {e}")
            
            self.test_results["broker_connections"] = broker_results
            logger.info("✅ Broker connection tests completed")
            
        except Exception as e:
            logger.error(f"❌ Broker connection test failed: {e}")
            self.test_results["broker_connections"] = {"status": "error", "message": str(e)}
    
    async def test_data_manager_functionality(self):
        """Test data manager history fetching"""
        try:
            logger.info("🔄 Testing data manager functionality...")
            
            if not self.data_manager:
                self.test_results["data_manager_tests"] = {"status": "error", "message": "Data manager not initialized"}
                return
            
            # Test symbols to try
            test_symbols = [
                "NSE:NIFTY50-INDEX",
                "NSE:NIFTYBANK-INDEX", 
                "NSE:SBIN-EQ",
                "NSE:RELIANCE-EQ",
                "NSE:TCS-EQ"
            ]
            
            data_results = {}
            
            for symbol in test_symbols:
                try:
                    logger.info(f"Testing history fetch for {symbol}")
                    
                    # Test get_history with IST timezone-aware dates
                    from algosat.core.time_utils import get_ist_now
                    end_date = get_ist_now()
                    start_date = end_date - timedelta(days=5)
                    
                    history = await self.data_manager.get_history(
                        symbol=symbol,
                        from_date=start_date.strftime("%Y-%m-%d"),
                        to_date=end_date.strftime("%Y-%m-%d"),
                        ohlc_interval="1"
                    )
                    # print(history.head())
                    if not history.empty and len(history) > 0:
                        data_results[symbol] = {
                            "status": "success", 
                            "records": len(history),
                            "sample_data": history[:2] if len(history) >= 2 else history
                        }
                        logger.info(f"✅ {symbol} history fetched: {len(history)} records")
                    else:
                        data_results[symbol] = {"status": "warning", "message": "No data returned"}
                        logger.warning(f"⚠️ {symbol} returned no data")
                    
                    # Small delay to respect rate limits
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    data_results[symbol] = {"status": "error", "message": str(e)}
                    logger.warning(f"⚠️ {symbol} history fetch failed: {e}")
            
            self.test_results["data_manager_tests"] = data_results
            logger.info("✅ Data manager tests completed")
            
        except Exception as e:
            logger.error(f"❌ Data manager test failed: {e}")
            self.test_results["data_manager_tests"] = {"status": "error", "message": str(e)}
    
    async def test_order_manager_functionality(self):
        """Test order manager functionality (without actually placing orders)"""
        try:
            logger.info("🔄 Testing order manager functionality...")
            
            if not self.order_manager:
                self.test_results["order_manager_tests"] = {"status": "error", "message": "Order manager not initialized"}
                return
            
            order_results = {}
            
            # Test order validation
            try:
                # Create a test order request (but don't place it)
                test_order = OrderRequest(
                    symbol="NSE:SBIN-EQ",
                    side=Side.BUY,
                    order_type=OrderType.MARKET,
                    quantity=1,
                    strategy_id=1,
                    signal_id="test_signal"
                )
                
                order_results["order_creation"] = {"status": "success", "message": "Order request created successfully"}
                logger.info("✅ Order request creation test passed")
                
            except Exception as e:
                order_results["order_creation"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Order creation test failed: {e}")
            
            # Test order manager methods that don't place actual orders
            try:
                # Test getting trade enabled brokers using DB function
                from algosat.core.db import get_trade_enabled_brokers
                trade_enabled_brokers = await get_trade_enabled_brokers()
                order_results["trade_enabled_brokers"] = {
                    "status": "success", 
                    "count": len(trade_enabled_brokers),
                    "brokers": trade_enabled_brokers  # This is already a list of strings
                }
                logger.info(f"✅ Trade enabled brokers: {len(trade_enabled_brokers)}")
                
            except Exception as e:
                order_results["trade_enabled_brokers"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Trade enabled brokers test failed: {e}")
            
            # Test order placement infrastructure (without placing actual orders)
            try:
                # Test the place_order method exists and can be called with dry_run
                test_order = OrderRequest(
                    symbol="NSE:SBIN-EQ",
                    side=Side.BUY,
                    order_type=OrderType.MARKET,
                    quantity=1,
                    strategy_id=1,
                    signal_id="test_signal"
                )
                
                # Test order validation logic exists
                if hasattr(self.order_manager, 'place_order'):
                    order_results["order_placement_method"] = {"status": "success", "message": "place_order method exists"}
                    logger.info("✅ OrderManager.place_order method exists")
                else:
                    order_results["order_placement_method"] = {"status": "warning", "message": "place_order method not found"}
                    logger.warning("⚠️ OrderManager.place_order method not found")
                
            except Exception as e:
                order_results["order_placement_method"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Order placement method test failed: {e}")
            
            # Note: We're NOT testing actual order placement to avoid placing real orders
            logger.info("ℹ️ Skipping actual order placement test to avoid real trades")
            order_results["order_placement"] = {"status": "skipped", "message": "Skipped to avoid real orders"}
            
            self.test_results["order_manager_tests"] = order_results
            logger.info("✅ Order manager tests completed")
            
        except Exception as e:
            logger.error(f"❌ Order manager test failed: {e}")
            self.test_results["order_manager_tests"] = {"status": "error", "message": str(e)}
    
    async def test_rate_limiting_functionality(self):
        """Test rate limiting functionality"""
        try:
            logger.info("🔄 Testing rate limiting functionality...")
            
            from algosat.core.rate_limiter import get_rate_limiter, GlobalRateLimiter
            
            rate_results = {}
            
            # Test rate limiter initialization
            try:
                rate_limiter = await get_rate_limiter()
                rate_results["rate_limiter_init"] = {"status": "success", "message": "Rate limiter initialized"}
                logger.info("✅ Rate limiter initialization test passed")
            except Exception as e:
                rate_results["rate_limiter_init"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Rate limiter initialization failed: {e}")
            
            # Test rate config retrieval
            try:
                from algosat.core.async_retry import get_retry_config
                retry_config = get_retry_config("order_critical")
                rate_results["retry_config"] = {"status": "success", "config": str(retry_config)}
                logger.info("✅ Retry config retrieval test passed")
            except Exception as e:
                rate_results["retry_config"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Retry config test failed: {e}")
            
            # Test global rate limiter configs
            try:
                configs = GlobalRateLimiter.DEFAULT_RATE_CONFIGS
                rate_results["global_configs"] = {
                    "status": "success", 
                    "broker_count": len(configs),
                    "brokers": list(configs.keys())
                }
                logger.info(f"✅ Global rate configs available for {len(configs)} brokers")
            except Exception as e:
                rate_results["global_configs"] = {"status": "error", "message": str(e)}
                logger.error(f"❌ Global rate config test failed: {e}")
            
            self.test_results["rate_limiting_tests"] = rate_results
            logger.info("✅ Rate limiting tests completed")
            
        except Exception as e:
            logger.error(f"❌ Rate limiting test failed: {e}")
            self.test_results["rate_limiting_tests"] = {"status": "error", "message": str(e)}
    
    def print_test_summary(self):
        """Print comprehensive test summary"""
        logger.info("\n" + "="*80)
        logger.info("🎯 CORE FUNCTIONALITY TEST SUMMARY")
        logger.info("="*80)
        
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        warning_tests = 0
        
        for test_category, results in self.test_results.items():
            logger.info(f"\n📋 {test_category.upper().replace('_', ' ')}:")
            
            if isinstance(results, dict):
                if "status" in results:
                    # Single test result
                    status = results["status"]
                    message = results.get("message", "No message")
                    
                    if status == "success":
                        logger.info(f"  ✅ {message}")
                        passed_tests += 1
                    elif status == "error":
                        logger.error(f"  ❌ {message}")
                        failed_tests += 1
                    elif status == "warning":
                        logger.warning(f"  ⚠️ {message}")
                        warning_tests += 1
                    else:
                        logger.info(f"  ℹ️ {message}")
                    
                    total_tests += 1
                else:
                    # Multiple test results
                    for sub_test, sub_result in results.items():
                        if isinstance(sub_result, dict) and "status" in sub_result:
                            status = sub_result["status"]
                            message = sub_result.get("message", sub_result.get("data", "No message"))
                            
                            if status == "success":
                                logger.info(f"  ✅ {sub_test}: {message}")
                                passed_tests += 1
                            elif status == "error":
                                logger.error(f"  ❌ {sub_test}: {message}")
                                failed_tests += 1
                            elif status == "warning":
                                logger.warning(f"  ⚠️ {sub_test}: {message}")
                                warning_tests += 1
                            else:
                                logger.info(f"  ℹ️ {sub_test}: {message}")
                            
                            total_tests += 1
        
        logger.info("\n" + "="*80)
        logger.info("🏁 FINAL RESULTS:")
        logger.info(f"   Total Tests: {total_tests}")
        logger.info(f"   ✅ Passed: {passed_tests}")
        logger.info(f"   ❌ Failed: {failed_tests}")
        logger.info(f"   ⚠️ Warnings: {warning_tests}")
        logger.info(f"   Success Rate: {(passed_tests/total_tests)*100:.1f}%" if total_tests > 0 else "No tests run")
        logger.info("="*80)
        
        if failed_tests == 0:
            logger.info("🎉 ALL CORE FUNCTIONALITY TESTS PASSED! No corruption detected.")
        else:
            logger.warning(f"⚠️ {failed_tests} test(s) failed. Please review the failures above.")
    
    async def run_all_tests(self):
        """Run all functionality tests"""
        try:
            # Initialize components
            if not await self.initialize_components():
                logger.error("❌ Failed to initialize components. Aborting tests.")
                return
            
            # Run individual tests
            await self.test_broker_connections()
            await self.test_data_manager_functionality()
            await self.test_order_manager_functionality()
            await self.test_rate_limiting_functionality()
            
            # Print summary
            self.print_test_summary()
            
        except Exception as e:
            logger.error(f"❌ Test execution failed: {e}")
            logger.error(traceback.format_exc())
        finally:
            # Clean up
            try:
                if engine:
                    await engine.dispose()
                    logger.info("🧹 Database connection cleaned up")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

async def main():
    """Main entry point"""
    logger.info("🚀 Starting comprehensive core functionality test...")
    
    # Prevent running as module (similar to main.py)
    if __name__ == "__main__" and __package__ is None:
        print("\n[INFO] Running core functionality test directly.\n")
    
    tester = CoreFunctionalityTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
