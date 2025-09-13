from datetime import datetime, time, timedelta
from typing import Any, Optional
from algosat.core.db import AsyncSessionLocal
from algosat.core.signal import TradeSignal
import pandas as pd
from algosat.common import constants, strategy_utils
from algosat.common.broker_utils import calculate_backdate_days, get_trade_day
from algosat.common.strategy_utils import (
    calculate_end_date,
    detect_regime,
    get_regime_reference_points,
    wait_for_first_candle_completion
)
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.time_utils import localize_to_ist, get_ist_datetime, to_ist
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import asyncio

logger = get_logger(__name__)

def is_holiday_or_weekend(check_date):
    """
    Check if given date is a holiday or weekend using centralized broker_utils.
    """
    try:
        # Check weekend (Saturday = 5, Sunday = 6)
        if check_date.weekday() >= 5:
            return True
        
        # Use centralized holiday checking from broker_utils
        from algosat.common.broker_utils import get_nse_holiday_list
        holidays = get_nse_holiday_list()
        if holidays is None:
            logger.warning("NSE holiday data not available, using basic weekend check")
            return False
        
        # Convert check_date to string format used by NSE API (DD-MMM-YYYY)
        check_date_str = check_date.strftime("%d-%b-%Y")
        return check_date_str in holidays
        
    except Exception as e:
        logger.error(f"Error checking holiday/weekend: {e}")
        return False

def is_tomorrow_holiday():
    """
    Check if tomorrow is a holiday.
    Simple check for holiday exit logic - exit today if tomorrow is a holiday.
    
    Returns:
        bool: True if tomorrow is a holiday, False otherwise
    """
    try:
        from algosat.core.time_utils import get_ist_datetime
        from datetime import timedelta
        
        current_datetime = get_ist_datetime()
        tomorrow = current_datetime + timedelta(days=1)
        
        # Convert to timezone-naive datetime for holiday checking to avoid timezone conflicts
        if tomorrow.tzinfo is not None:
            tomorrow = tomorrow.replace(tzinfo=None)
        
        # Check if tomorrow is a holiday or weekend
        return is_holiday_or_weekend(tomorrow)
        
    except Exception as e:
        logger.error(f"Error checking if tomorrow is holiday: {e}")
        return False

