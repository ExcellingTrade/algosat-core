"""
Test for Angel One get_balance() method using rmsLimit API
"""
import asyncio
import sys
import os

# Add the project root to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from algosat.brokers.angel import AngelWrapper


async def test_angel_get_balance():
    """
    Test Angel One get_balance method that calls smartapi.rmsLimit()
    """
    print("Testing Angel One get_balance() method...")
    print("=" * 50)
    
    try:
        # Initialize Angel wrapper
        angel_broker = AngelWrapper()
        
        # Initialize the broker connection
        await angel_broker.initialize()
        
        print("Angel broker initialized successfully")
        print("-" * 30)
        
        # Call get_balance method
        print("Calling get_balance() method...")
        balance_response = await angel_broker.get_balance()
        
        print("Balance Response:")
        print("=" * 50)
        
        if balance_response:
            # Print formatted response
            print(f"Status: {balance_response.get('status', 'N/A')}")
            print(f"Message: {balance_response.get('message', 'N/A')}")
            print(f"Error Code: {balance_response.get('errorcode', 'N/A')}")
            
            if 'data' in balance_response:
                data = balance_response['data']
                print("\nBalance Data:")
                print("-" * 20)
                
                # Print key balance fields in a readable format
                balance_fields = [
                    ('Net Balance', 'net'),
                    ('Available Cash', 'availablecash'),
                    ('Available Intraday Payin', 'availableintradaypayin'),
                    ('Available Limit Margin', 'availablelimitmargin'),
                    ('Collateral', 'collateral'),
                    ('M2M Unrealized', 'm2munrealized'),
                    ('M2M Realized', 'm2mrealized'),
                    ('Utilized Debits', 'utiliseddebits'),
                    ('Utilized Span', 'utilisedspan'),
                    ('Utilized Option Premium', 'utilisedoptionpremium'),
                    ('Utilized Holding Sales', 'utilisedholdingsales'),
                    ('Utilized Exposure', 'utilisedexposure'),
                    ('Utilized Turnover', 'utilisedturnover'),
                    ('Utilized Payout', 'utilisedpayout')
                ]
                
                for label, key in balance_fields:
                    value = data.get(key, 'N/A')
                    print(f"{label}: {value}")
                    
                # Print any additional fields not in our predefined list
                additional_fields = {k: v for k, v in data.items() 
                                   if k not in [field[1] for field in balance_fields]}
                if additional_fields:
                    print("\nAdditional Fields:")
                    for key, value in additional_fields.items():
                        print(f"{key}: {value}")
            else:
                print("No 'data' field in response")
                print(f"Full response: {balance_response}")
        else:
            print("Empty response received")
            
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 50)
    print("Test completed")


if __name__ == "__main__":
    asyncio.run(test_angel_get_balance())