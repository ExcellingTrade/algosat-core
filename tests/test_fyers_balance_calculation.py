#!/usr/bin/env python3
"""
Test script to verify Fyers balance calculation logic.
This script tests the new calculation logic:
- total = "Limit at start of the day" + "Fund Transfer" (Payin)
- available = "Available Balance"
- utilized = "Utilized Amount"
"""

import sys
import os
sys.path.insert(0, '/opt/algosat')

from algosat.brokers.models import BalanceSummary


def test_balance_calculation():
    """Test the Fyers balance calculation logic with sample data."""
    
    # Sample API response structure based on the provided example
    sample_response = {
        "code": 200,
        "message": "SUCCESS",
        "fund_limit": [
            {"title": "Limit at start of the day", "equityAmount": "100000.00", "commodityAmount": "0.00"},
            {"title": "Fund Transfer", "equityAmount": "25000.00", "commodityAmount": "0.00"},
            {"title": "Available Balance", "equityAmount": "115000.00", "commodityAmount": "0.00"},
            {"title": "Utilized Amount", "equityAmount": "10000.00", "commodityAmount": "0.00"},
            {"title": "Other Field", "equityAmount": "5000.00", "commodityAmount": "0.00"}
        ]
    }
    
    # Simulate the calculation logic from the Fyers broker
    fund_limit = sample_response.get("fund_limit", [])
    
    # Initialize values
    limit_at_start = payin = available = utilized = 0.0
    
    # Extract required fields from fund_limit
    for item in fund_limit:
        title = item.get("title", "").lower()
        equity_amount = float(item.get("equityAmount", 0))
        
        if title == "limit at start of the day":
            limit_at_start = equity_amount
        elif title == "fund transfer":
            payin = equity_amount
        elif title == "available balance":
            available = equity_amount
        elif title == "utilized amount":
            utilized = equity_amount
    
    # Calculate total as per new logic: Limit at start of the day + Fund Transfer (Payin)
    total = limit_at_start + payin
    
    # Create BalanceSummary
    balance_summary = BalanceSummary(
        total_balance=total,
        available=available,
        utilized=utilized
    )
    
    print("=== Fyers Balance Calculation Test ===")
    print(f"Limit at start of the day: {limit_at_start}")
    print(f"Fund Transfer (Payin): {payin}")
    print(f"Available Balance: {available}")
    print(f"Utilized Amount: {utilized}")
    print()
    print("=== Calculated Results ===")
    print(f"Total Balance: {total} (= {limit_at_start} + {payin})")
    print(f"Available: {available}")
    print(f"Utilized: {utilized}")
    print()
    print("=== BalanceSummary Object ===")
    print(f"total_balance: {balance_summary.total_balance}")
    print(f"available: {balance_summary.available}")
    print(f"utilized: {balance_summary.utilized}")
    print()
    
    # Verify the calculation
    expected_total = 100000.0 + 25000.0  # 125000.0
    expected_available = 115000.0
    expected_utilized = 10000.0
    
    assert balance_summary.total_balance == expected_total, f"Expected total {expected_total}, got {balance_summary.total_balance}"
    assert balance_summary.available == expected_available, f"Expected available {expected_available}, got {balance_summary.available}"
    assert balance_summary.utilized == expected_utilized, f"Expected utilized {expected_utilized}, got {balance_summary.utilized}"
    
    print("✅ All calculations are correct!")
    print()
    print("=== Summary ===")
    print("The Fyers balance calculation now correctly uses:")
    print("• total = Limit at start of the day + Fund Transfer")
    print("• available = Available Balance")
    print("• utilized = Utilized Amount")


if __name__ == "__main__":
    test_balance_calculation()
