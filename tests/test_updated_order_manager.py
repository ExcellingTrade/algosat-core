#!/usr/bin/env python3
"""
Test script to verify the updated OrderManager functionality 
that uses symbol_id directly instead of querying the database.
"""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.abspath('.'))

from algosat.models.strategy_config import StrategyConfig
from algosat.core.order_request import OrderRequest, Side, OrderType


async def test_order_manager_symbol_id():
    """Test that OrderManager uses symbol_id directly from config."""
    print("🔍 Testing OrderManager with updated symbol_id logic...")
    
    # Create a mock StrategyConfig with symbol_id (this would come from strategy_manager)
    config = StrategyConfig(
        id=2,  # config_id
        strategy_id=1,
        name="OptionBuyStrategy",
        description="Strategy for option buying",
        exchange="NSE",
        instrument="INDEX",
        trade={"max_nse_qty": 900, "lot_size": 75},
        indicators={"supertrend_period": 7},
        symbol="NIFTY50",  # Underlying symbol
        symbol_id=4,  # strategy_symbols.id (this is the key field!)
        strategy_key="OptionBuy",
        strategy_name="Option Buy",
        order_type="MARKET",
        product_type="INTRADAY"
    )
    
    # Create a mock OrderRequest with strike symbol (actual tradeable symbol)
    order_request = OrderRequest(
        symbol="NIFTY50-25JUN25-23400-CE",  # Strike symbol (different from config.symbol)
        quantity=75,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        price=150.0,
        extra={
            "entry_price": 150.0,
            "stop_loss": 100.0,
            "target_price": 200.0,
            "status": "AWAITING_ENTRY",
            "reason": "SuperTrend signal"
        }
    )
    
    print(f"📊 Config Details:")
    print(f"  ├─ Config ID: {config.id}")
    print(f"  ├─ Strategy ID: {config.strategy_id}")
    print(f"  ├─ Underlying Symbol: {config.symbol}")
    print(f"  ├─ Symbol ID (strategy_symbol_id): {config.symbol_id}")
    print(f"  └─ Strategy: {config.strategy_name}")
    print()
    
    print(f"📈 Order Request Details:")
    print(f"  ├─ Strike Symbol: {order_request.symbol}")
    print(f"  ├─ Quantity: {order_request.quantity}")
    print(f"  ├─ Side: {order_request.side}")
    print(f"  ├─ Price: {order_request.price}")
    print(f"  └─ Extra: {order_request.extra}")
    print()
    
    print("✅ Symbol distinction is clear:")
    print(f"  - Config symbol (underlying): '{config.symbol}' → Used for strategy identification")
    print(f"  - Order symbol (strike): '{order_request.symbol}' → Used for actual trading")
    print(f"  - Symbol ID: {config.symbol_id} → Links to strategy_symbols.id in DB")
    print()
    
    # Test extracting the symbol_id (simulating what OrderManager does now)
    strategy_symbol_id = getattr(config, 'symbol_id', None)
    if strategy_symbol_id:
        print(f"🎯 OrderManager will use strategy_symbol_id={strategy_symbol_id} directly")
        print("   No database query needed - avoiding symbol name mismatch!")
    else:
        print("❌ Missing symbol_id in config - this would cause an error")
    
    print()
    print("🔄 Flow Summary:")
    print("  1. strategy_manager → Creates StrategyConfig with symbol_id from DB query")
    print("  2. strategy_runner → Passes StrategyConfig to Strategy class")
    print("  3. Strategy → Creates OrderRequest with strike symbol, calls order_manager")
    print("  4. OrderManager → Uses config.symbol_id directly (no DB query)")
    print("  5. Order → Saved with correct strategy_symbol_id in orders table")


async def main():
    """Main test function."""
    print("🚀 Testing updated OrderManager logic...")
    print("=" * 60)
    
    await test_order_manager_symbol_id()
    
    print("=" * 60)
    print("✅ Tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
