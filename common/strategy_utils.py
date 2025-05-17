import math
import os
import json
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from utils.utils import localize_to_ist, get_ist_datetime
from core.time_utils import wait_for_first_candle_completion, calculate_first_candle_details

# --- MOVED FROM broker_utils.py ---

async def fetch_option_chain_and_first_candle_history(broker, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name):
    # This is a simplified version; adapt as needed
    option_chain_response = await broker.get_option_chain(symbol, int(max_strikes))
    if not option_chain_response.get('data') or not option_chain_response['data'].get('optionsChain'):
        return []
    import pandas as pd
    from common import constants
    option_chain_df = pd.DataFrame(option_chain_response['data']['optionsChain'])
    strike_symbols = option_chain_df[constants.COLUMN_SYMBOL].unique()
    strike_symbols = [s for s in strike_symbols if (s.endswith(constants.OPTION_TYPE_CALL)
                                                    or s.endswith(constants.OPTION_TYPE_PUT)) and "INDEX" not in s]
    # Fetch history for all strikes for the first candle
    history_data = []
    for strike_symbol in strike_symbols:
        hist = await broker.get_history(strike_symbol, from_date, to_date, ohlc_interval=interval_minutes, ins_type="")
        history_data.append(hist)
    return history_data

def identify_strike_price_combined(option_chain_df=None, history_data=None, max_premium=200):
    import pandas as pd
    from common import constants
    try:
        if option_chain_df is not None:
            ce_data = option_chain_df[
                (option_chain_df[constants.COLUMN_OPTION_TYPE] == constants.OPTION_TYPE_CALL)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
            pe_data = option_chain_df[
                (option_chain_df[constants.COLUMN_OPTION_TYPE] == constants.OPTION_TYPE_PUT)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
        elif history_data is not None:
            history_combined = []
            for strike_data in history_data:
                if strike_data is not None:
                    latest_close = strike_data.iloc[-1][constants.COLUMN_CLOSE]
                    history_combined.append(
                        {constants.COLUMN_SYMBOL: strike_data.attrs[constants.COLUMN_SYMBOL],
                         constants.COLUMN_PRICE: latest_close})
            option_chain_df = pd.DataFrame(history_combined)
            ce_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.contains(constants.OPTION_TYPE_CALL) & (
                        option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
            pe_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.contains(constants.OPTION_TYPE_PUT) & (
                        option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
        else:
            return None, None
        ce_strike = ce_data.iloc[(ce_data[constants.COLUMN_PRICE] - max_premium).abs().argsort()[:1]] if not ce_data.empty else None
        pe_strike = pe_data.iloc[(pe_data[constants.COLUMN_PRICE] - max_premium).abs().argsort()[:1]] if not pe_data.empty else None
        return ce_strike, pe_strike
    except Exception as error:
        return None, None
