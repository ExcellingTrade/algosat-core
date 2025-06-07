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

import pandas as pd
from algosat.common import constants
from algosat.core.order_request import OrderRequest, OrderResponse, OrderStatus
from typing import Any, Optional, Dict, List, Union

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
    "BO": "4",
    "MTF": "MTF",
}



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
        loop = asyncio.get_running_loop()
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

    async def login(self, force_reauth: bool = False) -> bool:
        """
        Authenticate with Fyers API using stored credentials.
        If force_reauth is True, always perform a fresh authentication (ignore existing token).
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
            api_key = fyers_creds.get("api_key")
            api_secret = fyers_creds.get("api_secret")
            redirect_uri = fyers_creds.get("redirect_uri")
            mobile_number = fyers_creds.get("client_id") # Updated to use client_id 
            password_2fa = fyers_creds.get("pin") # Updated to use pin instead of password_2fa
            totp_secret = fyers_creds.get("totp_secret")
            # Only reuse token if not forcing reauth and token is still valid
            if not force_reauth and access_token and generated_on_str and can_reuse_token(generated_on_str):
                try:
                    self.token = access_token
                    self.appId = api_key
                    self.fyers = fyersModel.FyersModel(
                        client_id=api_key,
                        is_async=self.is_async,
                        token=access_token,
                        log_path=constants.FYER_LOG_DIR
                    )
                    logger.debug("Reusing existing Fyers access token (generated today after 6AM or before 6AM and still before 6AM)")
                    return True
                except Exception as e:
                    logger.warning(f"Token reuse check failed: {e}, will generate new token")
            # Need to reauthenticate: get auth_code using authenticate(), then generate access_token
            logger.debug("Obtaining new Fyers access token via authentication flow")
            # Step 1: Get auth_code using authenticate()
            session = fyersModel.SessionModel(
                client_id=api_key,
                secret_key=api_secret,
                redirect_uri=redirect_uri,
                response_type="code",
                grant_type="authorization_code",
            )
            auth_url = session.generate_authcode()
            auth_code = self.authenticate(auth_url, mobile_number, password_2fa, totp_secret)
            if not auth_code:
                logger.error("Failed to obtain auth_code from Fyers authentication flow.")
                return False
            # Step 2: Exchange auth_code for access_token
            session.set_token(auth_code)
            response = session.generate_token()
            # credentials["access_token"] = response["access_token"]
        #   credentials["generated_on"] = get_ist_datetime().strftime("%d/%m/%Y %H:%M:%S")
            # Save new token and update DB
            fyers_creds["access_token"] = response["access_token"]
            fyers_creds["generated_on"] = get_ist_datetime().strftime("%d/%m/%Y %H:%M:%S")
            full_config["credentials"] = fyers_creds
            await upsert_broker_credentials("fyers", full_config)
            # Initialize fyersModel with new token
            self.token = access_token
            self.appId = api_key
            self.fyers = fyersModel.FyersModel(
                client_id=api_key,
                is_async=self.is_async,
                token=access_token,
                log_path=constants.FYER_LOG_DIR
            )
            logger.debug("Successfully authenticated and stored new Fyers access token.")
            return True
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
        # Only async path is supported
        return await self._setup_auth_async()

    async def _setup_auth_async(self):
        """
        Authenticate asynchronously using async DB and Fyers API logic.
        """
        full_config = await get_broker_credentials("fyers")
        credentials = full_config.get("credentials", {})
        access_token = credentials.get("access_token")
        self.token = access_token
        self.appId = credentials.get("api_key")
        from fyers_apiv3 import fyersModel
        from algosat.common import constants
        self.fyers = fyersModel.FyersModel(
            client_id=credentials.get("api_key"),
            is_async=True,
            token=access_token,
            log_path=constants.FYER_LOG_DIR
        )
        return True

    async def get_balance_async(self):
        """Fetch account balance asynchronously."""
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, self.fyers.funds)
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
        """
        Fetch account balance (raw API response).
        """
        if self.is_async:
            return await self.get_balance_async()
        else:
            return self.get_balance_sync()

    async def get_balance_summary(self) -> dict:
        """
        Return summary: total_balance, available, utilized for equity from Fyers funds API.
        """
        try:
            raw = await self.get_balance()
            # If get_balance() returns a coroutine, await it again (defensive, but should not happen)
            if asyncio.iscoroutine(raw):
                raw = await raw
            if not raw or not isinstance(raw, dict) or raw.get("code") != 200:
                logger.error(f"Fyers get_balance_summary: Invalid or failed response: {raw}")
                return {}
            fund_limit = raw.get("fund_limit", [])
            total = available = utilized = 0
            for item in fund_limit:
                if item.get("title", "").lower() == "total balance":
                    total = item.get("equityAmount", 0)
                if item.get("title", "").lower() == "available balance":
                    available = item.get("equityAmount", 0)
                if item.get("title", "").lower() == "utilized amount":
                    utilized = item.get("equityAmount", 0)
            return {
                "total_balance": total,
                "available": available,
                "utilized": utilized
            }
        except Exception as e:
            logger.error(f"Failed to summarize Fyers balance: {e}")
            return {}
    async def get_profile_async(self):
        """Fetch account profile asynchronously using Fyers async SDK."""
        try:
            result = self.fyers.get_profile()
            if asyncio.iscoroutine(result):
                response = await result
            else:
                response = result
            return response
        except Exception as e:
            logger.error(f"Failed to fetch profile asynchronously: {e}")
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
            # Always use async method and await it
            profile_data = await self.get_profile_async()
            # Check for authentication error and reauthenticate if needed
            if (
                profile_data
                and isinstance(profile_data, dict)
                and profile_data.get("message")
                and "Could not authenticate the user" in profile_data.get("message")
            ):
                logger.warning("Fyers profile fetch failed due to authentication. Reauthenticating...")
                await self.login(force_reauth=True)
                profile_data = await self.get_profile_async()  # Retry once after reauth
                if (
                    not profile_data
                    or not isinstance(profile_data, dict)
                    or profile_data.get("message") and "Could not authenticate the user" in profile_data.get("message")
                ):
                    logger.error("Fyers reauthentication failed. Could not fetch profile after retry.")
                    return {}
            if profile_data and isinstance(profile_data, dict) and profile_data.get("code") == 200 and profile_data.get("s") == "ok":
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
            result = self.fyers.optionchain(data)
            if asyncio.iscoroutine(result):
                response = await result
            else:
                response = result
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
        # Always await the async method and return the result
        return await self.get_option_chain_async(symbol, strike_count)

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

            result = self.fyers.history(params)
            if asyncio.iscoroutine(result):
                response = await result
            else:
                response = result

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
                error_message = response.get("message", "Unknown error") if isinstance(response, dict) else str(response)
                logger.debug(f"Failed to fetch history for {formatted_symbol}: {error_message}")
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

    def place_order_sync(self, order_payload: dict) -> Any:
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

    async def place_order(self, order_request: OrderRequest) -> dict:
        """
        Place an order with Fyers using a generic OrderRequest object.
        Fetch order details after placement and return a standard OrderResponse.
        """
        fyers_payload = order_request.to_fyers_dict()
        fyers_payload = {k: v for k, v in fyers_payload.items() if v is not None}
        print(fyers_payload)
        from algosat.core.order_request import OrderResponse, OrderStatus
        try:
            if self.is_async:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, self.fyers.place_order, fyers_payload)
                if asyncio.iscoroutine(response):
                    response = await response
            else:
                response = self.fyers.place_order(fyers_payload)
            logger.info(f"Fyers order placed: {response}")
            # Try to extract order_id from response
            order_id = None
            if isinstance(response, dict):
                order_id = response.get("id") or response.get("order_id") or response.get("data", {}).get("id")
            order_details = None
            if order_id:
                # Fetch order details from orderbook
                try:
                    orderbook_resp = await self.get_order_details(order_id)
                    # Fyers returns {"orderBook": [ ... ]}
                    if orderbook_resp and isinstance(orderbook_resp, dict) and "orderBook" in orderbook_resp:
                        # Find the order with this id
                        for o in orderbook_resp["orderBook"]:
                            if str(o.get("id")) == str(order_id):
                                order_details = o
                                break
                except Exception as e:
                    logger.warning(f"Fyers: Could not fetch orderbook for order_id {order_id}: {e}")
            return OrderResponse.from_fyers(order_details or response, order_request=order_request).dict()
        except Exception as e:
            logger.error(f"Fyers order placement failed: {e}")
            return OrderResponse(
                status=OrderStatus.FAILED,
                order_ids=[],
                order_messages={"error": str(e)},
                broker="fyers",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()

    async def place_order_async(self, order_payload: dict) -> Any:
        """
        Place an order in async mode.

        :param order_params: Parameters for the order (symbol, qty, type, etc.).
        :return: Response from the Fyers API.
        """
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, self.fyers.place_order, order_payload)
            # logger.debug(response)
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to place order (async): {e}")

    async def split_and_place_order(self, total_qty: int, max_nse_qty: int, trigger_price_diff: float, **order_params) -> List[Any]:
        """
        Split the order into chunks if the quantity exceeds max_nse_qty.

        :param total_qty: Total quantity to be ordered.
        :param max_nse_qty: Maximum quantity allowed per order.
        :param order_params: Parameters for the order.
        :param trigger_price_diff: Trigger_price_diff
        :return: List of responses for each placed order.

        """
        responses: List[Any] = []
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
            response = await self.place_order_async(order_params)
            responses.append(response)
            total_qty -= qty
        return responses

    async def place_split_orders_with_sl_tp(
        self,
        total_qty: int,
        max_nse_qty: int,
        stop_loss_price: float,
        target_price: float,
        trigger_price_diff: float,
        **order_params
    ) -> Dict[str, List[Any]]:
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
        entry_responses: List[Any] = []
        sl_responses: List[Any] = []
        target_responses: List[Any] = []

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
                entry_response = await self.place_order_async(order_params)
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
                        sl_response = await self.place_order_async(sl_order)
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
                        target_response = await self.place_order_async(target_order)
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
            except Exception as e:
                logger.error(f"Error placing entry order: {e}")

            # Reduce the remaining quantity
            total_qty -= qty

        return {
            "entry_responses": entry_responses,
            "sl_responses": sl_responses,
            "target_responses": target_responses
        }

    async def get_ltp(self, symbol: str) -> dict:
        """
        Fetch last traded price (LTP) for one or more symbols (comma-separated) from Fyers API.
        Returns a dict with symbol as key and last price as value.
        """
        quotes = await self.get_quote(symbol)
        ltp_dict = {}
        for sym, val in quotes.items():
            ltp = val.get("lp")
            if ltp is not None:
                ltp_dict[sym] = ltp
        return ltp_dict

    async def get_quote(self, symbol: str) -> dict:
        """
        Fetch quotes for one or more symbols (comma-separated) from Fyers API.
        Returns a dict with symbol as key and quote data as value.
        """
        loop = asyncio.get_event_loop()
        try:
            # Fyers expects a dict: {"symbols": symbol}
            data = {"symbols": symbol}
            response = await loop.run_in_executor(None, self.fyers.quotes, data)
            if asyncio.iscoroutine(response):
                response = await response
            if not response or response.get("code") != 200 or response.get("s") != "ok":
                logger.error(f"Fyers get_quote failed: {response}")
                return {}
            quotes = {}
            for item in response.get("d", []):
                sym = item.get("n")
                val = item.get("v", {})
                quotes[sym] = val
            return quotes
        except Exception as e:
            logger.error(f"Fyers get_quote exception: {e}")
            return {}

    async def get_order_details_async(self, order_id=None):
        """
        Fetch order details asynchronously.
        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        try:
            loop = asyncio.get_running_loop()
            if not order_id:
                response = await loop.run_in_executor(None, self.fyers.orderbook)
            else:
                response = await loop.run_in_executor(None, self.fyers.orderbook, {"id": order_id})
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch order details (async): {e}")

    def get_order_details_sync(self, order_id=None):
        """
        Fetch order details synchronously.

        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        try:
            if not order_id:
                response = self.fyers.orderbook()
            else:
                response = self.fyers.orderbook(data={"id": order_id})
            return response
        except Exception as e:
            raise RuntimeError(f"Failed to fetch order details (sync): {e}")

    async def get_order_details(self, order_id=None):
        """
        Dynamically fetch order details based on the mode (sync/async).

        :param order_id: List of order IDs. If None, fetch the full order book.
        :return: Response from the Fyers API.
        """
        if self.is_async:
            return await self.get_order_details_async(order_id)
        else:
            return self.get_order_details_sync(order_id)

    async def get_strike_list(self, symbol, max_strikes=40):
        """
        Fetch the list of option strike symbols for the given symbol using the option chain API.
        Returns a list of strike symbols (filtered for calls and puts, excluding INDEX).
        """
        option_chain_response = await self.get_option_chain(symbol, max_strikes)
        if (
            not option_chain_response
            or not option_chain_response.get('data')
            or not option_chain_response['data'].get('optionsChain')
        ):
            return []
        option_chain_df = pd.DataFrame(option_chain_response['data']['optionsChain'])
        strike_symbols = option_chain_df[constants.COLUMN_SYMBOL].unique()
        strike_symbols = [
            s for s in strike_symbols
            if (s.endswith(constants.OPTION_TYPE_CALL) or s.endswith(constants.OPTION_TYPE_PUT))
            and "INDEX" not in s
        ]
        return strike_symbols

    # ...existing code...

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
                    sb.save_screenshot("fyers_auth_before_captcha.png")
                    sb.wait_for_text("Let's begin!", timeout=15)
                    sb.uc_gui_handle_captcha()
                    sb.save_screenshot("fyers_auth_after_captcha.png")
                    sb.save_screenshot("fyers_auth_new.png")
                    sb.sleep(2)
                    # sb.sleep(20)

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
                    sb.sleep(1)

                    redirected_url = sb.get_current_url()
                    auth_code = parse_qs(urlparse(redirected_url).query).get("auth_code", [None])[0]
                    if auth_code:
                        return auth_code
                except Exception as e:
                    logger.error(f"Fyers authentication failed on attempt {attempt + 1}: {e}", exc_info=True)
                    sb.disconnect()
                    sb.sleep(1)
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

# Patch: KeyboardInterrupt-safe shutdown for asyncio event loop
import signal
import sys

def _handle_keyboard_interrupt(signum, frame):
    print("\n[INFO] KeyboardInterrupt received. Shutting down gracefully...")
    try:
        loop = asyncio.get_event_loop()
        loop.stop()
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, _handle_keyboard_interrupt)
