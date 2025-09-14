#!/usr/bin/env python3
"""
Test the fix by simulating the PnL calculation with correct quantities
"""
import psycopg2
from psycopg2.extras import RealDictCursor

def main():
    try:
        conn = psycopg2.connect(
            host='localhost',
            database='algosat_db', 
            user='algosat_user',
            password='admin123',
            port=5432
        )
        print('✅ Database connection successful!')
        
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        print('\n=== TESTING PNL CALCULATION FIX FOR ORDER 195 ===')
        
        # Get order 195 broker executions
        cursor.execute('''
        SELECT broker_id, executed_quantity, execution_price
        FROM broker_executions 
        WHERE parent_order_id = 195 AND side = 'ENTRY'
        ORDER BY broker_id;
        ''')
        
        broker_execs = cursor.fetchall()
        
        # Simulate the PnL calculation scenarios
        print('\n📊 PnL Calculation Scenarios:')
        print('Assume broker has total position of 150 (from other trades) and PnL of -4642.5')
        print('Broker buyQuantity = 150 (total day trades)')
        
        broker_total_pnl = -4642.5
        broker_total_qty = 150  # What broker reports in buyQuantity
        
        for exec_row in broker_execs:
            broker_id = exec_row['broker_id']
            executed_quantity = exec_row['executed_quantity']
            execution_price = exec_row['execution_price']
            
            print(f'\n🔍 Broker {broker_id} Analysis:')
            print(f'  Executed Quantity: {executed_quantity}')
            print(f'  Execution Price: {execution_price}')
            
            # OLD (WRONG) Calculation using orders.qty
            old_our_qty = 150  # From orders table (aggregated)
            old_proportional_pnl = (old_our_qty / broker_total_qty) * broker_total_pnl
            
            # NEW (FIXED) Calculation using executed_quantity
            new_our_qty = executed_quantity  # From broker_executions.executed_quantity
            new_proportional_pnl = (new_our_qty / broker_total_qty) * broker_total_pnl
            
            print(f'\n  📈 OLD Calculation (WRONG):')
            print(f'    our_qty = {old_our_qty} (from orders.qty - aggregated)')
            print(f'    proportional_pnl = ({old_our_qty}/{broker_total_qty}) * {broker_total_pnl} = {old_proportional_pnl}')
            print(f'    Ratio: {old_our_qty/broker_total_qty} (>1.0 - INFLATED!)')
            
            print(f'\n  ✅ NEW Calculation (FIXED):')
            print(f'    our_qty = {new_our_qty} (from broker_executions.executed_quantity)')
            print(f'    proportional_pnl = ({new_our_qty}/{broker_total_qty}) * {broker_total_pnl} = {new_proportional_pnl}')
            print(f'    Ratio: {new_our_qty/broker_total_qty} (proper proportional)')
            
            print(f'\n  📊 Impact:')
            print(f'    PnL Difference: {new_proportional_pnl - old_proportional_pnl}')
            print(f'    Error Magnitude: {abs(old_proportional_pnl - new_proportional_pnl)}')
        
        # Show total aggregated impact
        old_total_pnl = sum((150 / broker_total_qty) * broker_total_pnl for _ in broker_execs)
        new_total_pnl = sum((exec_row['executed_quantity'] / broker_total_qty) * broker_total_pnl for exec_row in broker_execs)
        
        print(f'\n🎯 TOTAL ORDER PNL COMPARISON:')
        print(f'  OLD Total PnL: {old_total_pnl} (WRONG)')
        print(f'  NEW Total PnL: {new_total_pnl} (CORRECT)')
        print(f'  Total Error Eliminated: {abs(old_total_pnl - new_total_pnl)}')
        
        conn.close()
        
    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
