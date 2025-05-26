# Unit tests for core order management functionality
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.order_manager import OrderManager
from core.order_request import OrderRequest, Side, OrderType
from models.strategy_config import StrategyConfig

class TestOrderManager:
    """Test cases for OrderManager class."""
    
    @pytest.mark.asyncio
    async def test_order_manager_initialization(self, mock_broker_manager):
        """Test OrderManager initializes correctly."""
        order_manager = OrderManager(mock_broker_manager)
        assert order_manager.broker_manager == mock_broker_manager
    
    @pytest.mark.asyncio
    @patch('core.order_manager.OrderManager.update_order_in_db')
    async def test_place_order_success(self, mock_update_db, mock_order_manager, sample_strategy_config):
        """Test successful order placement."""
        # Setup
        order_request = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0
        )
        
        # Mock database update to avoid database interaction
        mock_update_db.return_value = None
        
        # Mock broker response
        mock_order_manager.broker_manager.place_order = AsyncMock(return_value={
            "status": "success",
            "order_id": "TEST123",
            "message": "Order placed successfully"
        })
        
        # Execute
        result = await mock_order_manager.place_order(
            config=sample_strategy_config,
            order_payload=order_request
        )
        
        # Assert
        assert result["status"] == "success"
        assert "order_id" in result
        mock_order_manager.broker_manager.place_order.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('core.order_manager.OrderManager.update_order_in_db')
    async def test_place_order_failure(self, mock_update_db, mock_order_manager, sample_strategy_config):
        """Test order placement failure handling."""
        # Setup
        order_request = OrderRequest(
            symbol="INVALID_SYMBOL",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0
        )
        
        # Mock database update
        mock_update_db.return_value = None
        
        # Mock broker failure
        mock_order_manager.broker_manager.place_order = AsyncMock(return_value={
            "status": "error",
            "message": "Invalid symbol"
        })
        
        # Execute
        result = await mock_order_manager.place_order(
            config=sample_strategy_config,
            order_payload=order_request
        )
        
        # Assert
        assert result["status"] == "error"
        assert "message" in result
    
    @pytest.mark.asyncio
    async def test_extract_strategy_config_id(self, mock_order_manager):
        """Test strategy config ID extraction."""
        # Test with StrategyConfig object
        config = StrategyConfig(
            id=123,
            strategy_id=1,
            symbol="NIFTY50",
            exchange="NSE",
            instrument="INDEX",
            trade={},
            indicators={}
        )
        
        config_id = mock_order_manager.extract_strategy_config_id(config)
        assert config_id == 123
        
        # Test with dict
        config_dict = {"id": 456}
        config_id = mock_order_manager.extract_strategy_config_id(config_dict)
        assert config_id == 456
        
        # Test with invalid input
        config_id = mock_order_manager.extract_strategy_config_id("invalid")
        assert config_id is None
    
    @pytest.mark.asyncio
    async def test_order_validation(self, mock_order_manager):
        """Test order validation logic."""
        # Valid order
        valid_order = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0
        )
        
        order_dict = valid_order.to_dict()
        assert order_dict["symbol"] == "NIFTY25MAY25000CE"
        assert order_dict["quantity"] == 25
        assert order_dict["side"] == Side.BUY  # Enum value, not string
        assert order_dict["order_type"] == OrderType.LIMIT  # Enum value, not string
        assert order_dict["price"] == 50.0
    
    @pytest.mark.asyncio
    async def test_enum_conversion_utility(self, mock_order_manager):
        """Test enum conversion utility for database storage."""
        # Test enum values directly
        side_enum = Side.BUY
        assert side_enum.value == "BUY"
        
        order_type_enum = OrderType.LIMIT  
        assert order_type_enum.value == "LIMIT"
        
        # Test creating order request with enums
        order_request = OrderRequest(
            symbol="TEST",
            quantity=1,
            side=Side.SELL,
            order_type=OrderType.MARKET
        )
        assert order_request.side == Side.SELL
        assert order_request.order_type == OrderType.MARKET

class TestOrderRequest:
    """Test cases for OrderRequest class."""
    
    def test_order_request_creation(self):
        """Test OrderRequest object creation."""
        order = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0,
            trigger_price=49.0
        )
        
        assert order.symbol == "NIFTY25MAY25000CE"
        assert order.quantity == 25
        assert order.side == Side.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.price == 50.0
        assert order.trigger_price == 49.0
    
    def test_order_request_to_dict(self):
        """Test OrderRequest to_dict conversion."""
        order = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.MARKET
        )
        
        order_dict = order.to_dict()
        
        assert order_dict["symbol"] == "NIFTY25MAY25000CE"
        assert order_dict["quantity"] == 25
        assert order_dict["side"] == Side.BUY  # Enum value, not string
        assert order_dict["order_type"] == OrderType.MARKET  # Enum value, not string
    
    def test_side_enum_values(self):
        """Test Side enum values."""
        assert Side.BUY.value == "BUY"
        assert Side.SELL.value == "SELL"
    
    def test_order_type_enum_values(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderType.SL.value == "SL"

class TestOrderIntegration:
    """Integration tests for order management."""
    
    @pytest.mark.asyncio
    @patch('core.order_manager.OrderManager.update_order_in_db')
    async def test_end_to_end_order_flow(self, mock_update_db, mock_broker_manager, sample_strategy_config):
        """Test complete order placement flow."""
        # Setup
        order_manager = OrderManager(mock_broker_manager)
        
        # Mock database update
        mock_update_db.return_value = None
        
        # Mock successful broker response
        mock_broker_manager.place_order = AsyncMock(return_value={
            "status": "success",
            "order_id": "INTEGRATION_TEST_123",
            "message": "Order placed successfully"
        })
        
        # Create order
        order_request = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0,
            extra={"stopLoss": 45.0, "takeProfit": 60.0}
        )
        
        # Execute order placement
        result = await order_manager.place_order(
            config=sample_strategy_config,
            order_payload=order_request,
            strategy_name="OptionBuy"
        )
        
        # Verify results
        assert result["status"] == "success"
        assert result["order_id"] == "INTEGRATION_TEST_123"
        
        # Verify broker was called with correct parameters
        mock_broker_manager.place_order.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_order_error_handling(self, mock_broker_manager, sample_strategy_config):
        """Test error handling in order placement."""
        order_manager = OrderManager(mock_broker_manager)
        
        # Mock broker exception
        mock_broker_manager.place_order = AsyncMock(side_effect=Exception("Broker connection failed"))
        
        order_request = OrderRequest(
            symbol="NIFTY25MAY25000CE",
            quantity=25,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=50.0
        )
        
        # Execute and expect exception to be raised
        with pytest.raises(Exception, match="Broker connection failed"):
            await order_manager.place_order(
                config=sample_strategy_config,
                order_payload=order_request
            )

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
