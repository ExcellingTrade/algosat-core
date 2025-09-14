#!/usr/bin/env python3
"""
Test Angel One P&L calculation logic
"""

def test_angel_pnl_calculation():
    """Test Angel netvalue parsing"""
    
    # Sample Angel position response (your example)
    angel_position = {
        "exchange": "NSE",
        "symboltoken": "2885",
        "producttype": "DELIVERY",
        "tradingsymbol": "RELIANCE-EQ",
        "symbolname": "RELIANCE",
        "buyqty": "1",
        "sellqty": "0",
        "buyamount": "2235.80",
        "sellamount": "0",
        "netvalue": "- 2235.80",  # This indicates loss/unrealized P&L
        "netqty": "1",
        "totalbuyvalue": "2235.80",
        "totalsellvalue": "0"
    }
    
    # Test the parsing logic
    buyamount = float(angel_position.get('buyamount', 0.0))
    sellamount = float(angel_position.get('sellamount', 0.0))
    
    print(f"Buy Amount: {buyamount}")
    print(f"Sell Amount: {sellamount}")
    
    # Only calculate P&L for active positions
    if buyamount != 0.0 or sellamount != 0.0:
        netvalue_str = angel_position.get('netvalue', '0')
        print(f"Raw netvalue: '{netvalue_str}'")
        
        if isinstance(netvalue_str, str):
            netvalue_str = netvalue_str.strip()
            if netvalue_str.startswith('- '):
                position_pnl = -float(netvalue_str[2:])  # Remove "- " and convert
                print(f"Negative P&L: {position_pnl}")
            elif netvalue_str.startswith('+ '):
                position_pnl = float(netvalue_str[2:])   # Remove "+ " and convert
                print(f"Positive P&L: {position_pnl}")
            else:
                position_pnl = float(netvalue_str)
                print(f"Direct P&L: {position_pnl}")
        else:
            position_pnl = float(netvalue_str)
            print(f"Float P&L: {position_pnl}")
    
    print(f"\nFinal calculated P&L: {position_pnl}")
    
    # Test various netvalue formats
    test_cases = [
        "- 2235.80",  # Loss
        "+ 1500.50",  # Profit
        "1200.30",    # Direct positive
        "-800.40",    # Direct negative
        "0"           # No P&L
    ]
    
    print("\nTesting various netvalue formats:")
    for netvalue in test_cases:
        if isinstance(netvalue, str):
            netvalue_str = netvalue.strip()
            if netvalue_str.startswith('- '):
                pnl = -float(netvalue_str[2:])
            elif netvalue_str.startswith('+ '):
                pnl = float(netvalue_str[2:])
            else:
                pnl = float(netvalue_str)
        else:
            pnl = float(netvalue)
        print(f"  '{netvalue}' → {pnl}")

if __name__ == "__main__":
    test_angel_pnl_calculation()