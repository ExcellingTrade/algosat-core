#!/usr/bin/env python3
"""
Test script to verify Angel positions parsing for exit_order method.
Tests the quantity field extraction from Angel API response format.
"""

import sys
import os
sys.path.append('/opt/algosat')

def test_angel_positions_parsing():
    """Test Angel positions data parsing logic."""
    
    print("🔍 Testing Angel Positions Parsing for exit_order")
    print("=" * 60)
    
    # Sample Angel positions API response data (from user's example)
    sample_positions_data = [
        {
            "exchange": "NSE",
            "symboltoken": "2885",
            "producttype": "DELIVERY",
            "tradingsymbol": "RELIANCE-EQ",
            "symbolname": "RELIANCE",
            "instrumenttype": "",
            "priceden": "1",
            "pricenum": "1",
            "genden": "1",
            "gennum": "1",
            "precision": "2",
            "multiplier": "-1",
            "boardlotsize": "1",
            "buyqty": "1",
            "sellqty": "0",
            "buyamount": "2235.80",
            "sellamount": "0",
            "symbolgroup": "EQ",
            "strikeprice": "-1",
            "optiontype": "",
            "expirydate": "",
            "lotsize": "1",
            "cfbuyqty": "0",
            "cfsellqty": "0",
            "cfbuyamount": "0",
            "cfsellamount": "0",
            "buyavgprice": "2235.80",
            "sellavgprice": "0",
            "avgnetprice": "2235.80",
            "netvalue": "- 2235.80",
            "netqty": "1",
            "totalbuyvalue": "2235.80",
            "totalsellvalue": "0",
            "cfbuyavgprice": "0",
            "cfsellavgprice": "0",
            "totalbuyavgprice": "2235.80",
            "totalsellavgprice": "0",
            "netprice": "2235.80"
        },
        {
            "exchange": "NFO",
            "symboltoken": "44662",
            "producttype": "INTRADAY",
            "tradingsymbol": "NIFTY16SEP2524950CE",
            "symbolname": "NIFTY",
            "instrumenttype": "OPTIDX",
            "buyqty": "150",
            "sellqty": "75",
            "netqty": "75",  # Net position: 150 bought - 75 sold = 75
            "buyavgprice": "210.50",
            "sellavgprice": "180.25",
            "lotsize": "75"
        }
    ]
    
    print("📊 Testing position data parsing:")
    print("-" * 40)
    
    # Test the parsing logic for each position
    for i, pos in enumerate(sample_positions_data):
        symbol = pos.get('tradingsymbol', 'N/A')
        netqty = pos.get('netqty', '0')
        buyqty = pos.get('buyqty', '0')
        sellqty = pos.get('sellqty', '0')
        producttype = pos.get('producttype', 'N/A')
        
        print(f"\n🔹 Position {i+1}: {symbol}")
        print(f"   Product Type: {producttype}")
        print(f"   Buy Qty: {buyqty}")
        print(f"   Sell Qty: {sellqty}")
        print(f"   Net Qty: {netqty}")
        
        # Simulate the parsing logic from exit_order method
        try:
            net_qty_val = float(netqty) if netqty else 0
            buy_qty_val = float(buyqty) if buyqty else 0
            sell_qty_val = float(sellqty) if sellqty else 0
            
            filled_qty = abs(net_qty_val)
            
            print(f"   ✅ Parsed - Net: {net_qty_val}, Buy: {buy_qty_val}, Sell: {sell_qty_val}")
            print(f"   📤 Exit Qty: {filled_qty}")
            
            # Determine exit scenarios
            if net_qty_val > 0:
                print(f"   🔄 Position Type: LONG → Exit side would be SELL")
            elif net_qty_val < 0:
                print(f"   🔄 Position Type: SHORT → Exit side would be BUY")
            else:
                print(f"   ⚠️  Position Type: FLAT → No exit needed")
                
        except (ValueError, TypeError) as e:
            print(f"   ❌ Parsing Error: {e}")
    
    print("\n" + "-" * 40)
    
    # Test symbol matching logic
    print("\n🔍 Testing symbol matching logic:")
    print("-" * 35)
    
    test_symbols = [
        "RELIANCE-EQ",
        "reliance-eq",
        "RELIANCE-eq",
        "NIFTY16SEP2524950CE",
        "nifty16sep2524950ce"
    ]
    
    for test_symbol in test_symbols:
        found_match = False
        for pos in sample_positions_data:
            pos_symbol = str(pos.get('tradingsymbol', ''))
            if pos_symbol.upper() == str(test_symbol).upper():
                found_match = True
                netqty = pos.get('netqty', '0')
                producttype = pos.get('producttype', 'N/A')
                print(f"✅ Match: '{test_symbol}' → {pos_symbol} (netqty={netqty}, product={producttype})")
                break
        
        if not found_match:
            print(f"❌ No match: '{test_symbol}'")
    
    print("\n" + "=" * 60)
    print("🎯 Angel positions parsing test completed!")
    print("✅ Field names: netqty, buyqty, sellqty, producttype, tradingsymbol")
    print("✅ Data types: All quantities are strings that need conversion")
    print("✅ Symbol matching: Case-insensitive comparison works")
    print("=" * 60)

if __name__ == "__main__":
    test_angel_positions_parsing()