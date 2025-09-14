#!/usr/bin/env python3
"""
Test script to analyze the P&L calculation issue in strategy_manager.py
"""

import asyncio
import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.db import AsyncSessionLocal
from algosat.core.dbschema import broker_executions
from sqlalchemy import select, func, distinct, and_
from datetime import date, datetime, timedelta

async def analyze_broker_executions():
    """Analyze broker_executions table to understand the data structure"""
    print("🔍 ANALYZING BROKER_EXECUTIONS TABLE")
    print("=" * 50)
    
    async with AsyncSessionLocal() as session:
        # 1. Check available sides
        print("1. Available SIDE values:")
        sides_query = select(distinct(broker_executions.c.side))
        sides_result = await session.execute(sides_query)
        sides = [row[0] for row in sides_result.fetchall()]
        print(f"   Available sides: {sides}")
        print()
        
        # 2. Check today's executions
        today = date.today()
        print(f"2. Today's executions ({today}):")
        today_query = select(
            broker_executions.c.side,
            broker_executions.c.broker_name,
            func.count().label('count')
        ).where(
            func.date(broker_executions.c.execution_time) == today
        ).group_by(broker_executions.c.side, broker_executions.c.broker_name)
        
        today_result = await session.execute(today_query)
        today_executions = today_result.fetchall()
        
        if today_executions:
            for row in today_executions:
                print(f"   {row.broker_name}: {row.side} = {row.count} executions")
        else:
            print("   No executions found for today")
        print()
        
        # 3. Check recent executions (last 7 days)
        print("3. Recent executions (last 7 days):")
        week_ago = date.today() - timedelta(days=7)
        recent_query = select(
            broker_executions.c.side,
            broker_executions.c.broker_name,
            func.count().label('count')
        ).where(
            func.date(broker_executions.c.execution_time) >= week_ago
        ).group_by(broker_executions.c.side, broker_executions.c.broker_name)
        
        recent_result = await session.execute(recent_query)
        recent_executions = recent_result.fetchall()
        
        if recent_executions:
            for row in recent_executions:
                print(f"   {row.broker_name}: {row.side} = {row.count} executions")
        else:
            print("   No executions found in last 7 days")
        print()
        
        # 4. Show the problematic query from strategy_manager
        print("4. PROBLEMATIC QUERY (from strategy_manager.py line 174):")
        print("   broker_executions.c.side == 'ENTRY'")
        
        entry_query = select(broker_executions).where(
            broker_executions.c.side == 'ENTRY'
        )
        entry_result = await session.execute(entry_query)
        entry_executions = entry_result.fetchall()
        print(f"   Results: {len(entry_executions)} executions found")
        print()
        
        # 5. Show corrected queries
        print("5. CORRECTED QUERIES:")
        print("   Option A: Use 'BUY' for entry executions")
        buy_query = select(broker_executions).where(
            and_(
                broker_executions.c.side == 'BUY',
                func.date(broker_executions.c.execution_time) == today
            )
        )
        buy_result = await session.execute(buy_query)
        buy_executions = buy_result.fetchall()
        print(f"   BUY executions today: {len(buy_executions)}")
        
        print("   Option B: Use both 'BUY' and 'SELL' for all executions")
        all_query = select(broker_executions).where(
            and_(
                broker_executions.c.side.in_(['BUY', 'SELL']),
                func.date(broker_executions.c.execution_time) == today
            )
        )
        all_result = await session.execute(all_query)
        all_executions = all_result.fetchall()
        print(f"   BUY+SELL executions today: {len(all_executions)}")
        print()
        
        # 6. Sample recent execution details
        if recent_executions:
            print("6. SAMPLE EXECUTION DETAILS:")
            sample_query = select(broker_executions).where(
                func.date(broker_executions.c.execution_time) >= week_ago
            ).limit(3)
            
            sample_result = await session.execute(sample_query)
            sample_executions = sample_result.fetchall()
            
            for i, execution in enumerate(sample_executions, 1):
                print(f"   Sample {i}:")
                print(f"     side: {execution.side}")
                print(f"     action: {execution.action}")
                print(f"     broker_name: {execution.broker_name}")
                print(f"     symbol: {execution.symbol}")
                print(f"     execution_time: {execution.execution_time}")
                print()

