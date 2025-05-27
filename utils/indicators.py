"""
indicators.py

This module provides technical indicators used in trading strategies. These indicators are designed to
analyze historical price data and help identify potential market trends, reversals, and other trading
opportunities.

Supported Indicators:
- Supertrend: A trend-following indicator that determines the direction of the market and potential
  entry/exit points.
- Average True Range (ATR): Measures market volatility by analyzing the range of price movements.
- Moving Averages (SMA/EMA): Calculates the average price over a specific period to smooth out price data.

Features:
- Modular design for easy integration into trading systems.
- Optimized performance for large datasets.
- Flexibility to customize indicator parameters.

Usage Example:
    ```python
    from indicators import calculate_supertrend, calculate_atr

    # Calculate Supertrend
    supertrend_data = calculate_supertrend(data, period=10, multiplier=3)

    # Calculate ATR
    atr_data = calculate_atr(data, period=14)
    ```

Dependencies:
- pandas: Used for data manipulation.
- numpy: Used for numerical computations.

Notes:
- Ensure that the input data is in a DataFrame format with required columns (e.g., 'open', 'high', 'low', 'close').
- Each indicator function includes parameter defaults that can be customized as per requirements.
"""
import pandas as pd
from algosat.common.logger import get_logger

logger = get_logger("indicators")

pd.set_option('display.width', 1500)
pd.set_option('display.max_columns', 75)
pd.set_option('display.max_rows', 500)


def true_range(data):
    """
        True Range
    :param data: Pandas Dataframe :return:  with new Column 'TR,' which has the True Range
    """
    data['h-l'] = data['high'] - data['low']
    data['h-c'] = abs(data['high'] - data['close'].shift(1))
    data['l-pc'] = abs(data['low'] - data['close'].shift(1))
    data['TR'] = data.loc[:, ['h-l', 'h-c', 'l-pc']].max(axis=1)
    data.drop(['h-l', 'h-c', 'l-pc'], inplace=True, axis=1)
    return data


def calculate_atr(data, period=14, drop_tr=True, smoothing="RMA"):
    """
            Average True Range
    :param data: Pandas Dataframe
    :param period: Period for which the ATR needs to be calculated
    :param drop_tr: Whether to drop the TR field
    :param smoothing: Smoothing type - Possible values: RMA, SMA, EMA
    :return: Pandas Dataframe with new column atr_<period>_<smoothing>. Ex: atr_14_sma
    """
    data = true_range(data)
    if smoothing == "RMA":
        data['atr'] = data['TR'].ewm(com=period - 1, min_periods=period).mean()
    elif smoothing == "SMA":
        data['atr'] = data['TR'].rolling(window=period).mean()
    elif smoothing == "EMA":
        data['atr'] = data['TR'].ewm(span=period, adjust=False).mean()
    if drop_tr:
        data.drop(['TR'], inplace=True, axis=1)
    return data


