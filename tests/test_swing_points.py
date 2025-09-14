import pandas as pd
import asyncio
from datetime import datetime, timedelta, time
from algosat.brokers.fyers import FyersWrapper
from algosat.brokers.zerodha import ZerodhaWrapper
from algosat.common.swing_utils import find_hhlh_pivots, get_last_swing_points
from algosat.common.strategy_utils import localize_to_ist, calculate_end_date
from algosat.common.broker_utils import get_trade_day
from algosat.core.time_utils import get_ist_datetime
from rich.console import Console
from rich.table import Table
from rich import box

from algosat.utils.indicators import calculate_rsi

pd.options.display.max_rows = 1000


async def main():
    # Login to Fyers
    broker = ZerodhaWrapper()
    await broker.login()

    symbols = {
        "NSE:NIFTY 50": "INDEX",
        # "NSE:NIFTYBANK": "INDEX",
        # "NSE:TCS": "EQ",
        # "NSE:FEDERALBNK": "EQ",
        # "NSE:SBIN": "EQ",
        # "NSE:BHEL": "EQ",
        # "NSE:JINDALSTEL": "EQ",
        # "NSE:HCLTECH": "EQ",
        # "NSE:INFY": "EQ",
        # "NSE:RELIANCE": "EQ",
        # "NSE:WIPRO": "EQ",
        # "NSE:KOTAKBANK": "EQ",
        # "NSE:HDFCBANK": "EQ",
        # "NSE:ICICIBANK": "EQ",
        # "NSE:LT": "EQ",
        # "NSE:ITC": "EQ",
        # "NSE:MARUTI": "EQ",
        # "NSE:ASIANPAINT": "EQ",
        # "NSE:ULTRACEMCO": "EQ",
        # "NSE:HEROMOTOCO": "EQ",
        # "NSE:ONGC": "EQ",
        # "NSE:ADANIPORTS": "EQ",
        # "NSE:AXISBANK": "EQ",
        # "NSE:BAJFINANCE": "EQ",
        # "NSE:BAJAJFINSV": "EQ",
        # "NSE:BHARTIARTL": "EQ",
    }
    
    results = []

    for symbol, instrument_type in symbols.items():
        print(f"Processing {symbol}...")
        interval_minutes = 1
        lookback_days = 10
        current_date = get_ist_datetime()
        back_days = lookback_days
        trade_day = get_trade_day(current_date - timedelta(days=back_days))
        start_date = localize_to_ist(datetime.combine(trade_day, time(9, 15)))
        current_end_date = localize_to_ist(datetime.combine(current_date, get_ist_datetime().time()))
        current_end_date = current_end_date - timedelta(days=1)  # Adjust to the previous day for end date
        end_date = calculate_end_date(current_end_date, interval_minutes)
        end_date = end_date.replace(hour=15, minute=30, second=0, microsecond=0)

        formatted_symbol = f"{symbol}-{instrument_type}"
        
        df = await broker.get_history(
            symbol="NIFTY 50",
            from_date=start_date,
            to_date=end_date,
            ohlc_interval=interval_minutes,
            ins_type=instrument_type
        )
        if df is None or len(df) == 0:
            print(f"No data fetched for {symbol}.")
            continue
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = calculate_rsi(df, 14)
        
        # Debug date range
        # print(f"Data range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        # print(f"Total rows: {len(df)}")
        print(df.tail(670))
        
        # Use the new Pine Script-style swing detection
        # df_labeled = find_hhlh_pivots(df, left_bars=2, right_bars=4)
        
        # # Get last swing points
        # last_hh, last_ll, last_hl, last_lh = get_last_swing_points(df_labeled)
        
        # results.append({
        #     "symbol": symbol,
        #     "HH": last_hh,
        #     "LL": last_ll,
        #     "HL": last_hl,
        #     "LH": last_lh
        # })

    # console = Console()
    # table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE_HEAVY)
    # table.add_column("Symbol", style="dim")
    # table.add_column("Higher High")
    # table.add_column("Lower Low")
    # table.add_column("Higher Low")
    # table.add_column("Lower High")

    # for res in results:
    #     hh_str = f"{res['HH']['price']:.2f} @ {res['HH']['timestamp'].strftime('%m-%d %H:%M')}" if res['HH'] else "N/A"
    #     ll_str = f"{res['LL']['price']:.2f} @ {res['LL']['timestamp'].strftime('%m-%d %H:%M')}" if res['LL'] else "N/A"
    #     hl_str = f"{res['HL']['price']:.2f} @ {res['HL']['timestamp'].strftime('%m-%d %H:%M')}" if res['HL'] else "N/A"
    #     lh_str = f"{res['LH']['price']:.2f} @ {res['LH']['timestamp'].strftime('%m-%d %H:%M')}" if res['LH'] else "N/A"
    #     table.add_row(res["symbol"], hh_str, ll_str, hl_str, lh_str)

    # console.print(table)

if __name__ == "__main__":
    asyncio.run(main())
#