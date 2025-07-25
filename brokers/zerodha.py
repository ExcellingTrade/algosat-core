"""Zerodha broker implementation.

This is a placeholder implementation that follows the BrokerInterface.
"""
import asyncio
from typing import Dict, Any, List
import re
from datetime import datetime
from algosat.brokers.base import BrokerInterface
from algosat.brokers.models import BalanceSummary
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials, can_reuse_token
from algosat.common.logger import get_logger
from kiteconnect import KiteConnect, exceptions as kite_exceptions
import pyotp
from selenium.webdriver.common.by import By
from seleniumbase import SB
from pyvirtualdisplay import Display
from urllib.parse import urlparse, parse_qs
from algosat.core.time_utils import get_ist_datetime
import pandas as pd
import datetime
from algosat.core.order_request import OrderRequest, Side, OrderType

logger = get_logger("zerodha_wrapper")

class ZerodhaWrapper(BrokerInterface):

   
    """
    Async wrapper for Zerodha's Kite Connect API.
    This is a placeholder implementation.
    """
    def __init__(self, broker_name: str = "zerodha"):
        self.broker_name = broker_name
        self.kite = None
        self.access_token = None
        
    async def login(self, force_reauth: bool = False) -> bool:
        """
        Authenticate with Zerodha's Kite Connect API using stored credentials and TOTP.
        If force_reauth is True, always perform a fresh authentication (ignore existing token).
        Returns:
            bool: True if authentication was successful, False otherwise
        """
        try:
            full_config = await get_broker_credentials(self.broker_name)
            credentials = None
            if isinstance(full_config, dict):
                credentials = full_config.get("credentials")
            if not credentials or not isinstance(credentials, dict):
                logger.error("No Zerodha credentials found in database or credentials are invalid")
                return False

            access_token = credentials.get("access_token")
            generated_on_str = credentials.get("generated_on")
            api_key = credentials.get("api_key")
            api_secret = credentials.get("api_secret")
            user_id = credentials.get("user_id")
            password = credentials.get("password")
            totp_secret = credentials.get("totp_secret")
            # totp_secret = "DDEULTWO73Q65KT7AO3SQQM5Y24BLZ7K"

            # Only reuse token if not forcing reauth
            if not force_reauth and access_token and generated_on_str and can_reuse_token(generated_on_str):
                try:
                    self.kite = KiteConnect(api_key=api_key)
                    self.kite.set_access_token(access_token)
                    self.access_token = access_token
                    logger.debug("Reusing existing Zerodha access token.")
                    return True
                except Exception as e:
                    logger.warning(f"Token reuse check failed: {e}, will generate new token")

            # Start headless display for Selenium
            Display(visible=0, size=(1024, 768)).start()
            kite = KiteConnect(api_key=api_key)
            login_url = kite.login_url()
            with SB(uc=True, test=True, save_screenshot=True) as sb:
                try:
                    sb.uc_open_with_reconnect(login_url, 20)
                    sb.wait_for_ready_state_complete(20)
                    sb.wait_for_element_visible("#userid", timeout=10)
                    sb.type("#userid", user_id)
                    sb.type("#password", password)
                    sb.save_screenshot("zerodha_login.png")
                    sb.click('button[type="submit"]', timeout=20) 
                    sb.wait_for_element_visible("#userid", timeout=10)
                    sb.save_screenshot("zerodha_totp_1.png")
                    # Generate TOTP
                    totp = pyotp.TOTP(totp_secret).now()
                    sb.type("#userid", totp)
                    sb.save_screenshot("zerodha_totp.png")
                    # Allow time for auto-redirect after OTP
                    sb.sleep(2)
                    current_url = sb.get_current_url()
                    # If the URL already contains the one-time request_token, no click needed
                    if "request_token=" in current_url:
                        redirected_url = current_url
                    else:
                        # Otherwise click the submit button to proceed
                        sb.click('button[type="submit"]', timeout=20)
                        sb.sleep(2)
                        redirected_url = sb.get_current_url()
                except Exception as e:
                    logger.error(f"Zerodha authentication failed in Selenium: {e}")
                    return False
            # Parse out the request_token from the redirect URL
            parsed = urlparse(redirected_url)
            request_token = parse_qs(parsed.query).get("request_token", [None])[0]
            if not request_token:
                logger.error("Failed to obtain request_token from login flow.")
                return False
            try:
                data = kite.generate_session(request_token, api_secret=api_secret)
                access_token = data["access_token"]
                credentials["access_token"] = access_token
                credentials["generated_on"] = get_ist_datetime().strftime("%d/%m/%Y %H:%M:%S")
                full_config["credentials"] = credentials
                await upsert_broker_credentials(self.broker_name, full_config)
                self.kite = kite
                self.kite.set_access_token(access_token)
                self.access_token = access_token
                logger.debug("Successfully authenticated and stored new Zerodha access token.")
                return True
            except Exception as e:
                logger.error(f"Failed to generate Zerodha session: {e}")
                return False
        except Exception as e:
            logger.error(f"Zerodha authentication failed: {e}", exc_info=True)
            return False
        
    async def get_order_history(self, order_id) -> Dict[str, Any]:
        """
        Fetch order history for a given order_id and return status info.
        """
        try:
            loop = asyncio.get_event_loop()
            orderdetails = await loop.run_in_executor(None, self.kite.order_history, order_id)
            # orderdetails = [{'account_id': 'HU6119', 'trade_id': '1449361', 'order_id': '250704600366295', 'exchange': 'NFO', 'tradingsymbol': 'NIFTY2571025500PE', 'instrument_token': 10252802, 'product': 'MIS', 'average_price': 210.45, 'quantity': 75, 'exchange_order_id': '1600000045390177', 'transaction_type': 'BUY', 'fill_timestamp': datetime.datetime(2025, 7, 4, 11, 41), 'order_timestamp': '11:41:00', 'exchange_timestamp': datetime.datetime(2025, 7, 4, 11, 41)}] # Placeholder for actual last order details
            # orderdetails = [{"account_id":"HU6119","placed_by":"HU6119","order_id":"250704600366295","exchange_order_id":"1600000045390177","parent_order_id":None,"status":"COMPLETE","status_message":None,"status_message_raw":None,"order_timestamp":"2025-07-04 11:41:00","exchange_update_timestamp":"2025-07-04 11:41:00","exchange_timestamp":"2025-07-04 11:41:00","variety":"regular","modified":False,"exchange":"NFO","tradingsymbol":"NIFTY2571025500PE","instrument_token":10252802,"order_type":"LIMIT","transaction_type":"BUY","validity":"DAY","validity_ttl":0,"product":"MIS","quantity":75,"disclosed_quantity":0,"price":210.5,"trigger_price":210.3,"average_price":210.45,"filled_quantity":75,"pending_quantity":0,"cancelled_quantity":0,"market_protection":0,"meta":{},"tag":"AlgoOrder","tags":["AlgoOrder"],"guid":"149993X60EiJhmOXkjB"}]
            if not orderdetails:
                return {"order_id": order_id, "status": "UNKNOWN", "message": "No order history found"}
            statuses = [d.get('status') for d in orderdetails]
            status_messages = [d.get('status_message') for d in orderdetails]
            status_messages_raw = [d.get('status_message_raw') for d in orderdetails]
            last = orderdetails[-1]
           
            return {
                "order_id": order_id,
                "status": last.get('status'),
                "message": last.get('status_message'),
                "product": last.get('product'),
                "quantity": last.get('quantity'),
                "filled_quantity": last.get('filled_quantity'),
                "average_price": last.get('average_price'),
                "product_type": last.get('product'),
                "order_type": last.get('order_type'),
                "message_raw": last.get('status_message_raw'),
                "statuses": statuses,
                "status_messages": status_messages,
                "status_messages_raw": status_messages_raw,
                "raw": orderdetails
            }
        except Exception as e:
            logger.error(f"Failed to fetch order history for {order_id}: {e}")
            return {"order_id": order_id, "status": "ERROR", "message": str(e)}

    async def place_order(self, order_request: OrderRequest) -> dict:
        """
        Place an order with Zerodha using a generic OrderRequest object.
        Returns a standard OrderResponse with only order_id and order_message.
        Order monitoring is responsible for all status/fill updates.
        """
        from algosat.core.order_request import OrderResponse, OrderStatus
        if not self.kite:
            logger.error("Kite client not initialized. Please login first.")
            return OrderResponse(
                status=OrderStatus.FAILED,
                order_id="",
                order_message="Kite client not initialized",
                broker="zerodha",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()
        kite_payload = order_request.to_zerodha_dict()
        kite_payload = {k: v for k, v in kite_payload.items() if v is not None}
        logger.info(f"Placing Zerodha order with payload: {kite_payload}")
        try:
            loop = asyncio.get_event_loop()
            order_id = await loop.run_in_executor(
                None,
                lambda: self.kite.place_order(
                    tradingsymbol=kite_payload["tradingsymbol"],
                    exchange=kite_payload["exchange"],
                    transaction_type=kite_payload["transaction_type"],
                    quantity=kite_payload["quantity"],
                    order_type=kite_payload["order_type"],
                    price=  kite_payload.get("price"),
                    trigger_price= kite_payload.get("trigger_price"),
                    product=kite_payload["product"],
                    variety=kite_payload.get("variety", "regular"),
                    validity=kite_payload.get("validity", "DAY"),
                    tag=kite_payload.get("tag")
                )
            )
            # order_id = "250704600366295"  # Placeholder for actual order ID, ensure string type
            logger.info(f"Zerodha order placed, order_id: {order_id}")
            # Return only order_id and order_message, let monitor handle status/fills
            return OrderResponse(
                status=OrderStatus.AWAITING_ENTRY,
                order_id=str(order_id),
                order_message="Order submitted successfully.",
                broker="zerodha",
                raw_response={"order_id": order_id},
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()
        except Exception as e:
            logger.error(f"Zerodha order placement failed: {e}")
            return OrderResponse(
                status=OrderStatus.FAILED,
                order_id="",
                order_message=str(e),
                broker="zerodha",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()
        
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Retrieve current positions from Zerodha using the Kite Connect API.
        
        Returns:
            List of position dictionaries
        """
        try:
            if not self.kite:
                logger.error("Kite client not initialized. Please login first.")
                return [{"error": "Kite client not initialized"}]
            loop = asyncio.get_event_loop()
            try:
                positions = await loop.run_in_executor(None, self.kite.positions)
                return positions
            except kite_exceptions.PermissionException:
                logger.warning("Zerodha: PermissionException in get_positions, attempting reauth...")
                if await self.login(force_reauth=True):
                    positions = await loop.run_in_executor(None, self.kite.positions)
                else:
                    logger.error("Zerodha: Reauth failed in get_positions.")
                    return [{"error": "Reauth failed"}]
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha positions: {e}")
            return [{"error": str(e)}]
        
    async def get_history(self, symbol, from_date, to_date, ohlc_interval="5minute", ins_type=""):
        """
        Fetch historical market data for an option symbol using instrument_token.
        :param symbol: Option tradingsymbol (e.g., NIFTY24MAY22500CE)
        :param from_date: Start date (YYYY-MM-DD)
        :param to_date: End date (YYYY-MM-DD)
        :param ohlc_interval: Candle interval (int or str)
        :param ins_type: (ignored for Zerodha)
        :return: List of candle dicts
        """
        # Map integer and string intervals to Zerodha's string format
        interval_map = {
            1: "minute",
            3: "3minute",
            5: "5minute",
            10: "10minute",
            15: "15minute",
            30: "30minute",
            60: "60minute",
            "day": "day",
            "D": "day",
            "1D": "day"
        }
        interval = ohlc_interval
        if isinstance(ohlc_interval, int):
            interval = interval_map.get(ohlc_interval, "5minute")
        elif isinstance(ohlc_interval, str):
            interval = interval_map.get(ohlc_interval.strip().lower(), ohlc_interval)
        # fallback to '5minute' if not valid
        valid_intervals = set(interval_map.values())
        if interval not in valid_intervals:
            interval = "5minute"
        def get_token(kite, symbol):
            instruments = kite.instruments("NFO")
            for i in instruments:
                if i["tradingsymbol"] == symbol and i["segment"] == "NFO-OPT":
                    return i["instrument_token"]
            raise Exception(f"Token not found for {symbol}")
        loop = asyncio.get_event_loop()
        try:
            token = await loop.run_in_executor(None, get_token, self.kite, symbol)
            # Calculate interval in minutes for to_date adjustment
            interval_minutes_map = {
                "minute": 1, "3minute": 3, "5minute": 5, "10minute": 10, "15minute": 15, "30minute": 30, "60minute": 60, "day": 1440
            }
            interval_minutes = interval_minutes_map.get(interval, 5)
            # Format from_date and to_date as 'yyyy-mm-dd hh:mm:ss'
            from_dt = pd.to_datetime(from_date)
            to_dt = pd.to_datetime(to_date)
            # If from and to are the same, add interval_minutes to to_dt
            if from_dt == to_dt:
                to_dt = from_dt + pd.Timedelta(minutes=interval_minutes)
            from_date_fmt = from_dt.strftime("%Y-%m-%d %H:%M:%S")
            to_date_fmt = to_dt.strftime("%Y-%m-%d %H:%M:%S")
            logger.debug(f"Fetching historical data for {symbol} from {from_date_fmt} to {to_date_fmt} with interval {interval}")
            candles = await loop.run_in_executor(None, self.kite.historical_data, token, from_date_fmt, to_date_fmt, interval)
        except kite_exceptions.PermissionException:
            logger.warning("Zerodha: PermissionException in get_history, attempting reauth...")
            if await self.login(force_reauth=True):
                token = await loop.run_in_executor(None, get_token, self.kite, symbol)
                candles = await loop.run_in_executor(None, self.kite.historical_data, token, from_date_fmt, to_date_fmt, interval)
            else:
                logger.error("Zerodha: Reauth failed in get_history.")
                return []
       
        # Convert to DataFrame
        if candles and isinstance(candles, list):
            df = pd.DataFrame.from_dict(candles)
            # Add timestamp column from 'date' if present
            if not df.empty and 'date' in df.columns:
                df['timestamp'] = pd.to_datetime(df['date'])
                df.set_index(['date'], inplace=True)
                cols = ['open', 'low', 'close', 'high', 'volume']
                for col in cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
        return candles

    async def get_profile(self) -> Dict[str, Any]:
        """
        Retrieve user profile from Zerodha using the Kite Connect API.
        Returns:
            Dict containing profile data
        """
        try:
            if not self.kite:
                logger.error("Kite client not initialized. Please login first.")
                return {"error": "Kite client not initialized"}
            loop = asyncio.get_event_loop()
            try:
                profile = await loop.run_in_executor(None, self.kite.profile)
            except (kite_exceptions.PermissionException, kite_exceptions.TokenException):
                logger.warning("Zerodha: PermissionException or TokenException in get_profile, attempting reauth...")
                if await self.login(force_reauth=True):
                    profile = await loop.run_in_executor(None, self.kite.profile)
                else:
                    logger.error("Zerodha: Reauth failed in get_profile.")
                    return {"error": "Reauth failed"}
            return profile
        
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha profile: {e}")
            return {"error": str(e)}

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch a full quote for one or more symbols (comma-separated) via Kite Connect.
        Returns a dict with symbol as key and quote data as value.
        """
        loop = asyncio.get_event_loop()
        try:
            # Kite expects a list of symbols
            symbol_list = [s.strip() for s in symbol.split(",") if s.strip()]
            response = await loop.run_in_executor(None, self.kite.quote, symbol_list)
            # response: {symbol: { ... }}
            return response
        except kite_exceptions.PermissionException:
            logger.warning("Zerodha: PermissionException in get_quote, attempting reauth...")
            if await self.login(force_reauth=True):
                symbol_list = [s.strip() for s in symbol.split(",") if s.strip()]
                return await loop.run_in_executor(None, self.kite.quote, symbol_list)
            else:
                logger.error("Zerodha: Reauth failed in get_quote.")
                return {"error": "Reauth failed"}
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha quote: {e}")
            return {"error": str(e)}

    async def get_ltp(self, symbol: str) -> Dict[str, float]:
        """
        Fetch the last traded price for one or more symbols (comma-separated) via Kite Connect.
        Returns a dict with symbol as key and last price as value.
        """
        loop = asyncio.get_event_loop()
        try:
            symbol_list = [s.strip() for s in symbol.split(",") if s.strip()]
            response = await loop.run_in_executor(None, self.kite.ltp, symbol_list)
            # response: {symbol: { 'last_price': ... }}
            ltp_dict = {}
            for sym, val in response.items():
                ltp = val.get("last_price")
                if ltp is not None:
                    ltp_dict[sym] = ltp
            return ltp_dict
        except kite_exceptions.PermissionException:
            logger.warning("Zerodha: PermissionException in get_ltp, attempting reauth...")
            if await self.login(force_reauth=True):
                symbol_list = [s.strip() for s in symbol.split(",") if s.strip()]
                response = await loop.run_in_executor(None, self.kite.ltp, symbol_list)
                ltp_dict = {}
                for sym, val in response.items():
                    ltp = val.get("last_price")
                    if ltp is not None:
                        ltp_dict[sym] = ltp
                return ltp_dict
            else:
                logger.error("Zerodha: Reauth failed in get_ltp.")
                return {"error": "Reauth failed"}
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha ltp: {e}")
            return {"error": str(e)}
        
    async def get_order_details(self) -> list[dict]:
        """
        Fetch all order details for the current account/session from Zerodha.
        Returns a list of order dicts.
        """
        loop = asyncio.get_event_loop()
        try:
            orders = await loop.run_in_executor(None, self.kite.orders)
            # orders = [{"account_id":"HU6119","placed_by":"HU6119","order_id":"250704600366295","exchange_order_id":"1600000045390177","parent_order_id":None,"status":"COMPLETE","status_message":None,"status_message_raw":None,"order_timestamp":"2025-07-04 11:41:00","exchange_update_timestamp":"2025-07-04 11:41:00","exchange_timestamp":"2025-07-04 11:41:00","variety":"regular","modified":False,"exchange":"NFO","tradingsymbol":"NIFTY2571025500PE","instrument_token":10252802,"order_type":"LIMIT","transaction_type":"BUY","validity":"DAY","validity_ttl":0,"product":"MIS","quantity":75,"disclosed_quantity":0,"price":210.5,"trigger_price":210.3,"average_price":210.45,"filled_quantity":75,"pending_quantity":0,"cancelled_quantity":0,"market_protection":0,"meta":{},"tag":"AlgoOrder","tags":["AlgoOrder"],"guid":"149993X60EiJhmOXkjB"}]
            if isinstance(orders, list):
                return orders
                
            return []
        except Exception as e:
            logger.error(f"Error fetching Zerodha order details: {e}")
            return []

    async def get_strike_list(self, symbol: str, max_strikes: int) -> list:
        """
        Return a list of tradingsymbols for CE and PE strikes:
        1 ATM CE, 1 ATM PE, max_strikes ITM CE, max_strikes OTM CE, max_strikes ITM PE, max_strikes OTM PE.
        Expiry is auto-detected: weekly for NIFTY, monthly for others.
        Total returned: 4*max_strikes + 2
        """
        # Placeholder: implement as per your logic or leave as empty list
        logger.warning("Zerodha get_strike_list is a placeholder. Not implemented.")
        return []

    async def get_balance(self, segment: str = "equity") -> dict:
        """
        Fetch account balance (raw API response) for Zerodha using margins API.
        """
        try:
            if not self.kite:
                logger.error("Kite client not initialized. Please login first.")
                return {}
            
            loop = asyncio.get_event_loop()
            try:
                margins_data = await loop.run_in_executor(None, self.kite.margins)
                return margins_data
            except (kite_exceptions.PermissionException, kite_exceptions.TokenException):
                logger.warning("Zerodha: PermissionException or TokenException in get_balance, attempting reauth...")
                if await self.login(force_reauth=True):
                    margins_data = await loop.run_in_executor(None, self.kite.margins)
                    return margins_data
                else:
                    logger.error("Zerodha: Reauth failed in get_balance.")
                    return {}
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha balance: {e}")
            return {}

    async def get_balance_summary(self, segment: str = "equity") -> BalanceSummary:
        """
        Return summary: total_balance, available, utilized for equity from Zerodha margins API.
        
        Calculation:
        - available = net
        - utilized = utilised.debits  
        - total = available + utilized
        """
        try:
            raw = await self.get_balance(segment)
            if not raw or not isinstance(raw, dict):
                logger.error(f"Zerodha get_balance_summary: Invalid or failed response: {raw}")
                return BalanceSummary()
            
            # Extract equity segment data
            equity_data = raw.get("equity", {})
            if not equity_data:
                logger.error(f"Zerodha get_balance_summary: No equity data found in response: {raw}")
                return BalanceSummary()
            
            # Get values from equity segment
            net = float(equity_data.get("net", 0))
            utilised_data = equity_data.get("utilised", {})
            debits = float(utilised_data.get("debits", 0))
            
            # Calculate as per requirement
            available = net
            utilized = debits
            total = available + utilized
            
            return BalanceSummary(
                total_balance=total,
                available=available,
                utilized=utilized
            )
        except Exception as e:
            logger.error(f"Failed to summarize Zerodha balance: {e}")
            return BalanceSummary()

    async def get_trades(self, broker_order_id) -> int:
        """
        Fetch trades for a given broker_order_id and return the total filled quantity.
        """
        try:
            loop = asyncio.get_event_loop()
            trades = await loop.run_in_executor(None, self.kite.order_trades, broker_order_id)
            filled_qty = sum([t.get('quantity', 0) for t in trades if t.get('quantity')])
            return filled_qty
        except Exception as e:
            logger.error(f"Zerodha get_trades failed for order {broker_order_id}: {e}")
            return 0

    async def exit_order(self, broker_order_id, symbol=None, product_type=None, exit_reason=None, side=None):
        """
        Zerodha-specific exit logic: fetch filled qty from positions, compare to expected, and place opposite order if needed.
        Assumes symbol is already sanitized by BrokerManager.
        """
        try:
            # Symbol is already sanitized by BrokerManager; use as-is
            sanitized_symbol = symbol
            # Fetch current positions (net positions)
            positions = await self.get_positions()
            net_positions = positions.get('net', []) if isinstance(positions, dict) else positions
            # net_positions = [{'tradingsymbol': 'NIFTY2571025500PE', 'exchange': 'NFO', 'instrument_token': 10252802, 'product': 'MIS', 'quantity': 0, 'overnight_quantity': 0, 'multiplier': 1, 'average_price': 0, 'close_price': 0, 'last_price': 147.15, 'value': -4642.5, 'pnl': -4642.5, 'm2m': -4642.5, 'unrealised': -4642.5, 'realised': 0, 'buy_quantity': 75, 'buy_price': 210.45, 'buy_value': 15783.75, 'buy_m2m': 15783.75, 'sell_quantity': 75, 'sell_price': 148.55, 'sell_value': 11141.25, 'sell_m2m': 11141.25, 'day_buy_quantity': 75, 'day_buy_price': 210.45, 'day_buy_value': 15783.75, 'day_sell_quantity': 75, 'day_sell_price': 148.55, 'day_sell_value': 11141.25}]
            filled_qty = 0
            matched_position = None
            # Match by tradingsymbol (case-insensitive)
            for pos in net_positions:
                if str(pos.get('tradingsymbol', '')).upper() == str(sanitized_symbol).upper():
                    filled_qty = abs(pos.get('quantity', 0))  # Use abs in case of negative for shorts
                    matched_position = pos
                    break
            if filled_qty == 0:
                logger.warning(f"Zerodha exit_order: No filled quantity for symbol {sanitized_symbol} in positions, skipping exit.")
                return {"status": False, "message": "No filled quantity, cannot exit."}
            # Fetch original order details to get side, etc.
            # order_hist = await self.get_order_history(broker_order_id)
            # if not order_hist or not order_hist.get('raw'):
            #     logger.error(f"Zerodha exit_order: Could not fetch order history for {broker_order_id}")
            #     return {"status": False, "message": "Order history not found."}
            # orig_order = order_hist['raw'][-1] if isinstance(order_hist['raw'], list) else order_hist['raw']
            # orig_side = orig_order.get('transaction_type') or orig_order.get('side')
            orig_product = matched_position.get('product', product_type)
            # Determine exit side (opposite of original)
            exit_side = 'SELL' if side == 'BUY' else 'BUY'
            # Build exit order request
            exit_order_req = OrderRequest(
                symbol=sanitized_symbol,
                side=exit_side,
                order_type=OrderType.MARKET,
                product_type= orig_product,
                quantity=filled_qty
            )
            logger.info(f"Zerodha exit_order: Preparing exit order for {broker_order_id} with side={exit_side}, qty={filled_qty}, symbol={sanitized_symbol}, product_type={orig_product}, reason={exit_reason}")
            logger.info(f"Zerodha exit_order: Placing exit order for {broker_order_id} with side={exit_side}, qty={filled_qty}, symbol={sanitized_symbol}, product_type={orig_product}, reason={exit_reason}")
            result = await self.place_order(exit_order_req)
            return result
        except Exception as e:
            logger.error(f"Zerodha exit_order failed for order {broker_order_id}: {e}")
            return {"status": False, "message": str(e)}

    async def cancel_order(self, broker_order_id, symbol=None, product_type=None, variety="regular", **kwargs):
        """
        Cancel a Zerodha order using the Kite Connect API. Requires variety and order_id.
        """
        try:
            logger.info(f"Zerodha cancel_order: Cancelling order with id={broker_order_id}, variety={variety}")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self.kite.cancel_order, variety, broker_order_id)
            return {"status": True, "message": "Order cancelled", "result": result}
        except Exception as e:
            logger.error(f"Zerodha cancel_order failed for order {broker_order_id}: {e}")
            return {"status": False, "message": str(e)}
        
    async def get_order_margin(self, *order_params_list):
        """
        Call self.kite.order_margins with the given order params (list of dicts).
        Returns the list of margin dicts as returned by KiteConnect.
        """
        try:
            if not self.kite:
                logger.error("Kite client not initialized. Please login first.")
                return []
            # Kite expects a list of order dicts
            loop = asyncio.get_event_loop()
            margin_result = await loop.run_in_executor(None, self.kite.order_margins, list(order_params_list))
            return margin_result
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha order margin: {e}")
            return []

    async def check_margin_availability(self, *order_params_list):
        """
        Check if sufficient margin is available before placing the trade.
        Accepts one or more OrderRequest objects or dicts, converts OrderRequest to dict using to_zerodha_dict.
        :param order_params_list: One or more OrderRequest objects or dicts
        :return: True if sufficient margin is available, otherwise False
        """
        try:
            # Convert OrderRequest objects to dicts using to_zerodha_dict
            converted_params = []
            for param in order_params_list:
                if hasattr(param, 'to_zerodha_dict'):
                    d = param.to_zerodha_dict()
                    d = {k: v for k, v in d.items() if v is not None}
                    converted_params.append(d)
                elif isinstance(param, dict):
                    converted_params.append(param)
                else:
                    logger.error(f"Zerodha check_margin_availability: Invalid order param type: {type(param)}")
                    return False

            if not converted_params:
                logger.error("Zerodha check_margin_availability: No valid order params provided.")
                return False

            margin_result = await self.get_order_margin(*converted_params)
            if not margin_result or not isinstance(margin_result, list):
                logger.error(f"Zerodha check_margin_availability: Invalid margin result: {margin_result}")
                return False
            total_required = sum(float(m.get('total', 0)) for m in margin_result)
            logger.debug(f"Zerodha margin required for order(s): {total_required}")

            # Get available balance (net) from get_balance
            balance = await self.get_balance()
            equity_data = balance.get("equity", {})
            net_available = float(equity_data.get("net", 0))
            logger.debug(f"Zerodha available net balance: {net_available}")

            logger.info(f"Margin Check: Required (Zerodha): {total_required}, Available: {net_available}, Orders: {[o.get('tradingsymbol') for o in converted_params]}")
            return total_required <= net_available
        except Exception as error:
            logger.error(f"Error checking Zerodha margin: {error}")
            return False