def calculate_supertrend(df, period=7, multiplier=3):
    """
    Calculate Supertrend Indicator.

    :param df: Pandas DataFrame containing OHLC data.
    :param period: Period for ATR calculation (default is 7).
    :param multiplier: Multiplier for ATR in Supertrend calculation (default is 3).
    :return: Pandas DataFrame with Supertrend and Supertrend signal columns added.
    """
    try:
        # Ensure the DataFrame has enough data
        if len(df) < period:
            logger.error(f"Insufficient data for Supertrend calculation: {len(df)} rows available, {period} required.")
            return df
        # Reset index to ensure sequential indexing
        df = df.reset_index(drop=True)

        # Calculate True Range (TR)
        df['h-l'] = df['high'] - df['low']
        df['h-pc'] = abs(df['high'] - df['close'].shift(1))
        df['l-pc'] = abs(df['low'] - df['close'].shift(1))
        df['TR'] = df[['h-l', 'h-pc', 'l-pc']].max(axis=1)
        df.drop(['h-l', 'h-pc', 'l-pc'], axis=1, inplace=True)

        # Calculate ATR
        df = calculate_atr(df, period, True)

        # Calculate basic upper and lower bands
        atr_col = 'atr'
        df['basic_ub'] = ((df['high'] + df['low']) / 2) + (df[atr_col] * multiplier)
        df['basic_lb'] = ((df['high'] + df['low']) / 2) - (df[atr_col] * multiplier)

        # Initialize final upper and lower bands
        df['final_ub'] = 0.0
        df['final_lb'] = 0.0

        # Calculate final upper and lower bands
        for i in range(period, len(df)):
            if i >= len(df):
                logger.error(f"Row {i} out of bounds for DataFrame with length {len(df)}.")
                continue

            df.loc[i, 'final_ub'] = (
                df.loc[i, 'basic_ub']
                if df.loc[i, 'basic_ub'] < df.loc[i - 1, 'final_ub'] or
                   df.loc[i - 1, 'close'] > df.loc[i - 1, 'final_ub']
                else df.loc[i - 1, 'final_ub']
            )
            df.loc[i, 'final_lb'] = (
                df.loc[i, 'basic_lb']
                if df.loc[i, 'basic_lb'] > df.loc[i - 1, 'final_lb']
                   or df.loc[i - 1, 'close'] < df.loc[i - 1, 'final_lb']
                else df.loc[i - 1, 'final_lb']
            )

        # Calculate Supertrend
        st_col = 'supertrend'
        df[st_col] = 0.0
        for i in range(period, len(df)):

            if i >= len(df):
                logger.error(f"Row {i} out of bounds for DataFrame with length {len(df)}.")
                continue

            df.loc[i, st_col] = (
                df.loc[i, 'final_ub']
                if (df.loc[i - 1, st_col] == df.loc[i - 1, 'final_ub'] and df.loc[i, 'close'] <= df.loc[i, 'final_ub'])
                else df.loc[i, 'final_lb']
                if (df.loc[i - 1, st_col] == df.loc[i - 1, 'final_ub'] and df.loc[i, 'close'] > df.loc[i, 'final_ub'])
                else df.loc[i, 'final_lb']
                if (df.loc[i - 1, st_col] == df.loc[i - 1, 'final_lb'] and df.loc[i, 'close'] >= df.loc[i, 'final_lb'])
                else df.loc[i, 'final_ub']
                if (df.loc[i - 1, st_col] == df.loc[i - 1, 'final_lb'] and df.loc[i, 'close'] < df.loc[i, 'final_lb'])
                else 0.0
            )

        # Drop intermediate columns
        df.drop(['basic_ub', 'basic_lb', 'final_ub', 'final_lb'], axis=1, inplace=True)

        # Calculate Supertrend signal
        df[f'{st_col}_signal'] = None  # Initialize the signal column
        df.loc[df[st_col] > 0.0, f'{st_col}_signal'] = 'SELL'
        df.loc[(df[st_col] > 0.0) & (df['close'] >= df[st_col]), f'{st_col}_signal'] = 'BUY'

        return df

    except Exception as e:
        logger.error(f"Error calculating Supertrend: {e}")
        return df


def calculate_vwap(df_ma):
    """
    Volume Weighted Average Price (VWAP). Not applicable on Day's candle. Apply on minute candle only.

    :param df_ma: DataFrame of candles
    :return: DataFrame with the VWAP field
    """
    pd.options.mode.chained_assignment = None  # Suppress setting-with-copy warnings

    # Ensure the index is datetime
    if not isinstance(df_ma.index, pd.DatetimeIndex):
        if 'timestamp' in df_ma.columns:
            df_ma['timestamp'] = pd.to_datetime(df_ma['timestamp'])  # Convert to datetime if not already
            df_ma.set_index('timestamp', inplace=True)
        else:
            raise ValueError("DataFrame must contain a 'timestamp' column to calculate VWAP.")

    # Calculate VWAP components
    df_ma['tp'] = (df_ma['high'] + df_ma['low'] + df_ma['close']) / 3
    df_ma['vp'] = df_ma['volume'] * df_ma['tp']
    df_ma['tv'] = df_ma.groupby(pd.Grouper(freq='D'))['volume'].transform('cumsum')
    df_ma['tvp'] = df_ma.groupby(pd.Grouper(freq='D'))['vp'].transform('cumsum')

    # Calculate VWAP
    df_ma['vwap'] = df_ma['tvp'] / df_ma['tv']

    # Restore timestamp as a column
    df_ma.reset_index(inplace=True)

    # Clean up temporary columns
    df_ma.drop(['tp', 'vp', 'tv', 'tvp'], inplace=True, axis=1)
    pd.options.mode.chained_assignment = "warn"  # Restore default warning behavior

    return df_ma


