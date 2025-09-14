import asyncio
import pyotp
from datetime import datetime
import pytz
from SmartApi.smartConnect import SmartConnect
import logging
import logzero
import requests  # Add this import for better error handling
import pandas as pd
logzero.loglevel(logging.ERROR)
from algosat.brokers.base import BrokerInterface
from algosat.brokers.models import BalanceSummary
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials
from algosat.common.logger import get_logger
from typing import Dict, Any, List
from algosat.core.time_utils import get_ist_datetime

logger = get_logger("angel_wrapper")

class AngelWrapper(BrokerInterface):

    async def check_margin_availability(self, *order_params_list):
        """
        Check if sufficient margin is available before placing the trade using Angel One batch margin API.
        
        :param order_params_list: One or more standardized OrderRequest objects.
        :return: True if sufficient margin is available, otherwise False.
        """
        try:
            # Convert standardized OrderRequest objects to Angel format
            angel_positions = []
            for param in order_params_list:
                # If param is a list, flatten it
                if isinstance(param, list):
                    for p in param:
                        angel_positions.append(self._convert_to_angel_margin_format(p))
                else:
                    angel_positions.append(self._convert_to_angel_margin_format(param))

            # Create margin request payload
            margin_request_data = {
                "positions": angel_positions
            }
            
            logger.debug(f"Angel margin request data: {margin_request_data}")
            
            # Perform margin check using Angel batch margin API
            margin_response = await self._check_batch_margin(margin_request_data)
            logger.debug(f"Angel margin response: {margin_response}")
            
            # Extract margin details from response
            if margin_response and margin_response.get("status"):
                data = margin_response.get("data", {})
                required_margin = float(data.get("totalMarginRequired", 0))
                available_margin = await self._get_available_margin()
                
                logger.info(
                    f"Angel Margin Check: Required: {required_margin}, Available: {available_margin}, "
                    f"Orders: {[pos['token'] for pos in angel_positions]}"
                )
                
                return required_margin <= available_margin
            else:
                logger.error(f"Angel margin check failed: {margin_response}")
                return False
                
        except Exception as error:
            logger.error(f"Error checking Angel margin: {error}")
            return False

    def _convert_to_angel_margin_format(self, order_request):
        """
        Convert OrderRequest to Angel margin check format.
        
        :param order_request: OrderRequest object
        :return: Dict in Angel margin format
        """
        # Get instrument token from extra field
        instrument_token = None
        if hasattr(order_request, 'extra') and order_request.extra:
            instrument_token = order_request.extra.get('instrument_token')
        
        if not instrument_token:
            raise ValueError(f"Instrument token not found for symbol {order_request.symbol}")
        
        # Convert side to Angel tradeType
        trade_type = "BUY" if order_request.side.value.upper() == "BUY" else "SELL"
        
        # Convert order type
        order_type = "MARKET"
        if hasattr(order_request, 'order_type'):
            if order_request.order_type.value.upper() in ["LIMIT", "SL", "SL-M"]:
                order_type = "LIMIT"
        
        # Get price (0 for market orders)
        price = 0
        if order_type == "LIMIT" and hasattr(order_request, 'price') and order_request.price:
            price = float(order_request.price)
        
        return {
            "exchange": "NFO",  # Assuming NFO for options
            "qty": int(order_request.quantity),
            "price": price,
            "productType": "INTRADAY",  # Default to INTRADAY
            "orderType": order_type,
            "token": str(instrument_token),
            "tradeType": trade_type
        }

    async def _check_batch_margin(self, margin_request_data):
        """
        Call Angel One batch margin API.
        
        :param margin_request_data: Request data with positions
        :return: API response
        """
        try:
            # Check if authenticated
            if not self.auth_token:
                raise Exception("Angel broker not authenticated. Please login first.")
            
            credentials = await get_broker_credentials(self.broker_name)
            if not credentials:
                raise Exception("Angel credentials not found")
            
            # Extract the nested credentials object
            creds_data = credentials.get('credentials', {})
            
            # Try different possible key names for API key
            api_key = creds_data.get('api_key') or creds_data.get('client_id') or creds_data.get('api_secret')
            if not api_key:
                raise Exception(f"Angel API key not found in credential data")
            
            # Clean auth token - remove Bearer prefix if it exists
            auth_token = self.auth_token
            if auth_token.startswith('Bearer '):
                auth_token = auth_token[7:]  # Remove 'Bearer ' prefix
            
            # Prepare headers - ensure no None values
            headers = {
                'X-PrivateKey': api_key,
                'Accept': 'application/json',
                'X-SourceID': 'WEB',
                'X-ClientLocalIP': '127.0.0.1',
                'X-ClientPublicIP': '127.0.0.1', 
                'X-MACAddress': 'MAC_ADDRESS',
                'X-UserType': 'USER',
                'Authorization': f'Bearer {auth_token}',
                'Content-Type': 'application/json'
            }
            
            # Debug headers
            # logger.info(f"Angel margin headers: {headers}")
            
            url = "https://apiconnect.angelone.in/rest/secure/angelbroking/margin/v1/batch"
            
            logger.info(f"Angel margin check request: {margin_request_data}")
            
            # Make async HTTP request
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=margin_request_data, headers=headers) as response:
                    response_text = await response.text()
                    logger.debug(f"Angel margin API response: {response.status} - {response_text}")
                    
                    if response.status == 200:
                        try:
                            return await response.json()
                        except Exception as json_error:
                            logger.error(f"Error parsing JSON response: {json_error}")
                            return None
                    else:
                        logger.error(f"Angel margin API error: {response.status} - {response_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error calling Angel margin API: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _get_available_margin(self):
        """
        Get available margin from Angel One.
        This would typically come from balance/funds API.
        For now, return a large number as placeholder.
        """
        try:
            # TODO: Implement actual margin retrieval from Angel funds API
            # For now, return a reasonable default
            return 1000000.0  # 10 lakh as placeholder
        except Exception as e:
            logger.error(f"Error getting available margin: {e}")
            return 0.0
    """
    Async wrapper for Angel One (SmartAPI) using SmartConnect.
    Credentials are stored in broker_credentials table and managed via common.broker_utils.
    
    Features:
    - Authentication with TOTP and token management
    - Instruments data caching and search functionality
    - Token lookup by symbol and exchange
    - Similar to Zerodha's instruments handling for consistency
    """
    def __init__(self, broker_name: str = "angel"):
        self.broker_name = broker_name
        self.smart_api = None
        self.auth_token = None
        self.refresh_token = None
        self.feed_token = None
        self._instruments_cache = None  # Cache for instruments data
        
        # Initialize asyncio event for token synchronization
        self._token_refresh_lock = asyncio.Lock()

    async def login(self) -> bool:
        """
        Fetch stored credentials, generate TOTP, and establish SmartConnect session.
        Persist any updated tokens.
        
        This implementation includes token reuse similar to Fyers:
        - If a token was generated after 6 AM today, it will be reused
        - If current time is before 6 AM and token was generated earlier today, it will be reused
        - Otherwise, a new token will be generated
        
        Returns:
            bool: True if login was successful, False otherwise
        """
        try:
            # Get broker configuration from database
            full_config = await get_broker_credentials(self.broker_name)
            if not full_config:
                logger.error(f"No configuration found for broker '{self.broker_name}' in DB.")
                return False

            # Extract credentials
            creds_json = full_config.get("credentials", {})
            if not creds_json:
                logger.error(f"Credentials JSON missing in config for broker '{self.broker_name}'")
                return False

            # Always generate a new Angel access token with retry
            logger.debug("Generating a new Angel access token.")

            # Validate required fields
            api_key = creds_json.get("api_key")
            username = creds_json.get("client_id")  # client_id is used as username in Angel
            password = creds_json.get("password")
            totp_secret = creds_json.get("totp_secret")

            if not all([api_key, username, password, totp_secret]):
                missing_fields = [
                    field for field in ["api_key", "client_id", "password", "totp_secret"]
                    if not creds_json.get(field)
                ]
                logger.error(f"Incomplete Angel credentials in DB for '{self.broker_name}'. Missing: {missing_fields}")
                return False

            # Generate TOTP code
            totp_code = pyotp.TOTP(totp_secret).now()

            # Perform login using SmartConnect
            loop = asyncio.get_running_loop()
            def _sync_login():
                sc = SmartConnect(api_key)
                session_data = sc.generateSession(username, password, totp_code)
                return sc, session_data

            # Attempt login with improved error handling
            try:
                self.smart_api, login_data = await loop.run_in_executor(None, _sync_login)
            except requests.exceptions.RequestException as e:
                logger.error("Network error during Angel SmartConnect login: %s. Could not connect to AngelOne API. Please check your internet connection or if the broker's API is down.", e)
                return False
            except ConnectionResetError as e:
                logger.error("Connection reset during Angel SmartConnect login: %s. This may be a temporary issue with AngelOne's API or your network. Please try again later.", e)
                return False
            except Exception as e:
                # Handle SmartApi DataException without traceback
                try:
                    from SmartApi.smartExceptions import DataException
                except ImportError:
                    DataException = None
                if DataException and isinstance(e, DataException):
                    logger.error(f"Angel SmartConnect login failed (DataException): {e}")
                    return False
                logger.error(f"Angel SmartConnect login failed: {e}", exc_info=True)
                return False

            # Validate login response
            if not login_data or not login_data.get("status") or login_data.get("message", "").upper() != "SUCCESS":
                error_msg = login_data.get("message", "Unknown error")
                error_code = login_data.get("errorcode", "N/A")
                logger.error(f"Angel login API call failed. Status: {login_data.get('status')}, Message: {error_msg}, ErrorCode: {error_code}")
                return False

            # Extract tokens from response
            api_response_data = login_data.get("data", {})
            self.auth_token = api_response_data.get("jwtToken")
            self.refresh_token = api_response_data.get("refreshToken")
            self.feed_token = api_response_data.get("feedToken")

            if not all([self.auth_token, self.refresh_token, self.feed_token]):
                logger.error(f"Angel login successful but token(s) missing in response: {api_response_data}")
                return False

            # Save tokens back to database with generated timestamp
            creds_json["jwt_token"] = self.auth_token
            creds_json["refresh_token"] = self.refresh_token
            creds_json["feed_token"] = self.feed_token
            creds_json["generated_on"] = get_ist_datetime().strftime("%d/%m/%Y %H:%M:%S")

            full_config["credentials"] = creds_json
            await upsert_broker_credentials(self.broker_name, full_config)
            logger.debug(f"Angel login successful for '{username}' and new tokens updated in DB.")

            # Clear instruments cache after successful login to ensure fresh data
            self.clear_instruments_cache()

            return True

        except Exception as e:
            logger.error(f"Angel login failed: {e}", exc_info=True)
            return False
            
    async def _validate_token(self) -> bool:
        """
        Validate if the current token is still valid by making a simple API call.
        
        Returns:
            bool: True if the token is valid, False otherwise
        """
        try:
            if not self.smart_api:
                logger.warning("SmartAPI not initialized, token validation failed")
                return False
                
            # Try to get profile as a validation check
            loop = asyncio.get_running_loop()
            def _sync_validate():
                return self.smart_api.getProfile(self.refresh_token)
                
            response = await loop.run_in_executor(None, _sync_validate)
            
            # Check if response indicates a valid token
            is_valid = response and response.get("status") and response.get("data")
            if not is_valid:
                logger.warning(f"Token validation failed: {response}")
            return is_valid
        except Exception as e:
            logger.warning(f"Token validation failed: {e}")
            return False

    async def place_order(self, order_request) -> dict:
        """
        Place an order with Angel broker.
        
        Args:
            order_request: OrderRequest object or dict containing order details
            
        Returns:
            dict: Response from the broker containing order status
        """
        from algosat.core.order_request import OrderResponse, OrderStatus
        
        try:
            # Convert OrderRequest to Angel format if needed
            if hasattr(order_request, 'to_angel_dict'):
                order_payload = order_request.to_angel_dict()
            elif isinstance(order_request, dict):
                order_payload = order_request
            else:
                return OrderResponse(
                    status=OrderStatus.FAILED,
                    order_id="",
                    order_message="Invalid order request format",
                    broker="angel",
                    raw_response=None,
                    symbol=getattr(order_request, 'symbol', None),
                    side=getattr(order_request, 'side', None),
                    quantity=getattr(order_request, 'quantity', None),
                    order_type=getattr(order_request, 'order_type', None)
                ).dict()
                
            # Remove None values from payload
            order_payload = {k: v for k, v in order_payload.items() if v is not None}
            logger.info(f"Placing Angel order with payload: {order_payload}")
            
            # Make sure we're authenticated
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return OrderResponse(
                        status=OrderStatus.FAILED,
                        order_id="",
                        order_message="Authentication failed",
                        broker="angel",
                        raw_response=None,
                        symbol=getattr(order_request, 'symbol', None),
                        side=getattr(order_request, 'side', None),
                        quantity=getattr(order_request, 'quantity', None),
                        order_type=getattr(order_request, 'order_type', None)
                    ).dict()
                    
            # Place order using SmartAPI
            loop = asyncio.get_running_loop()
            def _sync_place():
                response =  self.smart_api.placeOrderFullResponse(order_payload)
                # return self.smart_api.placeOrder(order_payload)
                return response
                
            response = await loop.run_in_executor(None, _sync_place)
            
            # Check if we need to handle an invalid token
            if not response or (isinstance(response, dict) and not response.get("status")):
                logger.warning("Token may have expired, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return OrderResponse(
                        status=OrderStatus.FAILED,
                        order_id="",
                        order_message="Token refresh failed",
                        broker="angel",
                        raw_response=response,
                        symbol=getattr(order_request, 'symbol', None),
                        side=getattr(order_request, 'side', None),
                        quantity=getattr(order_request, 'quantity', None),
                        order_type=getattr(order_request, 'order_type', None)
                    ).dict()
                    
                # Try again with fresh token
                def _sync_place_retry():
                    return self.smart_api.placeOrder(order_payload)
                    
                response = await loop.run_in_executor(None, _sync_place_retry)
                logger.info(f"Angel order retry response: {response}")
            
            # Parse response and return standardized format
            if response and response.get("status"):
                return OrderResponse(
                    status=OrderStatus.AWAITING_ENTRY,
                    order_id=response.get("data", {}).get("orderid", ""),
                    order_message=response.get("message", "Order placed successfully"),
                    broker="angel",
                    raw_response=response,
                    symbol=getattr(order_request, 'symbol', None),
                    side=getattr(order_request, 'side', None),
                    quantity=getattr(order_request, 'quantity', None),
                    order_type=getattr(order_request, 'order_type', None)
                ).dict()
            else:
                return OrderResponse(
                    status=OrderStatus.FAILED,
                    order_id="",
                    order_message=response.get("message", "Order placement failed") if response else "No response from broker",
                    broker="angel",
                    raw_response=response,
                    symbol=getattr(order_request, 'symbol', None),
                    side=getattr(order_request, 'side', None),
                    quantity=getattr(order_request, 'quantity', None),
                    order_type=getattr(order_request, 'order_type', None)
                ).dict()
                
        except Exception as e:
            logger.error(f"Error placing Angel order: {e}")
            return OrderResponse(
                status=OrderStatus.FAILED,
                order_id="",
                order_message=f"Exception occurred: {str(e)}",
                broker="angel",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None)
            ).dict()
            
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Retrieve current positions from Angel broker.
        Will refresh token if needed.
        
        Returns:
            List of position dictionaries
        """
        try:
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return []
                    
            loop = asyncio.get_running_loop()
            def _sync_positions():
                return self.smart_api.position()
                
            positions_response = await loop.run_in_executor(None, _sync_positions)
            
            # Check if we need to handle an invalid token
            if not positions_response or (isinstance(positions_response, dict) and not positions_response.get("status")):
                logger.warning("Token may have expired, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return []
                    
                # Try again with fresh token
                def _sync_positions_retry():
                    return self.smart_api.position()
                    
                positions_response = await loop.run_in_executor(None, _sync_positions_retry)
                
            # Extract data if available
            if isinstance(positions_response, dict) and positions_response.get("data"):
                return positions_response.get("data", [])
            return positions_response
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    async def get_history(self, symbol: str, **kwargs) -> List[Any]:
        """
        Retrieve historical data for a symbol from Angel broker.
        Will refresh token if needed.
        
        Args:
            symbol: The trading symbol
            **kwargs: Additional parameters required by getCandleData
            
        Returns:
            List of candle data
        """
        try:
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return []
                    
            loop = asyncio.get_running_loop()
            def _sync_history():
                return self.smart_api.getCandleData(kwargs)
                
            history_response = await loop.run_in_executor(None, _sync_history)
            
            # Check if we need to handle an invalid token
            if not history_response or (isinstance(history_response, dict) and not history_response.get("status")):
                logger.warning("Token may have expired, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return []
                    
                # Try again with fresh token
                def _sync_history_retry():
                    return self.smart_api.getCandleData(kwargs)
                    
                history_response = await loop.run_in_executor(None, _sync_history_retry)
                
            # Extract data if available
            if isinstance(history_response, dict) and history_response.get("data"):
                return history_response.get("data", [])
            return history_response
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    async def get_profile(self) -> Dict[str, Any]:
        """
        Retrieve user profile from Angel broker.
        Will refresh token if needed.
        
        Returns:
            Dict containing profile data
        """
        # Try to validate token first
        try:
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return {}
                    
            loop = asyncio.get_running_loop()
            def _sync_get_profile():
                return self.smart_api.getProfile(self.refresh_token)
                
            profile_response = await loop.run_in_executor(None, _sync_get_profile)
            
            # Check if we need to handle an invalid token
            if not profile_response or not profile_response.get("status"):
                logger.warning("Token may have expired, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return {}
                    
                # Try again with fresh token
                def _sync_get_profile_retry():
                    return self.smart_api.getProfile()
                    
                profile_response = await loop.run_in_executor(None, _sync_get_profile_retry)
                
            return profile_response.get("data", {})
        except Exception as e:
            logger.error(f"Error getting profile: {e}")
            return {}

    async def get_ltp(self, symbol: str) -> Any:
        """
        Placeholder for get_ltp. Should return last traded price for the given symbol.
        """
        logger.warning("Angel get_ltp is a placeholder. Not implemented.")
        return None

    async def get_quote(self, symbol: str) -> dict:
        """
        Placeholder for get_quote. Should return full quote for the given symbol.
        """
        logger.warning("Angel get_quote is a placeholder. Not implemented.")
        return {}

    async def get_strike_list(self, symbol: str, expiry, atm_count: int, itm_count: int, otm_count: int) -> list:
        """
        Placeholder for get_strike_list. Should return a list of tradingsymbols for CE and PE strikes.
        """
        logger.warning("Angel get_strike_list is a placeholder. Not implemented.")
        return []

    async def get_order_details(self) -> list[dict]:
        """
        Fetch all order details for the current account/session from Angel One.
        Enhanced with proper status checking and error handling.
        Returns a list of order dicts or empty list on failure.
        """
        try:
            # Ensure we're authenticated
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return []
            
            loop = asyncio.get_event_loop()
            def _sync_get_orders():
                return self.smart_api.orderBook()
            
            # Get orders response
            orders_response = await loop.run_in_executor(None, _sync_get_orders)
            
            # Check if we need to handle an invalid token
            if not orders_response or (isinstance(orders_response, dict) and not orders_response.get("status")):
                logger.warning("Token may have expired while fetching orders, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return []
                    
                # Try again with fresh token
                def _sync_get_orders_retry():
                    return self.smart_api.orderBook()
                    
                orders_response = await loop.run_in_executor(None, _sync_get_orders_retry)
                logger.info(f"Angel order details retry response: {orders_response}")
            
            # Validate response structure
            if not isinstance(orders_response, dict):
                logger.error(f"Angel order details: Invalid response type {type(orders_response)}")
                return []
            
            # Check response status
            if not orders_response.get("status"):
                error_msg = orders_response.get("message", "Unknown error")
                error_code = orders_response.get("errorcode", "N/A")
                logger.error(f"Angel order details API call failed. Status: {orders_response.get('status')}, "
                           f"Message: {error_msg}, ErrorCode: {error_code}")
                return []
            
            # Extract data field
            data = orders_response.get("data", [])
            if not isinstance(data, list):
                logger.error(f"Angel order details: Expected list in data field, got {type(data)}")
                return []
            
            logger.info(f"Angel order details: Successfully retrieved {len(data)} orders")
            
            # Log sample order for debugging (first order only)
            if data and len(data) > 0:
                sample_order = data[0]
                logger.debug(f"Angel order sample: OrderID={sample_order.get('orderid')}, "
                           f"Symbol={sample_order.get('tradingsymbol')}, "
                           f"Status={sample_order.get('status')}, "
                           f"Type={sample_order.get('ordertype')}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching Angel order details: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

    async def get_balance_summary(self, *args, **kwargs) -> BalanceSummary:
        """
        Return summary: total_balance, available, utilized for Angel One from rmsLimit API.
        
        Calculation based on Angel API response:
        - available = availablecash (available cash for trading)
        - utilized = sum of all utilized amounts (debits, span, option premium, exposure, etc.)
        - total = net balance from API (or available + utilized if net not available)
        """
        try:
            raw = await self.get_balance()
            if not raw or not isinstance(raw, dict) or not raw.get("status"):
                logger.error(f"Angel get_balance_summary: Invalid or failed response: {raw}")
                return BalanceSummary()
            
            # Extract data from Angel API response
            data = raw.get("data", {})
            if not data:
                logger.error(f"Angel get_balance_summary: No data found in response: {raw}")
                return BalanceSummary()
            
            # Get available balance
            available = float(data.get("availablecash", 0))
            
            # Calculate total utilized amount from all utilized fields
            utilized_fields = [
                "utiliseddebits",
                # "utilisedspan", 
                # "utilisedoptionpremium",
                # "utilisedholdingsales",
                # "utilisedexposure",
                # "utilisedturnover",
                # "utilisedpayout"
            ]
            
            utilized = 0.0
            for field in utilized_fields:
                field_value = data.get(field, 0)
                try:
                    utilized += float(field_value) if field_value else 0.0
                except (ValueError, TypeError):
                    logger.debug(f"Angel: Could not convert {field} value '{field_value}' to float")
                    continue
            
            # Use net balance as total if available, otherwise calculate as available + utilized
            net_balance = data.get("net", 0)
            try:
                total = float(net_balance) if net_balance else (available + utilized)
            except (ValueError, TypeError):
                total = available + utilized
                logger.debug(f"Angel: Could not convert net balance '{net_balance}' to float, using calculated total")
            
            logger.debug(f"Angel balance summary - Total: {total}, Available: {available}, Utilized: {utilized}")
            
            return BalanceSummary(
                total_balance=total,
                available=available,
                utilized=utilized
            )
            
        except Exception as e:
            logger.error(f"Failed to summarize Angel balance: {e}")
            return BalanceSummary()

    async def get_balance(self, *args, **kwargs) -> dict:
        """
        Fetch account balance using Angel One RMS Limit API (raw API response).
        
        :return: Raw API response from rmsLimit() containing balance and limit information
        """
        try:
            logger.debug("Fetching balance using Angel RMS Limit API")
            
            # Call Angel's rmsLimit API and return raw response
            balance_response = self.smart_api.rmsLimit()
            logger.debug(f"Angel balance response: {balance_response}")
            
            return balance_response if balance_response else {}
                
        except Exception as e:
            logger.error(f"Error fetching balance from Angel: {e}")
            return {}
    
    async def get_instruments(self) -> pd.DataFrame:
        """
        Fetch instruments data from Angel One API and cache it as a DataFrame.
        Similar to Zerodha's instruments caching mechanism.
        
        Returns:
            pd.DataFrame: Instruments data with columns like 'symbol', 'token', 'exchange', etc.
        """
        try:
            # Return cached data if available
            if self._instruments_cache is not None:
                logger.debug("Angel: Using cached instruments data")
                return self._instruments_cache
            
            logger.debug("Angel: Fetching and caching instruments data")
            
            # Fetch instruments data from Angel API
            loop = asyncio.get_event_loop()
            
            def _fetch_instruments():
                """Synchronous function to fetch instruments data."""
                url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
                
                # Set timeout and headers for the request
                headers = {
                    'User-Agent': 'AlgoSat/1.0',
                    'Accept': 'application/json',
                    'Connection': 'close'
                }
                
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()  # Raises HTTPError for bad responses
                
                # Parse JSON response
                instruments_data = response.json()
                
                # Validate response structure
                if not isinstance(instruments_data, list):
                    raise ValueError(f"Expected list response, got {type(instruments_data)}")
                
                if not instruments_data:
                    raise ValueError("Empty instruments data received")
                
                return instruments_data
            
            # Execute in thread pool to avoid blocking
            instruments_data = await loop.run_in_executor(None, _fetch_instruments)
            
            # Convert to DataFrame
            df = pd.DataFrame(instruments_data)
            
            # Validate DataFrame structure
            if df.empty:
                raise ValueError("Converted DataFrame is empty")
            
            logger.debug(f"Angel: Successfully fetched {len(df)} instruments")
            
            # Log sample of available columns for debugging
            if not df.empty:
                logger.debug(f"Angel instruments columns: {list(df.columns)}")
                logger.debug(f"Angel instruments sample: {df.head(2).to_dict('records')}")
            
            # Cache the DataFrame
            self._instruments_cache = df
            
            return df
            
        except requests.exceptions.Timeout:
            logger.error("Angel: Timeout while fetching instruments data")
            return pd.DataFrame()
        except requests.exceptions.ConnectionError:
            logger.error("Angel: Connection error while fetching instruments data")
            return pd.DataFrame()
        except requests.exceptions.HTTPError as e:
            logger.error(f"Angel: HTTP error while fetching instruments data: {e}")
            return pd.DataFrame()
        except requests.exceptions.RequestException as e:
            logger.error(f"Angel: Request error while fetching instruments data: {e}")
            return pd.DataFrame()
        except ValueError as e:
            logger.error(f"Angel: Data validation error: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Angel: Unexpected error fetching instruments data: {e}", exc_info=True)
            return pd.DataFrame()
    
    def clear_instruments_cache(self):
        """
        Clear the cached instruments data.
        Useful when you want to force a fresh fetch of instruments data.
        """
        logger.debug("Angel: Clearing instruments cache")
        self._instruments_cache = None
    
    async def get_instrument_token(self, symbol: str, exchange: str = None) -> str:
        """
        Get instrument token for a given symbol.
        Similar to Zerodha's token lookup functionality.
        
        Args:
            symbol (str): Trading symbol to search for
            exchange (str, optional): Exchange segment to filter by (e.g., 'NSE', 'NFO', 'BSE')
            
        Returns:
            str: Instrument token if found, None otherwise
        """
        try:
            # Get instruments DataFrame
            instruments_df = await self.get_instruments()
            
            if instruments_df.empty:
                logger.error(f"Angel: Cannot get token for {symbol} - instruments data not available")
                return None
            
            # Sanitize symbol (remove exchange prefix if present)
            sanitized_symbol = symbol
            if ':' in symbol:
                sanitized_symbol = symbol.split(':', 1)[1]
            
            # Create filter conditions
            symbol_match = instruments_df['symbol'].str.upper() == sanitized_symbol.upper()
            
            # Apply exchange filter if provided
            if exchange:
                exchange_match = instruments_df['exch_seg'].str.upper() == exchange.upper()
                match = instruments_df[symbol_match & exchange_match]
            else:
                match = instruments_df[symbol_match]
            
            if not match.empty:
                token = match.iloc[0]['token']
                logger.debug(f"Angel: Found token {token} for symbol {symbol}")
                return str(token)
            
            # If no direct match, try name field as well
            if 'name' in instruments_df.columns:
                name_match = instruments_df['name'].str.upper() == sanitized_symbol.upper()
                if exchange:
                    match = instruments_df[name_match & exchange_match]
                else:
                    match = instruments_df[name_match]
                
                if not match.empty:
                    token = match.iloc[0]['token']
                    logger.debug(f"Angel: Found token {token} for symbol {symbol} (matched by name)")
                    return str(token)
            
            logger.warning(f"Angel: Token not found for symbol {symbol} in exchange {exchange}")
            return None
            
        except Exception as e:
            logger.error(f"Angel: Error getting token for symbol {symbol}: {e}")
            return None
    
    async def search_instruments(self, 
                               symbol_pattern: str = None, 
                               exchange: str = None, 
                               instrument_type: str = None,
                               limit: int = None) -> pd.DataFrame:
        """
        Search instruments by various criteria.
        
        Args:
            symbol_pattern (str, optional): Pattern to search in symbol/name (case-insensitive)
            exchange (str, optional): Exchange segment (e.g., 'NSE', 'NFO', 'BSE')
            instrument_type (str, optional): Instrument type (e.g., 'EQ', 'OPTIDX', 'FUTIDX')
            limit (int, optional): Maximum number of results to return
            
        Returns:
            pd.DataFrame: Filtered instruments data
        """
        try:
            # Get instruments DataFrame
            instruments_df = await self.get_instruments()
            
            if instruments_df.empty:
                logger.error("Angel: Cannot search instruments - data not available")
                return pd.DataFrame()
            
            # Start with full dataset
            filtered_df = instruments_df.copy()
            
            # Apply symbol pattern filter
            if symbol_pattern:
                symbol_mask = (
                    filtered_df['symbol'].str.contains(symbol_pattern, case=False, na=False) |
                    filtered_df['name'].str.contains(symbol_pattern, case=False, na=False)
                )
                filtered_df = filtered_df[symbol_mask]
            
            # Apply exchange filter
            if exchange:
                filtered_df = filtered_df[
                    filtered_df['exch_seg'].str.upper() == exchange.upper()
                ]
            
            # Apply instrument type filter
            if instrument_type:
                filtered_df = filtered_df[
                    filtered_df['instrumenttype'].str.upper() == instrument_type.upper()
                ]
            
            # Apply limit
            if limit and limit > 0:
                filtered_df = filtered_df.head(limit)
            
            logger.debug(f"Angel: Search returned {len(filtered_df)} instruments")
            return filtered_df
            
        except Exception as e:
            logger.error(f"Angel: Error searching instruments: {e}")
            return pd.DataFrame()
    
    async def cancel_order(self, broker_order_id, symbol=None, product_type=None, variety="NORMAL", cancel_reason=None, **kwargs):
        """
        Cancel an Angel order using the SmartConnect API.
        
        Args:
            broker_order_id: Angel order ID to cancel
            symbol: Trading symbol (optional, for logging)
            product_type: Product type (optional, for logging)
            variety: Order variety (default: "NORMAL")
            cancel_reason: Reason for cancellation (optional, for logging)
            **kwargs: Additional parameters
            
        Returns:
            dict: Response containing status and message
        """
        try:
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return {"status": False, "message": "Failed to initialize Angel API"}
            
            logger.info(f"Angel cancel_order: Cancelling order with id={broker_order_id}, variety={variety}, symbol={symbol}, reason='{cancel_reason}'")
            
            loop = asyncio.get_running_loop()
            
            def _sync_cancel():
                return self.smart_api.cancelOrder(broker_order_id, variety)
            
            result = await loop.run_in_executor(None, _sync_cancel)
            
            # Check if we need to handle an invalid token
            if not result or (isinstance(result, dict) and not result.get("status")):
                logger.warning("Token may have expired during cancel, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return {"status": False, "message": "Failed to refresh token"}
                    
                # Try again with fresh token
                def _sync_cancel_retry():
                    return self.smart_api.cancelOrder(broker_order_id, variety)
                    
                result = await loop.run_in_executor(None, _sync_cancel_retry)
            
            if isinstance(result, dict) and result.get("status"):
                logger.info(f"Angel cancel_order: Successfully cancelled order {broker_order_id} (reason: '{cancel_reason}')")
                return {"status": True, "message": "Order cancelled successfully", "result": result}
            else:
                error_msg = result.get("message", "Unknown error") if isinstance(result, dict) else str(result)
                logger.error(f"Angel cancel_order: Failed to cancel order {broker_order_id} (reason: '{cancel_reason}'): {error_msg}")
                return {"status": False, "message": error_msg}
                
        except Exception as e:
            logger.error(f"Angel cancel_order failed for order {broker_order_id} (reason: '{cancel_reason}'): {e}")
            return {"status": False, "message": str(e)}

    async def exit_order(self, broker_order_id, symbol=None, product_type=None, exit_reason=None, side=None):
        """
        Angel-specific exit logic: fetch filled qty from positions, compare to expected, and place opposite order if needed.
        Similar to Zerodha implementation but adapted for Angel API.
        
        Args:
            broker_order_id: Original order ID (for logging)
            symbol: Trading symbol (already sanitized by BrokerManager)
            product_type: Product type for the exit order
            exit_reason: Reason for exit (for logging)
            side: Original order side (BUY/SELL)
            
        Returns:
            dict: Response from placing the exit order
        """
        from algosat.core.order_request import OrderRequest, Side, OrderType
        
        try:
            # Symbol is already sanitized by BrokerManager; use as-is
            sanitized_symbol = symbol
            
            # Fetch current positions from Angel
            positions = await self.get_positions()
            if not positions:
                logger.warning(f"Angel exit_order: No positions found, cannot exit for symbol {sanitized_symbol}")
                return {"status": False, "message": "No positions found, cannot exit."}
            
            # Find position for the given symbol
            filled_qty = 0
            matched_position = None
            original_product = product_type
            
            # Match by tradingsymbol (case-insensitive)
            # Angel positions API response structure: 
            # {'tradingsymbol': '...', 'netqty': '...', 'producttype': '...', 'buyqty': '...', 'sellqty': '...'}
            for pos in positions:
                pos_symbol = str(pos.get('tradingsymbol', ''))
                if pos_symbol.upper() == str(sanitized_symbol).upper():
                    # Angel uses 'netqty' for net quantity (can be positive or negative)
                    net_qty = pos.get('netqty', '0')
                    buy_qty = pos.get('buyqty', '0') 
                    sell_qty = pos.get('sellqty', '0')
                    
                    try:
                        # Convert netqty to int/float, handle string format
                        net_qty_val = float(net_qty) if net_qty else 0
                        buy_qty_val = float(buy_qty) if buy_qty else 0
                        sell_qty_val = float(sell_qty) if sell_qty else 0
                        
                        # Use absolute value of net quantity for exit
                        filled_qty = abs(net_qty_val)
                        
                        logger.debug(f"Angel exit_order: Position found for {pos_symbol}: netqty={net_qty_val}, buyqty={buy_qty_val}, sellqty={sell_qty_val}")
                        
                    except (ValueError, TypeError) as e:
                        logger.error(f"Angel exit_order: Error parsing quantities for {pos_symbol}: netqty={net_qty}, buyqty={buy_qty}, sellqty={sell_qty}, error={e}")
                        filled_qty = 0
                    
                    matched_position = pos
                    original_product = pos.get('producttype', product_type)
                    break
            
            if filled_qty == 0:
                logger.warning(f"Angel exit_order: No filled quantity for symbol {sanitized_symbol} in positions, skipping exit.")
                return {"status": False, "message": "No filled quantity, cannot exit."}
            
            # Determine exit side (opposite of original)
            exit_side = 'SELL' if side == 'BUY' else 'BUY'
            
            # Build exit order request using Angel's product type mapping
            # Angel uses INTRADAY, CARRYFORWARD, etc.
            exit_order_req = OrderRequest(
                symbol=sanitized_symbol,
                side=exit_side,
                order_type=OrderType.MARKET,
                product_type=original_product,  # Use the product type from the position
                quantity=int(filled_qty)
            )
            
            logger.info(f"Angel exit_order: Preparing exit order for {broker_order_id} with side={exit_side}, qty={filled_qty}, symbol={sanitized_symbol}, product_type={original_product}, reason={exit_reason}")
            
            if matched_position:
                logger.debug(f"Angel exit_order: Using position data - netqty={matched_position.get('netqty')}, buyqty={matched_position.get('buyqty')}, sellqty={matched_position.get('sellqty')}, producttype={matched_position.get('producttype')}")
            
            # Place the exit order
            result = await self.place_order(exit_order_req)
            
            logger.info(f"Angel exit_order: Placed exit order for {broker_order_id} with side={exit_side}, qty={filled_qty}, symbol={sanitized_symbol}, product_type={original_product}, reason={exit_reason}")
            
            return result
            
        except Exception as e:
            logger.error(f"Angel exit_order failed for order {broker_order_id}: {e}")
            return {"status": False, "message": str(e)}
