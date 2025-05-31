"""Zerodha broker implementation.

This is a placeholder implementation that follows the BrokerInterface.
"""
import asyncio
from typing import Dict, Any, List
import re
from datetime import datetime
from algosat.brokers.base import BrokerInterface
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials, can_reuse_token
from algosat.common.logger import get_logger
from kiteconnect import KiteConnect
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
        
    async def place_order(self, order_request: OrderRequest) -> Dict[str, Any]:
        """
        Place an order with Zerodha using a generic OrderRequest object.
        
        Args:
            order_request: The order details
            
        Returns:
            Dict containing order response
        """
        # Not implemented yet for new unified order flow
        raise NotImplementedError("Zerodha place_order is not yet implemented for the new OrderRequest flow.")
        # Old code below (commented out):
        # kite_payload = {
        #     "tradingsymbol": order_request.symbol,
        #     "exchange": order_request.exchange or "NFO",
        #     "transaction_type": order_request.side.value,  # "BUY" or "SELL"
        #     "quantity": order_request.quantity,
        #     "order_type": order_request.order_type.value,  # "MARKET", "LIMIT", etc.
        #     "product": order_request.product_type or "MIS",
        #     "variety": order_request.variety or "regular",
        #     "price": order_request.price,
        #     "trigger_price": order_request.trigger_price,
        #     "validity": order_request.validity or "DAY",
        #     "tag": order_request.tag,
        # }
        # kite_payload = {k: v for k, v in kite_payload.items() if v is not None}
        # try:
        #     loop = asyncio.get_event_loop()
        #     response = await loop.run_in_executor(None, self.kite.place_order, kite_payload)
        #     logger.info(f"Zerodha order placed: {response}")
        #     return response
        # except Exception as e:
        #     logger.error(f"Zerodha order placement failed: {e}")
        #     return {"error": str(e)}
        
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
            positions = await loop.run_in_executor(None, self.kite.positions)
            # Flatten the positions dict to a list of all positions (day + net)
            all_positions = []
            for segment in ("day", "net"):
                segment_positions = positions.get(segment, [])
                if isinstance(segment_positions, list):
                    all_positions.extend(segment_positions)
            return all_positions
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
        # print("ZERODHA RAW CANDLES:", candles, token, from_date_fmt, to_date_fmt, interval)
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
            profile = await loop.run_in_executor(None, self.kite.profile)
            return profile
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha profile: {e}")
            return {"error": str(e)}

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch a full quote for the given symbol via Kite Connect.
        """
        loop = asyncio.get_event_loop()
        # KiteConnect.quote takes a list of symbols
        return await loop.run_in_executor(None, self.kite.quote, [symbol])

    async def get_ltp(self, symbol: str) -> Any:
        """
        Fetch the last traded price for the given symbol via Kite Connect.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.kite.ltp, symbol)

    async def get_strike_list(self, symbol: str, max_strikes: int) -> List[str]:
        """
        Return a list of tradingsymbols for CE and PE strikes:
        1 ATM CE, 1 ATM PE, max_strikes ITM CE, max_strikes OTM CE, max_strikes ITM PE, max_strikes OTM PE.
        Expiry is auto-detected: weekly for NIFTY, monthly for others.
        Total returned: 4*max_strikes + 2
        """
        import datetime
        loop = asyncio.get_event_loop()
        instruments = await loop.run_in_executor(None, lambda: pd.DataFrame(self.kite.instruments("NFO")))
        instruments['expiry'] = pd.to_datetime(instruments['expiry'])

        # Symbol normalization for filtering instruments
        symbol_filter = symbol.upper()
        if symbol_filter == "NIFTY 50":
            symbol_filter = "NIFTY"
        # In future, add more symbol renaming logic here as needed

        # Helper to get nearest expiry (weekly for NIFTY, monthly for others)
        def get_nearest_expiry(symbol: str, ref_date: datetime.date = None) -> datetime.date:
            if ref_date is None:
                ref_date = datetime.date.today()
            if symbol.upper() == "NIFTY 50":
                # Weekly expiry: next Thursday >= today
                days_ahead = (3 - ref_date.weekday() + 7) % 7
                expiry = ref_date + datetime.timedelta(days=days_ahead)
                # If today is Thursday and market not closed, expiry is today
                if days_ahead == 0:
                    expiry = ref_date
                return expiry
            else:
                # Monthly expiry: last Thursday of current month
                year = ref_date.year
                month = ref_date.month
                # Find last Thursday of the month
                last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1) if month < 12 else datetime.date(year, 12, 31)
                while last_day.weekday() != 3:
                    last_day -= datetime.timedelta(days=1)
                return last_day

        expiry = get_nearest_expiry(symbol)
        # Convert expiry to pandas.Timestamp for comparison
        expiry_pd = pd.Timestamp(expiry)
        df = instruments[
            (instruments['name'] == symbol_filter) &
            (instruments['segment'] == 'NFO-OPT') &
            (instruments['expiry'] == expiry_pd)
        ].copy()
        if df.empty:
            logger.error(f"No option contracts found for {symbol} and expiry {expiry_pd}")
            return []
        ltp_symbol = f"NSE:{symbol.upper()}"
        if symbol.upper() == 'NIFTY':
            ltp_symbol = f"NSE:{symbol.upper()} 50"
        ltp = await loop.run_in_executor(None, self.kite.ltp, ltp_symbol)
        spot = ltp[ltp_symbol]["last_price"]
        df["_strike_val"] = df["strike"].astype(float)
        ce = df[df["instrument_type"] == "CE"]
        pe = df[df["instrument_type"] == "PE"]
        all_strikes = sorted(df["_strike_val"].unique())
        if not all_strikes:
            logger.error(f"No strikes found for {symbol} on expiry {expiry_pd}")
            return []
        atm_strike = min(all_strikes, key=lambda x: abs(x - spot))
        # ATM
        atm_ce = ce[ce["_strike_val"] == atm_strike]["tradingsymbol"].tolist()[:1]
        atm_pe = pe[pe["_strike_val"] == atm_strike]["tradingsymbol"].tolist()[:1]
        # ITM/OTM
        ce_itm = ce[ce["_strike_val"] < atm_strike].sort_values(by="_strike_val", ascending=False).head(max_strikes)
        ce_otm = ce[ce["_strike_val"] > atm_strike].sort_values(by="_strike_val").head(max_strikes)
        pe_itm = pe[pe["_strike_val"] > atm_strike].sort_values(by="_strike_val").head(max_strikes)
        pe_otm = pe[pe["_strike_val"] < atm_strike].sort_values(by="_strike_val", ascending=False).head(max_strikes)
        picks = atm_ce + atm_pe + \
                ce_itm["tradingsymbol"].tolist() + ce_otm["tradingsymbol"].tolist() + \
                pe_itm["tradingsymbol"].tolist() + pe_otm["tradingsymbol"].tolist()
        return picks

    async def get_order_details(self) -> list[dict]:
        """
        Fetch all order details for the current account/session from Zerodha.
        Returns a list of order dicts.
        """
        loop = asyncio.get_event_loop()
        orders = await loop.run_in_executor(None, self.kite.orders)
        return orders

# === Broker-specific API code mapping ===
# These mappings translate generic enums to Zerodha API codes. Do not move these to order_defaults.py.
SIDE_MAP = {
    Side.BUY: "BUY",   # Zerodha API: "BUY"
    Side.SELL: "SELL", # Zerodha API: "SELL"
}

ORDER_TYPE_MAP = {
    OrderType.LIMIT: "LIMIT",   # Zerodha API: "LIMIT"
    OrderType.MARKET: "MARKET", # Zerodha API: "MARKET"
    OrderType.SL: "SL-M",       # Zerodha API: "SL-M"
    # Add more mappings as needed
}
