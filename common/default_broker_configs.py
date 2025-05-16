\
# algosat/common/default_broker_configs.py

DEFAULT_BROKER_CONFIGS = {
    "fyers": {
        "broker_name": "fyers",
        "credentials": {},
        "is_enabled": True,
        "data_source_priority": 1,
        "trade_execution_enabled": False,
        "notes": "Fyers Broker Configuration",
        "global_settings": {},
        "required_auth_fields": ["api_key", "api_secret", "redirect_uri", "client_id", "pin", "totp_secret"] # client_id is app_id for fyers
    },
    "angel": {
        "broker_name": "angel",
        "credentials": {},
        "is_enabled": False,
        "data_source_priority": 2,
        "trade_execution_enabled": False,
        "notes": "Angel One Broker Configuration",
        "global_settings": {},
        "required_auth_fields": ["api_key", "client_id", "password", "totp_secret"]
    },
    "zerodha": {
        "broker_name": "zerodha",
        "credentials": {},
        "is_enabled": False,
        "data_source_priority": 3,
        "trade_execution_enabled": False,
        "notes": "Zerodha Broker Configuration (Placeholder)",
        "global_settings": {},
        "required_auth_fields": ["api_key", "api_secret", "user_id", "password", "totp_secret"]
    }
}
