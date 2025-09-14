#!/usr/bin/env python3
"""
Direct test of Angel symbol format understanding using known working example.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_symbol_formats():
    """Test specific symbol format conversions."""
    
    from algosat.brokers.angel import AngelWrapper
    
    angel = AngelWrapper()
    await angel.login()
    
    print("🔍 Testing Known Angel Symbol Formats")
    print("=" * 50)
    
    # First, let's see what December 2025 NIFTY options are available
    instruments_df = await angel.get_instruments()
    
    # Filter for NIFTY December 2025 options
    dec_2025_options = instruments_df[
        (instruments_df['symbol'].str.contains('NIFTY.*DEC25', regex=True, case=False)) &
        (instruments_df['exch_seg'] == 'NFO')
    ]
    
    print(f"🗓️ Available NIFTY December 2025 options:")
    if not dec_2025_options.empty:
        print(dec_2025_options[['symbol', 'name', 'expiry', 'strike']].head(15).to_string(index=False))
        
        # Pick one for reverse engineering the input format
        if len(dec_2025_options) > 0:
            sample_symbol = dec_2025_options.iloc[0]['symbol']
            print(f"\n💡 Sample DEC25 symbol: {sample_symbol}")
            
            # Try to reverse engineer what the input should be
            # If Angel format is NIFTY30DEC2525000CE, what should input be?
            # NIFTY + date_encoded + 25000 + CE
            
            import re
            match = re.match(r'NIFTY(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)', sample_symbol)
            if match:
                day, month_abbr, year, strike, option_type = match.groups()
                month_map = {
                    'JAN': '1', 'FEB': '2', 'MAR': '3', 'APR': '4', 'MAY': '5', 'JUN': '6',
                    'JUL': '7', 'AUG': '8', 'SEP': '9', 'OCT': '10', 'NOV': '11', 'DEC': '12'
                }
                month_num = month_map.get(month_abbr, '1')
                
                # Reverse engineer input format
                # If 25916 -> 16SEP25, then input format is: YY + M + DD
                input_date_part = f"{year}{month_num}{day}"
                reverse_input = f"NIFTY{input_date_part}{strike}{option_type}"
                
                print(f"   Reverse engineered input: {reverse_input}")
                print(f"   Date part: {input_date_part} ({day} {month_abbr} 20{year})")
    else:
        print("No December 2025 options found")
    
    # Test if we can find the exact converted symbol in Angel's data  
    target_symbol = "NIFTY16SEP2524950CE"
    
    print(f"\n🎯 Testing known working conversion:")
    print(f"Looking for: {target_symbol}")
    
    exact_match = instruments_df[instruments_df['symbol'] == target_symbol]
    
    if not exact_match.empty:
        print("✅ Found exact match:")
        print(exact_match[['symbol', 'name', 'expiry', 'strike', 'token']].to_string(index=False))
        
        # Get token
        token = await angel.get_instrument_token(target_symbol)
        print(f"Token: {token}")
    else:
        print("❌ Exact match not found")

if __name__ == "__main__":
    asyncio.run(test_symbol_formats())