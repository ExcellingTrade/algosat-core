#!/usr/bin/env python3
"""
Test script for Angel broker instruments functionality.
Tests fetching, caching, searching, and token lookup capabilities.
"""

import asyncio
import sys
import os
import pandas as pd
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

async def test_angel_instruments():
    """Test Angel broker instruments functionality."""
    try:
        print("🚀 Testing Angel Broker Instruments Functionality")
        print("=" * 60)
        
        # Import Angel broker
        from algosat.brokers.angel import AngelWrapper
        
        # Create Angel broker instance (no login needed for instruments)
        angel = AngelWrapper()
        await angel.login()  # Ensure login to initialize session
        
        print("\n📊 Testing get_instruments()...")
        
        # Test fetching instruments
        start_time = datetime.now()
        instruments_df = await angel.get_instruments()
        fetch_time = (datetime.now() - start_time).total_seconds()
        
        if instruments_df is not None and not instruments_df.empty:
            print(f"✅ Successfully fetched {len(instruments_df):,} instruments in {fetch_time:.2f}s")
            print(f"📋 Columns: {list(instruments_df.columns)}")
            print(f"🔍 Sample instruments:")
            print(instruments_df.head(3).to_string(index=False))
        else:
            print("❌ Failed to fetch instruments")
            return
            
        print("\n🔍 Testing search_instruments()...")
        
        # Test searching for NIFTY instruments
        nifty_results = await angel.search_instruments("NIFTY", limit=5)
        print(f"📈 NIFTY search results ({len(nifty_results)} found):")
        for i, (_, result) in enumerate(nifty_results.iterrows(), 1):
            print(f"  {i}. {result['symbol']} - {result['name']} ({result['exch_seg']})")
            
        # Test searching for BANKNIFTY instruments  
        banknifty_results = await angel.search_instruments("BANKNIFTY", limit=3)
        print(f"\n🏦 BANKNIFTY search results ({len(banknifty_results)} found):")
        for i, (_, result) in enumerate(banknifty_results.iterrows(), 1):
            print(f"  {i}. {result['symbol']} - {result['name']} ({result['exch_seg']})")
            
        # Test searching for specific option symbol
        target_symbol = "NIFTY2591624950CE"
        print(f"\n🔍 Searching for specific symbol: {target_symbol}")
        
        option_results = await angel.search_instruments("NIFTY25", limit=5000)
        print(f"📊 NIFTY25 search results: {len(option_results)} found")
        
        # Direct DataFrame access to analyze NIFTY symbols
        print(f"\n📋 Direct DataFrame Analysis for NIFTY symbols...")
        instruments_df = await angel.get_instruments()
        
        # Filter for NIFTY symbols in NFO segment
        nifty_symbols = instruments_df[
            (instruments_df['name'].str.contains('NIFTY', case=False, na=False)) & 
            (instruments_df['exch_seg'] == 'NFO')
        ].copy()
        
        # Convert strike to numeric for comparison
        nifty_symbols['strike'] = pd.to_numeric(nifty_symbols['strike'], errors='coerce')
        
        print(f"🔍 Total NIFTY symbols in NFO: {len(nifty_symbols)}")
        
        # Check if our target symbol exists
        exact_match = nifty_symbols[nifty_symbols['symbol'] == target_symbol]
        if not exact_match.empty:
            print(f"✅ Found exact match for {target_symbol}:")
            print(exact_match.to_string(index=False))
        else:
            print(f"❌ No exact match for {target_symbol}")
            
            # Look for similar symbols
            similar_symbols = nifty_symbols[
                nifty_symbols['symbol'].str.contains('NIFTY259', case=False, na=False)
            ]
            print(f"\n🔍 Similar symbols containing 'NIFTY259': {len(similar_symbols)} found")
            if not similar_symbols.empty:
                print(similar_symbols[['symbol', 'name', 'exch_seg', 'expiry', 'strike']].head(10).to_string(index=False))
            
            # Look for symbols with strike around 24950 (checking nearby strikes)
            strike_range = nifty_symbols[
                (nifty_symbols['strike'] >= 2495000.0) & 
                (nifty_symbols['strike'] <= 2495000.0)
            ]
            print(f"\n🎯 NIFTY symbols with strike exactly 2495000 (24950*100): {len(strike_range)} found")
            if not strike_range.empty:
                print(strike_range[['symbol', 'name', 'exch_seg', 'expiry', 'strike']].head(10).to_string(index=False))
            
            # Check strikes around 24950 range (24900-25000)
            strike_nearby = nifty_symbols[
                (nifty_symbols['strike'] >= 2490000.0) & 
                (nifty_symbols['strike'] <= 2500000.0)
            ]
            print(f"\n📊 NIFTY symbols with strikes 24900-25000: {len(strike_nearby)} found")
            if not strike_nearby.empty:
                print("First 20 results:")
                print(strike_nearby[['symbol', 'name', 'exch_seg', 'expiry', 'strike']].head(20).to_string(index=False))
                
            # Look for 16 Dec 2025 expiry (25916 might be date format)
            # Check if any symbols have December 2025 expiry
            dec_2025 = nifty_symbols[
                nifty_symbols['expiry'].str.contains('DEC25', case=False, na=False)
            ]
            print(f"\n📅 NIFTY symbols expiring in DEC25: {len(dec_2025)} found")
            if not dec_2025.empty:
                print("Sample DEC25 expiry symbols:")
                print(dec_2025[['symbol', 'name', 'exch_seg', 'expiry', 'strike']].head(15).to_string(index=False))
                
            # Show some sample NIFTY option symbols to understand the format
            print(f"\n📋 Sample NIFTY option symbols (to understand format):")
            sample_options = nifty_symbols[
                (nifty_symbols['symbol'].str.contains('CE', case=False, na=False)) |
                (nifty_symbols['symbol'].str.contains('PE', case=False, na=False))
            ].head(15)
            print(sample_options.columns)
            print(sample_options[['symbol', 'name', 'exch_seg', 'expiry', 'strike', 'instrumenttype']].to_string(index=False))
            
        print("\n🎯 Testing get_instrument_token()...")
        
        # Test token lookup for some symbols
        test_symbols = [
            "NIFTY",
            "BANKNIFTY", 
            "SBIN",
        ]
        
        # Add some option symbols from search results if available
        if not nifty_results.empty:
            test_symbols.append(nifty_results.iloc[0]['symbol'])
        if not option_results.empty:
            test_symbols.append(option_results.iloc[0]['symbol'])
            
        for symbol in test_symbols:
            try:
                token = await angel.get_instrument_token(symbol)
                if token:
                    print(f"  ✅ {symbol}: token = {token}")
                else:
                    print(f"  ❌ {symbol}: token not found")
            except Exception as e:
                print(f"  ❌ {symbol}: error = {e}")
                
        print("\n⚡ Testing cache performance...")
        
        # Test cache hit performance
        start_time = datetime.now()
        cached_instruments = await angel.get_instruments()
        cache_time = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ Cache hit time: {cache_time:.4f}s (should be much faster than {fetch_time:.2f}s)")
        
        # Test multiple searches (should be fast due to caching)
        start_time = datetime.now()
        for _ in range(5):
            await angel.search_instruments("NIFTY", limit=10)
        search_time = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ 5 searches completed in {search_time:.4f}s")
        
        print("\n🧹 Testing clear_instruments_cache()...")
        
        # Clear cache and verify
        angel.clear_instruments_cache()
        print("✅ Cache cleared successfully")
        
        # Verify cache is actually cleared by fetching again
        start_time = datetime.now()
        instruments_df_2 = await angel.get_instruments()
        refetch_time = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ Refetch after cache clear: {refetch_time:.2f}s")
        print(f"📊 Instruments count: {len(instruments_df_2):,}")
        
        print("\n📈 Testing instrument type filtering...")
        
        # Test filtering by exchange segment
        equity_count = len(instruments_df_2[instruments_df_2['exch_seg'] == 'NSE'])
        nfo_count = len(instruments_df_2[instruments_df_2['exch_seg'] == 'NFO'])
        mcx_count = len(instruments_df_2[instruments_df_2['exch_seg'] == 'MCX'])
        
        print(f"  📊 NSE (Equity): {equity_count:,} instruments")
        print(f"  📊 NFO (F&O): {nfo_count:,} instruments") 
        print(f"  📊 MCX (Commodity): {mcx_count:,} instruments")
        
        print("\n✅ All Angel instruments tests completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_angel_instruments())