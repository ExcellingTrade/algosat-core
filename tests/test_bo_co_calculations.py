#!/usr/bin/env python3
"""
Test script to demonstrate the updated stopLoss and takeProfit calculation 
for BO and CO product types in the to_fyers_dict method.
"""

import sys
import os
sys.path.append('/opt/algosat')

from algosat.core.order_request import OrderRequest, Side, OrderType, ProductType

def test_bo_co_calculations():
    print("=== Testing BO/CO stopLoss and takeProfit calculations ===\n")
    
    # Test case 1: BO product type
    print("Test 1: BO Product Type")
    order_bo = OrderRequest(
        symbol="NIFTY50-25JUL25-24000-CE",
        quantity=75,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=200.0,  # limitPrice
        product_type=ProductType.BO,
        extra={
            "stopLoss": 100,    # Raw value: 100 rupees
            "takeProfit": 300   # Raw value: 300 rupees
        }
    )
    
    fyers_dict_bo = order_bo.to_fyers_dict()
    print(f"limitPrice: {fyers_dict_bo['limitPrice']}")
    print(f"stopLoss (raw=100): {fyers_dict_bo['stopLoss']} (calculated as 200-100)")
    print(f"takeProfit (raw=300): {fyers_dict_bo['takeProfit']} (calculated as 300-200)")
    print(f"productType: {fyers_dict_bo['productType']}\n")
    
    # Test case 2: CO product type
    print("Test 2: CO Product Type")
    order_co = OrderRequest(
        symbol="NIFTY50-25JUL25-24000-PE",
        quantity=75,
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=150.0,  # limitPrice
        product_type=ProductType.CO,
        extra={
            "stopLoss": 50,     # Raw value: 50 rupees
            "takeProfit": 200   # Raw value: 200 rupees
        }
    )
    
    fyers_dict_co = order_co.to_fyers_dict()
    print(f"limitPrice: {fyers_dict_co['limitPrice']}")
    print(f"stopLoss (raw=50): {fyers_dict_co['stopLoss']} (calculated as 150-50)")
    print(f"takeProfit (raw=200): {fyers_dict_co['takeProfit']} (calculated as 200-150)")
    print(f"productType: {fyers_dict_co['productType']}\n")
    
    # Test case 3: Non-negative constraint test
    print("Test 3: Non-negative constraint test")
    order_constraint = OrderRequest(
        symbol="NIFTY50-25JUL25-24000-CE",
        quantity=75,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=100.0,  # limitPrice
        product_type=ProductType.BO,
        extra={
            "stopLoss": 150,    # Raw value: 150 rupees (higher than limitPrice)
            "takeProfit": 80    # Raw value: 80 rupees (lower than limitPrice)
        }
    )
    
    fyers_dict_constraint = order_constraint.to_fyers_dict()
    print(f"limitPrice: {fyers_dict_constraint['limitPrice']}")
    print(f"stopLoss (raw=150): {fyers_dict_constraint['stopLoss']} (max(0, 100-150) = 0)")
    print(f"takeProfit (raw=80): {fyers_dict_constraint['takeProfit']} (max(0, 80-100) = 0)")
    print(f"productType: {fyers_dict_constraint['productType']}\n")
    
    # Test case 4: Regular product type (should use raw values)
    print("Test 4: Regular INTRADAY Product Type (uses raw values)")
    order_regular = OrderRequest(
        symbol="NIFTY50-25JUL25-24000-CE",
        quantity=75,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=200.0,  # limitPrice
        product_type=ProductType.INTRADAY,
        extra={
            "stopLoss": 100,    # Raw value: 100 rupees
            "takeProfit": 300   # Raw value: 300 rupees
        }
    )
    
    fyers_dict_regular = order_regular.to_fyers_dict()
    print(f"limitPrice: {fyers_dict_regular['limitPrice']}")
    print(f"stopLoss: {fyers_dict_regular['stopLoss']} (raw value, no calculation)")
    print(f"takeProfit: {fyers_dict_regular['takeProfit']} (raw value, no calculation)")
    print(f"productType: {fyers_dict_regular['productType']}\n")

if __name__ == "__main__":
    test_bo_co_calculations()
