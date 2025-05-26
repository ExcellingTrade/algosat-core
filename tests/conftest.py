# Test configuration for Algosat
import pytest
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import pandas as pd
from datetime import datetime, date

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.db import metadata
from models.strategy_config import StrategyConfig
from core.data_manager import DataManager
from core.broker_manager import BrokerManager
from core.order_manager import OrderManager

# Test database URL (use different DB for tests)
TEST_DATABASE_URL = "postgresql+asyncpg://algosat_user:admin123@localhost/algosat_test_db"

@pytest.fixture(scope="session")
def event_loop_policy():
    """Configure the event loop policy for tests."""
    return asyncio.get_event_loop_policy()

@pytest.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    
    yield engine
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def test_session(test_engine):
    """Create test database session."""
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest.fixture
def mock_broker():
    """Create mock broker for testing."""
    broker = AsyncMock()
    broker.login.return_value = True
    broker.get_positions.return_value = []
    broker.place_order.return_value = {"status": "success", "order_id": "TEST123"}
    broker.get_history.return_value = pd.DataFrame({
        'timestamp': [datetime.now()],
        'open': [100.0],
        'high': [102.0],
        'low': [99.0],
        'close': [101.0],
        'volume': [1000]
    })
    broker.get_option_chain.return_value = {
        "code": 200,
        "data": {
            "optionsChain": [
                {"symbol": "NIFTY25MAY25000CE", "ltp": 50.0},
                {"symbol": "NIFTY25MAY25000PE", "ltp": 45.0}
            ]
        }
    }
    return broker

@pytest.fixture
def sample_strategy_config():
    """Create sample strategy config for testing."""
    return StrategyConfig(
        id=1,
        strategy_id=1,
        symbol="NIFTY50",
        exchange="NSE",
        instrument="INDEX",
        trade={
            "max_trades": 2,
            "max_premium": 200,
            "interval_minutes": 5,
            "lot_size": 25,
            "ce_lot_qty": 1,
            "pe_lot_qty": 1
        },
        indicators={
            "supertrend_period": 7,
            "supertrend_multiplier": 3
        },
        is_default=True,
        enabled=True
    )

@pytest.fixture
def mock_data_manager(mock_broker):
    """Create mock data manager."""
    data_manager = DataManager(broker=mock_broker)
    return data_manager

@pytest.fixture
def mock_broker_manager(mock_broker):
    """Create mock broker manager."""
    broker_manager = AsyncMock()
    broker_manager.brokers = {"test_broker": mock_broker}
    broker_manager.place_order = AsyncMock(return_value={
        "status": "success", 
        "order_id": "TEST123"
    })
    return broker_manager

@pytest.fixture
def mock_order_manager(mock_broker_manager):
    """Create mock order manager."""
    return OrderManager(mock_broker_manager)

# Test data fixtures
@pytest.fixture
def sample_candle_data():
    """Sample candle data for testing."""
    return {
        'timestamp': datetime.now(),
        'open': 100.0,
        'high': 102.0,
        'low': 98.0,
        'close': 101.0,
        'volume': 1000,
        'supertrend_signal': 'BUY'
    }

@pytest.fixture
def sample_option_chain():
    """Sample option chain data."""
    return {
        "code": 200,
        "data": {
            "optionsChain": [
                {"symbol": "NIFTY25MAY25000CE", "ltp": 50.0, "strike": 25000, "option_type": "CE"},
                {"symbol": "NIFTY25MAY25000PE", "ltp": 45.0, "strike": 25000, "option_type": "PE"},
                {"symbol": "NIFTY25MAY25100CE", "ltp": 40.0, "strike": 25100, "option_type": "CE"},
                {"symbol": "NIFTY25MAY25100PE", "ltp": 55.0, "strike": 25100, "option_type": "PE"}
            ]
        }
    }

# Utility functions for tests
def assert_order_valid(order_data):
    """Assert order data is valid."""
    required_fields = ['symbol', 'quantity', 'side', 'order_type']
    for field in required_fields:
        assert field in order_data, f"Missing required field: {field}"
    
    assert order_data['quantity'] > 0, "Quantity must be positive"
    assert order_data['side'] in ['BUY', 'SELL'], "Side must be BUY or SELL"

def create_mock_history_data(num_candles=100):
    """Create mock historical data."""
    dates = pd.date_range(start='2025-01-01', periods=num_candles, freq='5min')
    return pd.DataFrame({
        'timestamp': dates,
        'open': 100 + (pd.Series(range(num_candles)) % 10),
        'high': 102 + (pd.Series(range(num_candles)) % 10),
        'low': 98 + (pd.Series(range(num_candles)) % 10),
        'close': 101 + (pd.Series(range(num_candles)) % 10),
        'volume': 1000 + (pd.Series(range(num_candles)) * 10)
    })

# Async test helpers
def async_test(coro):
    """Decorator to run async tests."""
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro(*args, **kwargs))
    return wrapper
