# core/broker_manager.py

import asyncio
from typing import Dict, Optional, List
from brokers.factory import get_broker
from common.broker_utils import get_broker_credentials, upsert_broker_credentials
from common.default_broker_configs import DEFAULT_BROKER_CONFIGS
from common.logger import get_logger
from core.db import get_trade_enabled_brokers as db_get_trade_enabled_brokers

logger = get_logger("BrokerManager")

class BrokerManager:
    def __init__(self):
        self.brokers: Dict[str, object] = {}

    async def _discover_enabled_brokers(self) -> List[str]:
        # Discover all brokers that have credentials or default configs
        enabled_brokers = []
        # Get all broker keys from default configs
        all_broker_keys = list(DEFAULT_BROKER_CONFIGS.keys())
        for broker_key in all_broker_keys:
            full_config = await get_broker_credentials(broker_key)
            if not full_config:
                full_config = DEFAULT_BROKER_CONFIGS.get(broker_key)
                if full_config:
                    if "credentials" not in full_config:
                        full_config["credentials"] = {}
                    if "required_auth_fields" not in full_config:
                        full_config["required_auth_fields"] = []
                    await upsert_broker_credentials(broker_key, full_config)
                    enabled_brokers.append(broker_key)
            else:
                enabled_brokers.append(broker_key)
        return enabled_brokers

    async def _prompt_for_missing_credentials(self, broker_key: str) -> bool:
        logger.debug(f"🔑 Prompting for missing credentials for broker: {broker_key}")
        full_config = await get_broker_credentials(broker_key)
        if not full_config:
            logger.warning(f"🟡 No configuration found for {broker_key}. Skipping credential prompt.")
            return False
        current_credentials = full_config.get("credentials", {})
        required_fields = full_config.get("required_auth_fields", [])
        if not required_fields:
            logger.warning(f"🟡 No required authentication fields defined for {broker_key}. Skipping prompt.")
            return False
        credentials_updated = False
        for field in required_fields:
            if not current_credentials.get(field):
                value = input(f"Enter {field} for broker {broker_key}: ")
                if value:
                    current_credentials[field] = value
                    credentials_updated = True
        if credentials_updated:
            full_config["credentials"] = current_credentials
            await upsert_broker_credentials(broker_key, full_config)
            logger.info(f"🟢 Credentials updated for {broker_key}")
            return True
        return False

    async def _authenticate_broker(self, broker_key: str) -> bool:
        broker = get_broker(broker_key)
        if not broker:
            logger.error(f"🔴 Could not instantiate broker: {broker_key}")
            self.brokers[broker_key] = None
            return False
        success = await broker.login()
        self.brokers[broker_key] = broker if success else None
        if success:
            logger.info(f"🟢 Authentication successful for {broker_key}")
        else:
            logger.warning(f"🟡 Authentication failed for {broker_key}")
        return success

    async def setup(self):
        logger.debug("🔄 Starting BrokerManager setup...")
        enabled_brokers = await self._discover_enabled_brokers()
        for broker_key in enabled_brokers:
            await self._prompt_for_missing_credentials(broker_key)
            await self._authenticate_broker(broker_key)
        logger.info("🟢 BrokerManager setup complete.")

    async def reauthenticate_broker(self, broker_key: str) -> bool:
        broker = self.brokers.get(broker_key)
        if not broker:
            logger.info(f"🔄 Broker {broker_key} not initialized. Initializing now...")
            # Attempt to authenticate broker if not initialized
            return await self._authenticate_broker(broker_key)
        logger.info(f"🔄 Reauthenticating broker: {broker_key}")
        success = await broker.login()
        if success:
            logger.info(f"🟢 Reauthentication successful for {broker_key}")
        else:
            logger.warning(f"🟡 Reauthentication failed for {broker_key}")
        return success

    async def reauthenticate_all(self):
        logger.info("🟢 Reauthenticating all enabled brokers...")
        for broker_key in list(self.brokers.keys()):
            await self.reauthenticate_broker(broker_key)

    def get_data_broker(self, broker_name: Optional[str] = None):
        """
        Returns the broker instance to be used for fetching data.
        If broker_name is given, return that broker if available and valid.
        Otherwise, return the first authenticated broker.
        """
        if broker_name and broker_name in self.brokers and self.brokers[broker_name]:
            return self.brokers[broker_name]
        # Return the first valid broker, if any
        for broker in self.brokers.values():
            if broker:
                return broker
        return None

    async def place_order(self, order_payload):
        """
        Place order in all authenticated brokers that implement place_order.
        Returns a dict of broker_name -> order result.
        """
        results = {}
        for broker_name, broker in self.brokers.items():
            if not broker:
                results[broker_name] = {"status": False, "message": "Broker not initialized"}
                continue
            if not hasattr(broker, "place_order") or not callable(getattr(broker, "place_order", None)):
                results[broker_name] = {"status": False, "message": "place_order not implemented"}
                continue
            try:
                result = await broker.place_order(order_payload)
                results[broker_name] = result
            except Exception as e:
                results[broker_name] = {"status": False, "message": str(e)}
        return results

    async def get_trade_enabled_brokers(self):
        """
        Return a list of broker names where trade_execution_enabled is True.
        """
        return await db_get_trade_enabled_brokers()

    async def get_active_trade_brokers(self) -> Dict[str, object]:
        """
        Returns a dict of broker_name -> broker_obj for brokers that are both
        trade enabled in DB and are live/authenticated right now.
        """
        enabled_broker_names = await db_get_trade_enabled_brokers()
        return {
            name: self.brokers[name]
            for name in enabled_broker_names
            if name in self.brokers and self.brokers[name] is not None
        }
