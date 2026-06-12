-- Mwosho Data Cleaning App — one-time DB migration
-- Run this in phpMyAdmin → SQL tab, or: mysql -u root 1ndependence < migrate.sql
-- Safe to re-run: each ALTER is wrapped in IF NOT EXISTS logic via PROCEDURE

USE `1ndependence`;

DROP PROCEDURE IF EXISTS _add_col;
DELIMITER ;;
CREATE PROCEDURE _add_col(
    tbl VARCHAR(64), col VARCHAR(64), def TEXT
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = tbl
          AND COLUMN_NAME  = col
    ) THEN
        SET @sql = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN `', col, '` ', def);
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('  + added: ', col) AS status;
    ELSE
        SELECT CONCAT('  . exists: ', col) AS status;
    END IF;
END;;
DELIMITER ;

CALL _add_col('users', 'billing_cycle',          "VARCHAR(20) DEFAULT 'monthly'");
CALL _add_col('users', 'period_end',              'DATETIME NULL');
CALL _add_col('users', 'stripe_customer_id',      'VARCHAR(100) NULL');
CALL _add_col('users', 'stripe_subscription_id',  'VARCHAR(100) NULL');
CALL _add_col('users', 'totp_secret',             'VARCHAR(64) NULL');
CALL _add_col('users', 'is_2fa_enabled',          'BOOLEAN DEFAULT FALSE');
CALL _add_col('users', 'is_email_verified',       'BOOLEAN DEFAULT FALSE');
CALL _add_col('users', 'email_otp_hash',          'VARCHAR(64) NULL');
CALL _add_col('users', 'otp_expires_at',          'DATETIME NULL');

DROP PROCEDURE IF EXISTS _add_col;

SELECT 'Migration complete.' AS result;