def calculate_sma(df, period=14, field='close'):
    """
        Simple Moving average
        https://www.investopedia.com/terms/s/sma.asp
    :param df: Pandas DataFrame
    :param period: Period for the SMA needs to be calculated. Default=14
    :param field: Field which the SMA to be calculated. By default, it will be 'close'.
    :return: DataFrame with new column SMA + <Period>. Ex: SMA14
    """
    try:
        df['sma'] = df[field].rolling(window=period).mean()
        return df
    except Exception as err:
        logger.error("Error deriving SMA. Error: {0}".format(err))
        return pd.DataFrame()


def average_true_range(data, period=14, drop_tr=True, smoothing="RMA"):
    """
            Average True Range
    :param data: Pandas Dataframe
    :param period: Period for which the ATR needs to be calculated
    :param drop_tr: Whether to drop the TR field
    :param smoothing: Smoothing type - Possible values: RMA, SMA, EMA
    :return: Pandas Dataframe with new column atr_<period>_<smoothing>. Ex: atr_14_sma
    """
    try:
        data = true_range(data)
        if smoothing == "RMA":
            data['atr_' + str(period) + '_' + str(smoothing)] = data['TR'].ewm(com=period - 1,
                                                                               min_periods=period).mean()
        elif smoothing == "SMA":
            data['atr_' + str(period) + '_' + str(smoothing)] = data['TR'].rolling(window=period).mean()
        elif smoothing == "EMA":
            data['atr_' + str(period) + '_' + str(smoothing)] = data['TR'].ewm(span=period, adjust=False).mean()
        if drop_tr:
            data.drop(['TR'], inplace=True, axis=1)
        data = data.round(decimals=4)
        return data
    except Exception as err:
        logger.error("Error deriving SMA. Error: {0}".format(err))
        return pd.DataFrame()


def calculate_atr_trial_stops(data, atr_multiplier=3, atr_period=21, high_low=False):
    """
            ATR Trailing Stops
    :param data: Pandas Dataframe
    :param atr_multiplier: Multiplier. Default is 3
    :param atr_period: ATR Period. Default is 21
    :param high_low: To calculate on high low. Default is Close
    :return: Pandas Dataframe with two fields buy_stop and sell_stop
    """
    try:
        moving_average = "RMA"
        data = average_true_range(data, atr_period, True, moving_average)
        if high_low:
            data['buy_stop'] = data['high'].rolling(window=atr_period).max() - (
                    atr_multiplier * data['atr_' + str(atr_period) + '_' + moving_average])
            data['sell_stop'] = data['low'].rolling(window=atr_period).min() + (
                    atr_multiplier * data['atr_' + str(atr_period) + '_' + moving_average])
        else:
            data['buy_stop'] = data['close'].rolling(window=atr_period).max() - (
                    atr_multiplier * data['atr_' + str(atr_period) + '_' + moving_average])
            data['sell_stop'] = data['close'].rolling(window=atr_period).min() + (
                    atr_multiplier * data['atr_' + str(atr_period) + '_' + moving_average])
        return data
    except Exception as err:
        logger.error("Error deriving SMA. Error: {0}".format(err))
        return pd.DataFrame()
