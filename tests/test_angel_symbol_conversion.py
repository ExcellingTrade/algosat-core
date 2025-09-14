#!/usr/bin/env python3
"""
Test Angel broker symbol conversion for get_symbol_info method.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_angel_symbol_conversion():
    """Test Angel broker symbol conversion in get_symbol_info."""
    try:
        print("🚀 Testing Angel Broker Symbol Conversion")
        print("=" * 60)
        
        # Import broker manager and Angel broker directly
        from algosat.core.broker_manager import BrokerManager
        from algosat.brokers.angel import AngelWrapper
        
        # Create Angel broker instance for testing
        angel_broker = AngelWrapper()
        await angel_broker.login()  # Initialize with credentials from DB
        
        # Create broker manager and manually add Angel broker
        broker_manager = BrokerManager()
        broker_manager.brokers['angel'] = angel_broker
        
        # Test symbols for conversion (updated format)
        test_symbols = [
            # Jan-Sep: Numbers 1-9
            "NIFTY2591624950CE",      # 16 Sep 2025, Strike 24950, Call (known working)
            "NIFTY16SEP2524950CE",      # 09 Sep 2025, Strike 24700, Call (non-existent to test variations)
            # "NIFTY25520000CE",        # 05 May 2025, Strike 20000, Call
            # "NIFTY25825000PE",        # 08 Aug 2025, Strike 25000, Put
            
            # # Oct-Dec: Letters O, N, D
            # "NIFTY25O2025000CE",      # 20 Oct 2025, Strike 25000, Call (O = Oct)
            # "NIFTY25N1524800PE",      # 15 Nov 2025, Strike 24800, Put (N = Nov)
            # "NIFTY25D3030000PE",      # 30 Dec 2025, Strike 30000, Put (D = Dec)
            
            # # Simple symbols
            # "NIFTY",                  # Simple index symbol
            # "BANKNIFTY",             # Simple index symbol
        ]
        
        print("\n🔄 Testing Symbol Conversions:")
        print("-" * 80)
        
        for symbol in test_symbols:
            try:
                print(f"\n📊 Testing: {symbol}")
                
                # Test with NFO instrument type (for options)
                if any(x in symbol for x in ['CE', 'PE']):
                    result = await broker_manager.get_symbol_info('angel', symbol, instrument_type='NFO')
                else:
                    result = await broker_manager.get_symbol_info('angel', symbol, instrument_type='OPTIDX')
                print(f"  Result: {result}")
                converted_symbol = result.get('symbol')
                instrument_token = result.get('instrument_token')
                
                if converted_symbol != symbol:
                    print(f"  ✅ Converted: {symbol} -> {converted_symbol}")
                else:
                    print(f"  ➡️  No conversion: {symbol}")
                
                if instrument_token:
                    print(f"  🎯 Token: {instrument_token}")
                else:
                    print(f"  ❌ No token found")
                    
            except Exception as e:
                print(f"  ❌ Error: {e}")
        
        print("\n" + "=" * 60)
        print("✅ Symbol conversion testing completed!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_symbol_conversion())