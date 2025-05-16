"""
fyers_wrapper.py

This module provides a wrapper for interacting with the Fyers API. It includes utility
functions and classes to handle common operations like placing, modifying, and canceling
orders, fetching market data, and managing positions. The module supports both synchronous
and asynchronous workflows.

Features:
- Place orders (sync and async).
- Modify existing orders.
- Cancel orders.
- Fetch order details.
- Exit positions.
- Split large orders into manageable chunks.
- Handle both paper and live trading scenarios.

Dependencies:
- Fyers API Python SDK
- Logging for tracking operations

Usage:
- Import the required functions or classes in your main trading script.
- Initialize and configure the module for your trading environment (paper or live).
"""

import asyncio
import json
import os
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import nest_asyncio
import pandas as pd
import pyotp
import pytz
import requests
from asynciolimiter import Limiter
from fyers_apiv3 import fyersModel
from selenium.webdriver.common.by import By
from seleniumbase import SB

from brokers.base import BrokerInterface
from common import constants
from common.broker_utils import shutdown_gracefully, get_broker_credentials, upsert_broker_credentials, can_reuse_token
from common.logger import get_logger
from utils.utils import get_ist_datetime
from pyvirtualdisplay import Display

nest_asyncio.apply()


# Get the directory of the calling script
def get_caller_directory() -> str:
    """
    Get the directory of the script that is calling this function.

    :return: Directory path of the calling script.
    """

    try:
        # Find the main script being executed
        script_name = os.path.splitext(os.path.basename(__import__("__main__").__file__))[0]
        return os.path.dirname(os.path.abspath(script_name))
    except (KeyError, AttributeError) as e:
        logger.debug(f"KeyError: '__file__' not found in __main__: {e}")
        shutdown_gracefully("error reading config file")
    except Exception as e:
        logger.debug(f"KeyError: '__file__' not found in __main__: {e}")
        shutdown_gracefully("error reading config file")


logger = get_logger("fyers_wrapper")

# rate_limiter = Limiter(10, max_burst=20)
rate_limiter_per_second = Limiter(9 / 1)  # 10 requests per second
rate_limiter_per_minute = Limiter(190 / 60)


