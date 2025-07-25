from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from typing import Dict, Any, List
import asyncio

from algosat.core.db import get_all_brokers, get_broker_by_name, add_broker, update_broker, delete_broker
from algosat.api.schemas import BrokerResponse, BrokerCreate, BrokerUpdate, BrokerListResponse, BrokerDetailResponse
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError
from algosat.common.logger import get_logger

logger = get_logger("api.brokers")

# from algosat.main import broker_manager

# Require authentication for all endpoints in this router
router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()

@router.get("/", response_model=List[BrokerListResponse])
async def list_brokers(db=Depends(get_db)):
    brokers = [BrokerListResponse(**row) for row in await get_all_brokers(db)]
    return sorted(brokers, key=lambda b: b.id)

@router.get("/{broker_name}", response_model=BrokerDetailResponse)
async def get_broker(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await get_broker_by_name(db, validated_broker_name)
    if not row:
        raise HTTPException(status_code=404, detail="Broker not found")
    return BrokerDetailResponse.from_db(row)

@router.post("/", response_model=BrokerResponse)
async def add_broker_api(broker: BrokerCreate, db=Depends(get_db)):
    # Validate BrokerCreate fields
    validated_broker_name = input_validator.validate_and_sanitize(broker.broker_name, "broker.broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    validated_broker_title = input_validator.validate_and_sanitize(broker.broker_title, "broker.broker_title", expected_type=str, max_length=256)
    # Create a new BrokerCreate instance with validated data if necessary, or update in place if Pydantic model allows
    validated_broker_data = broker.dict()
    validated_broker_data["broker_name"] = validated_broker_name
    validated_broker_data["broker_title"] = validated_broker_title

    row = await add_broker(db, validated_broker_data)
    return BrokerResponse(**row)

@router.delete("/{broker_name}")
async def delete_broker_api(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    await delete_broker(db, validated_broker_name)
    return {"status": "deleted", "broker_name": validated_broker_name}

@router.put("/{broker_name}/enable")
async def enable_broker(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await update_broker(db, validated_broker_name, {"is_enabled": True})
    return {"status": "enabled", "broker_name": validated_broker_name}

@router.put("/{broker_name}/disable")
async def disable_broker(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await update_broker(db, validated_broker_name, {"is_enabled": False})
    return {"status": "disabled", "broker_name": validated_broker_name}

@router.put("/{broker_name}/enable-data-provider")
async def enable_data_provider(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    allowed_brokers = {"fyers", "zerodha"}
    if validated_broker_name.lower() not in allowed_brokers:
        raise HTTPException(
            status_code=406,
            detail="Only fyers and zerodha are allowed as data providers. No changes made."
        )
    # Set is_data_provider=False for all brokers first using db.py logic
    brokers = await get_all_brokers(db)
    for broker in brokers:
        if broker["broker_name"] != validated_broker_name and broker["is_data_provider"]:
            await update_broker(db, broker["broker_name"], {"is_data_provider": False})
    # Set is_data_provider=True for the selected broker
    row = await update_broker(db, validated_broker_name, {"is_data_provider": True})
    return {"status": "data_provider_enabled", "broker_name": validated_broker_name}

@router.put("/{broker_name}/disable-data-provider")
async def disable_data_provider(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await update_broker(db, validated_broker_name, {"is_data_provider": False})
    return {"status": "data_provider_disabled", "broker_name": validated_broker_name}

@router.put("/{broker_name}/enable-trade-execution")
async def enable_trade_execution(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await update_broker(db, validated_broker_name, {"trade_execution_enabled": True})
    return {"status": "trade_execution_enabled", "broker_name": validated_broker_name}

@router.put("/{broker_name}/disable-trade-execution")
async def disable_trade_execution(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    row = await update_broker(db, validated_broker_name, {"trade_execution_enabled": False})
    return {"status": "trade_execution_disabled", "broker_name": validated_broker_name}

@router.post("/{broker_name}/auth")
async def reauth_broker(broker_name: str, db=Depends(get_db)):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")

    # Update broker status to AUTHENTICATING and set last_auth_check timestamp
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        await update_broker(db, validated_broker_name, {
            "status": "AUTHENTICATING",
            "last_auth_check": now  # Pass as datetime, not isoformat string
        })
        logger.info(f"Set broker {validated_broker_name} status to AUTHENTICATING and updated last_auth_check")
    except Exception as e:
        logger.error(f"Failed to update broker status for {validated_broker_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update broker status")

    from algosat.main import broker_manager
    # Schedule the reauth as a background task using asyncio.create_task
    asyncio.create_task(broker_manager.reauthenticate_broker(validated_broker_name))
    return {
        "status": "reauth_started",
        "broker_name": validated_broker_name,
        "message": "Reauthentication started. Check /brokers/{broker_name} for the new token's generated_on field. If not updated within a minute, check logs for errors."
    }

@router.put("/{broker_name}", response_model=BrokerResponse)
async def update_broker_api(
    broker_name: str,
    update: BrokerUpdate = Body(...),
    db=Depends(get_db)
):
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")

    update_data_dict = update.dict(exclude_unset=True)
    validated_update_data = {}

    for key, value in update_data_dict.items():
        if value is None: # Allow optional fields to be None
            validated_update_data[key] = None
            continue
        if key == "broker_title":
            validated_update_data[key] = input_validator.validate_and_sanitize(value, f"update.{key}", expected_type=str, max_length=256)
        elif key == "broker_name": # Should not happen if broker_name is path param, but good for safety
             validated_update_data[key] = input_validator.validate_and_sanitize(value, f"update.{key}", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
        elif key in ["is_enabled", "is_data_provider", "trade_execution_enabled"]:
            if not isinstance(value, bool):
                raise InvalidInputError(f"Invalid type for {key}, expected boolean.")
            validated_update_data[key] = value
        elif key in ["max_loss", "max_profit"]:
            if not isinstance(value, (int, float)):
                raise InvalidInputError(f"Invalid type for {key}, expected number.")
            if value < 0:
                raise InvalidInputError(f"{key} must be greater than or equal to 0.")
            validated_update_data[key] = float(value)
        elif key == "status":
            allowed_statuses = ["CONNECTED", "DISCONNECTED", "AUTHENTICATING", "ERROR"]
            if value not in allowed_statuses:
                raise InvalidInputError(f"Invalid status value. Allowed values: {allowed_statuses}")
            validated_update_data[key] = value
        elif key == "config": # Assuming config is a dict
            if not isinstance(value, dict):
                raise InvalidInputError(f"Invalid type for {key}, expected dict.")
            # Add deeper validation for config dict if needed
            # For now, just basic sanitization for string values within the config dict
            validated_config = {}
            for cfg_key, cfg_value in value.items():
                if isinstance(cfg_value, str):
                    validated_config[cfg_key] = input_validator.validate_and_sanitize(cfg_value, f"update.config.{cfg_key}", max_length=1024)
                else:
                    validated_config[cfg_key] = cfg_value # Pass other types as is, or add validation
            validated_update_data[key] = validated_config
        else:
            # For any other fields, if they are strings, sanitize them.
            # Adjust as necessary if other types or more specific validations are needed.
            if isinstance(value, str):
                 validated_update_data[key] = input_validator.validate_and_sanitize(value, f"update.{key}", max_length=1024)
            else:
                validated_update_data[key] = value

    # If is_data_provider is being set to True, set all others to False first
    if validated_update_data.get("is_data_provider") is True:
        brokers = await get_all_brokers(db)
        for broker_in_db in brokers: # renamed broker to broker_in_db to avoid conflict
            if broker_in_db["broker_name"] != validated_broker_name and broker_in_db["is_data_provider"]:
                await update_broker(db, broker_in_db["broker_name"], {"is_data_provider": False})
    
    row = await update_broker(db, validated_broker_name, validated_update_data)
    if not row:
        raise HTTPException(status_code=404, detail="Broker not found")
    return BrokerResponse(**row)

@router.get("/{broker_name}/credentials")
async def get_broker_credentials(broker_name: str, db=Depends(get_db)):
    """Get broker credentials configuration including required auth fields"""
    validated_broker_name = input_validator.validate_and_sanitize(broker_name, "broker_name", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$")
    
    try:
        # Query broker_credentials table for the broker's required auth fields
        from algosat.core.dbschema import broker_credentials
        from sqlalchemy import select
        
        query = select(broker_credentials.c.required_auth_fields).where(
            broker_credentials.c.broker_name == validated_broker_name
        )
        result = await db.execute(query)
        row = result.fetchone()
        
        if not row or not row[0]:
            # Return default config if not found in broker_credentials table
            default_config = {
                "broker_name": validated_broker_name,
                "required_auth_fields": [
                    {"field_name": "api_key", "field_type": "password", "is_required": True, "description": "API Key from broker portal"},
                    {"field_name": "api_secret", "field_type": "password", "is_required": True, "description": "API Secret from broker portal"},
                    {"field_name": "client_id", "field_type": "string", "is_required": True, "description": "Client ID"}
                ]
            }
            return default_config
        
        return {
            "broker_name": validated_broker_name,
            "required_auth_fields": row[0] or []
        }
        
    except Exception as e:
        logger.error(f"Error fetching credentials config for {validated_broker_name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch broker credentials configuration")
