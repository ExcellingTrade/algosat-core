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

from algosat.brokers.base import BrokerInterface
from algosat.common import constants
from algosat.common.broker_utils import shutdown_gracefully, get_broker_credentials, upsert_broker_credentials, can_reuse_token
from algosat.common.logger import get_logger
from algosat.core.time_utils import get_ist_datetime, localize_to_ist
from pyvirtualdisplay import Display

# === Broker-specific API code mapping ===
# These mappings translate generic enums to Fyers API codes. Do not move these to order_defaults.py.
SIDE_MAP = {
    "BUY": 1,   # Fyers API: 1 for BUY
    "SELL": -1, # Fyers API: -1 for SELL
}

ORDER_TYPE_MAP = {
    "LIMIT": 1,   # Fyers API: 1 = Limit Order
    "MARKET": 2,  # Fyers API: 2 = Market Order
    "SL": 3,      # Fyers API: 3 = Stop Order (SL-M)
    # Add more mappings as needed
}

PRODUCT_TYPE_MAP = {
    "CNC": "CNC",
    "INTRADAY": "INTRADAY",
    "MARGIN": "MARGIN",
    "CO": "CO",
    "BO": "BO",
    "MTF": "MTF",
}

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

    def __init__(self):
        self.fyers = None
        self.is_async = True  # Default to asynchronous mode
        self.token = None
        self.appId = None

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

    async def login(self):
        """
        Authenticate with Fyers API using stored credentials.
        This method conforms to the BrokerInterface.
        Returns:
            bool: True if authentication was successful, False otherwise
        """
        try:
            full_config = await get_broker_credentials("fyers")
            credentials = None
            if isinstance(full_config, dict):
                credentials = full_config.get("credentials")
            if not credentials or not isinstance(credentials, dict):
                logger.error("No Fyers credentials found in database or credentials are invalid")
                return False
            fyers_creds = credentials
            access_token = fyers_creds.get("access_token")
            generated_on_str = fyers_creds.get("generated_on")
            if access_token and generated_on_str and can_reuse_token(generated_on_str):
                try:
                    self.token = access_token
                    self.appId = fyers_creds.get("api_key")
                    self.fyers = fyersModel.FyersModel(
                        client_id=fyers_creds.get("api_key"),
                        is_async=self.is_async,
                        token=access_token,
                        log_path=constants.FYER_LOG_DIR
                    )
                    logger.debug("Reusing existing Fyers access token (generated today after 6AM or before 6AM and still before 6AM)")
                    return True
                except Exception as e:
                    logger.warning(f"Token reuse check failed: {e}, will generate new token")
            logger.debug("Obtaining new Fyers access token")
            result = await self.setup_auth()
            return result is not None
        except Exception as e:
            logger.error(f"Fyers authentication failed: {e}", exc_info=True)
            return False

    async def setup_auth(self, is_async=True):
        """
        Authenticate and initialize the Fyers API.
        By default, operates in async mode (is_async=True).
        Set is_async=False to use synchronous mode.
        """
        self.is_async = is_async
        if self.is_async:
            return await self._setup_auth_async()
        else:
            return self._setup_auth_sync()  # No `await` needed

    async def _setup_auth_async(self):
        """Authenticate asynchronously."""
        return self._setup_auth_sync()

    def _setup_auth_sync(self):
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
                self.fyers = fyersModel.FyersModel(
                    token=credentials["access_token"],
                    is_async=self.is_async,
                    client_id=credentials["api_key"],
                    log_path=constants.FYER_LOG_DIR,
                )
                self.token = credentials["access_token"]
                self.appId = credentials["api_key"]
                logger.debug("Successfully authenticated using existing token.")
                return True
            except Exception as e:
                logger.exception("Token validation exception while checking reuse")

        # Perform re-authentication
        logger.debug("Generating a new access token.")
        session = fyersModel.SessionModel(
            client_id=credentials["api_key"],
            secret_key=credentials["api_secret"],
            redirect_uri=credentials["redirect_uri"],
            response_type="code",
            grant_type="authorization_code",
        )

        auth_url = session.generate_authcode()
        auth_code = self.authenticate(
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

        self.fyers = fyersModel.FyersModel(
            token=credentials["access_token"],
            is_async=self.is_async,
            client_id=credentials["api_key"],
            log_path=constants.FYER_LOG_DIR,
        )
        self.token = credentials["access_token"]
        self.appId = credentials["api_key"]
        logger.debug(f"Successfully authenticated with new token.")
        return True

    async def _wrap_async(callable_func, *args, **kwargs):
        """Wrapper for calling sync methods in async mode."""
        return await asyncio.to_thread(callable_func, *args, **kwargs)

    async def get_balance_async(self):
        """Fetch account balance asynchronously."""
        try:
            response = await self.fyers.funds()  # Ensure it's awaited here
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance asynchronously: {e}")
            return None

    def get_balance_sync(self):
        """Fetch account balance synchronously."""
        try:
            response = self.fyers.funds()
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance synchronously: {e}")
            return None

    async def get_balance(self):
        """Dynamic balance method based on is_async flag."""
        if self.is_async:
            return await self.get_balance_async()  # Return coroutine for await
        else:
            return self.get_balance_sync()

    async def get_profile_async(self):
        """Fetch account balance asynchronously."""
        try:
            response = await self.fyers.get_profile()  # Ensure it's awaited here
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance asynchronously: {e}")
            return None

    def get_profile_sync(self):
        """Fetch account balance synchronously."""
        try:
            response = self.fyers.get_profile()
            return response
        except Exception as e:
            logger.error(f"Failed to fetch balance synchronously: {e}")
            return None

    async def get_profile(self):
        """
        Get user profile information from the broker.
        This method implements the BrokerInterface.
        
        Returns:
            dict: Profile data or empty dict if unsuccessful
        """
        try:
            if not self.fyers:
                logger.error("Fyers client not initialized, please call login() first")
                return {}

            # Dispatch to sync or async based on mode
            if self.is_async:
                profile_data = await self.get_profile_async()
            else:
                profile_data = self.get_profile_sync()

            if profile_data and profile_data.get("code") == 200 and profile_data.get("s") == "ok":
                return profile_data.get("data", {})
            else:
                logger.error(f"Failed to get profile: {profile_data.get('message', 'Unknown error') if isinstance(profile_data, dict) else profile_data}")
                return {}
        except Exception as e:
            logger.error(f"Error getting profile: {e}", exc_info=True)
            return {}

    async def get_option_chain_async(self, symbol, strike_count):
        """Fetch the option chain asynchronously."""
        try:
            data = {
                "symbol": symbol,
                "strikecount": strike_count,
                "timestamp": "",
            }
            response = await self.fyers.optionchain(data)
            return response
        except Exception as e:
            logger.error(f"Failed to fetch option chain for {symbol}: {e}")
            return None

    def get_option_chain_sync(self, symbol, strike_count=20):
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
            logger.debug(f"Fetching option chain for {symbol} with strike count {strike_count}")

            # Call the sync method and get the response
            response = self.fyers.optionchain(data)

            # Validate response
            if response.get("code") != 200 or response.get("s") != "ok":
                logger.error(f"Error fetching option chain: {response.get('message', 'Unknown error')}")
                return None

            logger.debug("Successfully fetched option chain.")
            return response

        except Exception as e:
            logger.error(f"Failed to fetch option chain for {symbol}: {e}")
            return None

    async def get_option_chain(self, symbol, strike_count):
        """Fetch the option chain dynamically based on async/sync mode."""
        if self.is_async:
            return await self.get_option_chain_async(symbol, strike_count)
        else:
            return self.get_option_chain_sync(symbol, strike_count)

    async def get_history_async(self, symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data asynchronously.

        :param symbol: Trading symbol (e.g., "NSE:SBIN-EQ").
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: Interval for OHLC data (e.g., 1, 5, 15 min).
        :param ins_type: Instrument type (default is "EQ").
        :return: DataFrame containing OHLC data or None on failure.
        """
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
                f"Fetching async history for {formatted_symbol} from {from_date} to {to_date}... ")

            response = await self.fyers.history(params)

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

        return None

    def get_history_sync(self, symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data synchronously.

        :param symbol: Trading symbol (e.g., "NSE:SBIN-EQ").
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: Interval for OHLC data (e.g., 1, 5, 15 min).
        :param ins_type: Instrument type (default is "EQ").
        :return: DataFrame containing OHLC data or None on failure.
        """
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

            logger.debug(
                f"Fetching sync history for {symbol} from {from_date} to {to_date}... ")
            response = self.fyers.history(params)

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

                logger.debug(f"Successfully fetched sync historical data for {symbol}.")
                return df
            else:
                logger.warning(
                    f"Failed to fetch history for {symbol}: {response.get('message', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Exception while fetching sync history for {symbol}: {e}")

        return None

    async def get_history(self, symbol, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """
        Fetch historical OHLC data dynamically based on "is_async" flag.

        :param symbol: Trading symbol.
        :param from_date: Start timestamp (epoch seconds or date).
        :param to_date: End timestamp (epoch seconds or date).
        :param ohlc_interval: OHLC interval (e.g., 1 min, 5 min, or 'D' for day).
        :param ins_type: Instrument type.
        :return: DataFrame or None.
        """
        # Map int/str intervals to Fyers format
        interval_map = {
            1: "1", 2: "2", 3: "3", 5: "5", 10: "10", 15: "15", 20: "20", 30: "30", 60: "60",
            120: "120", 240: "240", "day": "D", "d": "D", "1d": "D", "D": "D", "1D": "D"
        }
        interval = ohlc_interval
        if isinstance(ohlc_interval, int):
            interval = interval_map.get(ohlc_interval, str(ohlc_interval))
        elif isinstance(ohlc_interval, str):
            interval = interval_map.get(ohlc_interval.strip().lower(), ohlc_interval)
        if self.is_async:
            return await self.get_history_async(symbol, from_date, to_date, interval, ins_type)
        else:
            return self.get_history_sync(symbol, from_date, to_date, interval, ins_type)

    async def place_order_async(self, order_payload: dict):
        """
        Place an order in async mode.

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = await self.fyers.place_order(order_payload)
            # logger.debug(response)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to place order (async): {e}")

    def place_order_sync(self, order_payload: dict):
        """
        Place an order in sync mode.

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        try:
            response = self.fyers.place_order(order_payload)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to place order (sync): {e}")

    async def place_order(self, order_request):
        """
        Place an order with Fyers using a generic OrderRequest object.
        """
        fyers_payload = order_request.to_fyers_dict()
        fyers_payload = {k: v for k, v in fyers_payload.items() if v is not None}
        try:
            response = await self.fyers.place_order(fyers_payload)
            logger.info(f"Fyers order placed: {response}")
            from algosat.core.order_request import OrderResponse
            return OrderResponse.from_fyers(response, order_request=order_request).dict()
        except Exception as e:
            logger.error(f"Fyers order placement failed: {e}")
            from algosat.core.order_request import OrderStatus, OrderResponse
            return OrderResponse(
                status=OrderStatus.FAILED,
                order_ids=[],
                order_messages={},
                broker="fyers",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()

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

    async def get_ltp(self, symbol):
        raise NotImplementedError("get_ltp is not implemented for FyersWrapper yet.")

    async def get_quote(self, symbol):
        raise NotImplementedError("get_quote is not implemented for FyersWrapper yet.")

    async def get_strike_list(self, symbol, max_strikes=40):
        """
        Fetch the list of option strike symbols for the given symbol using the option chain API.
        Returns a list of strike symbols (filtered for calls and puts, excluding INDEX).
        """
        option_chain_response = await self.get_option_chain(symbol, max_strikes)
        if not option_chain_response or not option_chain_response.get('data') or not option_chain_response['data'].get('optionsChain'):
            return []
        import pandas as pd
        from common import constants
        option_chain_df = pd.DataFrame(option_chain_response['data']['optionsChain'])
        strike_symbols = option_chain_df[constants.COLUMN_SYMBOL].unique()
        strike_symbols = [s for s in strike_symbols if (s.endswith(constants.OPTION_TYPE_CALL)
                                                        or s.endswith(constants.OPTION_TYPE_PUT)) and "INDEX" not in s]
        return strike_symbols

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

    async def get_positions_async(self):
        """
        Fetch the positions asynchronously.

        :return: The response JSON contains positions data.
        """
        try:
            response = await self.fyers.positions()
            if response.get("code") != 200 or response.get("s") != "ok":
                raise RuntimeError(f"Error fetching positions: {response.get('message', 'Unknown error')}")
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions (async): {e}")

    def get_positions_sync(self):
        """
        Fetch the positions synchronously.

        :return: The response JSON contains positions data.
        """
        try:
            response = self.fyers.positions()
            if response.get("code") != 200 or response.get("s") != "ok":
                raise RuntimeError(f"Error fetching positions: {response.get('message', 'Unknown error')}")
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch positions (sync): {e}")

    async def get_positions(self):
        """
        Dynamically fetch positions based on the mode (sync/async).

        :return: The response JSON contains positions data.
        """
        if self.is_async:
            return await self.get_positions_async()

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
    """
    Convert a datetime, or string in '%d/%m/%Y %H:%M:%S' format, to IST epoch timestamp (seconds).
    Always localizes to IST before conversion.

    :param date_value: Can be a datetime object or string date/time.
    :return: Epoch seconds (int) in IST.
    """
    if isinstance(date_value, str):
        date_value = datetime.strptime(date_value, "%d/%m/%Y %H:%M:%S")
    ist_aware_dt = localize_to_ist(date_value)
    return int(ist_aware_dt.timestamp())
