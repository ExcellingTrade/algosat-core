import pytest
import asyncio
from algosat.core.broker_manager import BrokerManager
from algosat.brokers.angel import Angel
from algosat.brokers.zerodha import Zerodha

# Test symbols in different formats
TEST_SYMBOL_CASES = [
    {
        'input_symbol': 'NSE:NIFTY50',  # Common NSE index format
        'instrument_type': 'INDEX',
        'expected_angel': {'symbol': 'NIFTY 50'},  # Angel's index symbol format
    },
    {
        'input_symbol': 'NSE:NIFTY2591625050CE',  # Option contract in NSE format
        'instrument_type': 'INDEX',  # Should still process as option due to CE/PE
        'expected_angel': {'symbol': 'NIFTY16SEP2525050CE'},  # Angel's option format
    },
    {
        'input_symbol': 'NSE:BANKNIFTY25O2043500PE',  # October option with letter O
        'instrument_type': 'INDEX',  # Should still process as option due to CE/PE
        'expected_angel': {'symbol': 'BANKNIFTY20OCT2543500PE'},  # Angel's format for Oct
    },
    {
        'input_symbol': 'NSE:NIFTY25N1550000CE',  # November option with letter N
        'instrument_type': 'INDEX',  # Should still process as option due to CE/PE
        'expected_angel': {'symbol': 'NIFTY15NOV2550000CE'},  # Angel's format for Nov
    },
    {
        'input_symbol': 'NSE:MIDCPNIFTY',  # Different index
        'instrument_type': 'INDEX',
        'expected_angel': {'symbol': 'NIFTY MIDCAP 100'},  # Angel's index format
    }
]

@pytest.mark.asyncio
async def test_broker_manager_symbol_info():
    """
    Test broker_manager.get_symbol_info with focus on Angel symbol conversion
    """
    print("\n🔍 Testing broker_manager symbol info conversion...")
    
    # Initialize BrokerManager with both Zerodha and Angel
    brokers = {
        'zerodha': Zerodha(),
        'angel': Angel()
    }
    broker_manager = BrokerManager(brokers)
    
    for case in TEST_SYMBOL_CASES:
        input_symbol = case['input_symbol']
        instrument_type = case['instrument_type']
        expected_angel = case['expected_angel']
        
        print(f"\n📊 Testing symbol: {input_symbol}")
        print(f"   Instrument Type: {instrument_type}")
        print(f"   Expected Angel Format: {expected_angel['symbol']}")
        
        try:
            # Get symbol info for Angel broker
            angel_info = await broker_manager.get_symbol_info('angel', input_symbol, instrument_type)
            
            print(f"   Angel Result: {angel_info}")
            
            # Validate the conversion
            if angel_info and angel_info.get('symbol') == expected_angel['symbol']:
                print(f"   ✅ Angel symbol conversion matches expected")
            else:
                print(f"   ❌ Angel symbol mismatch:")
                print(f"      Expected: {expected_angel['symbol']}")
                print(f"      Got: {angel_info['symbol'] if angel_info else None}")
                
            # Additional validation
            if angel_info and 'instrument_token' in angel_info:
                print(f"   🔑 Got instrument token: {angel_info['instrument_token']}")
            
        except Exception as e:
            print(f"   ❌ Error testing {input_symbol}: {str(e)}")
            raise
            
if __name__ == '__main__':
    asyncio.run(test_broker_manager_symbol_info())