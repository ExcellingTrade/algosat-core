from algosat.strategies.base import StrategyBase
from algosat.common.swing_utils import find_hhlh_pivots, get_last_swing_points
from typing import Optional
import pandas as pd

class SwingHighLowBuyStrategy(StrategyBase):
    """
    Buy strategy based on swing low/high logic.
    Entry: Buy at/near swing low, exit at swing high or custom rule.
    """
    def evaluate_signal(self, data: pd.DataFrame, *args, **kwargs) -> Optional[dict]:
        # Identify pivots and swings
        df = find_hhlh_pivots(data)
        last_hh, last_ll, last_hl, last_lh = get_last_swing_points(df)
        # Example: Buy if last swing is HL (higher low)
        if last_hl is not None:
            entry_price = last_hl['price']
            return {
                'side': 'BUY',
                'price': entry_price,
                'signal_type': 'ENTRY',
                'reason': 'Swing HL'
            }
        return None

    def evaluate_exit(self, data: pd.DataFrame, position: dict, *args, **kwargs) -> Optional[dict]:
        # Exit at next swing high
        df = find_hhlh_pivots(data)
        last_hh, *_ = get_last_swing_points(df)
        if last_hh is not None:
            exit_price = last_hh['price']
            return {
                'side': 'SELL',
                'price': exit_price,
                'signal_type': 'EXIT',
                'reason': 'Swing HH'
            }
        return None