class FyersWrapper(BrokerInterface):
    """
    FyersWrapper

    A utility class for interacting with the Fyers API. This class provides methods
    to place, modify, and cancel orders, fetch order details, and manage positions.

    Features:
    - Supports both synchronous and asynchronous operations.
    - Handles paper and live trading scenarios.
    - Includes methods for order splitting and other common trading utilities.

    Usage:
    - Initialize the class with necessary configurations (e.g., API credentials).
    - Use the provided methods to perform trading operations.
    """
    fyers = None
    is_async = False  # Default to synchronous mode
    token = None
    appId = None

    @staticmethod
    def _make_margin_request(data):
        """
        Helper method to make margin request using the Fyers API.
        """
        try:
            url = "https://api-t1.fyers.in/api/v3/multiorder/margin"
            headers = {
                "Authorization": f"{FyersWrapper.appId}:{FyersWrapper.token}",
                "Content-Type": "application/json",
            }
            response = requests.post(url, headers=headers, json=data)
            return response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to check margin: {e}")

    @staticmethod
    async def check_margin_async(data):
        """
        Check margin requirements asynchronously before placing orders.

        :param data: Order details to check the margin for.
        :return: Parsed margin response.
        """
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, FyersWrapper._make_margin_request, data)
        if response.get("s") != "ok":
            raise ValueError(f"Margin check failed: {response.get('message', 'Unknown error')}")
        return response["data"]

    @staticmethod
    def check_margin_sync(data):
        """
        Check margin requirements synchronously before placing orders.

        :param data: Order details to check the margin for.
        :return: Parsed margin response.
        """
        response = FyersWrapper._make_margin_request(data)
        if response.get("s") != "ok":
            raise ValueError(f"Margin check failed: {response.get('message', 'Unknown error')}")
        return response["data"]

    @staticmethod
    def check_margin(data):
        """
        Dynamically check margin based on the mode (sync/async).

        :param data: Order details to check the margin for.
        :return: Parsed margin response.
        """
        if FyersWrapper.is_async:
            return FyersWrapper.check_margin_async(data)
        else:
            return FyersWrapper.check_margin_sync(data)

    @staticmethod
    async def setup_auth(is_async=False):
        """Authenticate and initialize the Fyers API with async or sync mode."""
        FyersWrapper.is_async = is_async
        if FyersWrapper.is_async:
            return await FyersWrapper._setup_auth_async()
        else:
            return FyersWrapper._setup_auth_sync()  # No `await` needed

    @staticmethod
    async def _setup_auth_async():
        """Authenticate asynchronously."""
        return FyersWrapper._setup_auth_sync()

    @staticmethod
    def _setup_auth_sync():
        """Authenticate synchronously."""
        # Fetch full broker config and extract credentials only
        full_config = asyncio.run(get_broker_credentials("fyers"))
        credentials = None
        if isinstance(full_config, dict):
            credentials = full_config.get("credentials")
        if not credentials or not isinstance(credentials, dict):
            logger.error("No Fyers credentials found in database or credentials are invalid")
            return False

        # Use can_reuse_token utility for token validation
        if (
            "access_token" in credentials and
            "generated_on" in credentials and
            can_reuse_token(credentials["generated_on"])
        ):
            try:
                FyersWrapper.fyers = fyersModel.FyersModel(
                    token=credentials["access_token"],
                    is_async=FyersWrapper.is_async,
                    client_id=credentials["api_key"],
                    log_path=constants.FYER_LOG_DIR,
                )
                FyersWrapper.token = credentials["access_token"]
                FyersWrapper.appId = credentials["api_key"]
                logger.info("Successfully authenticated using existing token.")
                return True
            except Exception as e:
                logger.exception("Token validation exception while checking reuse")

        # Perform re-authentication
        logger.info("Generating a new access token.")
        session = fyersModel.SessionModel(
            client_id=credentials["api_key"],
            secret_key=credentials["api_secret"],
            redirect_uri=credentials["redirect_uri"],
            response_type="code",
            grant_type="authorization_code",
        )

        auth_url = session.generate_authcode()
        auth_code = FyersWrapper.authenticate(
            url=auth_url,
            mobile_number=credentials["client_id"], # Assuming client_id is the mobile number
            password_2fa=credentials["pin"], # Assuming pin is the 2FA password
            totp_secret_key=credentials["totp_secret"],
        )

        if not auth_code:
            return False

        session.set_token(auth_code)
        response = session.generate_token()
        credentials["access_token"] = response["access_token"]
        credentials["generated_on"] = get_ist_datetime().strftime("%d/%m/%Y %H:%M:%S")
        # Persist the entire broker config, not just the credentials sub-dict
        full_config["credentials"] = credentials
        asyncio.run(upsert_broker_credentials("fyers", full_config))

        FyersWrapper.fyers = fyersModel.FyersModel(
            token=credentials["access_token"],
            is_async=FyersWrapper.is_async,
            client_id=credentials["api_key"],
            log_path=constants.FYER_LOG_DIR,
        )
        FyersWrapper.token = credentials["access_token"]
        FyersWrapper.appId = credentials["api_key"]
        logger.info(f"Successfully authenticated with new token.")
        return True

    @staticmethod
    async def login():
        """
        Authenticate with Fyers API using stored credentials.
        This method conforms to the BrokerInterface.
        Returns:
            bool: True if authentication was successful, False otherwise
        """
        try:
            # Fetch full broker config and extract only the credentials field
            full_config = await get_broker_credentials("fyers")
            credentials = None
            if isinstance(full_config, dict):
                credentials = full_config.get("credentials")
            if not credentials or not isinstance(credentials, dict):
                logger.error("No Fyers credentials found in database or credentials are invalid")
                return False

            # Use only the credentials dict from now on
            fyers_creds = credentials

            # Check if we already have a valid access token based on generation time
            access_token = fyers_creds.get("access_token")
            generated_on_str = fyers_creds.get("generated_on")
            if access_token and generated_on_str and can_reuse_token(generated_on_str):
                try:
                    FyersWrapper.token = access_token
                    FyersWrapper.appId = fyers_creds.get("api_key")
                    FyersWrapper.fyers = fyersModel.FyersModel(
                        client_id = fyers_creds.get("api_key"),
                        is_async=FyersWrapper.is_async,
                        token=access_token,
                        log_path=constants.FYER_LOG_DIR
                    )
                    logger.info("Reusing existing Fyers access token (generated today after 6AM or before 6AM and still before 6AM)")
                    return True
                except Exception as e:
                    logger.warning(f"Token reuse check failed: {e}, will generate new token")

            # Use the existing setup_auth method for now
            # This maintains backward compatibility while still using the new interface
            logger.info("Obtaining new Fyers access token")
            result = await FyersWrapper.setup_auth(is_async=True)
            return result is not None  # Return True if we got a result
        except Exception as e:
            logger.error(f"Fyers authentication failed: {e}", exc_info=True)
            return False

    @staticmethod
    async def _wrap_async(callable_func, *args, **kwargs):
        """Wrapper for calling sync methods in async mode."""
        return await asyncio.to_thread(callable_func, *args, **kwargs)

    @staticmethod
    async def get_balance_async():
        """Fetch account balance asynchronously."""
        try:
            response = await FyersWrapper.fyers.funds()  # Ensure it's awaited here
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance asynchronously: {e}")
            return None

    @staticmethod
    def get_balance_sync():
        """Fetch account balance synchronously."""
        try:
            response = FyersWrapper.fyers.funds()
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance synchronously: {e}")
            return None

    @staticmethod
    async def get_balance():
        """Dynamic balance method based on is_async flag."""
        if FyersWrapper.is_async:
            return await FyersWrapper.get_balance_async()  # Return coroutine for await
        else:
            return FyersWrapper.get_balance_sync()

    @staticmethod
    async def get_profile_async():
        """Fetch account balance asynchronously."""
        try:
            response = await FyersWrapper.fyers.get_profile()  # Ensure it's awaited here
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance asynchronously: {e}")
            return None

    @staticmethod
    def get_profile_sync():
        """Fetch account balance synchronously."""
        try:
            response = FyersWrapper.fyers.get_profile()
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance synchronously: {e}")
            return None

    @staticmethod
    async def get_profile():
        """
        Get user profile information from the broker.
        This method implements the BrokerInterface.
        
        Returns:
            dict: Profile data or empty dict if unsuccessful
        """
        try:
            if not FyersWrapper.fyers:
                logger.error("Fyers client not initialized, please call login() first")
                return {}

            # Dispatch to sync or async based on mode
            if FyersWrapper.is_async:
                profile_data = await FyersWrapper.get_profile_async()
            else:
                profile_data = FyersWrapper.get_profile_sync()

            if profile_data and profile_data.get("code") == 200 and profile_data.get("s") == "ok":
                return profile_data.get("data", {})
            else:
                logger.error(f"Failed to get profile: {profile_data.get('message', 'Unknown error') if isinstance(profile_data, dict) else profile_data}")
                return {}
        except Exception as e:
            logger.error(f"Error getting profile: {e}", exc_info=True)
            return {}

    @staticmethod
    async def get_option_chain_async(symbol, strike_count):
        """Fetch the option chain asynchronously."""
        try:
            data = {
                "symbol": symbol,
                "strikecount": strike_count,
                "timestamp": "",
            }
            response = await FyersWrapper.fyers.optionchain(data)  # Directly await here
            return response
        except Exception as e:
            logger.error(f"Failed to fetch option chain for {symbol}: {e}")
            return None

    @staticmethod
    def get_option_chain_sync(symbol, strike_count):
        """
        Fetch the option chain synchronously.

        :param symbol: The trading symbol, e.g., "NSE: NIFTY50-INDEX".
        :param strike_count: Number of strikes to fetch for the option chain.
        :return: The option chain data as a dictionary or None on failure.
        """
        try:
            # Data payload to fetch the option chain
            data = {
                "symbol": symbol,
                "strikecount": strike_count,
                "timestamp": "",
            }
            logger.info(f"Fetching option chain for {symbol} with strike count {strike_count}")

            # Call the sync method and get the response
            response = FyersWrapper.fyers.optionchain(data)

            # Validate response
            if response.get("code") != 200 or response.get("s") != "ok":
                logger.error(f"Error fetching option chain: {response.get('message', 'Unknown error')}")
                return None

            logger.info("Successfully fetched option chain.")
            return response

        except Exception as e:
            logger.error(f"Failed to fetch option chain for {symbol}: {e}")
            return None

    @staticmethod
    def get_option_chain(symbol, strike_count):
        """Fetch the option chain dynamically based on async/sync mode."""
        if FyersWrapper.is_async:
            return FyersWrapper.get_option_chain_async(symbol, strike_count)
        else:
            return FyersWrapper.get_option_chain_sync(symbol, strike_count)

    @staticmethod
    async def get_history_async(symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data asynchronously with retry logic.

        :param symbol: Trading symbol (e.g., "NSE:SBIN-EQ").
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: Interval for OHLC data (e.g., 1, 5, 15 min).
        :param ins_type: Instrument type (default is "EQ").
        :return: DataFrame containing OHLC data or None on failure.
        """
        retries = 3
        base_delay = 2
        for attempt in range(retries):
            try:
                # Rate limiter to adhere to API limits
                await rate_limiter_per_second.wait()
                await rate_limiter_per_minute.wait()

                exchange = "MCX" if "MCX" in ins_type else "NSE"
                if not symbol.startswith("NSE:") and not symbol.startswith("MCX:"):
                    symbol = f"{exchange}:{symbol}"

                from_date_epoch = convert_to_epoch(from_date)
                to_date_epoch = convert_to_epoch(to_date)
                formatted_symbol = f"{symbol}-{ins_type}" if ins_type else symbol

                params = {
                    "symbol": formatted_symbol,
                    "resolution": ohlc_interval,
                    "range_from": from_date_epoch,
                    "range_to": to_date_epoch,
                    "date_format": "0",
                    "cont_flag": 1,
                }

                logger.debug(
                    f"Fetching async history for {formatted_symbol} from {from_date} to {to_date}... "
                    f"(Attempt {attempt + 1})")

                response = await FyersWrapper.fyers.history(params)

                if isinstance(response, dict) and response.get("code") == 200 and response.get("s") == "ok":
                    candles = response.get("candles", [])
                    if not candles:  # Safe check for empty or None candles
                        logger.debug(f"No historical data found for {formatted_symbol}.")
                        return None

                    # Process the candle data
                    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    ist_timezone = pytz.timezone("Asia/Kolkata")
                    df["timestamp"] = (
                        pd.to_datetime(df["timestamp"], unit="s")
                        .dt.tz_localize("UTC")
                        .dt.tz_convert(ist_timezone)
                    )
                    df["timestamp"] = df["timestamp"].dt.tz_localize(None)  # Remove timezone info if needed
                    df.attrs[constants.COLUMN_SYMBOL] = formatted_symbol

                    logger.debug(f"Successfully fetched historical data for {formatted_symbol}.")
                    return df
                else:
                    error_message = response.get("message", "Unknown error") if isinstance(response, dict) else str(
                        response)
                    logger.debug(
                        f"Failed to fetch history for {formatted_symbol}: {error_message}")
                    if "request limit reached" in error_message.lower():
                        logger.debug("Getting 'request limit reached' error. Waiting 10 seconds before retrying...")
                        await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Exception while fetching async history for {symbol}: {e}")

            # Retry logic with exponential backoff
            if attempt < retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff: 2, 4, 8 seconds
                logger.debug(f"Retrying {symbol} history fetching in {delay} seconds...")
                await asyncio.sleep(delay)

        logger.debug(f"Exhausted retries for async history fetch for {symbol}. ")
        return None

    @staticmethod
    def get_history_sync(symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data synchronously with retry logic.

        :param symbol: Trading symbol (e.g., "NSE:SBIN-EQ").
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: Interval for OHLC data (e.g., 1, 5, 15 min).
        :param ins_type: Instrument type (default is "EQ").
        :return: DataFrame containing OHLC data or None on failure.
        """
        retries = 3
        delay = 2
        for attempt in range(retries):
            try:
                exchange = "MCX" if "MCX" in ins_type else "NSE"
                from_date_epoch = convert_to_epoch(from_date)
                to_date_epoch = convert_to_epoch(to_date)
                formatted_symbol = f"{exchange}:{symbol}-{ins_type}" if ins_type else f"{exchange}:{symbol}"

                params = {
                    "symbol": formatted_symbol,
                    "resolution": ohlc_interval,
                    "range_from": from_date_epoch,
                    "range_to": to_date_epoch,
                    "date_format": "0",
                    "cont_flag": 1,
                }

                logger.info(
                    f"Fetching sync history for {symbol} from {from_date} to {to_date}... (Attempt {attempt + 1})")
                response = FyersWrapper.fyers.history(params)

                if response.get("code") == 200 and response.get("s") == "ok":
                    candles = response.get("candles", [])
                    if not candles:
                        logger.warning(f"No historical data found for {symbol}.")
                        return None

                    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                    ist_timezone = pytz.timezone("Asia/Kolkata")
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s").dt.tz_localize("UTC").dt.tz_convert(
                        ist_timezone)
                    df["timestamp"] = df["timestamp"].dt.tz_localize(None)

                    logger.info(f"Successfully fetched sync historical data for {symbol}.")
                    return df
                else:
                    logger.warning(
                        f"Failed to fetch history for {symbol}: {response.get('message', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Exception while fetching sync history for {symbol}: {e}")

            if attempt < retries - 1:
                time.sleep(delay)  # Backoff before retrying

        logger.debug(f"Exhausted retries for sync history fetch for {symbol}.")
        return None

    @staticmethod
    async def get_history(symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data dynamically based on "is_async" flag.

        :param symbol: Trading symbol.
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: OHLC interval (e.g., 1 min, 5 min).
        :param ins_type: Instrument type.
        :return: DataFrame or None.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.get_history_async(symbol, from_date, to_date, ohlc_interval, ins_type)
        else:
            return FyersWrapper.get_history_sync(symbol, from_date, to_date, ohlc_interval, ins_type)

    @staticmethod
    async def place_order_async(**order_params):
        """
        Place an order in async mode.

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = await FyersWrapper.fyers.place_order(order_params)
            # logger.debug(response)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to place order (async): {e}")

    @staticmethod
    def place_order_sync(**order_params):
        """
        Place an order in sync mode.

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = FyersWrapper.fyers.place_order(order_params)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to place order (sync): {e}")

    @staticmethod
    async def place_order(**order_params):
        """
        Common method to place an order dynamically based on the mode (sync/async).

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.place_order_async(**order_params)
        else:
            return FyersWrapper.place_order_sync(**order_params)

    @staticmethod
    async def split_and_place_order(total_qty, max_nse_qty, trigger_price_diff, **order_params):
        """
        Split the order into chunks if the quantity exceeds max_nse_qty.

        :param total_qty: Total quantity to be ordered.
        :param max_nse_qty: Maximum quantity allowed per order.
        :param order_params: Parameters for the order.
        :param trigger_price_diff: Trigger_price_diff
        :return: List of responses for each placed order.

        """
        responses = []
        # Extract original price from order parameters
        original_price = order_params.get("limitPrice", 0)  # Ensure price exists
        max_price_increase = 2.00  # Maximum allowed price increase
        price_increment = 0.20  # Increment per order
        current_price = original_price  # Track updated price

        while total_qty > 0:
            qty = min(total_qty, max_nse_qty)
            order_params["qty"] = qty
            # not incrementing for the market orders (type =2 is market order)
            if order_params["type"] != 2:
                order_params["limitPrice"] = current_price  # Update price
                order_params["stopPrice"] = current_price - trigger_price_diff
            # Update price for next order (increment by ₹0.20 but max ₹2 total increase)
            if (current_price - original_price) < max_price_increase:
                current_price = min(original_price + max_price_increase, current_price + price_increment)
            logger.debug(f"Placing order {order_params}")
            response = await FyersWrapper.place_order(**order_params)
            responses.append(response)
            total_qty -= qty
        return responses

    @staticmethod
    async def place_split_orders_with_sl_tp(total_qty, max_nse_qty, stop_loss_price, target_price, trigger_price_diff,
                                            **order_params):
        """
        Place main orders and corresponding Stop-Loss (SL) & Target (TP) orders.
        - If total_qty > max_nse_qty, it splits the order into chunks.
        - For each successful entry, it places an equivalent SL and TP order.
        - The entry price increments by ₹0.20 per order but does not exceed ₹2 from the original price.
        - If an entry fails, SL & TP for that order won't be placed.
        - Logs errors but continues processing other orders.

        :param total_qty: Total quantity to be ordered.
        :param max_nse_qty: Maximum quantity allowed per order.
        :param stop_loss_price: Stop-Loss price for the order.
        :param target_price: Target price for the order.
        :param trigger_price_diff: Trigger price difference
        :param order_params: Order parameter (including initial price).
        :return: Dictionary containing `entry_responses`, `sl_responses`, and `target_responses`.
        """
        entry_responses = []
        sl_responses = []
        target_responses = []

        # Extract original price from order parameters
        original_price = order_params.get("limitPrice", 0)  # Ensure price exists
        max_price_increase = 2.00  # Maximum allowed price increase
        price_increment = 0.20  # Increment per order
        current_price = original_price  # Track updated price

        logger.debug(
            f"Stop Loss Price: {stop_loss_price}, Target Price: {target_price}, Trigger Diff: {trigger_price_diff}")

        while total_qty > 0:
            qty = min(total_qty, max_nse_qty)
            order_params["qty"] = qty
            order_params["limitPrice"] = current_price  # Update price
            order_params["stopPrice"] = current_price + trigger_price_diff

            # Place entry order
            try:
                logger.debug(f"Placing entry order {order_params}")
                entry_response = await FyersWrapper.place_order(**order_params)
                if entry_response.get("s") == "ok":  # Check if order placement was successful
                    entry_responses.append(entry_response)
                    logger.debug(f"Entry order placed successfully at Rs.{current_price} for {qty} quantity")
                    # Prepare SL and Target orders (opposite direction - BUY)
                    sl_order = order_params.copy()
                    sl_order["qty"] = qty
                    sl_order["side"] = 1  # Assuming 1 is Buy for SL
                    sl_order["limitPrice"] = stop_loss_price
                    sl_order["stopPrice"] = stop_loss_price - trigger_price_diff
                    sl_order["type"] = 4

                    target_order = order_params.copy()
                    target_order["qty"] = qty
                    target_order["side"] = 1  # Assuming 1 is Buy for Target
                    # Ensure limitPrice does not go below 0.70
                    target_order["limitPrice"] = max(target_price, 0.70)

                    # Ensure stopPrice does not go below 0.50
                    # target_order["stopPrice"] = max(target_price - trigger_price_diff, 0.50)
                    target_order["stopPrice"] = 0
                    target_order["type"] = 1

                    # Place SL Order
                    try:
                        logger.debug(f"Placing SL order {sl_order}")
                        sl_response = await FyersWrapper.place_order(**sl_order)
                        if sl_response.get("s") == "ok":
                            sl_responses.append(sl_response)
                            logger.debug(f"Stop-Loss order placed: {sl_response}")
                        else:
                            logger.error(f"Failed to place Stop-Loss order: {sl_response}")
                    except Exception as e:
                        logger.error(f"Error placing Stop-Loss order: {e}")

                    # Place Target Order
                    try:
                        logger.debug(f"Placing target order {target_order}")
                        target_response = await FyersWrapper.place_order(**target_order)
                        if target_response.get("s") == "ok":
                            target_responses.append(target_response)
                            logger.debug(f"Target order placed: {target_response}")
                        else:
                            logger.error(f"Failed to place Target order: {target_response}")
                    except Exception as e:
                        logger.error(f"Error placing Target order: {e}")

                    # Update price for next order (increment by ₹0.20 but max ₹2 total increase)
                    if (current_price - original_price) < max_price_increase:
                        current_price = min(original_price + max_price_increase, current_price + price_increment)
                else:
                    logger.error(f"Entry order failed: {entry_response}")
                    # return []
            except Exception as e:
                logger.error(f"Error placing entry order: {e}")
                # return []

            # Reduce the remaining quantity
            total_qty -= qty

        return {
            "entry_responses": entry_responses,
            "sl_responses": sl_responses,
            "target_responses": target_responses
        }

    @staticmethod
    async def get_order_details_async(order_id=None):
        """
        Fetch order details asynchronously.
        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        try:
            if not order_id:
                response = await FyersWrapper.fyers.orderbook()
            else:
                response = await FyersWrapper.fyers.orderbook(data={"id": order_id})
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch order details (async): {e}")

    @staticmethod
    def get_order_details_sync(order_id=None):
        """
        Fetch order details synchronously.

        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        try:
            if not order_id:
                response = FyersWrapper.fyers.orderbook()
            else:
                response = FyersWrapper.fyers.orderbook(data={"id": order_id})
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch order details (sync): {e}")

    @staticmethod
    def get_order_details(order_id=None):
        """
        Dynamically fetch order details based on the mode (sync/async).

        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        if FyersWrapper.is_async:
            return FyersWrapper.get_order_details_async(order_id)
        else:
            return FyersWrapper.get_order_details_sync(order_id)

    @staticmethod
    async def modify_order_async(data: dict):
        """
        Modify an existing order asynchronously.

        :param data: Order id details
        :return: Response from the Fyers API.
        """
        try:
            response = await FyersWrapper.fyers.modify_order(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to modify order (async): {e}")

    @staticmethod
    def modify_order_sync(data: dict):
        """
        Modify an existing order synchronously.

        :param data: Order id details
        :return: Response from the Fyers API.
        """
        try:
            response = FyersWrapper.fyers.modify_order(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to modify order (sync): {e}")

    @staticmethod
    async def modify_order(data: dict):
        """
        Dynamically modify an existing order based on the mode (sync/async).
         :param data: Order id details
        :return: Response from the Fyers API.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.modify_order_async(data)
        else:
            return FyersWrapper.modify_order_sync(data)

    @staticmethod
    async def cancel_order_async(order_id: str):
        """
        Cancel an existing order asynchronously.

        :param order_id: Order ID to be canceled.
        :return: Response from the Fyers API.
        """
        try:
            data = {"id": order_id}
            print(data)
            response = await FyersWrapper.fyers.cancel_order(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to cancel order (async): {e}")

    @staticmethod
    def cancel_order_sync(order_id: str):
        """
        Cancel an existing order synchronously.

        :param order_id: Order ID to be canceled.
        :return: Response from the Fyers API.
        """
        try:
            data = {"id": order_id}
            response = FyersWrapper.fyers.cancel_order(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to cancel order (sync): {e}")

    @staticmethod
    async def cancel_order(order_id: str):
        """
        Dynamically cancel an existing order based on the mode (sync/async).

        :param order_id: Order ID to be canceled.
        :return: Response from the Fyers API.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.cancel_order_async(order_id)
        else:
            return FyersWrapper.cancel_order_async(order_id)

    @staticmethod
    async def exit_positions_async(data: dict):
        """
        Exit positions using Fyers API in async mode.

        :param data: Parameters for exiting positions (segment, side, productType, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = await FyersWrapper.fyers.exit_positions(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to exit positions (async): {e}")

    @staticmethod
    def exit_positions_sync(data: dict):
        """
        Exit positions using Fyers API in sync mode.

        :param data: Parameters for exiting positions (segment, side, productType, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = FyersWrapper.fyers.exit_positions(data=data)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to exit positions (sync): {e}")

    @staticmethod
    async def exit_positions(data: dict):
        """
        Common method to exit positions dynamically based on the mode (sync/async).

        :param data: Parameters for exiting positions (segment, side, productType, etc.).
        :return: Response from the Fyers API.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.exit_positions_async(data)
        else:
            return FyersWrapper.exit_positions_sync(data)

    @staticmethod
    async def get_positions_async():
        """
        Fetch the positions asynchronously.

        :return: The response JSON contains positions data.
        """
        try:
            response = await FyersWrapper.fyers.positions()
            if response.get("code") != 200 or response.get("s") != "ok":
                raise RuntimeError(f"Error fetching positions: {response.get('message', 'Unknown error')}")
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions (async): {e}")

    @staticmethod
    def get_positions_sync():
        """
        Fetch the positions synchronously.

        :return: The response JSON contains positions data.
        """
        try:
            response = FyersWrapper.fyers.positions()
            if response.get("code") != 200 or response.get("s") != "ok":
                raise RuntimeError(f"Error fetching positions: {response.get('message', 'Unknown error')}")
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions (sync): {e}")

    @staticmethod
    async def get_positions():
        """
        Dynamically fetch positions based on the mode (sync/async).

        :return: The response JSON contains positions data.
        """
        if FyersWrapper.is_async:
            return await FyersWrapper.get_positions_async()

        else:
            return FyersWrapper.get_positions_sync()

    @staticmethod
    def authenticate(url, mobile_number, password_2fa, totp_secret_key):
        """
        Automate Fyers login using SeleniumBase, entering mobile, password, TOTP, and extracting auth code.
        """
        headless = True
        MAX_RETRIES = 3
        Display(visible=0, size=(1024, 768)).start()
        from selenium.webdriver.common.by import By
        import pyotp
        from urllib.parse import urlparse, parse_qs

        with SB(uc=True, test=True, save_screenshot=True) as sb:
            for attempt in range(MAX_RETRIES):
                try:
                    sb.uc_open_with_reconnect(url, 20)
                    sb.wait_for_ready_state_complete(20)
                    sb.wait_for_text("Let's begin!", timeout=15)
                    sb.sleep(2)
                    sb.uc_gui_handle_captcha()
                    sb.save_screenshot("fyers_auth_after_captcha.png")
                    sb.sleep(3)
                    sb.save_screenshot("fyers_auth_new.png")
                    sb.sleep(20)

                    if sb.is_element_enabled("#mobileNumberSubmit"):
                        sb.wait_for_element_visible("#mobile-code", timeout=10)
                        sb.type("#mobile-code", mobile_number)
                        sb.wait_for_element_visible("#mobileNumberSubmit", timeout=10)
                        sb.click("#mobileNumberSubmit")
                    else:
                        raise Exception("Mobile submit button is disabled.")

                    sb.wait_for_ready_state_complete(20)

                    # TOTP
                    for _ in range(MAX_RETRIES):
                        sb.sleep(0.2)
                        totp_ids = ["first", "second", "third", "fourth", "fifth", "sixth"]
                        totp = pyotp.TOTP(totp_secret_key).now()
                        for i, digit in enumerate(totp):
                            pin_input = sb.find_element(By.ID, totp_ids[i])
                            pin_input.send_keys(digit)
                            sb.sleep(0.2)
                        sb.click("#confirmOtpSubmit")
                        sb.sleep(2)
                        if sb.is_text_visible("Please enter the valid TOTP"):
                            continue
                        break
                    else:
                        return None

                    sb.wait_for_ready_state_complete(15)
                    # 2FA password
                    for i, digit in enumerate(password_2fa):
                        pin_input_xpath = f"//input[contains(@class, 'fy-secure-input')][{i + 1}]"
                        pin_input = sb.find_element(By.XPATH, pin_input_xpath)
                        pin_input.send_keys(digit)
                        sb.sleep(0.5)
                    sb.click("#verifyPinSubmit")
                    sb.sleep(2)

                    redirected_url = sb.get_current_url()
                    auth_code = parse_qs(urlparse(redirected_url).query).get("auth_code", [None])[0]
                    if auth_code:
                        return auth_code
                except Exception as e:
                    sb.disconnect()
                    sb.sleep(2)
        return None


# Assuming from_date and to_date are in 'YYYY-MM-DD HH:MM:SS' format or datetime objects
def convert_to_epoch(date_value):
    """Convert a datetime or string date to epoch timestamp."""
    if isinstance(date_value, str):
        date_value = datetime.strptime(date_value, "%d/%m/%Y %H:%M:%S")  # Adjust the format if needed
    return int(date_value.timestamp())  # Convert to epoch (seconds)
