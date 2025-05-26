-- Migration: Fix orders table schema type mismatches
-- Date: 2024-12-19
-- Description: Change price columns from String to Float and side column from Integer to String

BEGIN;

-- Create backup table (optional but recommended)
CREATE TABLE orders_backup AS SELECT * FROM orders;

-- Alter columns to correct types
ALTER TABLE orders 
    ALTER COLUMN entry_price TYPE DOUBLE PRECISION USING 
        CASE 
            WHEN entry_price IS NULL THEN NULL
            WHEN entry_price ~ '^[0-9]*\.?[0-9]+$' THEN entry_price::double precision
            ELSE NULL
        END,
    ALTER COLUMN stop_loss TYPE DOUBLE PRECISION USING 
        CASE 
            WHEN stop_loss IS NULL THEN NULL
            WHEN stop_loss ~ '^[0-9]*\.?[0-9]+$' THEN stop_loss::double precision
            ELSE NULL
        END,
    ALTER COLUMN target_price TYPE DOUBLE PRECISION USING 
        CASE 
            WHEN target_price IS NULL THEN NULL
            WHEN target_price ~ '^[0-9]*\.?[0-9]+$' THEN target_price::double precision
            ELSE NULL
        END,
    ALTER COLUMN exit_price TYPE DOUBLE PRECISION USING 
        CASE 
            WHEN exit_price IS NULL THEN NULL
            WHEN exit_price ~ '^[0-9]*\.?[0-9]+$' THEN exit_price::double precision
            ELSE NULL
        END,
    ALTER COLUMN atr TYPE DOUBLE PRECISION USING 
        CASE 
            WHEN atr IS NULL THEN NULL
            WHEN atr ~ '^[0-9]*\.?[0-9]+$' THEN atr::double precision
            ELSE NULL
        END,
    ALTER COLUMN side TYPE VARCHAR USING 
        CASE 
            WHEN side IS NULL THEN NULL
            WHEN side = '1' THEN 'BUY'
            WHEN side = '0' THEN 'SELL'
            ELSE side::text
        END;

-- Add indexes for performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_strategy_broker ON orders(strategy_config_id, broker_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_status_time ON orders(status, signal_time);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_symbol_time ON orders(symbol, entry_time);

COMMIT;

-- Verify migration
SELECT 
    column_name, 
    data_type, 
    is_nullable 
FROM information_schema.columns 
WHERE table_name = 'orders' 
    AND column_name IN ('entry_price', 'stop_loss', 'target_price', 'exit_price', 'atr', 'side')
ORDER BY ordinal_position;
