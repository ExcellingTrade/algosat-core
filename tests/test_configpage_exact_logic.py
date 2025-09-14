#!/usr/bin/env python3
"""
Test script to verify the API methods used by ConfigsPage
"""
import requests
import json

BASE_URL = "http://localhost:8001"

def get_auth_token():
    """Get authentication token by logging in"""
    print("Getting authentication token...")
    
    login_url = f"{BASE_URL}/auth/login"
    login_data = {
        "username": "admin",
        "password": "admin123"
    }
    
    try:
        response = requests.post(login_url, json=login_data)
        if response.status_code == 200:
            auth_data = response.json()
            access_token = auth_data.get('access_token')
            print("✅ Authentication successful!")
            return access_token
        else:
            print(f"❌ Login failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None

def test_configpage_logic():
    """Test the exact same logic that ConfigsPage uses"""
    
    token = get_auth_token()
    if not token:
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Get strategy 1 (Option Buy)
        strategy_id = 1
        
        # Get configs for this strategy
        configs_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/configs/", headers=headers)
        configs = configs_response.json()
        
        # Get symbols for this strategy  
        symbols_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/symbols/", headers=headers)
        symbols = symbols_response.json()
        
        print(f"Strategy {strategy_id} has {len(configs)} configs and {len(symbols)} symbols")
        
        for config in configs:
            config_id = config['id']
            config_name = config['name']
            
            # Filter symbols for this config (same as ConfigsPage)
            config_symbols = [s for s in symbols if s.get('config_id') == config_id]
            
            if len(config_symbols) == 0:
                print(f"\nConfig '{config_name}' has no symbols, skipping...")
                continue
                
            print(f"\n=== Config '{config_name}' (ID: {config_id}) ===")
            print(f"Config has {len(config_symbols)} symbols")
            
            total_pnl = 0
            total_trades = 0
            live_trades = 0
            
            for symbol in config_symbols:
                symbol_id = symbol['id'] 
                symbol_name = symbol['symbol']
                
                print(f"\n  Processing symbol '{symbol_name}' (ID: {symbol_id})")
                
                # Test getOrdersPnlStatsBySymbolId (same as ConfigsPage)
                pnl_url = f"{BASE_URL}/orders/pnl-stats/by-symbol-id/{symbol_id}"
                pnl_response = requests.get(pnl_url, headers=headers)
                
                if pnl_response.status_code == 200:
                    pnl_stats = pnl_response.json()
                    print(f"    PnL Stats: {pnl_stats}")
                else:
                    print(f"    ❌ PnL Stats failed: {pnl_response.status_code}")
                    pnl_stats = {'overall_pnl': 0, 'overall_trade_count': 0}
                
                # Test getOrdersSummaryBySymbol (same as ConfigsPage) 
                summary_url = f"{BASE_URL}/orders/summary/{symbol_name}"
                summary_response = requests.get(summary_url, headers=headers)
                
                if summary_response.status_code == 200:
                    orders_summary = summary_response.json()
                    print(f"    Orders Summary: {orders_summary}")
                else:
                    print(f"    ❌ Orders Summary failed: {summary_response.status_code}")
                    orders_summary = {'live_pnl': 0, 'open_trades': 0}
                
                # Aggregate the same way as ConfigsPage
                symbol_total_pnl = (pnl_stats.get('overall_pnl', 0) or 0) + (orders_summary.get('live_pnl', 0) or 0)
                symbol_total_trades = pnl_stats.get('overall_trade_count', 0) or 0
                symbol_live_trades = orders_summary.get('open_trades', 0) or 0
                
                total_pnl += symbol_total_pnl
                total_trades += symbol_total_trades
                live_trades += symbol_live_trades
                
                print(f"    Symbol aggregation: P&L={symbol_total_pnl}, Trades={symbol_total_trades}, Live={symbol_live_trades}")
            
            print(f"\n  *** CONFIG '{config_name}' FINAL TOTALS ***")
            print(f"    Total P&L: ₹{total_pnl}")
            print(f"    Total Trades: {total_trades}")
            print(f"    Live Trades: {live_trades}")
            print(f"    This should be what appears in ConfigsPage!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_configpage_logic()
