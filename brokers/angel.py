import asyncio
import pyotp
from datetime import datetime
import pytz
from SmartApi.smartConnect import SmartConnect
from brokers.base import BrokerInterface
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.logger import get_logger
from typing import Dict, Any, List
from utils.utils import get_ist_datetime

logger = get_logger("angel_wrapper")

class AngelWrapper(BrokerInterface):
    """
    Async wrapper for Angel One (SmartAPI) using SmartConnect.
    Credentials are stored in broker_credentials table and managed via common.broker_utils.
    """
    def __init__(self, broker_name: str = "angel"):
        self.broker_name = broker_name
        self.smart_api = None
        self.auth_token = None
        self.refresh_token = None
        self.feed_token = None
        
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

            # Check if we have existing tokens that might be reusable
            regenerate_token = True
            # if "jwt_token" in creds_json and "feed_token" in creds_json and "generated_on" in creds_json:
                # ist_timezone = pytz.timezone("Asia/Kolkata")
                # token_generated_on = ist_timezone.localize(datetime.strptime(creds_json["generated_on"],
                #                                                           "%d/%m/%Y %H:%M:%S"))
                # current_ist_time = get_ist_datetime()
                # today_6am = current_ist_time.replace(hour=6, minute=0, second=0, microsecond=0)
                # today_date = current_ist_time.date()
                # token_date = token_generated_on.date()

                # # Token reuse logic:
                # # 1. If token generated after 6AM today and we're still on the same day - reuse token
                # # 2. If token generated before 6AM today AND current time is after 6AM - regenerate token
                # # 3. If token generated on previous day - regenerate token
                
                # can_reuse_token = (
                #     token_date == today_date and  # Same day
                #     (token_generated_on >= today_6am)  # Generated after 6AM
                # )
                
                # if can_reuse_token:
                #     try:
                #         # Initialize SmartConnect with existing token
                #         api_key = creds_json.get("api_key")
                #         loop = asyncio.get_running_loop()
                        
                #         def _init_with_existing_token():
                #             sc = SmartConnect(api_key)
                #             # Set the existing tokens
                #             sc._SmartConnect__access_token = creds_json["jwt_token"]
                #             sc._SmartConnect__refresh_token = creds_json.get("refresh_token", "")
                #             sc._SmartConnect__feedToken = creds_json["feed_token"]
                #             return sc
                        
                #         self.smart_api = await loop.run_in_executor(None, _init_with_existing_token)
                #         self.auth_token = creds_json["jwt_token"]
                #         self.refresh_token = creds_json.get("refresh_token", "")
                #         self.feed_token = creds_json["feed_token"]
                        
                #         # Test if token is still valid
                #         token_valid = await self._validate_token()
                #         if token_valid:
                #             logger.info(f"Successfully reused existing token for Angel broker.")
                #             regenerate_token = False
                #         else:
                #             logger.warning(f"Existing Angel token failed validation, regenerating.")
                #     except Exception as e:
                #         logger.warning(f"Token validation failed for Angel: {e}")
                # else:
                #     # Log the reason for regenerating token
                #     if token_date != today_date:
                #         logger.info(f"Token was generated on a previous day ({token_date}), regenerating")
                #     elif token_generated_on < today_6am and current_ist_time > today_6am:
                #         logger.info(f"Token was generated before 6AM ({token_generated_on.strftime('%H:%M:%S')}) and current time is after 6AM, regenerating")
            
            # If we need to regenerate the token
            if regenerate_token:
                logger.info("Generating a new Angel access token.")
                
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

                try:
                    self.smart_api, login_data = await loop.run_in_executor(None, _sync_login)
                except Exception as e:
                    logger.error(f"Angel SmartConnect login attempt failed: {e}", exc_info=True)
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
                logger.info(f"Angel login successful for '{username}' and new tokens updated in DB.")
            
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

    async def place_order(self, order_payload: dict) -> dict:
        """
        Place an order with Angel broker.
        Will refresh token if needed.
        
        Args:
            order_payload: The order details as required by Angel SmartAPI
            
        Returns:
            dict: Response from the broker containing order status
        """
        # Make sure token is valid
        try:
            if not self.smart_api:
                await self.login()
                if not self.smart_api:
                    logger.error("Failed to initialize SmartAPI for Angel broker")
                    return {"status": False, "message": "Authentication failed"}
                    
            # Direct call to SmartAPI
            loop = asyncio.get_running_loop()
            def _sync_place():
                return self.smart_api.placeOrder(order_payload)
                
            response = await loop.run_in_executor(None, _sync_place)
            
            # Check if we need to handle an invalid token
            if not response or (isinstance(response, dict) and not response.get("status")):
                logger.warning("Token may have expired, attempting to login again")
                login_success = await self.login()
                if not login_success:
                    logger.error("Failed to refresh token for Angel broker")
                    return {"status": False, "message": "Token refresh failed"}
                    
                # Try again with fresh token
                def _sync_place_retry():
                    return self.smart_api.placeOrder(order_payload)
                    
                response = await loop.run_in_executor(None, _sync_place_retry)
                
            return response
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"status": False, "message": str(e)}
            
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
