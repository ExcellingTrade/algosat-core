#!/usr/bin/env python3
"""
Test script to debug config stats aggregation
"""
import requests
import json
import getpass

BASE_URL = "http://localhost:8001"

def get_auth_token():
    """Get authentication token by logging in"""
    print("Getting authentication token...")
    
    # Get username and password
    # username = input("Username: ")
    # password = getpass.getpass("Password: ")
    
    login_url = f"{BASE_URL}/auth/login"
    login_data = {
        "username": "admin",
        "password": "admin123"  # Use your actual credentials here
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

def test_api_endpoints():
    """Test the API endpoints used by ConfigsPage"""
    
    # Get authentication token first
    token = get_auth_token()
    if not token:
        print("Cannot proceed without authentication token")
        return
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # First get configs and symbols
    print("Testing config stats aggregation...")
    
    try:
        # Test strategy endpoint first to get strategy ID
        strategies_response = requests.get(f"{BASE_URL}/strategies/", headers=headers)
        if strategies_response.status_code != 200:
            print(f"❌ Failed to get strategies: {strategies_response.status_code}")
            return
        
        strategies = strategies_response.json()
        if not strategies:
            print("No strategies found")
            return
        
        strategy = strategies[0]  # Use first strategy
        strategy_id = strategy['id']
        strategy_name = strategy['name']
        print(f"Testing with strategy: {strategy_name} (ID: {strategy_id})")
        
        # Get configs for this strategy
        configs_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/configs/", headers=headers)
        if configs_response.status_code != 200:
            print(f"❌ Failed to get configs: {configs_response.status_code}")
            return
        
        configs = configs_response.json()
        print(f"Found {len(configs)} configs")
        
        # Get symbols for this strategy
        symbols_response = requests.get(f"{BASE_URL}/strategies/{strategy_id}/symbols/", headers=headers)
        if symbols_response.status_code != 200:
            print(f"❌ Failed to get symbols: {symbols_response.status_code}")
            return
            
        symbols = symbols_response.json()
        print(f"Found {len(symbols)} symbols")
        
        for config in configs[:2]:  # Test first 2 configs
            config_id = config['id']
            config_name = config['name']
            
            # Filter symbols for this config
            config_symbols = [s for s in symbols if s.get('config_id') == config_id]
            print(f"\nConfig '{config_name}' has {len(config_symbols)} symbols")
            
            total_pnl = 0
            total_trades = 0
            live_trades = 0
            
            for symbol in config_symbols:
                symbol_id = symbol['id']
                symbol_name = symbol['symbol']
                
                try:
                    # Test the symbol stats API endpoint that ConfigsPage uses
                    symbol_stats_url = f"{BASE_URL}/strategies/symbols/{symbol_id}/stats"
                    
                    print(f"  Testing symbol {symbol_name} (ID: {symbol_id})")
                    print(f"    Symbol stats URL: {symbol_stats_url}")
                    
                    # Get symbol stats (this is what ConfigsPage uses)
                    stats_response = requests.get(symbol_stats_url, headers=headers)
                    if stats_response.status_code == 200:
                        stats_data = stats_response.json()
                        print(f"    Symbol stats: {stats_data}")
                        
                        # Extract stats as ConfigsPage does
                        symbol_total_pnl = stats_data.get('total_pnl', 0)
                        symbol_live_pnl = stats_data.get('live_pnl', 0)
                        symbol_total_trades = stats_data.get('total_trades', 0)
                        symbol_live_trades = stats_data.get('live_trades', 0)
                        
                        # Aggregate as ConfigsPage does
                        total_pnl += symbol_total_pnl + symbol_live_pnl
                        total_trades += symbol_total_trades
                        live_trades += symbol_live_trades
                        
                        print(f"    Symbol totals: Total P&L={symbol_total_pnl}, Live P&L={symbol_live_pnl}, Total Trades={symbol_total_trades}, Live Trades={symbol_live_trades}")
                        
                    else:
                        print(f"    ❌ Symbol stats failed: {stats_response.status_code} - {stats_response.text}")
                    
                    # Also test the PnL stats API for comparison
                    pnl_stats_url = f"{BASE_URL}/orders/pnl-stats/by-symbol-id/{symbol_id}"
                    pnl_response = requests.get(pnl_stats_url, headers=headers)
                    if pnl_response.status_code == 200:
                        pnl_data = pnl_response.json()
                        print(f"    PnL stats comparison: {pnl_data}")
                    else:
                        print(f"    PnL stats failed: {pnl_response.status_code}")
                    
                except Exception as e:
                    print(f"    ❌ Error processing symbol {symbol_name}: {e}")
            
            print(f"  Config '{config_name}' FINAL totals: P&L={total_pnl}, Trades={total_trades}, Live Trades={live_trades}")
            print(f"  This is what should appear in ConfigsPage for this config!")
    
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_api_endpoints()
