

from typing import Optional
from algosat.strategies.base import StrategyBase
from algosat.core.order_request import TradeSignal, Side, SignalType
import logging

logger = logging.getLogger(__name__)

class OptionSellStrategy(StrategyBase):
    """
    Option Sell strategy:
    - Entry: SELL (short option)
    - Exit: BUY (cover position)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positions = {}  # Tracks open sell positions

    async def setup(self, symbol, config):
        pass

    async def process_cycle(self, data, config: dict, strike: str):
        entry_signal = self.evaluate_signal(data, config, strike)
        if entry_signal:
            await self.process_order(entry_signal, config, strike)
        exit_signal = self.evaluate_exit(data, config, strike)
        if exit_signal:
            await self.process_order(exit_signal, config, strike)

    def evaluate_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Entry logic for Option Sell:
        - Example: Sell if condition met and not already open.
        """
        if self._positions.get(strike):
            return None
        try:
            curr = data.iloc[-1]
            # Dummy condition: Sell if close > ema (adjust as per your logic)
            if curr.get('close', 0) > curr.get('ema', 0):
                trade_signal = TradeSignal(
                    symbol=strike,
                    side=Side.SELL,
                    price=curr.get('close'),
                    signal_type=SignalType.ENTRY
                )
                self._positions[strike] = [dict(entry_price=curr.get('close'))]
                return trade_signal
        except Exception as e:
            logger.error(f"Error in evaluate_signal for {strike}: {e}")
        return None

    def evaluate_exit(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Exit logic for Option Sell:
        - BUY to cover if SL/target or reversal signal.
        """
        if not self._positions.get(strike):
            return None
        try:
            prev = data.iloc[-2]
            curr = data.iloc[-1]
            entry_price = self._positions[strike][0].get('entry_price', 0)
            # 1) Stoploss (e.g., price goes up)
            max_loss_pct = config.get('max_loss_percentage', 25)
            stoploss_price = entry_price * (1 + max_loss_pct / 100)
            if curr['high'] >= stoploss_price:
                self._positions.pop(strike, None)
                return TradeSignal(
                    symbol=strike,
                    side=Side.BUY,
                    price=stoploss_price,
                    signal_type=SignalType.STOPLOSS
                )
            # 2) Target (e.g., premium decayed)
            atr_multiplier = config.get('atr_target_multiplier', 3)
            target_price = entry_price - curr.get('atr', 0) * atr_multiplier
            if curr['low'] <= target_price:
                self._positions.pop(strike, None)
                return TradeSignal(
                    symbol=strike,
                    side=Side.BUY,
                    price=target_price,
                    signal_type=SignalType.TARGET
                )
            # 3) Optional: Trend reversal (e.g., supertrend flip up)
            if not prev.get('in_downtrend') and curr.get('in_downtrend'):
                self._positions.pop(strike, None)
                return TradeSignal(
                    symbol=strike,
                    side=Side.BUY,
                    price=curr['close'],
                    signal_type=SignalType.TRAIL
                )
        except Exception as e:
            logger.error(f"Error in evaluate_exit for {strike}: {e}")
        return None

    async def process_order(self, trade_signal, config, strike):
        try:
            await self.order_manager.broker_manager.build_order_request_for_strategy(trade_signal, config)
        except Exception as e:
            logger.error(f"Order processing failed for {strike}: {e}")