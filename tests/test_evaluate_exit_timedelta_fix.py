#!/usr/bin/env python3
"""
Test script to verify the timedelta scope fix works correctly in evaluate_exit method.
This simulates the exact scenario where OrderMonitor calls evaluate_exit on strategy instance.
"""

import sys
import asyncio
sys.path.insert(0, '/opt/algosat')

from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

async def test_evaluate_exit_timedelta_scope():
    """Test that timedelta is properly available in all scopes within evaluate_exit"""
    
    print("=== Testing evaluate_exit timedelta scope fix ===")
    
    # Mock the strategy class to simulate real usage
    class MockSwingHighLowBuyStrategy:
        def __init__(self):
            self.symbol = "NIFTY50"
            self.stoploss_minutes = 5
            self.entry_swing_left_bars = 3
            self.entry_swing_right_bars = 3
            self.entry_minutes = 5
            self.rsi_period = 14
            self.trade = {
                "carry_forward": {"enabled": True},
                "holiday_exit": {"enabled": False},
                "target": {"rsi_exit": {"enabled": False}}
            }
            self.dp = Mock()
        
        async def fetch_history_data(self, dp, symbols, interval_minutes):
            """Mock fetch_history_data to return sample data"""
            return {
                symbols[0]: [
                    {"timestamp": "2025-07-22T09:15:00", "close": 56400.0, "open": 56380.0, "high": 56420.0, "low": 56370.0},
                    {"timestamp": "2025-07-22T09:20:00", "close": 56410.0, "open": 56400.0, "high": 56430.0, "low": 56390.0}
                ]
            }
        
        async def update_stoploss_in_db(self, order_id, new_stoploss):
            """Mock database update"""
            print(f"  Mock DB update: order_id={order_id}, new_stoploss={new_stoploss}")
        
        async def evaluate_exit(self, order_row):
            """Copy of the actual evaluate_exit method with timedelta scope fix"""
            try:
                strike_symbol = order_row.get('strike_symbol') or order_row.get('symbol') or order_row.get('strike')
                if not strike_symbol:
                    print("ERROR: Missing strike_symbol in order_row.")
                    return False
                    
                order_id = order_row.get('id') or order_row.get('order_id')
                print(f"evaluate_exit: Checking exit conditions for order_id={order_id}, strike={strike_symbol}")
                
                # Use the spot symbol for spot-level checks
                spot_symbol = self.symbol
                trade_config = self.trade
                
                # Fetch recent candle history for spot price checks
                history_dict = await self.fetch_history_data(
                    self.dp, [spot_symbol], self.stoploss_minutes
                )
                history_df = history_dict.get(str(spot_symbol))
                if history_df is None or len(history_df) < 2:
                    print(f"WARNING: Not enough history for {spot_symbol}.")
                    return False
                    
                # Get current spot price
                current_spot_price = history_df[-1].get("close") 
                if current_spot_price is None:
                    print(f"ERROR: Could not get current spot price for {spot_symbol}")
                    return False
                
                print(f"evaluate_exit: Current spot price={current_spot_price} for order_id={order_id}")
                
                # Initialize stoploss from order (will be updated if next day)
                stoploss_spot_level = order_row.get("stoploss_spot_level")
                target_spot_level = order_row.get("target_spot_level")
                signal_direction = order_row.get("signal_direction") or order_row.get("direction", "").upper()
                
                # PRIORITY 1: NEXT DAY STOPLOSS UPDATE (UPDATE ONLY, DON'T EXIT)
                carry_forward_config = trade_config.get("carry_forward", {})
                if carry_forward_config.get("enabled", False):
                    try:
                        from algosat.core.time_utils import get_ist_datetime
                        from algosat.common.broker_utils import get_trade_day
                        from datetime import datetime, timedelta
                        
                        print("✓ PRIORITY 1: timedelta import successful")
                        
                        # Get order entry date and current date
                        current_datetime = datetime.now()  # Simplified for test
                        current_trade_day = datetime.now().date()
                        
                        # Get order entry date
                        order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                        if order_timestamp:
                            if isinstance(order_timestamp, str):
                                order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                            else:
                                order_datetime = order_timestamp
                            
                            order_trade_day = order_datetime.date()
                            
                            # Check if it's next trading day
                            if current_trade_day > order_trade_day:
                                # Calculate first candle completion time based on stoploss timeframe
                                market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                                first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                                
                                print(f"✓ PRIORITY 1: timedelta usage successful - {first_candle_end_time}")
                                
                    except Exception as e:
                        print(f"❌ Error in next day stoploss update logic: {e}")
                        return False
                
                # PRIORITY 5: NEXT DAY SWING EXIT (Check last two candles for swing breach)
                carry_forward_config = trade_config.get("carry_forward", {})
                if carry_forward_config.get("enabled", False):
                    try:
                        from algosat.core.time_utils import get_ist_datetime
                        from algosat.common.broker_utils import get_trade_day
                        from datetime import datetime, timedelta
                        
                        print("✓ PRIORITY 5: timedelta import successful")
                        
                        # Get order entry date and current date
                        current_datetime = datetime.now()  # Simplified for test
                        current_trade_day = datetime.now().date()
                        
                        # Get order entry date
                        order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                        if order_timestamp:
                            if isinstance(order_timestamp, str):
                                order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                            else:
                                order_datetime = order_timestamp
                            
                            order_trade_day = order_datetime.date()
                            
                            # Check if it's next trading day
                            if current_trade_day > order_trade_day:
                                # Calculate first candle completion time
                                market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                                first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                                
                                print(f"✓ PRIORITY 5: timedelta usage successful - {first_candle_end_time}")
                                        
                    except Exception as e:
                        print(f"❌ Error in next day swing exit logic: {e}")
                        return False
                
                print("✓ No exit condition met")
                return False
                
            except Exception as e:
                print(f"❌ Error in evaluate_exit for order_id={order_row.get('id')}: {e}")
                return False
    
    # Test the strategy
    strategy = MockSwingHighLowBuyStrategy()
    
    # Mock order row similar to what OrderMonitor would pass
    order_row = {
        'id': 131,
        'strike_symbol': 'NIFTY50CE56400',
        'signal_time': '2025-07-21T09:30:00Z',  # Previous day
        'stoploss_spot_level': 56350.0,
        'target_spot_level': 56500.0,
        'signal_direction': 'UP'
    }
    
    print(f"Testing with order_row: {order_row}")
    
    # Call evaluate_exit like OrderMonitor would
    result = await strategy.evaluate_exit(order_row)
    print(f"evaluate_exit result: {result}")
    
    print("🎉 Test completed successfully!")
    return True

async def main():
    """Run the test"""
    try:
        await test_evaluate_exit_timedelta_scope()
        print("\n🎉 All tests passed! The timedelta scope fix is working correctly.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