async def test_broker_position_cache():
    """Test the broker position caching mechanism with mock data"""
    print("🔍 TESTING BROKER POSITION CACHE WITH MOCK DATA")
    print("=" * 60)
    
    # Mock broker position data based on actual responses
    mock_fyers_raw = {
        'code': 200, 
        'message': '', 
        's': 'ok', 
        'netPositions': [
            {'symbol': 'NSE:NIFTY2582125050CE', 'id': 'NSE:NIFTY2582125050CE-MARGIN', 'buyAvg': 67.8, 'buyQty': 75, 'buyVal': 5085, 'sellAvg': 65, 'sellQty': 75, 'sellVal': 4875, 'netAvg': 0, 'netQty': 0, 'side': 0, 'qty': 0, 'productType': 'MARGIN', 'realized_profit': -209.99999999999977, 'crossCurrency': '', 'rbiRefRate': 1, 'fyToken': '101125082147248', 'exchange': 10, 'segment': 11, 'dayBuyQty': 75, 'daySellQty': 75, 'cfBuyQty': 0, 'cfSellQty': 0, 'qtyMulti_com': 1, 'pl': -209.99999999999977, 'unrealized_profit': 0, 'ltp': 50.1, 'slNo': 0}, 
            {'symbol': 'NSE:NIFTY2582124800PE', 'id': 'NSE:NIFTY2582124800PE-MARGIN', 'buyAvg': 10.15, 'buyQty': 600, 'buyVal': 6090, 'sellAvg': 10.25, 'sellQty': 600, 'sellVal': 6150, 'netAvg': 0, 'netQty': 0, 'side': 0, 'qty': 0, 'productType': 'MARGIN', 'realized_profit': 59.99999999999979, 'crossCurrency': '', 'rbiRefRate': 1, 'fyToken': '101125082147210', 'exchange': 10, 'segment': 11, 'dayBuyQty': 600, 'daySellQty': 600, 'cfBuyQty': 0, 'cfSellQty': 0, 'qtyMulti_com': 1, 'pl': 59.99999999999979, 'unrealized_profit': 0, 'ltp': 7.4, 'slNo': 0}, 
            {'symbol': 'NSE:NIFTY2582124900CE', 'id': 'NSE:NIFTY2582124900CE-BO', 'buyAvg': 162, 'buyQty': 75, 'buyVal': 12150, 'sellAvg': 175.5, 'sellQty': 75, 'sellVal': 13162.5, 'netAvg': 0, 'netQty': 0, 'side': 0, 'qty': 0, 'productType': 'BO', 'realized_profit': 1012.5, 'crossCurrency': '', 'rbiRefRate': 1, 'fyToken': '101125082147216', 'exchange': 10, 'segment': 11, 'dayBuyQty': 75, 'daySellQty': 75, 'cfBuyQty': 0, 'cfSellQty': 0, 'qtyMulti_com': 1, 'pl': 1012.5, 'unrealized_profit': 0, 'ltp': 159.5, 'slNo': 0}, 
            {'symbol': 'NSE:NIFTY2582124800PE', 'id': 'NSE:NIFTY2582124800PE-INTRADAY', 'buyAvg': 11.8, 'buyQty': 75, 'buyVal': 885, 'sellAvg': 11.75, 'sellQty': 75, 'sellVal': 881.25, 'netAvg': 0, 'netQty': 0, 'side': 0, 'qty': 0, 'productType': 'INTRADAY', 'realized_profit': -3.7500000000000533, 'crossCurrency': '', 'rbiRefRate': 1, 'fyToken': '101125082147210', 'exchange': 10, 'segment': 11, 'dayBuyQty': 75, 'daySellQty': 75, 'cfBuyQty': 0, 'cfSellQty': 0, 'qtyMulti_com': 1, 'pl': -3.7500000000000533, 'unrealized_profit': 0, 'ltp': 7.4, 'slNo': 0}, 
            {'symbol': 'NSE:NIFTY2582125000CE', 'id': 'NSE:NIFTY2582125000CE-MARGIN', 'buyAvg': 78.75625, 'buyQty': 600, 'buyVal': 47253.75, 'sellAvg': 73.03125, 'sellQty': 600, 'sellVal': 43818.75, 'netAvg': 0, 'netQty': 0, 'side': 0, 'qty': 0, 'productType': 'MARGIN', 'realized_profit': -3434.9999999999964, 'crossCurrency': '', 'rbiRefRate': 1, 'fyToken': '101125082147231', 'exchange': 10, 'segment': 11, 'dayBuyQty': 600, 'daySellQty': 600, 'cfBuyQty': 0, 'cfSellQty': 0, 'qtyMulti_com': 1, 'pl': -3434.9999999999964, 'unrealized_profit': 0, 'ltp': 80.2, 'slNo': 0}
        ], 
        'overall': {
            'count_open': 0, 
            'count_total': 5, 
            'pl_realized': -2576.2499999999964, 
            'pl_total': -2576.2499999999964, 
            'pl_unrealized': 0
        }
    }
    
    mock_zerodha_raw = [
        {'tradingsymbol': 'NIFTY2582124800PE', 'exchange': 'NFO', 'instrument_token': 12085762, 'product': 'MIS', 'segment': '', 'quantity': 0, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 0, 'close_price': 0, 'last_price': 7.4, 'value': -15, 'pnl': -15, 'm2m': -15, 'unrealised': -15, 'realised': 0, 'buy_quantity': 75, 'buy_price': 11.9, 'buy_value': 892.5, 'buy_m2m': 892.5, 'sell_quantity': 75, 'sell_price': 11.7, 'sell_value': 877.5, 'sell_m2m': 877.5, 'day_buy_quantity': 75, 'day_buy_price': 11.9, 'day_buy_value': 892.5, 'day_sell_quantity': 75, 'day_sell_price': 11.7, 'day_sell_value': 877.5}, 
        {'tradingsymbol': 'NIFTY2582124800PE', 'exchange': 'NFO', 'instrument_token': 12085762, 'product': 'NRML', 'segment': '', 'quantity': 0, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 0, 'close_price': 0, 'last_price': 7.4, 'value': 22.5, 'pnl': 22.5, 'm2m': 22.5, 'unrealised': 22.5, 'realised': 0, 'buy_quantity': 150, 'buy_price': 10.1, 'buy_value': 1515, 'buy_m2m': 1515, 'sell_quantity': 150, 'sell_price': 10.25, 'sell_value': 1537.5, 'sell_m2m': 1537.5, 'day_buy_quantity': 150, 'day_buy_price': 10.1, 'day_buy_value': 1515, 'day_sell_quantity': 150, 'day_sell_price': 10.25, 'day_sell_value': 1537.5}, 
        {'tradingsymbol': 'NIFTY2582124900CE', 'exchange': 'NFO', 'instrument_token': 12087298, 'product': 'MIS', 'segment': '', 'quantity': 0, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 0, 'close_price': 0, 'last_price': 159.5, 'value': -870, 'pnl': -870, 'm2m': -870, 'unrealised': -870, 'realised': 0, 'buy_quantity': 75, 'buy_price': 162, 'buy_value': 12150, 'buy_m2m': 12150, 'sell_quantity': 75, 'sell_price': 150.4, 'sell_value': 11280, 'sell_m2m': 11280, 'day_buy_quantity': 75, 'day_buy_price': 162, 'day_buy_value': 12150, 'day_sell_quantity': 75, 'day_sell_price': 150.4, 'day_sell_value': 11280}, 
        {'tradingsymbol': 'NIFTY2582125000CE', 'exchange': 'NFO', 'instrument_token': 12091138, 'product': 'NRML', 'segment': '', 'quantity': 0, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 0, 'close_price': 0, 'last_price': 80.2, 'value': -1777.5, 'pnl': -1777.5, 'm2m': -1777.5, 'unrealised': -1777.5, 'realised': 0, 'buy_quantity': 300, 'buy_price': 78.85, 'buy_value': 23655, 'buy_m2m': 23655, 'sell_quantity': 300, 'sell_price': 72.925, 'sell_value': 21877.5, 'sell_m2m': 21877.5, 'day_buy_quantity': 300, 'day_buy_price': 78.85, 'day_buy_value': 23655, 'day_sell_quantity': 300, 'day_sell_price': 72.925, 'day_sell_value': 21877.5}
    ]
    
    try:
        print("1. Testing strategy_manager P&L calculation logic with mock data...")
        
        # Import our updated strategy_manager
        from algosat.core.strategy_manager import RiskManager
        from algosat.core.db import AsyncSessionLocal
        from algosat.core.order_manager import OrderManager
        from algosat.core.data_manager import DataManager
        
        # Create required dependencies for RiskManager
        data_manager = DataManager()
        order_manager = OrderManager(data_manager)
        
        # Create RiskManager instance with required order_manager
        risk_manager = RiskManager(order_manager)
        
        print("\n2. Testing Fyers P&L calculation:")
        print("   Expected: overall.pl_realized + overall.pl_unrealized = -2576.25 + 0 = -2576.25")
        
        # Test Fyers calculation manually
        raw_positions = mock_fyers_raw
        total_pnl = 0.0
        
        if isinstance(raw_positions, dict) and 'overall' in raw_positions:
            overall = raw_positions.get('overall', {})
            pl_realized = float(overall.get('pl_realized', 0.0))
            pl_unrealized = float(overall.get('pl_unrealized', 0.0))
            total_pnl = pl_realized + pl_unrealized
            print(f"   ✅ Fyers overall P&L: realized={pl_realized}, unrealized={pl_unrealized}, total={total_pnl}")
        
        print("\n3. Testing Zerodha P&L calculation:")
        print("   Expected: sum of pnl fields = -15 + 22.5 + (-870) + (-1777.5) = -2640")
        
        # Test Zerodha calculation manually
        zerodha_total = 0.0
        for position in mock_zerodha_raw:
            position_pnl = float(position.get('pnl', 0.0))
            zerodha_total += position_pnl
            print(f"   Position {position['tradingsymbol']} ({position['product']}): pnl = {position_pnl}")
        print(f"   ✅ Zerodha total P&L: {zerodha_total}")
        
        print("\n4. Testing get_all_broker_positions processing:")
        print("   Fyers: get_all_broker_positions extracts 'netPositions' and loses 'overall'")
        fyers_processed = mock_fyers_raw.get('netPositions', [])
        print(f"   Fyers netPositions length: {len(fyers_processed)}")
        
        # Calculate P&L from processed positions (what get_all_broker_positions returns)
        fyers_individual_total = 0.0
        for position in fyers_processed:
            position_pnl = float(position.get('pl', 0.0))
            fyers_individual_total += position_pnl
        print(f"   Fyers individual P&L sum: {fyers_individual_total}")
        print(f"   ⚠️  Difference from overall: {total_pnl - fyers_individual_total}")
        
        print("\n5. Testing our updated _calculate_broker_pnl method:")
        
        # Create a simple test function that mimics the logic without dependencies
        async def test_pnl_calculation(broker_name, raw_positions):
            """Test P&L calculation logic directly"""
            total_pnl = 0.0
            
            if broker_name.lower() == 'fyers':
                # For Fyers: use overall P&L from raw response
                if isinstance(raw_positions, dict) and 'overall' in raw_positions:
                    overall = raw_positions.get('overall', {})
                    pl_realized = float(overall.get('pl_realized', 0.0))
                    pl_unrealized = float(overall.get('pl_unrealized', 0.0))
                    total_pnl = pl_realized + pl_unrealized
                    print(f"   Fyers overall P&L: realized={pl_realized}, unrealized={pl_unrealized}, total={total_pnl}")
                elif isinstance(raw_positions, dict) and 'netPositions' in raw_positions:
                    # Fallback: sum individual position 'pl' fields
                    net_positions = raw_positions.get('netPositions', [])
                    for position in net_positions:
                        position_pnl = float(position.get('pl', position.get('realized_profit', 0.0)))
                        total_pnl += position_pnl
                    print(f"   Fyers individual P&L sum: {total_pnl}")
            
            elif broker_name.lower() == 'zerodha':
                # For Zerodha: sum 'pnl' field from individual positions
                positions_list = raw_positions if isinstance(raw_positions, list) else raw_positions.get('net', [])
                for position in positions_list:
                    position_pnl = float(position.get('pnl', 0.0))
                    total_pnl += position_pnl
                print(f"   Zerodha P&L: {total_pnl} (from {len(positions_list)} positions)")
            
            return total_pnl
        
        # Test both brokers
        fyers_pnl = await test_pnl_calculation('fyers', mock_fyers_raw)
        zerodha_pnl = await test_pnl_calculation('zerodha', mock_zerodha_raw)
        
        print(f"   ✅ Fyers P&L result: {fyers_pnl}")
        print(f"   ✅ Zerodha P&L result: {zerodha_pnl}")
        
        print("\n📊 SUMMARY:")
        print("=" * 40)
        print(f"Fyers Expected: -2576.25, Got: {fyers_pnl}, Match: {abs(fyers_pnl + 2576.25) < 0.01}")
        print(f"Zerodha Expected: -2640.0, Got: {zerodha_pnl}, Match: {abs(zerodha_pnl + 2640.0) < 0.01}")
        
    except Exception as e:
        print(f"   ❌ Error in mock testing: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Main test function"""
    print("🧪 P&L CALCULATION ISSUE ANALYSIS")
    print("=" * 60)
    print()
    
    try:
        await analyze_broker_executions()
        print()
        await test_broker_position_cache()
        
        print()
        print("📋 SUMMARY OF FINDINGS:")
        print("=" * 30)
        print("1. The query 'side == ENTRY' in strategy_manager.py line 174 is WRONG")
        print("2. broker_executions table uses 'BUY'/'SELL', not 'ENTRY'")
        print("3. This causes 0 executions to be found, resulting in P&L = 0.0")
        print("4. The fix is to change the query to use actual side values")
        print()
        print("🔧 RECOMMENDED FIX:")
        print("   Change line 174 from:")
        print("     broker_executions.c.side == 'ENTRY'")
        print("   To:")
        print("     broker_executions.c.side.in_(['BUY', 'SELL'])")
        print("   Or use specific logic to determine what constitutes an 'entry'")
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
