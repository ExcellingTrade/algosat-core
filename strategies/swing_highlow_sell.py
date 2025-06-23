from algosat.strategies.base import StrategyBase
from algosat.common.swing_utils import find_hhlh_pivots, get_last_swing_points
from typing import Optional
import pandas as pd

class SwingHighLowSellStrategy(StrategyBase):
    """
    Sell strategy based on swing high/low logic.
    Entry: Sell at/near swing high, exit at swing low or custom rule.
    """
    def evaluate_signal(self, data: pd.DataFrame, *args, **kwargs) -> Optional[dict]:
        # Identify pivots and swings
        df = find_hhlh_pivots(data)
        last_hh, last_ll, last_hl, last_lh = get_last_swing_points(df)
        # Example: Sell if last swing is LH (lower high)
        if last_lh is not None:
            entry_price = last_lh['price']
            return {
                'side': 'SELL',
                'price': entry_price,
                'signal_type': 'ENTRY',
                'reason': 'Swing LH'
            }
        return None

    def evaluate_exit(self, data: pd.DataFrame, position: dict, *args, **kwargs) -> Optional[dict]:
        # Exit at next swing low
        df = find_hhlh_pivots(data)
        _, last_ll, *_ = get_last_swing_points(df)
        if last_ll is not None:
            exit_price = last_ll['price']
            return {
                'side': 'BUY',
                'price': exit_price,
                'signal_type': 'EXIT',
                'reason': 'Swing LL'
            }
        return None