class SwingHighLowBuyStrategy(StrategyBase):

    async def sync_open_positions(self):
        """
        Synchronize self._positions with open orders in the database for this strategy symbol for the current trade day.
        Uses the strategy_symbol_id (symbol_id) from config to find related open orders for this specific configuration.
        """
        self._positions = {}
        from algosat.core.db import get_open_orders_for_strategy_symbol_and_tradeday_by_id
        from algosat.core.db import AsyncSessionLocal
        trade_day = get_trade_day(get_ist_datetime())
        strategy_symbol_id = getattr(self.cfg, 'symbol_id', None)
        if not strategy_symbol_id:
            logger.warning("No symbol_id found in config, cannot sync open positions")
            return
        async with AsyncSessionLocal() as session:
            open_orders = await get_open_orders_for_strategy_symbol_and_tradeday_by_id(session, strategy_symbol_id, trade_day)
            for order in open_orders:
                symbol = order.get("strike_symbol")
                if symbol:
                    if symbol not in self._positions:
                        self._positions[symbol] = []
                    self._positions[symbol].append(order)
            logger.debug(f"Synced positions for strategy_symbol_id {strategy_symbol_id}: {list(self._positions.keys())}")
    """
    Concrete implementation of a Swing High/Low breakout buy strategy.
    Modularized and standardized to match option_buy.py structure.
    """
    def __init__(self, config, data_manager: DataManager, execution_manager: OrderManager):
        super().__init__(config, data_manager, execution_manager)
        # Standardized config/state
        self.symbol = self.cfg.symbol
        self.name = "SwingHighLowBuy"
        self.exchange = self.cfg.exchange
        self.instrument = self.cfg.instrument
        self.trade = self.cfg.trade
        self.indicators = self.cfg.indicators
        self.order_manager = execution_manager
        # Internal state
        self._strikes = []  # Not used for spot, but kept for interface parity
        self._positions = {}  # open positions by strike
        self._setup_failed = False
        self._hh_levels = []
        self._ll_levels = []
        self._pending_signal = None  # Dict with 'breakout_price', 'breakout_time'
        self._pending_signal_confirm_until = None  # Timestamp until which confirmation window ends
        # Config fields modularized
        self._entry_cfg = self.trade.get("entry", {})
        self._stoploss_cfg = self.trade.get("stoploss", {})
        self.entry_timeframe = self._entry_cfg.get("timeframe", "5m")
        self.entry_minutes = int(self.entry_timeframe.replace("min", "").replace("m", "")) if (self.entry_timeframe.endswith("m") or self.entry_timeframe.endswith("min")) else 5
        self.stoploss_timeframe = self._stoploss_cfg.get("timeframe", "5m")
        self.stoploss_minutes = int(self.stoploss_timeframe.replace("min", "").replace("m", "")) if (self.stoploss_timeframe.endswith("m") or self.stoploss_timeframe.endswith("min")) else 5
        self.entry_swing_left_bars = self._entry_cfg.get("swing_left_bars", 3)
        self.entry_swing_right_bars = self._entry_cfg.get("swing_right_bars", 3)
        self.entry_buffer = self._entry_cfg.get("entry_buffer", 0)
        self.sl_buffer = self._stoploss_cfg.get("sl_buffer", 0)
        self.stop_percentage = self._stoploss_cfg.get("percentage", 0.05)
        self.confirm_timeframe = self._entry_cfg.get("confirmation_candle_timeframe", "1m")
        self.confirm_atomic = self._entry_cfg.get("atomic_check", True)
        self.confirm_minutes = int(self.confirm_timeframe.replace("min", "").replace("m", "")) if (self.confirm_timeframe.endswith("m") or self.confirm_timeframe.endswith("min")) else 1
        self.ce_lot_qty = self.trade.get("ce_lot_qty", 2)
        self.pe_lot_qty = self.trade.get("pe_lot_qty", 2)
        self.lot_size = self.trade.get("lot_size", 75)
        
        # Read RSI ignore thresholds from target.rsi_exit config (not entry config)
        target_cfg = self.trade.get("target", {})
        rsi_exit_config = target_cfg.get("rsi_exit", {})
        self.rsi_ignore_above = rsi_exit_config.get("ce_ignore_above", 80)
        self.rsi_ignore_below = rsi_exit_config.get("pe_ignore_below", 20)
        
        self.rsi_period = self.indicators.get("rsi_period", 14)
        self.rsi_timeframe_raw = self.indicators.get("rsi_timeframe", "5m") 
        self.rsi_timeframe_minutes = int(self.rsi_timeframe_raw.replace("min", "").replace("m", "")) if (self.rsi_timeframe_raw.endswith("m") or self.rsi_timeframe_raw.endswith("min")) else int(self.rsi_timeframe_raw) 
        self.atr_period = self.indicators.get("atr_period", 14)
        self.atr_timeframe_raw = self.indicators.get("atr_timeframe", "5m")
        self.atr_timeframe_minutes = int(self.atr_timeframe_raw.replace("min", "").replace("m", "")) if (self.atr_timeframe_raw.endswith("m") or self.atr_timeframe_raw.endswith("min")) else int(self.atr_timeframe_raw)
        # Smart Level Integration
        self._smart_levels_enabled = getattr(self.cfg, 'enable_smart_levels', False)
        self._strategy_symbol_id = getattr(self.cfg, 'symbol_id', None)
        self._smart_level = None  # Cache for single active smart level (dict)
        
        # Re-entry Logic Integration
        self._is_re_entry_mode = False  # Instance variable to track re-entry mode
        
        # Regime reference for sideways detection
        self.regime_reference = None
        logger.info(f"SwingHighLowBuyStrategy config: {self.trade}")
        logger.info(f"Smart levels enabled: {self._smart_levels_enabled}, strategy_symbol_id: {self._strategy_symbol_id}")
    
    async def ensure_broker(self):
        # No longer needed for data fetches, but keep for order placement if required
        await self.dp._ensure_broker()

    async def setup(self) -> None:
        """
        One-time setup: assign key config parameters to self for easy access throughout the strategy.
        No data fetching or calculations are performed here.
        """
        try:
            # All config fields are set in __init__, nothing else to do.
            logger.info(
                f"SwingHighLowBuyStrategy setup: symbol={self.symbol}, "
                f"entry_timeframe={self.entry_timeframe}, stop_timeframe={self.stoploss_timeframe}, "
                f"entry_swing_left_bars={self.entry_swing_left_bars}, entry_swing_right_bars={self.entry_swing_right_bars}, "
                f"entry_buffer={self.entry_buffer}, confirm_timeframe={self.confirm_timeframe}, "
                f"atomic_check={self.confirm_atomic}, "
                f"ce_lot_qty={self.ce_lot_qty}, lot_size={self.lot_size}, "
                f"rsi_ignore_above={self.rsi_ignore_above}, rsi_ignore_below={self.rsi_ignore_below}, rsi_period={self.rsi_period}, stop_percentage={self.stop_percentage}"
            )
            
            # Setup regime reference for sideways detection
            today_dt = get_ist_datetime()
            first_candle_time = self.trade.get("first_candle_time", "09:15")
            # 1. Wait for first candle completion
            await wait_for_first_candle_completion(self.entry_minutes, first_candle_time, self.symbol)
            await asyncio.sleep(2)  # Give some time for the first candle to complete
            logger.info('First candle completed, proceeding with regime reference setup...')
            self.regime_reference = await get_regime_reference_points(
                self.dp,
                self.symbol,
                first_candle_time,
                self.entry_minutes,
                today_dt
            )
            logger.info(f"Regime reference points for {self.symbol}: {self.regime_reference}")
            
            # Load smart levels if enabled
            if self._smart_levels_enabled:
                await self.load_smart_levels()
                logger.info(f"Smart level setup complete:")
                logger.info(self.get_smart_level_info_string())
            
        except Exception as e:
            logger.error(f"SwingHighLowBuyStrategy setup failed: {e}", exc_info=True)
            self._setup_failed = True

    def compute_indicators(self, df: pd.DataFrame, config: dict) -> dict:
        """
        Compute swing pivots and any other indicators for the strategy.
        Returns a dict with keys: hh_levels, ll_levels.
        """
        try:
            left_bars = config.get("swing_left_bars", 3)
            right_bars = config.get("swing_right_bars", 3)
            swing_df = swing_utils.find_hhlh_pivots(
                df,
                left_bars=left_bars,
                right_bars=right_bars
            )
            hh_points = swing_df[swing_df["is_HH"]]
            ll_points = swing_df[swing_df["is_LL"]]
            hh_levels = hh_points[["timestamp", "zz"]].to_dict("records")
            ll_levels = ll_points[["timestamp", "zz"]].to_dict("records")
            return {"hh_levels": hh_levels, "ll_levels": ll_levels}
        except Exception as e:
            logger.error(f"Error in compute_indicators: {e}", exc_info=True)
            return {"hh_levels": [], "ll_levels": []}

    async def load_smart_levels(self):
        """
        Load active smart levels for this strategy symbol from database.
        Uses either strategy_symbol_id or symbol name + strategy_id for lookup.
        """
        try:
            from algosat.core.db import AsyncSessionLocal, get_smart_levels_for_strategy_symbol_id, get_smart_levels_for_symbol
            from algosat.common.swing_utils import sanitize_symbol_for_db
            
            logger.info(f"🔄 Loading smart levels - enabled: {self._smart_levels_enabled}, strategy_symbol_id: {self._strategy_symbol_id}, symbol: {self.symbol}")
            
            # Initialize empty cache 
            self._smart_level = None
            
            if not self._smart_levels_enabled:
                logger.info("Smart levels disabled, skipping load")
                return
            
            # Sanitize symbol for database lookup (NSE:NIFTY50-INDEX -> NIFTY50)
            db_symbol = sanitize_symbol_for_db(self.symbol)
            logger.debug(f"Sanitized symbol for DB lookup: '{self.symbol}' -> '{db_symbol}'")

            async with AsyncSessionLocal() as session:
                smart_levels = []
                lookup_method = None
                
                # Method 1: Use strategy_symbol_id if available (most direct)
                if self._strategy_symbol_id:
                    smart_levels = await get_smart_levels_for_strategy_symbol_id(session, self._strategy_symbol_id)
                    lookup_method = f"strategy_symbol_id={self._strategy_symbol_id}"
                    logger.debug(f"Method 1: Loaded {len(smart_levels)} smart levels using {lookup_method}")
                
                # Method 2: Fallback to symbol name + strategy_id lookup (only if Method 1 found no data)
                if not smart_levels and hasattr(self.cfg, 'strategy_id') and self.cfg.strategy_id and db_symbol:
                    smart_levels = await get_smart_levels_for_symbol(session, db_symbol, self.cfg.strategy_id)
                    lookup_method = f"symbol={db_symbol}, strategy_id={self.cfg.strategy_id}"
                    logger.debug(f"Method 2: Loaded {len(smart_levels)} smart levels using {lookup_method}")
                
                # Method 3: Last fallback - symbol name only (only if previous methods found no data)
                if not smart_levels and db_symbol:
                    smart_levels = await get_smart_levels_for_symbol(session, db_symbol)
                    lookup_method = f"symbol={db_symbol} only"
                    logger.debug(f"Method 3: Loaded {len(smart_levels)} smart levels using {lookup_method}")
                
                # If still no data found - FAIL THE SETUP when smart levels are enabled
                if not smart_levels:
                    error_msg = f"❌ Smart levels are ENABLED but no configuration found for {db_symbol} (original: {self.symbol})!"
                    logger.error(error_msg)
                    logger.error(f"    Lookup attempts failed: strategy_symbol_id={self._strategy_symbol_id}, db_symbol={db_symbol}, strategy_id={getattr(self.cfg, 'strategy_id', None)}")
                    raise ValueError(f"Smart levels enabled but no configuration found for symbol '{db_symbol}' (original: '{self.symbol}'). Cannot proceed without smart level data.")
                
                # Process smart levels - expect only one active level per symbol
                if smart_levels:
                    active_level = None
                    
                    for level in smart_levels:
                        if not isinstance(level, dict):
                            logger.warning(f"⚠️ Invalid smart level data type: {type(level)}, expected dict")
                            continue
                            
                        # Check required fields
                        required_fields = ['name', 'entry_level', 'is_active']
                        missing_fields = [field for field in required_fields if field not in level]
                        if missing_fields:
                            logger.warning(f"⚠️ Smart level missing required fields {missing_fields}: {level}")
                            continue
                            
                        # Only include active levels
                        if not level.get('is_active', False):
                            logger.debug(f"Skipping inactive smart level: {level.get('name')}")
                            continue
                        
                        # Take the first active level (should be only one per symbol)
                        if active_level is None:
                            active_level = level
                            logger.info(f"✅ Active smart level found: '{level['name']}'")
                        else:
                            logger.warning(f"⚠️ Multiple active smart levels found for {db_symbol}! Using first: '{active_level['name']}', skipping: '{level['name']}'")
                    
                    # Cache the single smart level
                    self._smart_level = active_level
                    
                    if active_level:
                        logger.info(f"✅ Smart level loaded for {db_symbol} using {lookup_method}")
                        
                        # Use summary method for comprehensive logging
                        summary = self.get_smart_level_summary()
                        level_info = summary['level']
                        logger.info(f"📊 Smart Level Summary: '{level_info['name']}'")
                        logger.info(f"    Entry Level: {level_info['entry_level']}")
                        logger.info(f"    Targets: Bullish={level_info['bullish_target']}, Bearish={level_info['bearish_target']}")
                        logger.info(f"    Initial Lots: CE={level_info['initial_lot_ce']}, PE={level_info['initial_lot_pe']}")
                        logger.info(f"    Remaining Lots: CE={level_info['remaining_lot_ce']}, PE={level_info['remaining_lot_pe']}")
                        logger.info(f"    Buy Enabled: CE={level_info['ce_buy_enabled']}, PE={level_info['pe_buy_enabled']}")
                        logger.info(f"    Sell Enabled: CE={level_info['ce_sell_enabled']}, PE={level_info['pe_sell_enabled']}")
                        logger.info(f"    Limits: Max Trades={level_info['max_trades']}, Max Loss={level_info['max_loss_trades']}")
                        if level_info['pullback_percentage']:
                            logger.info(f"    Pullback: {level_info['pullback_percentage']}%")
                        if level_info['notes']:
                            logger.info(f"    Notes: {level_info['notes']}")
                    else:
                        # FAIL THE SETUP when smart levels are enabled but no active level found
                        error_msg = f"❌ Smart levels are ENABLED but no ACTIVE configuration found for {self.symbol}!"
                        logger.error(error_msg)
                        logger.error(f"    Found {len(smart_levels)} smart level records but none are active")
                        raise ValueError(f"Smart levels enabled but no active configuration found for symbol '{self.symbol}'. Cannot proceed without active smart level data.")
                    
        except Exception as e:
            logger.error(f"❌ Error loading smart levels: {e}", exc_info=True)
            self._smart_level = None  # Ensure cache is cleared on error
            # Re-raise the exception to fail the setup
            raise

    def get_active_smart_level(self):
        """
        Get currently cached smart level.
        
        Returns:
            dict: Smart level dict if available, None otherwise
        """
        return self._smart_level

    def get_primary_smart_level(self):
        """
        Get the primary smart level for validation (same as get_active_smart_level).
        
        Returns:
            dict: Smart level if available, None otherwise
        """
        return self._smart_level

    def find_smart_level_by_name(self, name: str):
        """
        Find the smart level by name (since we only have one).
        
        Args:
            name: Smart level name to search for
            
        Returns:
            dict: Smart level if name matches, None otherwise
        """
        if self._smart_level and self._smart_level.get('name') == name:
            return self._smart_level
        return None

    async def reload_smart_levels(self):
        """
        Force reload smart level from database.
        Useful when smart level is updated during runtime.
        
        Returns:
            bool: True if reload was successful, False otherwise
        """
        try:
            logger.info("🔄 Force reloading smart level from database")
            await self.load_smart_levels()
            smart_level_name = self._smart_level.get('name') if self._smart_level else 'None'
            logger.info(f"✅ Smart level reloaded: {smart_level_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to reload smart level: {e}", exc_info=True)
            return False

    def get_smart_level_summary(self):
        """
        Get a comprehensive summary of loaded smart level for debugging.
        
        Returns:
            dict: Complete summary information about smart level
        """
        if not self._smart_level:
            return {
                'enabled': self._smart_levels_enabled,
                'loaded': False,
                'level': None
            }
        
        return {
            'enabled': self._smart_levels_enabled,
            'loaded': True,
            'level': {
                # Basic Info
                'id': self._smart_level.get('id'),
                'name': self._smart_level.get('name'),
                'strategy_symbol_id': self._smart_level.get('strategy_symbol_id'),
                'is_active': self._smart_level.get('is_active'),
                
                # Trading Levels
                'entry_level': self._smart_level.get('entry_level'),
                'bullish_target': self._smart_level.get('bullish_target'),
                'bearish_target': self._smart_level.get('bearish_target'),
                
                # Initial Lots
                'initial_lot_ce': self._smart_level.get('initial_lot_ce', 0),
                'initial_lot_pe': self._smart_level.get('initial_lot_pe', 0),
                
                # Remaining Lots  
                'remaining_lot_ce': self._smart_level.get('remaining_lot_ce', 0),
                'remaining_lot_pe': self._smart_level.get('remaining_lot_pe', 0),
                
                # Enable/Disable Flags
                'ce_buy_enabled': self._smart_level.get('ce_buy_enabled', False),
                'ce_sell_enabled': self._smart_level.get('ce_sell_enabled', False),
                'pe_buy_enabled': self._smart_level.get('pe_buy_enabled', False),
                'pe_sell_enabled': self._smart_level.get('pe_sell_enabled', False),
                
                # Trading Limits
                'max_trades': self._smart_level.get('max_trades'),
                'max_loss_trades': self._smart_level.get('max_loss_trades'),
                'pullback_percentage': self._smart_level.get('pullback_percentage'),
                'strict_entry_vs_swing_check': self._smart_level.get('strict_entry_vs_swing_check', False),
                
                # Metadata
                'notes': self._smart_level.get('notes'),
                'created_at': self._smart_level.get('created_at'),
                'updated_at': self._smart_level.get('updated_at'),
                
                # Strategy Info (if available from join)
                'symbol': self._smart_level.get('symbol'),
                'strategy_id': self._smart_level.get('strategy_id'),
                'strategy_name': self._smart_level.get('strategy_name'),
                'strategy_key': self._smart_level.get('strategy_key')
            }
        }

    def get_smart_level_info_string(self):
        """
        Get a formatted string representation of smart level for logging.
        
        Returns:
            str: Formatted smart level information
        """
        if not self._smart_level:
            return "Smart Level: Not loaded"
        
        summary = self.get_smart_level_summary()
        level = summary['level']
        
        info_lines = [
            f"Smart Level: '{level['name']}'",
            f"  Entry: {level['entry_level']}",
            f"  Targets: Bullish={level['bullish_target']}, Bearish={level['bearish_target']}",
            f"  Initial: CE={level['initial_lot_ce']}, PE={level['initial_lot_pe']}",
            f"  Remaining: CE={level['remaining_lot_ce']}, PE={level['remaining_lot_pe']}",
            f"  Buy Enabled: CE={level['ce_buy_enabled']}, PE={level['pe_buy_enabled']}",
            f"  Sell Enabled: CE={level['ce_sell_enabled']}, PE={level['pe_sell_enabled']}",
            f"  Strict Entry vs Swing Check: {level['strict_entry_vs_swing_check']}"
        ]
        
        if level['max_trades']:
            info_lines.append(f"  Max Trades: {level['max_trades']}")
        if level['max_loss_trades']:
            info_lines.append(f"  Max Loss Trades: {level['max_loss_trades']}")
        if level['pullback_percentage']:
            info_lines.append(f"  Pullback: {level['pullback_percentage']}%")
        if level['notes']:
            info_lines.append(f"  Notes: {level['notes']}")
            
        return "\n".join(info_lines)

    def is_smart_levels_enabled(self):
        """
        Check if smart level is enabled for this strategy.
        
        Returns:
            bool: True if smart level is enabled and available
        """
        enabled = self._smart_levels_enabled and self._smart_level is not None
        
        if not self._smart_levels_enabled:
            logger.debug("Smart levels not enabled in configuration")
        elif self._smart_level is None:
            logger.debug("Smart levels enabled but no active level loaded")
        else:
            logger.debug(f"Smart level enabled: '{self._smart_level.get('name')}'")
            
        return enabled

    async def validate_smart_level_entry(self, breakout_type, spot_price, direction, swing_high=None, swing_low=None):
        """
        Validate entry against smart levels with comprehensive logging.
        
        Business Logic:
        - Initial Entry: Uses initial_lot_ce/pe for quantity calculation (trade execution)
        - Re-entry: Uses remaining_lot_ce/pe for quantity calculation (pullback scenarios)
        - Quantity = (initial_lot_ce/pe OR remaining_lot_ce/pe) * ce_lot_qty/pe_lot_qty
        - Re-entry mode is controlled by self._is_re_entry_mode instance variable
        
        Args:
            breakout_type: "CE" or "PE" (reusing existing terminology)
            spot_price: Current spot price from last_candle["close"] 
            direction: "UP" or "DOWN" (reusing existing terminology)
            swing_high: Latest swing high level for strict entry check (optional)
            swing_low: Latest swing low level for strict entry check (optional)
            
        Returns:
            (is_valid: bool, smart_level_data: dict, smart_lot_qty: int)
        """
        try:
            entry_mode = "RE-ENTRY" if self._is_re_entry_mode else "INITIAL ENTRY"
            logger.info(f"🔍 Smart Level Validation ({entry_mode}): breakout_type={breakout_type}, spot_price={spot_price}, direction={direction}")
            
            if not self.is_smart_levels_enabled():
                logger.warning(f"Smart levels validation called but smart levels not enabled or no active level (mode: {entry_mode})")
                return False, None, 0
            
            # Get the smart level (single dict)
            smart_level = self._smart_level
            if smart_level is None:
                logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): No smart level available")
                return False, None, 0
            
            entry_level = smart_level.get('entry_level')
            if entry_level is None:
                logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): entry_level is None for smart level '{smart_level.get('name')}'")
                return False, smart_level, 0
            
            # Log the smart level being validated using summary method
            summary = self.get_smart_level_summary()
            level_info = summary['level']
            logger.debug(f"🔍 Validating Smart Level Summary ({entry_mode}):")
            logger.debug(f"    Name: '{level_info['name']}', Entry: {level_info['entry_level']}")
            logger.debug(f"    Targets: Bullish={level_info['bullish_target']}, Bearish={level_info['bearish_target']}")
            logger.debug(f"    CE: buy_enabled={level_info['ce_buy_enabled']}, initial_lots={level_info['initial_lot_ce']}, remaining_lots={level_info['remaining_lot_ce']}")
            logger.debug(f"    PE: buy_enabled={level_info['pe_buy_enabled']}, initial_lots={level_info['initial_lot_pe']}, remaining_lots={level_info['remaining_lot_pe']}")
            logger.debug(f"    Limits: Max Trades={level_info['max_trades']}, Max Loss={level_info['max_loss_trades']}")
            
            # Position validation: for UP trend, spot should be above entry_level; for DOWN trend, below
            if direction == "UP" and float(spot_price) > float(entry_level):
                logger.info(f"✅ Smart Level Position Check ({entry_mode}, UP trend): spot_price={spot_price} > entry_level={entry_level}")
            elif direction == "DOWN" and float(spot_price) < float(entry_level):
                logger.info(f"✅ Smart Level Position Check ({entry_mode}, DOWN trend): spot_price={spot_price} < entry_level={entry_level}")
            else:
                logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): Position check failed - spot_price={spot_price} vs entry_level={entry_level} for {direction} trend")
                return False, smart_level, 0
            
            # Extract smart level data for validation using summary method
            summary = self.get_smart_level_summary()
            level_info = summary['level']
            entry_level = float(level_info['entry_level'])
            bullish_target = level_info['bullish_target']
            bearish_target = level_info['bearish_target'] 
            ce_buy_enabled = level_info['ce_buy_enabled']
            pe_buy_enabled = level_info['pe_buy_enabled']
            strict_entry_vs_swing_check = level_info['strict_entry_vs_swing_check']
            
            logger.info(f"📊 Smart Level Validation Data ({entry_mode}):")
            logger.info(f"    Name: '{level_info['name']}', Entry: {entry_level}")
            logger.info(f"    Targets: Bullish={bullish_target}, Bearish={bearish_target}")
            logger.info(f"    CE: enabled={ce_buy_enabled}")
            logger.info(f"    PE: enabled={pe_buy_enabled}")
            logger.info(f"    Strict Entry vs Swing Check: {strict_entry_vs_swing_check}")
            
            # Validation 0: Strict Entry vs Swing Check (if enabled)
            if strict_entry_vs_swing_check:
                logger.info(f"🔍 Strict Entry vs Swing Check ENABLED ({entry_mode}) - validating swing levels")
                
                if direction == "UP":
                    # For UP trend, swing high should be above entry_level
                    if swing_high is None:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}): swing_high is None for UP trend validation")
                        return False, smart_level, 0
                    
                    swing_high_price = swing_high.get('price') if isinstance(swing_high, dict) else swing_high
                    if swing_high_price is None:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}): swing_high_price is None for UP trend")
                        return False, smart_level, 0
                    
                    if float(swing_high_price) > float(entry_level):
                        logger.info(f"✅ Strict Entry vs Swing Check PASSED ({entry_mode}, UP trend): swing_high={swing_high_price} > entry_level={entry_level}")
                    else:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}, UP trend): swing_high={swing_high_price} <= entry_level={entry_level}")
                        logger.warning(f"    📊 Levels Summary: spot_price={spot_price}, swing_high={swing_high_price}, entry_level={entry_level}")
                        return False, smart_level, 0
                        
                elif direction == "DOWN":
                    # For DOWN trend, swing low should be below entry_level
                    if swing_low is None:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}): swing_low is None for DOWN trend validation")
                        return False, smart_level, 0
                    
                    swing_low_price = swing_low.get('price') if isinstance(swing_low, dict) else swing_low
                    if swing_low_price is None:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}): swing_low_price is None for DOWN trend")
                        return False, smart_level, 0
                    
                    if float(swing_low_price) < float(entry_level):
                        logger.info(f"✅ Strict Entry vs Swing Check PASSED ({entry_mode}, DOWN trend): swing_low={swing_low_price} < entry_level={entry_level}")
                    else:
                        logger.warning(f"🚫 Strict Entry vs Swing Check FAILED ({entry_mode}, DOWN trend): swing_low={swing_low_price} >= entry_level={entry_level}")
                        logger.warning(f"    📊 Levels Summary: spot_price={spot_price}, swing_low={swing_low_price}, entry_level={entry_level}")
                        return False, smart_level, 0
                        
                logger.info(f"✅ Strict Entry vs Swing Check validation completed successfully ({entry_mode})")
            else:
                logger.debug(f"Strict Entry vs Swing Check DISABLED ({entry_mode}) - skipping swing level validation")
            
            # Validation 1: Target Boundary Check
            if direction == "UP" and bullish_target is not None:
                if float(spot_price) >= float(bullish_target):
                    logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): UP trend spot_price={spot_price} >= bullish_target={bullish_target} (no room to move up)")
                    return False, smart_level, 0
                else:
                    logger.info(f"✅ Target Boundary Check ({entry_mode}, UP): spot_price={spot_price} < bullish_target={bullish_target} (room to move up)")
            
            if direction == "DOWN" and bearish_target is not None:
                if float(spot_price) <= float(bearish_target):
                    logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): DOWN trend spot_price={spot_price} <= bearish_target={bearish_target} (no room to move down)")
                    return False, smart_level, 0
                else:
                    logger.info(f"✅ Target Boundary Check ({entry_mode}, DOWN): spot_price={spot_price} > bearish_target={bearish_target} (room to move down)")
            
            # Validation 2: Direction Enable Check
            if breakout_type == "CE" and not ce_buy_enabled:
                logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): CE buy signal detected but ce_buy_enabled={ce_buy_enabled} for level '{smart_level.get('name')}'")
                return False, smart_level, 0
            
            if breakout_type == "PE" and not pe_buy_enabled:
                logger.warning(f"🚫 Smart Level Validation FAILED ({entry_mode}): PE buy signal detected but pe_buy_enabled={pe_buy_enabled} for level '{smart_level.get('name')}'")
                return False, smart_level, 0
            
            logger.info(f"✅ Direction Enable Check ({entry_mode}): {breakout_type} buy is enabled for level '{smart_level.get('name')}'")
            
            # Validation 3: Quantity Calculation - Use appropriate lots based on entry mode
            if self._is_re_entry_mode:
                # RE-ENTRY MODE: Use remaining lots
                remaining_lot_ce = level_info['remaining_lot_ce']
                remaining_lot_pe = level_info['remaining_lot_pe']
                
                if breakout_type == "CE":
                    # Check availability for re-entry
                    if remaining_lot_ce <= 0:
                        logger.warning(f"🚫 Smart Level Validation FAILED (RE-ENTRY): remaining_lot_ce={remaining_lot_ce} <= 0, no lots available for CE re-entry")
                        return False, smart_level, 0
                    
                    # Calculate smart level quantity using REMAINING lots: remaining_lot_ce * ce_lot_qty
                    original_ce_lot_qty = self.ce_lot_qty
                    smart_lot_qty = remaining_lot_ce * original_ce_lot_qty
                    logger.info(f"💰 Quantity Calculation (RE-ENTRY CE): remaining_lot_ce={remaining_lot_ce} * ce_lot_qty={original_ce_lot_qty} = smart_lot_qty={smart_lot_qty}")
                                
                elif breakout_type == "PE":
                    # Check availability for re-entry
                    if remaining_lot_pe <= 0:
                        logger.warning(f"🚫 Smart Level Validation FAILED (RE-ENTRY): remaining_lot_pe={remaining_lot_pe} <= 0, no lots available for PE re-entry")
                        return False, smart_level, 0
                    
                    # Calculate smart level quantity using REMAINING lots: remaining_lot_pe * pe_lot_qty  
                    original_pe_lot_qty = self.pe_lot_qty
                    smart_lot_qty = remaining_lot_pe * original_pe_lot_qty
                    logger.info(f"💰 Quantity Calculation (RE-ENTRY PE): remaining_lot_pe={remaining_lot_pe} * pe_lot_qty={original_pe_lot_qty} = smart_lot_qty={smart_lot_qty}")
                    
            else:
                # INITIAL ENTRY MODE: Use initial lots (No availability check needed for initial entry)
                initial_lot_ce = level_info['initial_lot_ce']
                initial_lot_pe = level_info['initial_lot_pe']
                
                if breakout_type == "CE":
                    # Calculate smart level quantity using INITIAL lots: initial_lot_ce * ce_lot_qty
                    original_ce_lot_qty = self.ce_lot_qty
                    smart_lot_qty = initial_lot_ce * original_ce_lot_qty
                    logger.info(f"💰 Quantity Calculation (INITIAL CE): initial_lot_ce={initial_lot_ce} * ce_lot_qty={original_ce_lot_qty} = smart_lot_qty={smart_lot_qty}")
                                
                elif breakout_type == "PE":
                    # Calculate smart level quantity using INITIAL lots: initial_lot_pe * pe_lot_qty  
                    original_pe_lot_qty = self.pe_lot_qty
                    smart_lot_qty = initial_lot_pe * original_pe_lot_qty
                    logger.info(f"💰 Quantity Calculation (INITIAL PE): initial_lot_pe={initial_lot_pe} * pe_lot_qty={original_pe_lot_qty} = smart_lot_qty={smart_lot_qty}")
                
            logger.info(f"🎉 Smart Level Validation PASSED ({entry_mode}): All checks successful for {breakout_type} {direction} trade with smart_lot_qty={smart_lot_qty}")
            return True, smart_level, smart_lot_qty
            
        except Exception as e:
            logger.error(f"Error in validate_smart_level_entry: {e}", exc_info=True)
            return False, None, 0

    def select_strikes_from_pivots(self):
        """
        Select option strikes for entry based on latest swing high/low pivots.
        Returns a list of strike symbols to monitor/trade.
        """
        if not self._hh_levels or not self._ll_levels:
            logger.warning("No HH/LL pivots available for strike selection.")
            return []
        latest_hh = self._hh_levels[-1]["zz"]
        latest_ll = self._ll_levels[-1]["zz"]
        premium_selection = self.trade.get("premium_selection", {})
        atm = round((latest_hh + latest_ll) / 2, -2)
        strikes = [atm]
        otm_offset = premium_selection.get("otm_offset", 100)
        strikes.append(atm + otm_offset)
        strikes.append(atm - otm_offset)
        return [str(s) for s in strikes]

    async def process_cycle(self) -> Optional[dict]:
        """
        Modularized process_cycle: fetches data, evaluates signal, places order, and confirms entry.
        All signal logic is moved to evaluate_signal.
        Includes re-entry logic integration for pullback scenarios.
        """
        try:
            if self._setup_failed:
                logger.warning("process_cycle aborted: setup failed.")
                return None
            
            # Check trade limits before proceeding with any new trades
            can_trade, limit_reason = await self.check_trade_limits()
            if not can_trade:
                logger.warning(f"process_cycle aborted: {limit_reason}")
                return None
            
            logger.debug(f"Trade limits check passed: {limit_reason}")

            # Sync open positions from DB before proceeding
            await self.sync_open_positions()
            
            # Modified position check for re-entry logic
            has_open_positions = self._positions and any(self._positions.values())
            
            if has_open_positions:
                logger.info("🔄 Open position(s) exist - checking for re-entry opportunities")
                
                # Check for re-entry logic if smart levels are enabled
                if self.is_smart_levels_enabled():
                    re_entry_result = await self.check_re_entry_logic()
                    if re_entry_result:
                        logger.info(f"✅ Re-entry order placed: {re_entry_result}")
                        return re_entry_result
                    else:
                        logger.debug("No re-entry opportunities detected")
                else:
                    logger.debug("Re-entry logic skipped - smart levels not enabled")
                
                # Skip initial entry processing if positions exist
                logger.info("Skipping initial entry processing due to existing positions")
                return None

            # Continue with existing initial entry logic
            logger.info("🔄 No open positions - processing initial entry logic")

            # 1. Fetch latest confirm timeframe data (1-min by default)
            confirm_history_dict = await self.fetch_history_data(
                self.dp, [self.symbol], self.confirm_minutes
            )
            confirm_df = confirm_history_dict.get(self.symbol)
            if confirm_df is not None and not isinstance(confirm_df, pd.DataFrame):
                confirm_df = pd.DataFrame(confirm_df)
            # Defensive check
            if confirm_df is None or len(confirm_df) < 2:
                logger.info("Not enough confirm_df data for breakout evaluation.")
                return None
            # Only use closed candles
            now = pd.Timestamp.now(tz="Asia/Kolkata").floor("min")
            df = confirm_df.copy()
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp")
                df = df.set_index("timestamp")
            else:
                logger.error("confirm_df missing 'timestamp' column.")
                return None
            if df.index.tz is None:
                df.index = df.index.tz_localize("Asia/Kolkata")
            df = df[df.index < now].copy()
            if df is None or len(df) < 2:
                logger.info("Not enough closed 1-min candles for breakout evaluation.")
                return None
            confirm_df_sorted = df.reset_index()

            # 2. Fetch entry timeframe candles
            entry_history_dict = await self.fetch_history_data(
                self.dp, [self.symbol], self.entry_minutes
            )
            entry_df = entry_history_dict.get(self.symbol)
            if entry_df is not None and not isinstance(entry_df, pd.DataFrame):
                entry_df = pd.DataFrame(entry_df)
            if entry_df is None or len(entry_df) < 10:
                logger.info("Not enough entry_df data for swing high/low detection.")
                return None
            logger.debug(f"Fetched {len(entry_df)} entry timeframe candles for {self.entry_minutes}-min interval.")
            logger.debug(f"Entry timeframe candles sample:\n{entry_df.tail(3)}")
            # 3. Evaluate signal using modular method
            signal = await self.evaluate_signal(entry_df, confirm_df_sorted, self.trade)
            if not signal:
                logger.info("No trade signal detected for this cycle.")
                return None
            logger.info(f"Trade signal detected: {signal}")

            # 4. Place order if signal
            order_info = await self.process_order(signal, confirm_df_sorted, signal.symbol)
            
            # Log atomic check configuration for transparency
            logger.info(f"🔍 Atomic confirmation setting: enabled={self.confirm_atomic}")
            
            if self.confirm_atomic:
                logger.info("🕐 Atomic confirmation ENABLED - verifying entry on next candle close.")
                if order_info:
                    # Check if all broker_responses are terminal (FAILED, CANCELLED, REJECTED)
                    broker_responses = order_info.get('broker_responses') if order_info else None
                    failed_statuses = {"FAILED", "CANCELLED", "REJECTED"}
                    all_failed = False
                    if broker_responses and isinstance(broker_responses, dict):
                        statuses = [str(resp.get('status')) if resp else None for resp in broker_responses.values()]
                        statuses = [s.split('.')[-1].replace("'", "").replace(">", "").upper() if s else None for s in statuses]
                        if statuses and all(s in failed_statuses for s in statuses if s):
                            all_failed = True
                    if all_failed:
                        logger.error(f"❌ Order placement failed for all brokers, skipping atomic confirmation: {order_info}")
                        return order_info
                    logger.info(f"✅ Order placed successfully: {order_info}")
                    logger.info(f"⏳ Awaiting atomic confirmation on next entry candle close (entry_minutes={self.entry_minutes})")
                    # Wait for next entry candle to confirm breakout
                    await strategy_utils.wait_for_next_candle(self.entry_minutes)
                    # Fetch fresh entry_df for confirmation
                    entry_history_dict2 = await self.fetch_history_data(
                        self.dp, [self.symbol], self.entry_minutes
                    )
                    entry_df2 = entry_history_dict2.get(self.symbol)
                    if entry_df2 is not None and not isinstance(entry_df2, pd.DataFrame):
                        entry_df2 = pd.DataFrame(entry_df2)
                    if entry_df2 is None or len(entry_df2) < 2:
                        logger.warning("Not enough entry_df data for atomic confirmation after order.")
                        # Unable to confirm, exit order for safety
                        await self.order_manager.exit_order(order_info.get("order_id") or order_info.get("id"), exit_reason="Atomic confirmation failed",check_live_status=True)
                        
                        # Update status to EXIT_ATOMIC_FAILED_PENDING
                        from algosat.common import constants
                        logger.info(f"Entry confirmation failed due to missing data. Order exited: {order_info}. Updating status to EXIT_ATOMIC_FAILED_PENDING")
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_info.get("order_id") or order_info.get("id"),
                            status=constants.TRADE_STATUS_EXIT_ATOMIC_FAILED_PENDING
                        )
                        
                        # await self.exit_order(order_info.get("order_id") or order_info.get("id"))
                        logger.info(f"Entry confirmation failed due to missing data. Order exited: {order_info}")
                        return order_info
                    entry_df2_sorted = entry_df2.sort_values("timestamp")
                    latest_entry = entry_df2_sorted.iloc[-1]
                    # Confirm based on the breakout direction
                    confirm_last_close = confirm_df.iloc[-1]["close"] if "close" in confirm_df.columns else None
                    if (signal.signal_direction == "UP" and latest_entry["close"] > confirm_last_close) or \
                    (signal.signal_direction == "DOWN" and latest_entry["close"] < confirm_last_close):
                        logger.info(f"✅ Breakout CONFIRMED after atomic check: {signal.signal_direction} breakout validated")
                        logger.info(f"📊 Confirmation details: latest_close={latest_entry['close']}, confirm_close={confirm_last_close}, direction={signal.signal_direction}")
                        
                        # Calculate and store pullback level for re-entry logic - ONLY if smart levels enabled
                        if self.is_smart_levels_enabled():
                            pullback_success = await self.calculate_and_store_pullback_level(order_info, signal)
                            if pullback_success:
                                logger.info(f"✅ Pullback level stored successfully for order_id={order_info.get('order_id')}")
                            else:
                                logger.warning(f"⚠️ Failed to store pullback level for order_id={order_info.get('order_id')}")
                        else:
                            logger.debug("🔄 Pullback calculation skipped - smart levels not enabled")
                            
                        return order_info
                    else:
                        logger.warning(f"❌ Breakout FAILED atomic confirmation: {signal.signal_direction} breakout not validated")
                        logger.warning(f"📊 Failure details: latest_close={latest_entry['close']}, confirm_close={confirm_last_close}, direction={signal.signal_direction}")
                        logger.info("🔄 Exiting order due to failed atomic confirmation")
                        await self.order_manager.exit_order(order_info.get("order_id") or order_info.get("id"), exit_reason="Atomic confirmation failed", check_live_status=True)
                        
                        # Update status to EXIT_ATOMIC_FAILED_PENDING
                        from algosat.common import constants
                        logger.info(f"Entry confirmation failed (candle close {latest_entry['close']} not confirming breakout). Order exited: {order_info}. Updating status to EXIT_ATOMIC_FAILED_PENDING")
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_info.get("order_id") or order_info.get("id"),
                            status=constants.TRADE_STATUS_EXIT_ATOMIC_FAILED_PENDING
                        )
                        # await self.exit_order(order_info.get("order_id") or order_info.get("id"))
                        logger.info(f"Entry confirmation failed (candle close {latest_entry['close']} not confirming breakout). Order exited: {order_info}")
                        return order_info
                else:
                    logger.error("Order placement failed in dual timeframe breakout.")
                    return None
            else:
                logger.info("🚀 Atomic confirmation DISABLED - proceeding without verification.")
                logger.info(f"✅ Order placement completed: {order_info}")
                
                # Calculate and store pullback level for re-entry logic - ONLY if smart levels enabled (even without atomic check)
                if self.is_smart_levels_enabled() and order_info:
                    pullback_success = await self.calculate_and_store_pullback_level(order_info, signal)
                    if pullback_success:
                        logger.info(f"✅ Pullback level stored successfully for order_id={order_info.get('order_id')}")
                    else:
                        logger.warning(f"⚠️ Failed to store pullback level for order_id={order_info.get('order_id')}")
                else:
                    logger.debug("🔄 Pullback calculation skipped - smart levels not enabled or order_info unavailable")
                
                return order_info
        except Exception as e:
            logger.error(f"Error in process_cycle: {e}", exc_info=True)
            return None


    async def fetch_history_data(self, broker, symbols, interval_minutes):
        """
        Modular history fetch for spot/option data, returns dict[symbol] = pd.DataFrame.
        All datetimes should be timezone-aware (IST).
        Calculates from_date and to_date internally based on config and current time.
        """
        from algosat.common import strategy_utils
        try:
            current_date = pd.Timestamp.now(tz="Asia/Kolkata")
            back_days = calculate_backdate_days(interval_minutes)
            trade_day = get_trade_day(current_date - timedelta(days=back_days))
            start_date = localize_to_ist(datetime.combine(trade_day, time(9, 15)))
            current_end_date = localize_to_ist(datetime.combine(current_date, get_ist_datetime().time()))
            # if interval_minutes == 1:
            #     current_end_date = current_end_date.replace(hour=10, minute=15)  # Align to minute
            # elif interval_minutes == 5:
            #     current_end_date = current_end_date.replace(hour=10, minute=20)
            # current_end_date = current_end_date.replace(day=18)
            broker_name = self.dp.get_current_broker_name()
            end_date = calculate_end_date(current_end_date, interval_minutes, broker_name)
            # end_date = end_date.replace(day=15,hour=10, minute=48, second=0, microsecond=0)  # Market close time
            logger.info(f"Fetching history for {symbols} from {start_date} to {end_date} interval {interval_minutes}m")
            # history_dict = await strategy_utils.fetch_instrument_history(
            #     broker, symbols, start_date, end_date, interval_minutes, ins_type=self.instrument, cache=False
            # )
            
            history_data = await strategy_utils.fetch_instrument_history(
                self.dp,
                [self.symbol],
                from_date=start_date,
                to_date=end_date,
                interval_minutes=interval_minutes,
                ins_type="",
                cache=False
            )
            
            return history_data
        except Exception as e:
            logger.error(f"Error in fetch_history_data: {e}", exc_info=True)
            return {}

    async def check_re_entry_logic(self) -> Optional[dict]:
        """
        Check for re-entry opportunities when existing positions are found.
        This implements pullback-based re-entry logic using smart levels configuration.
        
        Re-entry Logic:
        1. For each open position, check if pullback has occurred (50% retracement)
        2. If pullback touched, wait for price to move back toward original direction
        3. Place re-entry order using remaining lots from smart level
        4. Update re-entry tracking in database
        
        Returns:
            dict: Order info if re-entry placed, None otherwise
        """
        try:
            logger.info("🔄 Starting re-entry logic check for existing positions")
            
            if not self.is_smart_levels_enabled():
                logger.debug("❌ Re-entry logic skipped: Smart levels not enabled")
                return None
            
            # Get smart level configuration
            smart_level = self.get_active_smart_level()
            if not smart_level:
                logger.debug("❌ Re-entry logic skipped: No active smart level")
                return None
            
            pullback_percentage = smart_level.get('pullback_percentage')
            if not pullback_percentage or pullback_percentage <= 0:
                logger.debug(f"❌ Re-entry logic skipped: Invalid pullback_percentage={pullback_percentage}")
                return None
            
            logger.info(f"📊 Re-entry logic parameters: pullback_percentage={pullback_percentage}%")
            
            # Process each open position for re-entry opportunities
            for symbol, position_list in self._positions.items():
                for position in position_list:
                    order_id = position.get('id') or position.get('order_id')
                    
                    # Check if re-entry is applicable for this position
                    re_entry_result = await self._check_position_re_entry(position, pullback_percentage)
                    if re_entry_result:
                        logger.info(f"✅ Re-entry opportunity found for order_id={order_id}")
                        return re_entry_result
                    else:
                        logger.debug(f"No re-entry opportunity for order_id={order_id}")
            
            logger.debug("No re-entry opportunities found for any position")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error in check_re_entry_logic: {e}", exc_info=True)
            return None
    
    async def _check_position_re_entry(self, position, pullback_percentage) -> Optional[dict]:
        """
        Check specific position for re-entry opportunity.
        
        Args:
            position: Position dict from database
            pullback_percentage: Pullback percentage from smart level config
            
        Returns:
            dict: Order info if re-entry placed, None otherwise
        """
        try:
            order_id = position.get('id') or position.get('order_id')
            signal_direction = position.get('signal_direction', '').upper()
            entry_spot_price = position.get('entry_spot_price')
            target_spot_level = position.get('target_spot_level')
            
            logger.info(f"🔍 Checking re-entry for order_id={order_id}, direction={signal_direction}, entry_price={entry_spot_price}, target={target_spot_level}")
            
            if not all([signal_direction, entry_spot_price, target_spot_level]):
                logger.warning(f"❌ Missing required data for re-entry check: direction={signal_direction}, entry_price={entry_spot_price}, target={target_spot_level}")
                return None
            
            # Check if re-entry tracking exists
            from algosat.core.re_entry_db_helpers import get_re_entry_tracking, create_re_entry_tracking, update_pullback_touched, update_re_entry_attempted
            
            # Get smart level for pullback configuration
            smart_level = self.get_active_smart_level()
            if not smart_level:
                logger.warning(f"❌ Re-entry check failed - no active smart level available for order_id={order_id}")
                return None
            
            re_entry_record = await get_re_entry_tracking(order_id)
            
            # If no re-entry record exists, try to calculate and create it
            if not re_entry_record:
                logger.info(f"🔄 No re-entry tracking found for order_id={order_id}, attempting to calculate pullback level")
                
                # Get pullback percentage from smart level - required for re-entry calculation
                pullback_percentage = smart_level.get('pullback_percentage')
                
                if not pullback_percentage or pullback_percentage <= 0:
                    logger.error(f"❌ Re-entry check failed - invalid or missing pullback_percentage in smart level for order_id={order_id}")
                    return None
                
                # Get swing levels from position data
                entry_spot_swing_high = position.get('entry_spot_swing_high')
                entry_spot_swing_low = position.get('entry_spot_swing_low')
                
                # Validate that we have both swing levels for distance calculation
                if not entry_spot_swing_high or not entry_spot_swing_low:
                    logger.error(f"❌ Cannot recalculate pullback - missing swing levels. High: {entry_spot_swing_high}, Low: {entry_spot_swing_low}")
                    return None
                
                # Calculate pullback level using swing distance
                pullback_factor = pullback_percentage / 100.0
                swing_high = float(entry_spot_swing_high)
                swing_low = float(entry_spot_swing_low)
                
                # Calculate swing distance (high - low)
                swing_distance = swing_high - swing_low
                pullback_distance = swing_distance * pullback_factor
                
                logger.info(f"📊 Re-entry Swing Range Analysis:")
                logger.info(f"    Swing High: {swing_high}")
                logger.info(f"    Swing Low: {swing_low}")
                logger.info(f"    Swing Distance: {swing_distance}")
                logger.info(f"    Pullback %: {pullback_percentage}%")
                logger.info(f"    Pullback Distance: {pullback_distance}")
                
                if signal_direction == "UP":
                    # CE trade: Pullback is percentage down from swing high based on swing distance
                    pullback_level = swing_high - pullback_distance
                    logger.info(f"📈 Recalculating CE pullback: {swing_high} - {pullback_distance} = {pullback_level}")
                    
                else:  # DOWN
                    # PE trade: Pullback is percentage up from swing low based on swing distance
                    pullback_level = swing_low + pullback_distance
                    logger.info(f"📉 Recalculating PE pullback: {swing_low} + {pullback_distance} = {pullback_level}")
                
                # Round to 2 decimal places
                pullback_level = round(pullback_level, 2)
                
                # Create re-entry tracking record
                success = await create_re_entry_tracking(order_id, pullback_level)
                if success:
                    logger.info(f"✅ Recalculated and stored pullback level for order_id={order_id}: {pullback_level}")
                    re_entry_record = {'pullback_touched': False, 're_entry_attempted': False}
                else:
                    logger.error(f"❌ Failed to store recalculated pullback level for order_id={order_id}")
                    return None
            
            # Calculate pullback level from re-entry record or use the one we just calculated
            pullback_level = None
            
            if re_entry_record:
                # Get stored pullback level from database
                existing_record = await get_re_entry_tracking(order_id)
                if existing_record and 'pullback_level' in existing_record:
                    pullback_level = existing_record['pullback_level']
                    logger.info(f"📊 Using stored pullback level: {pullback_level}")
                    
            if pullback_level is None:
                logger.error(f"❌ Unable to determine pullback level for order_id={order_id}")
                return None
            
            # Get current market data
            current_history = await self.fetch_history_data(self.dp, [self.symbol], self.confirm_minutes)
            current_df = current_history.get(self.symbol)
            if current_df is None or current_df.empty:
                logger.warning(f"❌ No current market data available for re-entry check")
                return None
            logger.debug(f"Current market data for re-entry check: {current_df.tail(3)}")
            current_spot_price = current_df.iloc[-1]["close"]
            logger.info(f"📊 Re-entry data: current_price={current_spot_price}, pullback_level={pullback_level}, pullback_touched={re_entry_record.get('pullback_touched')}, re_entry_attempted={re_entry_record.get('re_entry_attempted')}")
            
            # Step 1: Check if pullback level has been touched
            if not re_entry_record.get('pullback_touched', False):
                pullback_touched = False
                
                if signal_direction == "UP":
                    # UP trend: Check if price dropped to/below pullback level
                    if float(current_spot_price) <= pullback_level:
                        pullback_touched = True
                        logger.info(f"✅ Pullback TOUCHED (UP trend): current_price={current_spot_price} <= pullback_level={pullback_level}")
                else:  # DOWN trend
                    # DOWN trend: Check if price rose to/above pullback level  
                    if float(current_spot_price) >= pullback_level:
                        pullback_touched = True
                        logger.info(f"✅ Pullback TOUCHED (DOWN trend): current_price={current_spot_price} >= pullback_level={pullback_level}")
                
                if pullback_touched:
                    # Update database - pullback has been touched
                    success = await update_pullback_touched(order_id)
                    if success:
                        logger.info(f"📝 Updated pullback_touched=True for order_id={order_id}")
                    else:
                        logger.error(f"❌ Failed to update pullback_touched for order_id={order_id}")
                        return None
                else:
                    logger.debug(f"Pullback not yet touched: current_price={current_spot_price}, pullback_level={pullback_level}, direction={signal_direction}")
                    return None
            
            # Step 2: Check if re-entry should be attempted (pullback touched but not yet attempted)
            if re_entry_record.get('pullback_touched', False) and not re_entry_record.get('re_entry_attempted', False):
                logger.info(f"🎯 Pullback touched, checking for re-entry signal")
                
                # Set re-entry mode for validation
                self._is_re_entry_mode = True
                
                try:
                    # Fetch entry timeframe data for signal evaluation
                    entry_history_dict = await self.fetch_history_data(self.dp, [self.symbol], self.entry_minutes)
                    entry_df = entry_history_dict.get(self.symbol)
                    
                    # Fetch confirm timeframe data  
                    confirm_history_dict = await self.fetch_history_data(self.dp, [self.symbol], self.confirm_minutes)
                    confirm_df = confirm_history_dict.get(self.symbol)
                    
                    if entry_df is not None and not isinstance(entry_df, pd.DataFrame):
                        entry_df = pd.DataFrame(entry_df)
                    if confirm_df is not None and not isinstance(confirm_df, pd.DataFrame):
                        confirm_df = pd.DataFrame(confirm_df)
                    
                    # Proper DataFrame validation to avoid "truth value ambiguous" error
                    if (entry_df is None or entry_df.empty or len(entry_df) < 10 or 
                        confirm_df is None or confirm_df.empty or len(confirm_df) < 2):
                        logger.warning(f"❌ Insufficient data for re-entry signal evaluation")
                        return None
                    logger.debug(f"Entry DF for re-entry: {entry_df.tail(3)}")
                    logger.debug(f"Confirm DF for re-entry: {confirm_df.tail(3)}")  
                    # Process confirm_df similar to main process_cycle
                    now = pd.Timestamp.now(tz="Asia/Kolkata").floor("min")
                    df = confirm_df.copy()
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp")
                        df = df.set_index("timestamp")
                    if df.index.tz is None:
                        df.index = df.index.tz_localize("Asia/Kolkata")
                    df = df[df.index < now].copy()
                    if df.empty or len(df) < 2:
                        logger.warning(f"❌ Not enough closed candles for re-entry evaluation")
                        return None
                    confirm_df_sorted = df.reset_index()
                    
                    # Evaluate signal for re-entry
                    re_entry_signal = await self.evaluate_signal(entry_df, confirm_df_sorted, self.trade)
                    
                    if re_entry_signal:
                        logger.info(f"🎉 Re-entry signal detected for order_id={order_id}: {re_entry_signal}")
                        
                        # Validate signal direction matches original position
                        if re_entry_signal.signal_direction != signal_direction:
                            logger.warning(f"❌ Re-entry signal direction mismatch: expected={signal_direction}, got={re_entry_signal.signal_direction}")
                            return None
                        
                        # Place re-entry order
                        re_entry_order_info = await self.process_order(re_entry_signal, confirm_df_sorted, re_entry_signal.symbol)
                        
                        if re_entry_order_info:
                            re_entry_order_id = re_entry_order_info.get('order_id') or re_entry_order_info.get('id')
                            logger.info(f"📝 Re-entry order placed successfully for order_id={order_id}, re_entry_order_id={re_entry_order_id}")
                            
                            # Wait for atomic confirmation
                            import asyncio
                            await asyncio.sleep(1)  # Brief pause
                            from algosat.common import strategy_utils
                            await strategy_utils.wait_for_next_candle(self.entry_minutes)
                            
                            # Fetch fresh data for confirmation
                            entry_history_dict2 = await self.fetch_history_data(self.dp, [self.symbol], self.entry_minutes)
                            entry_df2 = entry_history_dict2.get(self.symbol)
                            if entry_df2 is not None and not isinstance(entry_df2, pd.DataFrame):
                                entry_df2 = pd.DataFrame(entry_df2)
                            
                            # Proper DataFrame validation to avoid "truth value ambiguous" error
                            if entry_df2 is None or entry_df2.empty or len(entry_df2) < 2:
                                logger.warning("❌ Not enough entry_df data for re-entry atomic confirmation")
                                await self.order_manager.exit_order(re_entry_order_info.get("order_id") or re_entry_order_info.get("id"), exit_reason="Atomic confirmation failed", check_live_status=True)
                                
                                # Update status to EXIT_ATOMIC_FAILED_PENDING
                                from algosat.common import constants
                                await self.order_manager.update_order_status_in_db(
                                    order_id=re_entry_order_info.get("order_id") or re_entry_order_info.get("id"),
                                    status=constants.TRADE_STATUS_EXIT_ATOMIC_FAILED_PENDING
                                )
                                
                                # DO NOT set re_entry_attempted=TRUE - allow retry on next cycle
                                logger.info(f"� Re-entry atomic confirmation failed due to insufficient data - re-entry will be retried on next cycle")
                                return re_entry_order_info
                            logger.debug(f"Entry DF for re-entry confirmation: {entry_df2.tail(3)}")
                            entry_df2_sorted = entry_df2.sort_values("timestamp")
                            latest_entry = entry_df2_sorted.iloc[-1]
                            confirm_last_close = confirm_df.iloc[-1]["close"] if "close" in confirm_df.columns else None
                            
                            # Atomic confirmation check
                            if (re_entry_signal.signal_direction == "UP" and latest_entry["close"] > confirm_last_close) or \
                               (re_entry_signal.signal_direction == "DOWN" and latest_entry["close"] < confirm_last_close):
                                # ✅ ATOMIC CONFIRMATION PASSED - Now mark re-entry as attempted
                                success = await update_re_entry_attempted(order_id, re_entry_order_id)
                                
                                if success:
                                    logger.info(f"✅ Re-entry atomic confirmation PASSED for order_id={order_id}")
                                    logger.info(f"📝 Updated re_entry_attempted=True for order_id={order_id}, re_entry_order_id={re_entry_order_id}")
                                    return re_entry_order_info
                                else:
                                    logger.error(f"❌ Failed to update re_entry_attempted for order_id={order_id}")
                                    return re_entry_order_info
                            else:
                                logger.info(f"❌ Re-entry atomic confirmation FAILED for order_id={order_id}")
                                await self.order_manager.exit_order(re_entry_order_info.get("order_id") or re_entry_order_info.get("id"), exit_reason="Atomic confirmation failed", check_live_status=True)
                                
                                # Update status to EXIT_ATOMIC_FAILED_PENDING
                                from algosat.common import constants
                                logger.info(f"Re-entry atomic confirmation failed (candle close {latest_entry['close']} not confirming breakout). Order exited: {re_entry_order_info}. Updating status to EXIT_ATOMIC_FAILED_PENDING")
                                await self.order_manager.update_order_status_in_db(
                                    order_id=re_entry_order_info.get("order_id") or re_entry_order_info.get("id"),
                                    status=constants.TRADE_STATUS_EXIT_ATOMIC_FAILED_PENDING
                                )
                                
                                # DO NOT set re_entry_attempted=TRUE - allow retry on next cycle
                                logger.info(f"� Re-entry atomic confirmation failed - re-entry will be retried on next cycle")
                                return re_entry_order_info
                        else:
                            logger.error(f"❌ Re-entry order placement failed for order_id={order_id}")
                            return None
                    else:
                        logger.debug(f"No re-entry signal detected for order_id={order_id}")
                        return None
                        
                finally:
                    # Reset re-entry mode
                    self._is_re_entry_mode = False
            
            else:
                logger.debug(f"Re-entry already attempted or pullback not touched for order_id={order_id}")
                return None
            
        except Exception as e:
            logger.error(f"❌ Error in _check_position_re_entry for order_id={position.get('id')}: {e}", exc_info=True)
            # Reset re-entry mode in case of error
            self._is_re_entry_mode = False
            return None

    async def calculate_and_store_pullback_level(self, order_info: dict, signal_payload: dict) -> bool:
        """
        Calculate 50% pullback level and store in re_entry_tracking table.
        Called immediately after successful order placement.
        
        Args:
            order_info: Order information from successful placement
            signal_payload: Signal information containing entry details
            
        Returns:
            bool: True if pullback level calculated and stored successfully
        """
        try:
            logger.info(f"🔄 Calculating pullback level for order_info={order_info}")
            order_id = order_info.get('order_id') or order_info.get('id')
            if not order_id:
                logger.error("❌ Cannot calculate pullback level - missing order_id")
                return False
            
            # Get pullback percentage from smart level - required for pullback calculation
            pullback_percentage = None
            
            if self.is_smart_levels_enabled():
                smart_level = self.get_active_smart_level()
                if smart_level and smart_level.get('pullback_percentage'):
                    pullback_percentage = smart_level.get('pullback_percentage')
                    logger.info(f"📊 Using smart level pullback percentage: {pullback_percentage}%")
                else:
                    logger.error(f"❌ Smart levels enabled but no pullback_percentage found in smart level configuration")
                    return False
            else:
                logger.error(f"❌ Smart levels disabled - pullback calculation requires smart level configuration")
                return False
            
            # Get signal direction from signal payload
            signal_direction = signal_payload.signal_direction
            breakout_type = signal_payload.breakout_type
            
            # Get current spot price from signal payload
            current_spot_price = signal_payload.entry_spot_price
            
            logger.info(f"🔄 Calculating pullback level for order_id={order_id}")
            logger.info(f"    Signal Direction: {signal_direction}")
            logger.info(f"    Breakout Type: {breakout_type}")
            logger.info(f"    Current Spot Price: {current_spot_price}")
            logger.info(f"    Pullback Percentage: {pullback_percentage}%")
            
            # Calculate pullback level using smart level percentage
            pullback_factor = pullback_percentage / 100.0
            
            # Get swing levels for proper pullback calculation
            entry_spot_swing_high = signal_payload.entry_spot_swing_high
            entry_spot_swing_low = signal_payload.entry_spot_swing_low
            
            # Validate that we have both swing levels for distance calculation
            if not entry_spot_swing_high or not entry_spot_swing_low:
                logger.error(f"❌ Cannot calculate pullback - missing swing levels. High: {entry_spot_swing_high}, Low: {entry_spot_swing_low}")
                return False
            
            swing_high = float(entry_spot_swing_high)
            swing_low = float(entry_spot_swing_low)
            
            # Calculate swing distance (high - low)
            swing_distance = swing_high - swing_low
            pullback_distance = swing_distance * pullback_factor
            
            logger.info(f"� Swing Range Analysis:")
            logger.info(f"    Swing High: {swing_high}")
            logger.info(f"    Swing Low: {swing_low}")
            logger.info(f"    Swing Distance: {swing_distance}")
            logger.info(f"    Pullback Percentage: {pullback_percentage}%")
            logger.info(f"    Pullback Distance: {pullback_distance}")
            
            if signal_direction == "UP":
                # CE trade: Pullback is percentage down from swing high based on swing distance
                pullback_level = swing_high - pullback_distance
                
                logger.info(f"📈 CE Trade Pullback Calculation:")
                logger.info(f"    Pullback Level: {swing_high} - {pullback_distance} = {pullback_level}")
                
            elif signal_direction == "DOWN":
                # PE trade: Pullback is percentage up from swing low based on swing distance
                pullback_level = swing_low + pullback_distance
                
                logger.info(f"📉 PE Trade Pullback Calculation:")
                logger.info(f"    Pullback Level: {swing_low} + {pullback_distance} = {pullback_level}")
                
            else:
                logger.error(f"❌ Invalid signal direction for pullback calculation: {signal_direction}")
                return False
            
            # Round pullback level to 2 decimal places for cleaner logging
            pullback_level = round(pullback_level, 2)
            
            # Store pullback level in database
            from algosat.core.re_entry_db_helpers import create_re_entry_tracking
            
            success = await create_re_entry_tracking(order_id, pullback_level)
            
            if success:
                logger.info(f"✅ Pullback level calculated and stored successfully:")
                logger.info(f"    Order ID: {order_id}")
                logger.info(f"    Direction: {signal_direction}")
                logger.info(f"    Current Price: {current_spot_price}")
                logger.info(f"    Pullback Level: {pullback_level}")
                logger.info(f"    Re-entry will trigger when price reaches {pullback_level}")
                return True
            else:
                logger.error(f"❌ Failed to store pullback level in database for order_id={order_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error calculating pullback level: {e}", exc_info=True)
            return False

    async def process_order(self, signal_payload, data, strike):
        """
        Place an order using the order_manager, passing config as in option_buy.py.
        Returns order info dict if an order is placed, else None.
        """
        if signal_payload:
            ts = data.iloc[-1].get('timestamp', 'N/A') if hasattr(data, 'iloc') and len(data) > 0 else signal_payload.get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")

            order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                signal_payload, self.cfg
            )
            result = await self.order_manager.place_order(
                self.cfg,
                order_request,
                strategy_name=None
            )
            if result:
                logger.info(f"Order placed successfully: {result}")
                # Convert OrderRequest to dict for merging
                if hasattr(order_request, 'dict'):
                    order_request_dict = order_request.dict()
                else:
                    order_request_dict = dict(order_request)
                return {**order_request_dict, **result}
            else:
                logger.error(f"Order placement failed: {result}")
                return None
        else:
            logger.debug(f"No signal for {strike}.")
            return None


    async def evaluate_exit(self, order_row):
        """
        Evaluate exit for a given order_row with prioritized exit conditions:
        1. Next Day Stoploss Update (first, but don't exit immediately)
        2. Stop Loss Check (with potentially updated stoploss)
        3. Target Achievement 
        4. Swing High/Low Stoploss Update
        5. Holiday Exit
        
        Args:
            order_row: The order dict (from DB).
        Returns:
            True if exit signal should be triggered, else False.
        """
        try:
            strike_symbol = order_row.get('strike_symbol') or order_row.get('symbol') or order_row.get('strike')
            if not strike_symbol:
                logger.error("evaluate_exit: Missing strike_symbol in order_row.")
                return False
            logger.info(f"evaluate_exit: Evaluating exit for order_row={order_row}") 
            order_id = order_row.get('id') or order_row.get('order_id')
            logger.info(f"evaluate_exit: Checking exit conditions for order_id={order_id}, strike={strike_symbol}")
            
            # Use the spot symbol for spot-level checks
            spot_symbol = self.symbol
            trade_config = self.trade
            
            # Fetch recent candle history for spot price checks
            history_dict = await self.fetch_history_data(
                self.dp, [spot_symbol], self.stoploss_minutes
            )
            history_df = history_dict.get(str(spot_symbol))
            if history_df is None or len(history_df) < 2:
                logger.warning(f"evaluate_exit: Not enough history for {spot_symbol}.")
                return False
                
            # Get current spot price
            current_spot_price = history_df.iloc[-1].get("close") 
            if current_spot_price is None:
                logger.error(f"evaluate_exit: Could not get current spot price for {spot_symbol}")
                return False
            
            logger.info(f"evaluate_exit: Current spot price={current_spot_price} for order_id={order_id}")
            
            # Initialize stoploss from order (will be updated if next day)
            stoploss_spot_level = order_row.get("stoploss_spot_level")
            target_spot_level = order_row.get("target_spot_level")
            signal_direction = order_row.get("signal_direction") or order_row.get("direction", "").upper()
            logger.debug(f"evaluate_exit: Initial stoploss={stoploss_spot_level}, target={target_spot_level}, direction={signal_direction} for order_id={order_id}")
            # PRIORITY 1: NEXT DAY STOPLOSS UPDATE (UPDATE ONLY, DON'T EXIT)
            # Always check for next day logic if order exists from previous trading day
            # This ensures proper stoploss management even if carry_forward is disabled after position creation
            try:
                from algosat.core.time_utils import get_ist_datetime
                from algosat.common.broker_utils import get_trade_day
                from datetime import datetime, timedelta
                
                # Get order entry date and current date
                current_datetime = get_ist_datetime()
                current_trade_day = get_trade_day(current_datetime)
                
                # Get order entry date
                order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                if order_timestamp:
                    if isinstance(order_timestamp, str):
                        order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                    else:
                        order_datetime = order_timestamp
                    
                    # Convert order_datetime to IST for consistent trade day calculation
                    # (database timestamps are typically in UTC)
                    order_datetime_ist = to_ist(order_datetime)
                    order_trade_day = get_trade_day(order_datetime_ist)
                    
                    # Check if it's next trading day (compare dates only, not times)
                    current_trade_date = current_trade_day.date() if hasattr(current_trade_day, 'date') else current_trade_day
                    order_trade_date = order_trade_day.date() if hasattr(order_trade_day, 'date') else order_trade_day
                    
                    # If this is a next-day position, apply stoploss updates regardless of current carry_forward setting
                    # This ensures proper risk management for existing positions
                    if current_trade_date > order_trade_date:
                            # Calculate first candle completion time based on stoploss timeframe
                            market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                            first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                            
                            # Calculate check threshold time: first_candle_end_time + one more candle period
                            # This gives us a reasonable window to check for next day stoploss updates
                            next_day_check_threshold_time = first_candle_end_time + timedelta(minutes=self.stoploss_minutes)
                            
                            logger.info(f"evaluate_exit: Next day detected - order_id={order_id}, entry_date={order_trade_date}, current_date={current_trade_date}")
                            logger.info(f"evaluate_exit: Time windows - market_open={market_open_time.strftime('%H:%M')}, first_candle_end={first_candle_end_time.strftime('%H:%M')}, check_threshold={next_day_check_threshold_time.strftime('%H:%M')}, current_time={current_datetime.strftime('%H:%M')}")
                            
                            # Check only within the specific window: after first candle completion and before threshold
                            if current_datetime >= first_candle_end_time and current_datetime <= next_day_check_threshold_time:
                                logger.info(f"evaluate_exit: Within next day check window, checking stoploss update for order_id={order_id}")
                                
                                # Get first candle data to update stoploss
                                first_candle_history = await self.fetch_history_data(
                                    self.dp, [spot_symbol], self.stoploss_minutes
                                )
                                first_candle_df = first_candle_history.get(str(spot_symbol))
                                
                                if first_candle_df is not None and len(first_candle_df) > 0:
                                    # Get today's first candle (9:15 - first_candle_end_time)
                                    first_candle_df = first_candle_df.copy()
                                    first_candle_df['timestamp'] = pd.to_datetime(first_candle_df['timestamp'])
                                    
                                    # Convert market_open_time and first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
                                    market_open_ts = pd.to_datetime(market_open_time)
                                    first_candle_end_ts = pd.to_datetime(first_candle_end_time)
                                    
                                    # Ensure all timestamps are timezone-naive for comparison
                                    if first_candle_df['timestamp'].dt.tz is not None:
                                        first_candle_df['timestamp'] = first_candle_df['timestamp'].dt.tz_localize(None)
                                    if market_open_ts.tz is not None:
                                        market_open_ts = market_open_ts.tz_localize(None)
                                    if first_candle_end_ts.tz is not None:
                                        first_candle_end_ts = first_candle_end_ts.tz_localize(None)
                                    
                                    today_candles = first_candle_df[
                                        (first_candle_df['timestamp'] >= market_open_ts) & 
                                        (first_candle_df['timestamp'] < first_candle_end_ts)
                                    ]
                                    logger.debug(f"evaluate_exit: Today's candles for next day stoploss update: {today_candles}")
                                    if len(today_candles) > 0:
                                        first_candle = today_candles.iloc[0]  # First candle of the day
                                        first_candle_open = first_candle.get("open")
                                        current_stoploss = stoploss_spot_level  # Current stoploss (could be swing low/high)
                                        
                                        # Check if market opened beyond current stoploss and update accordingly
                                        should_update_stoploss = False
                                        
                                        if signal_direction == "UP":  # CE trade
                                            # For CE: Update stoploss if market opened below current stoploss
                                            if first_candle_open and current_stoploss and first_candle_open < float(current_stoploss):
                                                should_update_stoploss = True
                                                updated_stoploss = first_candle.get("low")
                                                update_reason = f"market opened {first_candle_open} below stoploss {current_stoploss}"
                                            
                                        elif signal_direction == "DOWN":  # PE trade  
                                            # For PE: Update stoploss if market opened above current stoploss
                                            if first_candle_open and current_stoploss and first_candle_open > float(current_stoploss):
                                                should_update_stoploss = True
                                                updated_stoploss = first_candle.get("high")
                                                update_reason = f"market opened {first_candle_open} above stoploss {current_stoploss}"
                                        
                                        if should_update_stoploss and updated_stoploss:
                                            stoploss_spot_level = updated_stoploss  # Update for subsequent checks
                                            logger.info(f"evaluate_exit: Next day {signal_direction} - UPDATED stoploss to first candle {'low' if signal_direction == 'UP' else 'high'} {updated_stoploss} (was {current_stoploss}) - {update_reason}")
                                            # Update DB with new stoploss
                                            await self.update_stoploss_in_db(order_id, updated_stoploss)
                                        else:
                                            logger.info(f"evaluate_exit: Next day - Stoploss NOT updated. Market opened at {first_candle_open}, current stoploss={current_stoploss}, direction={signal_direction}")
                                else:
                                    logger.warning(f"evaluate_exit: Could not get first candle data for next day stoploss update")
                            else:
                                # Outside the check window - either too early or too late
                                if current_datetime < first_candle_end_time:
                                    logger.debug(f"evaluate_exit: Too early for next day check - current_time={current_datetime.strftime('%H:%M')}, first_candle_ends={first_candle_end_time.strftime('%H:%M')}")
                                else:
                                    logger.debug(f"evaluate_exit: Past next day check window - current_time={current_datetime.strftime('%H:%M')}, threshold_time={next_day_check_threshold_time.strftime('%H:%M')}")
                                
            except Exception as e:
                logger.error(f"Error in next day stoploss update logic: {e}")
            
            # PRIORITY 2: TWO-CANDLE STOPLOSS CONFIRMATION CHECK
            if stoploss_spot_level is not None and len(history_df) >= 2:
                logger.debug(f"evaluate_exit: Starting TWO-CANDLE STOPLOSS check for order_id={order_id}, "
                           f"stoploss_level={stoploss_spot_level}, sl_buffer={self.sl_buffer}, signal_direction={signal_direction}")
                
                # Get last two candles for confirmation
                last_two_candles = history_df.tail(2)
                prev_candle = last_two_candles.iloc[0]
                current_candle = last_two_candles.iloc[1]
                
                # Two-candle confirmation logic with sl_buffer
                stoploss_level = float(stoploss_spot_level)
                sl_buffer_value = self.sl_buffer
                
                if signal_direction == "UP":  # CE trade
                    # For UP trades: exit when price goes below (stoploss + buffer)
                    buffered_stoploss_level = stoploss_level - sl_buffer_value
                    prev_close = prev_candle.get("close", 0)
                    current_close = current_candle.get("close", 0)
                    
                    logger.debug(f"evaluate_exit: UP trade stoploss check - prev_close={prev_close}, "
                               f"buffered_stoploss={buffered_stoploss_level} (original={stoploss_level} - buffer={sl_buffer_value}), "
                               f"current_close={current_close}")
                    
                    # Check: prev_candle below buffered stoploss AND current_candle below prev_candle
                    if (prev_close < buffered_stoploss_level and current_close < prev_close):
                        
                        # Update order status to EXIT_STOPLOSS
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_id,
                            status=constants.TRADE_STATUS_EXIT_STOPLOSS
                        )
                        
                        logger.info(f"evaluate_exit: ✅ TWO-CANDLE STOPLOSS confirmed for UP/CE trade. order_id={order_id}, "
                                  f"prev_candle_close={prev_close} < buffered_stoploss={buffered_stoploss_level} "
                                  f"(stoploss={stoploss_level} + sl_buffer={sl_buffer_value}), "
                                  f"current_candle_close={current_close} < prev_candle_close={prev_close} - Status updated to EXIT_STOPLOSS")
                        return True
                        
                elif signal_direction == "DOWN":  # PE trade
                    # For DOWN trades: exit when price goes above (stoploss - buffer)
                    buffered_stoploss_level = stoploss_level + sl_buffer_value
                    prev_close = prev_candle.get("close", 0)
                    current_close = current_candle.get("close", 0)
                    
                    logger.debug(f"evaluate_exit: DOWN trade stoploss check - prev_close={prev_close}, "
                               f"buffered_stoploss={buffered_stoploss_level} (original={stoploss_level} + buffer={sl_buffer_value}), "
                               f"current_close={current_close}")
                    
                    # Check: prev_candle above buffered stoploss AND current_candle above prev_candle
                    if (prev_close > buffered_stoploss_level and current_close > prev_close):
                        
                        # Update order status to EXIT_STOPLOSS
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_id,
                            status=constants.TRADE_STATUS_EXIT_STOPLOSS
                        )
                        
                        logger.info(f"evaluate_exit: ✅ TWO-CANDLE STOPLOSS confirmed for DOWN/PE trade. order_id={order_id}, "
                                  f"prev_candle_close={prev_close} > buffered_stoploss={buffered_stoploss_level} "
                                  f"(stoploss={stoploss_level} - sl_buffer={sl_buffer_value}), "
                                  f"current_candle_close={current_close} > prev_candle_close={prev_close} - Status updated to EXIT_STOPLOSS")
                        return True
                        
                # If no stoploss exit triggered, log the current status
                logger.debug(f"evaluate_exit: TWO-CANDLE STOPLOSS not triggered for order_id={order_id}. "
                           f"Conditions not met for {signal_direction} trade")
            else:
                if stoploss_spot_level is None:
                    logger.debug(f"evaluate_exit: Skipping TWO-CANDLE STOPLOSS check - no stoploss_spot_level for order_id={order_id}")
                elif len(history_df) < 2:
                    logger.debug(f"evaluate_exit: Skipping TWO-CANDLE STOPLOSS check - insufficient history data "
                               f"({len(history_df)} candles) for order_id={order_id}")
            
            # PRIORITY 3: TARGET ACHIEVEMENT CHECK
            if target_spot_level is not None:
                # Check target based on trade direction
                logger.info(f"evaluate_exit: Checking target achievement for order_id={order_id}, target={target_spot_level}, current_price={current_spot_price}")
                if signal_direction == "UP":  # CE trade
                    if float(current_spot_price) >= float(target_spot_level):
                        # Update order status to EXIT_TARGET
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_id,
                            status=constants.TRADE_STATUS_EXIT_TARGET
                        )
                        logger.info(f"evaluate_exit: TARGET achieved for CE trade. order_id={order_id}, spot_price={current_spot_price} >= target={target_spot_level} - Status updated to EXIT_TARGET")
                        return True
                elif signal_direction == "DOWN":  # PE trade
                    if float(current_spot_price) <= float(target_spot_level):
                        # Update order status to EXIT_TARGET
                        await self.order_manager.update_order_status_in_db(
                            order_id=order_id,
                            status=constants.TRADE_STATUS_EXIT_TARGET
                        )
                        logger.info(f"evaluate_exit: TARGET achieved for PE trade. order_id={order_id}, spot_price={current_spot_price} <= target={target_spot_level} - Status updated to EXIT_TARGET")
                        return True
            
            # PRIORITY 4: SWING HIGH/LOW STOPLOSS UPDATE
            try:
                # Calculate latest swing high/low from current history data
                if len(history_df) >= 10:  # Need enough data for swing calculation
                    swing_df = swing_utils.find_hhlh_pivots(
                        history_df,
                        left_bars=self.entry_swing_left_bars,
                        right_bars=self.entry_swing_right_bars
                    )
                    latest_hh, latest_ll = swing_utils.get_latest_confirmed_high_low(swing_df)
                    
                    if latest_hh and latest_ll:
                        new_stoploss = None
                        logger.debug(f"evaluate_exit: Latest swing high/low found - HH: {latest_hh}, LL: {latest_ll} for order_id={order_id}")
                        logger.debug(f"evaluate_exit: Current stoploss level: {stoploss_spot_level} for order_id={order_id}")
                        if signal_direction == "UP":  # CE trade
                            # New stoploss is latest swing low, but take max of current and new
                            latest_swing_low = latest_ll["price"]
                            if stoploss_spot_level:
                                new_stoploss = max(float(stoploss_spot_level), float(latest_swing_low))
                            else:
                                new_stoploss = float(latest_swing_low)
                                
                            if new_stoploss != float(stoploss_spot_level):
                                logger.info(f"evaluate_exit: CE - Updated stoploss from {stoploss_spot_level} to {new_stoploss} (latest swing low)")
                                stoploss_spot_level = new_stoploss
                                await self.update_stoploss_in_db(order_id, new_stoploss)
                                
                        elif signal_direction == "DOWN":  # PE trade
                            # New stoploss is latest swing high, but take min of current and new
                            latest_swing_high = latest_hh["price"]
                            if stoploss_spot_level:
                                new_stoploss = min(float(stoploss_spot_level), float(latest_swing_high))
                            else:
                                new_stoploss = float(latest_swing_high)
                                
                            if new_stoploss != float(stoploss_spot_level):
                                logger.info(f"evaluate_exit: PE - Updated stoploss from {stoploss_spot_level} to {new_stoploss} (latest swing high)")
                                stoploss_spot_level = new_stoploss
                                await self.update_stoploss_in_db(order_id, new_stoploss)
                                
            except Exception as e:
                logger.error(f"Error in swing high/low stoploss update: {e}")
            
            # PRIORITY 5: NEXT DAY SWING EXIT (Check last two candles for swing breach)
            # Always check for next day logic if order exists from previous trading day
            # This ensures proper exit logic even if carry_forward is disabled after position creation
            try:
                from algosat.core.time_utils import get_ist_datetime
                from algosat.common.broker_utils import get_trade_day
                from datetime import datetime, timedelta
                
                # Get order entry date and current date
                current_datetime = get_ist_datetime()
                current_trade_day = get_trade_day(current_datetime)
                
                # Get order entry date
                order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                if order_timestamp:
                    if isinstance(order_timestamp, str):
                        order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                    else:
                        order_datetime = order_timestamp
                    
                    # Convert order_datetime to IST for consistent trade day calculation
                    # (database timestamps are typically in UTC)
                    order_datetime_ist = to_ist(order_datetime)
                    order_trade_day = get_trade_day(order_datetime_ist)
                    
                    # Check if it's next trading day (compare dates only, not times)
                    current_trade_date = current_trade_day.date() if hasattr(current_trade_day, 'date') else current_trade_day
                    order_trade_date = order_trade_day.date() if hasattr(order_trade_day, 'date') else order_trade_day
                    
                    # If this is a next-day position, apply swing exit logic regardless of current carry_forward setting
                    if current_trade_date > order_trade_date:
                            # Calculate first candle completion time
                            market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                            first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                            
                            # Get history data AFTER first candle completion time
                            post_first_candle_history = await self.fetch_history_data(
                                self.dp, [spot_symbol], self.stoploss_minutes
                            )
                            post_first_candle_df = post_first_candle_history.get(str(spot_symbol))
                            
                            if post_first_candle_df is not None and len(post_first_candle_df) > 0:
                                # Filter to get data after first candle end time
                                post_first_candle_df = post_first_candle_df.copy()
                                post_first_candle_df['timestamp'] = pd.to_datetime(post_first_candle_df['timestamp'])
                                
                                # Convert first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
                                first_candle_end_ts = pd.to_datetime(first_candle_end_time)
                                
                                # Ensure all timestamps are timezone-naive for comparison
                                if post_first_candle_df['timestamp'].dt.tz is not None:
                                    post_first_candle_df['timestamp'] = post_first_candle_df['timestamp'].dt.tz_localize(None)
                                if first_candle_end_ts.tz is not None:
                                    first_candle_end_ts = first_candle_end_ts.tz_localize(None)
                                
                                post_first_candle_df = post_first_candle_df[
                                    post_first_candle_df['timestamp'] > first_candle_end_ts
                                ].copy()
                                
                                # Check if we have at least 2 candles post first candle
                                if len(post_first_candle_df) >= 2:
                                    # Check last two candles for stoploss breach confirmation
                                    last_two_candles = post_first_candle_df.tail(2)
                                    prev_candle = last_two_candles.iloc[0]
                                    current_candle = last_two_candles.iloc[1]
                                    
                                    # Use current stoploss level (updated by PRIORITY 1 and 4)
                                    current_stoploss = stoploss_spot_level
                                    
                                    if signal_direction == "UP":  # CE trade
                                        # Two-candle confirmation: prev_candle below stoploss AND current_candle below prev_candle
                                        if (current_stoploss and
                                            prev_candle.get("close", 0) < float(current_stoploss) and 
                                            current_candle.get("close", 0) < prev_candle.get("close", 0)):
                                            
                                            # Update order status to EXIT_STOPLOSS
                                            await self.order_manager.update_order_status_in_db(
                                                order_id=order_id,
                                                status=constants.TRADE_STATUS_EXIT_STOPLOSS
                                            )
                                            
                                            logger.info(f"evaluate_exit: NEXT DAY TWO-CANDLE STOPLOSS for CE trade. order_id={order_id}, "
                                                      f"prev_candle={prev_candle.get('close')} < stoploss={current_stoploss}, "
                                                      f"current_candle={current_candle.get('close')} < prev_candle={prev_candle.get('close')} (post-first-candle) - Status updated to EXIT_STOPLOSS")
                                            return True
                                            
                                    elif signal_direction == "DOWN":  # PE trade
                                        # Two-candle confirmation: prev_candle above stoploss AND current_candle above prev_candle
                                        if (current_stoploss and
                                            prev_candle.get("close", 0) > float(current_stoploss) and 
                                            current_candle.get("close", 0) > prev_candle.get("close", 0)):
                                            
                                            # Update order status to EXIT_STOPLOSS
                                            await self.order_manager.update_order_status_in_db(
                                                order_id=order_id,
                                                status=constants.TRADE_STATUS_EXIT_STOPLOSS
                                            )
                                            
                                            logger.info(f"evaluate_exit: NEXT DAY TWO-CANDLE STOPLOSS for PE trade. order_id={order_id}, "
                                                      f"prev_candle={prev_candle.get('close')} > stoploss={current_stoploss}, "
                                                      f"current_candle={current_candle.get('close')} > prev_candle={prev_candle.get('close')} (post-first-candle) - Status updated to EXIT_STOPLOSS")
                                            return True
                                else:
                                    logger.debug(f"evaluate_exit: Not enough post-first-candle data for swing exit check. Need 2, have {len(post_first_candle_df)}")
                            else:
                                logger.warning(f"evaluate_exit: Could not get post-first-candle history data for swing exit check")
                                
            except Exception as e:
                logger.error(f"Error in next day swing exit logic: {e}")
            
            # PRIORITY 6: HOLIDAY EXIT CHECK
            holiday_exit_config = trade_config.get("holiday_exit", {})
            if holiday_exit_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    
                    current_datetime = get_ist_datetime()
                    
                    # Simple check: if tomorrow is a holiday, exit today after specified time
                    if is_tomorrow_holiday():
                        # Use square_off_time from trade config since holiday_exit doesn't have exit_time
                        exit_time = trade_config.get("square_off_time", "15:10")
                        try:
                            exit_hour, exit_minute = map(int, exit_time.split(":"))
                            exit_datetime = current_datetime.replace(
                                hour=exit_hour, minute=exit_minute, second=0, microsecond=0
                            )
                            
                            if current_datetime >= exit_datetime:
                                # Update order status to EXIT_HOLIDAY (more specific than EXIT_EOD)
                                await self.order_manager.update_order_status_in_db(
                                    order_id=order_id,
                                    status=constants.TRADE_STATUS_EXIT_HOLIDAY
                                )
                                logger.info(f"evaluate_exit: HOLIDAY exit triggered. order_id={order_id}, tomorrow_is_holiday=True, time={current_datetime.strftime('%H:%M')}, square_off_time={exit_time} - Status updated to EXIT_HOLIDAY")
                                return True
                        except Exception as e:
                            logger.error(f"Error parsing square_off_time {exit_time}: {e}")
                                
                except Exception as e:
                    logger.error(f"Error in holiday exit logic: {e}")
            
            # PRIORITY 7: RSI-based exit (optional)
            target_cfg = trade_config.get("target", {})
            rsi_exit_config = target_cfg.get("rsi_exit", {})
            if rsi_exit_config.get("enabled", False):
                try:
                    from algosat.utils.indicators import calculate_rsi
                    
                    # Fetch fresh data using entry timeframe for RSI consistency
                    rsi_history_dict = await self.fetch_history_data(
                        self.dp, [spot_symbol], self.rsi_timeframe_minutes
                    )
                    rsi_history_df = rsi_history_dict.get(str(spot_symbol))
                    
                    if rsi_history_df is not None and len(rsi_history_df) > 0:
                        # Calculate RSI on entry timeframe data
                        rsi_period = rsi_exit_config.get("rsi_period", self.rsi_period or 14)
                        rsi_df = calculate_rsi(rsi_history_df, rsi_period)
                        
                        if "rsi" in rsi_df.columns and len(rsi_df) > 0:
                            current_rsi = rsi_df["rsi"].iloc[-1]
                            entry_rsi = order_row.get("entry_rsi")
                            
                            logger.info(f"evaluate_exit: RSI check - current_rsi={current_rsi}, entry_rsi={entry_rsi}, direction={signal_direction}")
                            
                            # RSI exit logic with ignore conditions
                            if signal_direction == "UP":  # CE trade
                                target_level = rsi_exit_config.get("ce_target_level", 60)
                                ignore_above = rsi_exit_config.get("ce_ignore_above", 80)
                                
                                # Check ignore condition: if entry RSI was above ignore threshold, skip RSI exit
                                if entry_rsi is not None and float(entry_rsi) >= ignore_above:
                                    logger.info(f"evaluate_exit: RSI exit IGNORED for CE trade - entry_rsi={entry_rsi} >= ignore_above={ignore_above}")
                                    # Don't trigger RSI exit, continue to other checks
                                else:
                                    # Normal RSI exit logic
                                    if current_rsi >= target_level:
                                        # Update order status to EXIT_RSI_TARGET
                                        await self.order_manager.update_order_status_in_db(
                                            order_id=order_id,
                                            status=constants.TRADE_STATUS_EXIT_RSI_TARGET
                                        )
                                        logger.info(f"evaluate_exit: RSI exit for CE trade. order_id={order_id}, rsi={current_rsi} >= target_level={target_level} - Status updated to EXIT_RSI_TARGET")
                                        return True
                                        
                            elif signal_direction == "DOWN":  # PE trade
                                target_level = rsi_exit_config.get("pe_target_level", 20)
                                ignore_below = rsi_exit_config.get("pe_ignore_below", 10)
                                
                                # Check ignore condition: if entry RSI was below ignore threshold, skip RSI exit
                                if entry_rsi is not None and float(entry_rsi) <= ignore_below:
                                    logger.info(f"evaluate_exit: RSI exit IGNORED for PE trade - entry_rsi={entry_rsi} <= ignore_below={ignore_below}")
                                    # Don't trigger RSI exit, continue to other checks
                                else:
                                    # Normal RSI exit logic
                                    if current_rsi <= target_level:
                                        # Update order status to EXIT_RSI_TARGET
                                        await self.order_manager.update_order_status_in_db(
                                            order_id=order_id,
                                            status=constants.TRADE_STATUS_EXIT_RSI_TARGET
                                        )
                                        logger.info(f"evaluate_exit: RSI exit for PE trade. order_id={order_id}, rsi={current_rsi} <= target_level={target_level} - Status updated to EXIT_RSI_TARGET")
                                        return True
                        else:
                            logger.warning(f"evaluate_exit: Could not calculate current RSI - missing RSI column")
                    else:
                        logger.warning(f"evaluate_exit: Could not fetch history data for RSI calculation")
                                
                except Exception as e:
                    logger.error(f"Error in RSI exit logic: {e}")
            
            # PRIORITY 8: EXPIRY EXIT CHECK
            expiry_date = order_row.get("expiry_date")
            expiry_exit_config = trade_config.get("expiry_exit", {})
            if expiry_date is not None and expiry_exit_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    from datetime import datetime
                    
                    current_datetime = get_ist_datetime()
                    
                    # Convert expiry_date to pandas datetime if it's a string
                    if isinstance(expiry_date, str):
                        expiry_dt = pd.to_datetime(expiry_date)
                    else:
                        expiry_dt = expiry_date
                    
                    # Calculate effective expiry date considering days_before_expiry
                    days_before_expiry = int(expiry_exit_config.get("days_before_expiry", 0))
                    effective_expiry_dt = expiry_dt - pd.Timedelta(days=days_before_expiry)
                    
                    # Check if today is the effective expiry date (or later)
                    if current_datetime.date() >= effective_expiry_dt.date():
                        # Use square_off_time from trade config for expiry exit time
                        square_off_time = trade_config.get("square_off_time", "15:10")
                        
                        try:
                            # Parse square_off_time (format: "HH:MM")
                            exit_hour, exit_minute = map(int, square_off_time.split(":"))
                            exit_time = current_datetime.replace(
                                hour=exit_hour, minute=exit_minute, second=0, microsecond=0
                            )
                            
                            if current_datetime >= exit_time:
                                # Update order status to EXIT_EXPIRY
                                await self.order_manager.update_order_status_in_db(
                                    order_id=order_id,
                                    status=constants.TRADE_STATUS_EXIT_EXPIRY
                                )
                                logger.info(f"evaluate_exit: EXPIRY exit triggered. order_id={order_id}, expiry_date={expiry_date}, effective_expiry_date={effective_expiry_dt.date()}, days_before_expiry={days_before_expiry}, current_time={current_datetime.strftime('%H:%M')}, square_off_time={square_off_time} - Status updated to EXIT_EXPIRY")
                                return True
                        except Exception as e:
                            logger.error(f"Error parsing square_off_time {square_off_time}: {e}")
                            
                except Exception as e:
                    logger.error(f"Error in expiry exit logic: {e}")
            
            # PRIORITY 9: SQUARE OFF TIME EXIT (when carry_forward is not enabled)
            carry_forward_config = trade_config.get("carry_forward", {})
            if not carry_forward_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    
                    current_datetime = get_ist_datetime()
                    square_off_time = trade_config.get("square_off_time", "15:10")
                    
                    try:
                        # Parse square_off_time (format: "HH:MM")
                        exit_hour, exit_minute = map(int, square_off_time.split(":"))
                        exit_datetime = current_datetime.replace(
                            hour=exit_hour, minute=exit_minute, second=0, microsecond=0
                        )
                        
                        if current_datetime >= exit_datetime:
                            # Update order status to EXIT_EOD
                            await self.order_manager.update_order_status_in_db(
                                order_id=order_id,
                                status=constants.TRADE_STATUS_EXIT_EOD
                            )
                            logger.info(f"evaluate_exit: SQUARE OFF TIME exit triggered. order_id={order_id}, carry_forward_enabled=False, time={current_datetime.strftime('%H:%M')}, square_off_time={square_off_time} - Status updated to EXIT_EOD")
                            return True
                    except Exception as e:
                        logger.error(f"Error parsing square_off_time {square_off_time}: {e}")
                        
                except Exception as e:
                    logger.error(f"Error in square off time exit logic: {e}")
            
            # No exit condition met
            logger.debug(f"evaluate_exit: No exit condition met for order_id={order_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error in evaluate_exit for order_id={order_row.get('id')}: {e}", exc_info=True)
            return False
    
    async def update_stoploss_in_db(self, order_id, new_stoploss):
        """Update stoploss level in database"""
        try:
            from algosat.core.db import update_rows_in_table
            from algosat.core.dbschema import orders
            update_values = {"stoploss_spot_level": float(new_stoploss)}
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values=update_values
            )
            logger.info(f"Updated stoploss in DB: order_id={order_id}, new_stoploss={new_stoploss}")
        except Exception as e:
            logger.error(f"Error updating stoploss in DB for order_id={order_id}: {e}")
    
    async def update_target_in_db(self, order_id, new_target):
        """Update target level in database"""
        try:
            from algosat.core.db import update_rows_in_table
            from algosat.core.dbschema import orders
            update_values = {"target_spot_level": float(new_target)}
            await update_rows_in_table(
                target_table=orders,
                condition=orders.c.id == order_id,
                new_values=update_values
            )
            logger.info(f"Updated target in DB: order_id={order_id}, new_target={new_target}")
        except Exception as e:
            logger.error(f"Error updating target in DB for order_id={order_id}: {e}")
    
    async def update_swing_levels_in_db(self, order_id, swing_high=None, swing_low=None):
        """Update swing high/low levels in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            from algosat.core.dbschema import orders
            async with AsyncSessionLocal() as session:
                # Build dynamic update values based on provided parameters
                update_values = {}
                
                if swing_high is not None:
                    update_values["entry_spot_swing_high"] = float(swing_high)
                
                if swing_low is not None:
                    update_values["entry_spot_swing_low"] = float(swing_low)
                
                if update_values:
                    await session.execute(
                        orders.update().where(orders.c.id == order_id).values(**update_values)
                    )
                    await session.commit()
                    logger.info(f"Updated swing levels in DB: order_id={order_id}, swing_high={swing_high}, swing_low={swing_low}")
        except Exception as e:
            logger.error(f"Error updating swing levels in DB for order_id={order_id}: {e}")
    
    async def update_entry_rsi_in_db(self, order_id, entry_rsi):
        """Update entry RSI level in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            from algosat.core.dbschema import orders
            async with AsyncSessionLocal() as session:
                # Update orders table with entry RSI
                await session.execute(
                    orders.update().where(orders.c.id == order_id).values(entry_rsi=float(entry_rsi))
                )
                await session.commit()
                logger.info(f"Updated entry_rsi in DB: order_id={order_id}, entry_rsi={entry_rsi}")
        except Exception as e:
            logger.error(f"Error updating entry_rsi in DB for order_id={order_id}: {e}")
    
    # async def update_exit_status_in_db(self, order_id, exit_result):
    #     """
    #     Update the order exit status in database when exit is triggered.
    #     Args:
    #         order_id: The order ID to update
    #         exit_result: Dict containing exit information from evaluate_exit
    #     """
    #     try:
    #         from algosat.core.db import AsyncSessionLocal
    #         from algosat.core.db import update_order_exit_status
            
    #         async with AsyncSessionLocal() as session:
    #             await update_order_exit_status(
    #                 session, 
    #                 order_id, 
    #                 exit_reason=exit_result.get('exit_reason'),
    #                 exit_price=exit_result.get('exit_price'),
    #                 exit_metadata=exit_result
    #             )
    #             logger.info(f"Updated exit status in DB for order_id={order_id}, reason={exit_result.get('exit_reason')}")
                
    #     except Exception as e:
    #         logger.error(f"Error updating exit status in DB for order_id={order_id}: {e}", exc_info=True)

    async def check_trade_limits(self) -> tuple[bool, str]:
        """
        Check if the symbol has exceeded maximum trades or maximum loss trades configured limits.
        For smart level enabled strategies, uses limits from smart level.
        For normal strategies, uses limits from trade config.
        Now symbol-based instead of strategy-based.
        Returns (can_trade: bool, reason: str)
        """
        try:
            # Ensure smart levels are loaded if they should be enabled
            if not hasattr(self, '_smart_level') or self._smart_level is None:
                await self.load_smart_levels()
            
            # Determine source of trade limits
            if self.is_smart_levels_enabled():
                # Use smart level limits
                summary = self.get_smart_level_summary()
                level_info = summary['level']
                max_trades = level_info.get('max_trades', None)
                max_loss_trades = level_info.get('max_loss_trades', None)
                limits_source = f"smart level '{level_info.get('name')}'"
                
                logger.debug(f"Using trade limits from {limits_source}: max_trades={max_trades}, max_loss_trades={max_loss_trades}")
            else:
                # Use trade config limits
                trade_config = self.trade
                max_trades = trade_config.get('max_trades', None)
                max_loss_trades = trade_config.get('max_loss_trades', None)
                limits_source = "trade config"
                
                logger.debug(f"Using trade limits from {limits_source}: max_trades={max_trades}, max_loss_trades={max_loss_trades}")
            
            # If no limits are configured, allow trading
            if max_trades is None and max_loss_trades is None:
                return True, f"No trade limits configured in {limits_source}"
            
            symbol_id = getattr(self.cfg, 'symbol_id', None)
            if not symbol_id:
                logger.warning("No symbol_id found in config, cannot check trade limits")
                return True, "No symbol_id found, allowing trade"
            
            trade_day = get_trade_day(get_ist_datetime())
            
            async with AsyncSessionLocal() as session:
                from algosat.core.db import get_all_orders_for_strategy_symbol_and_tradeday
                
                # Get all orders for this strategy symbol on the current trade day
                all_orders = await get_all_orders_for_strategy_symbol_and_tradeday(session, symbol_id, trade_day)
                
                # Count completed trades (both profitable and loss trades)
                completed_statuses = [
                    constants.TRADE_STATUS_EXIT_TARGET,
                    constants.TRADE_STATUS_EXIT_STOPLOSS,
                    constants.TRADE_STATUS_EXIT_REVERSAL,
                    constants.TRADE_STATUS_EXIT_EOD,
                    constants.TRADE_STATUS_EXIT_MAX_LOSS,
                    constants.TRADE_STATUS_EXIT_ATOMIC_FAILED,
                    constants.TRADE_STATUS_ENTRY_CANCELLED,
                    constants.TRADE_STATUS_EXIT_CLOSED
                    
                ]
                
                completed_trades = [order for order in all_orders if order.get('status') in completed_statuses]
                total_completed_trades = len(completed_trades)
                
                # Count loss trades (excluding profitable trades) - check all orders for negative PnL
                loss_statuses = [
                    constants.TRADE_STATUS_EXIT_STOPLOSS,
                    constants.TRADE_STATUS_EXIT_MAX_LOSS,
                    constants.TRADE_STATUS_ENTRY_CANCELLED
                ]
                
                # loss_trades = [order for order in completed_trades if order.get('status') in loss_statuses]
                loss_trades = [order for order in all_orders if order.get('pnl') is not None and order.get('pnl') < 0]
                
                total_loss_trades = len(loss_trades)
                
                logger.debug(f"Trade limits check - Total completed trades: {total_completed_trades}, Loss trades: {total_loss_trades}")
                logger.debug(f"Trade limits from {limits_source} - Max trades: {max_trades}, Max loss trades: {max_loss_trades}")
                logger.debug(f"Completed trade statuses found: {[order.get('status') for order in completed_trades]}")
                logger.debug(f"Loss trade statuses found: {[order.get('status') for order in loss_trades]}")
                
                # Check max_trades limit
                if max_trades is not None and total_completed_trades >= max_trades:
                    reason = f"Maximum trades limit reached for symbol: {total_completed_trades}/{max_trades} (from {limits_source})"
                    logger.info(reason)
                    return False, reason
                
                # Check max_loss_trades limit
                if max_loss_trades is not None and total_loss_trades >= max_loss_trades:
                    reason = f"Maximum loss trades limit reached for symbol: {total_loss_trades}/{max_loss_trades} (from {limits_source})"
                    logger.info(reason)
                    return False, reason
                
                return True, f"Trade limits OK for symbol - Completed: {total_completed_trades}/{max_trades or 'unlimited'}, Loss: {total_loss_trades}/{max_loss_trades or 'unlimited'} (from {limits_source})"
                
        except Exception as e:
            logger.error(f"Error checking trade limits: {e}")
            # On error, allow trading to avoid blocking legitimate trades
            return True, f"Error checking trade limits, allowing trade: {e}"
        
    async def evaluate_signal(self, entry_df, confirm_df, config) -> Optional[TradeSignal]:
        """
        Modular method to evaluate entry signals for swing high/low breakouts.
        Returns a TradeSignal object if signal is detected, else None.
        """
        from algosat.core.signal import TradeSignal, SignalType
        try:
            # 1. Identify most recent swing high/low from entry_df
            entry_left = self.entry_swing_left_bars
            entry_right = self.entry_swing_right_bars
            swing_df = swing_utils.find_hhlh_pivots(
                entry_df,
                left_bars=entry_left,
                right_bars=entry_right
            )
            last_hh, last_ll, last_hl, last_lh = swing_utils.get_last_swing_points(swing_df)
            logger.info(f"{self.cfg.symbol}'s Latest swing points: HH={last_hh}, LL={last_ll}, HL={last_hl}, LH={last_lh}")
            last_hh, last_ll = swing_utils.get_latest_confirmed_high_low(swing_df)
            if not last_hh or not last_ll:
                logger.info("No HH/LL pivot available for breakout evaluation.")
                return None
            entry_buffer = self.entry_buffer
            breakout_high_level = last_hh["price"] + entry_buffer
            breakout_low_level = last_ll["price"] - entry_buffer

            # Prepare new fields
            entry_spot_price = None
            entry_spot_swing_high = None
            entry_spot_swing_low = None
            stoploss_spot_level = None
            target_spot_level = None

            # 2. In confirm_df, check last two closed candles for breakout
            if "timestamp" in confirm_df.columns:
                confirm_df = confirm_df.sort_values("timestamp")
            last_two = confirm_df.tail(2)
            if len(last_two) < 2:
                logger.info("Not enough 1-min candles for confirmation logic.")
                return None
            prev_candle = last_two.iloc[0]
            last_candle = last_two.iloc[1]

            # 3. Determine breakout direction and signal
            breakout_type = None
            trend = None
            direction = None
            signal_price = None
            if prev_candle["close"] > breakout_high_level and last_candle["close"] > prev_candle["close"]:
                breakout_type = "CE"
                trend = "UP"
                direction = "UP"
                signal_price = breakout_high_level
            elif prev_candle["close"] < breakout_low_level and last_candle["close"] < prev_candle["close"]:
                breakout_type = "PE"
                trend = "DOWN"
                direction = "DOWN"
                signal_price = breakout_low_level
            else:
                logger.debug("No breakout detected in confirm candles.")
                return None

            # 4. Get spot price and ATM strike for option
            spot_price = last_candle["close"]  # Use last candle close as spot price
            
            # 4.1 Smart Level Validation (if enabled)
            if self.is_smart_levels_enabled():
                logger.info(f"🔍 Starting Smart Level Validation for {breakout_type} {direction} breakout at spot_price={spot_price}")
                is_valid, smart_level_data, smart_lot_qty = await self.validate_smart_level_entry(
                    breakout_type, spot_price, direction, swing_high=last_hh, swing_low=last_ll
                )
                if not is_valid:
                    logger.warning(f"🚫 Smart Level Validation REJECTED {breakout_type} {direction} trade at spot_price={spot_price}")
                    return None
                logger.info(f"✅ Smart Level Validation APPROVED {breakout_type} {direction} trade with smart_lot_qty={smart_lot_qty}")
            else:
                logger.debug("Smart levels not enabled, proceeding with normal validation")
                smart_level_data = None
                smart_lot_qty = None
            
            strike, expiry_date = swing_utils.get_atm_strike_symbol(self.cfg.symbol, spot_price, breakout_type, self.trade)
            
            qty = self.ce_lot_qty * self.lot_size if breakout_type == "CE" else self.trade.get("pe_lot_qty", 1) * self.lot_size
            
            # Use smart level quantity if available, otherwise use config quantity
            if smart_lot_qty is not None:
                lot_qty = smart_lot_qty
                logger.info(f"📊 Using Smart Level Quantity: lot_qty={lot_qty} (from smart level validation)")
            else:
                if breakout_type == "CE":
                    lot_qty = config.get("ce_lot_qty", 1)
                else:
                    lot_qty = config.get("pe_lot_qty", 1)
                logger.info(f"📊 Using Config Quantity: lot_qty={lot_qty} (from strategy config)")
            
            if breakout_type == "CE":
                stoploss_spot_level = last_ll["price"]  # Stoploss is swing low for CE
            else:
                stoploss_spot_level = last_hh["price"]  # Stoploss is swing high for PE

            entry_spot_price = spot_price
            entry_spot_swing_high = last_hh["price"]
            entry_spot_swing_low = last_ll["price"]
            logger.info(f"Evaluating {breakout_type} breakout: spot_price={spot_price}, entry_spot_swing_high={entry_spot_swing_high}, "
                        f"entry_spot_swing_low={entry_spot_swing_low}, stoploss_spot_level={stoploss_spot_level}, "
                        f"signal_price={signal_price}, lot_qty={lot_qty}, strike={strike}, expiry_date={expiry_date}")

            # --- Regime detection and quantity adjustment logic ---
            # Check if regime_reference is available, if not try to get it
            if not getattr(self, 'regime_reference', None):
                logger.warning("regime_reference is empty, attempting to fetch regime reference points")
                interval_minutes = self.entry_minutes
                first_candle_time = config.get("first_candle_time", "09:15")
                today_dt = get_ist_datetime()
                self.regime_reference = await get_regime_reference_points(
                    self.dp,
                    self.symbol,
                    first_candle_time,
                    interval_minutes,
                    today_dt
                )
                logger.info(f"Regime reference points for {self.symbol}: {self.regime_reference}")
            
            # If regime_reference is still empty, skip sideways calculation
            if not getattr(self, 'regime_reference', None):
                logger.error("regime_reference is still empty after retry, skipping sideways regime detection")
                regime = "Unknown"
            else:
                regime = detect_regime(
                    entry_price=entry_spot_price,
                    regime_ref=getattr(self, 'regime_reference', None),
                    option_type=breakout_type,
                    strategy="BUY"
                )
            
            logger.info(f"Regime detected for {self.symbol}: {regime} (entry_price={entry_spot_price}, option_type={breakout_type})")
            
            # Adjust quantity for sideways regime if enabled
            sideways_enabled = config.get('sideways_trade_enabled', False)
            sideways_qty_perc = config.get('sideways_qty_percentage', 0)
            sideways_target_atr_multiplier = config.get("sideways_target_atr_multiplier", 1)
            original_lot_qty = lot_qty
            
            if sideways_enabled and regime == "Sideways":
                if sideways_qty_perc == 0:
                    logger.info(f"Sideways regime detected for {self.symbol} at {last_candle['timestamp']}, sideways_qty_percentage is 0, skipping trade.")
                    return None
                new_lot_qty = int(round(lot_qty * sideways_qty_perc / 100))
                if new_lot_qty == 0:
                    logger.info(f"Sideways regime detected for {self.symbol} at {last_candle['timestamp']}, computed lot_qty is 0, skipping trade.")
                    return None
                lot_qty = new_lot_qty
                logger.info(f"Sideways regime detected for {self.symbol} at {last_candle['timestamp']}, updating lot_qty to {lot_qty} ({sideways_qty_perc}% of {original_lot_qty}) and using target_atr_multiplier={sideways_target_atr_multiplier}")
            elif not sideways_enabled and regime == "Sideways":
                # If sideways is not enabled, skip the trade entirely
                logger.info(f"Sideways regime detected for {self.symbol} at {last_candle['timestamp']}, but sideways_trade_enabled is False, skipping trade entirely")
                return None

            # Target calculation
            target_cfg = config.get("target", {})
            target_type = target_cfg.get("type", "ATR")
            if target_type == "ATR":
                # Calculate ATR on entry timeframe (5m default)
                atr_period = self.atr_period or 14

                atr_multiplier = target_cfg.get("atr_multiplier", 3)  # Default to 3x ATR
                
                # Use sideways_target_atr_multiplier if in sideways regime
                if sideways_enabled and regime == "Sideways":
                    effective_atr_multiplier = sideways_target_atr_multiplier
                    logger.info(f"Using sideways target ATR multiplier: {effective_atr_multiplier} for {self.symbol}")
                else:
                    effective_atr_multiplier = atr_multiplier
                
                # Defensive: ensure entry_df has enough data
                atr_value = None
                try:
                    from algosat.utils.indicators import calculate_atr
                    # Fetch fresh data using entry timeframe for RSI consistency
                    atr_history_dict = await self.fetch_history_data(
                        self.dp, [self.symbol,], self.atr_timeframe_minutes
                    )
                    atr_history_df = atr_history_dict.get(str(self.symbol))
                    if atr_history_df is not None and len(atr_history_df) > 0:
                        # Calculate ATR on entry timeframe data
                        atr_df = calculate_atr(atr_history_df, atr_period)
                    else:
                        logger.warning("Could not fetch history data for ATR calculation")
                        atr_df = pd.DataFrame()  # Empty DataFrame to avoid errors
                    if "atr" in atr_df.columns:
                        atr_value = atr_df["atr"].iloc[-1]
                        logger.info(f"ATR calculated on {self.atr_timeframe_minutes}min interval: {atr_value} (period={atr_period})")
                except Exception as e:
                    logger.error(f"Error calculating ATR for target: {e}")
                
                if atr_value is not None:
                    target_points = float(atr_value) * float(effective_atr_multiplier)
                    if breakout_type == "CE":
                        # For CE: Target = swing_high + entry_buffer + (ATR * effective_multiplier)
                        target_spot_level = float(entry_spot_swing_high) + float(entry_buffer) + target_points
                    else:
                        # For PE: Target = swing_low - entry_buffer - (ATR * effective_multiplier)
                        target_spot_level = float(entry_spot_swing_low) - float(entry_buffer) - target_points
                    logger.info(f"Target calculated using ATR: {target_spot_level} (effective_multiplier={effective_atr_multiplier}, target_points={target_points})")
                else:
                    logger.warning("Could not calculate ATR for target, using fallback")
                    target_spot_level = None
                    target_points = None
            elif target_type == "fixed":
                target_points = target_cfg.get("fixed_points", 0)
                if breakout_type == "CE":
                    # For CE: Target = swing_high + entry_buffer + fixed_points
                    target_spot_level = float(entry_spot_swing_high) + float(entry_buffer) + float(target_points)
                else:
                    # For PE: Target = swing_low - entry_buffer - fixed_points  
                    target_spot_level = float(entry_spot_swing_low) - float(entry_buffer) - float(target_points)
                logger.info(f"Target calculated using fixed points: {target_spot_level} (fixed_points={target_points})")
            else:
                target_spot_level = None
                target_points = None

            # Validate target direction and minimum distance before proceeding with RSI calculation
            if target_spot_level is not None and target_points is not None:
                # Check if entry_spot_price is in correct direction relative to target
                direction_valid = False
                if breakout_type == "CE" and direction == "UP":
                    # For uptrend CE: entry_spot_price should be below target_spot_level
                    direction_valid = float(entry_spot_price) < float(target_spot_level)
                elif breakout_type == "PE" and direction == "DOWN":
                    # For downtrend PE: entry_spot_price should be above target_spot_level
                    direction_valid = float(entry_spot_price) > float(target_spot_level)
                
                if not direction_valid:
                    logger.info(f"🚫 Target direction validation failed for {breakout_type} {direction} trade: entry_spot_price={entry_spot_price}, target_spot_level={target_spot_level}. Skipping trade.")
                    return None
                
                # Check minimum distance requirement (75% of target points)
                distance_required = float(target_points) * 0.75
                actual_distance = abs(float(target_spot_level) - float(entry_spot_price))
                
                if actual_distance < distance_required:
                    logger.info(f"🚫 Insufficient target distance for {breakout_type} {direction} trade: actual_distance={actual_distance:.2f}, required={distance_required:.2f} (75% of target_points={target_points}). Skipping trade to ensure adequate room.")
                    return None
                
                logger.info(f"✅ Target validation passed: direction_valid={direction_valid}, actual_distance={actual_distance:.2f}, required_distance={distance_required:.2f}")
            else:
                logger.warning("Target spot level or target points not calculated, skipping target validation")

            

            # Calculate entry RSI using entry timeframe
            entry_rsi_value = None
            try:
                from algosat.utils.indicators import calculate_rsi
                rsi_period = self.rsi_period or 14
                
                # Fetch fresh data using entry timeframe for RSI consistency
                rsi_history_dict = await self.fetch_history_data(
                    self.dp, [self.symbol,], self.rsi_timeframe_minutes
                )
                rsi_history_df = rsi_history_dict.get(str(self.symbol))
                
                if rsi_history_df is not None and len(rsi_history_df) > 0:
                    # Calculate RSI on entry timeframe data
                    rsi_df = calculate_rsi(rsi_history_df, rsi_period)

                    # Use entry timeframe data for RSI calculation to ensure consistency
                     # rsi_df = calculate_rsi(entry_df, rsi_period)
                    if "rsi" in rsi_df.columns and len(rsi_df) > 0:
                        entry_rsi_value = rsi_df["rsi"].iloc[-1]
                        logger.info(f"Entry RSI calculated on {self.rsi_timeframe_minutes}min interval: {entry_rsi_value} (period={rsi_period})")
                    else:
                        logger.warning("Could not calculate entry RSI - missing RSI column")
                else:
                    logger.warning("Could not fetch history data for entry RSI calculation")
            except Exception as e:
                logger.error(f"Error calculating entry RSI: {e}")

            logger.info(f"Breakout detected: type={breakout_type}, trend={trend}, direction={direction}, strike={strike}, price={last_candle['close']}, entry_spot_price={entry_spot_price}, entry_spot_swing_high={entry_spot_swing_high}, entry_spot_swing_low={entry_spot_swing_low}, stoploss_spot_level={stoploss_spot_level}, target_spot_level={target_spot_level}, entry_rsi={entry_rsi_value}, target_type={target_type}, expiry_date={expiry_date}, regime={regime}, lot_qty={lot_qty}, smart_level_enabled={self.is_smart_levels_enabled()}")
            from algosat.core.signal import Side
            signal = TradeSignal(
                symbol=strike,
                side="BUY",
                signal_type=SignalType.ENTRY,
                signal_time=last_candle["timestamp"],
                signal_direction=direction,
                lot_qty=lot_qty,
                entry_spot_price=entry_spot_price,
                entry_spot_swing_high=entry_spot_swing_high,
                entry_spot_swing_low=entry_spot_swing_low,
                stoploss_spot_level=stoploss_spot_level,
                target_spot_level=target_spot_level,
                entry_rsi=entry_rsi_value,
                expiry_date=expiry_date
            )
            
            # Final log with smart level information
            smart_level_info = ""
            if smart_level_data:
                smart_level_info = f", smart_level='{smart_level_data.get('name')}'"
            
            logger.info(f"🟢 Swing breakout signal formed for {self.symbol}: type={breakout_type}, direction={direction}, strike={strike}, price={last_candle['close']}, regime={regime}, lot_qty={lot_qty} (original: {original_lot_qty}){smart_level_info}")
            return signal
        except Exception as e:
            logger.error(f"Error in evaluate_signal: {e}", exc_info=True)
            return None
